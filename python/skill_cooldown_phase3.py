"""Phase 3, synthetic providers only; original engine and Phase 2 stay untouched."""
import argparse, collections, copy, gc, json, math, sys
from pathlib import Path
from skill_simulation_bench import Bench, SimStopEvent, states
from skill_cooldown_adapter import SyntheticGame, NAMES
import profile_store

def own_memory():
    """Own-process counters only; no VM_READ or foreign process inspection."""
    import ctypes as c
    from ctypes import wintypes as w
    class Counters(c.Structure):
        _fields_=[('cb',w.DWORD),('faults',w.DWORD)]+[(n,c.c_size_t) for n in
            ('peak_working_set','working_set','peak_paged','paged','peak_nonpaged','nonpaged','pagefile','peak_pagefile')]
    k=c.WinDLL('kernel32');k.GetCurrentProcess.restype=w.HANDLE
    api=c.WinDLL('psapi');api.GetProcessMemoryInfo.argtypes=[w.HANDLE,c.c_void_p,w.DWORD]
    data=Counters();data.cb=c.sizeof(data)
    if not api.GetProcessMemoryInfo(k.GetCurrentProcess(),c.byref(data),data.cb):raise OSError('Own memory counters unavailable')
    return dict(working_set_bytes=data.working_set,peak_working_set_bytes=data.peak_working_set,
                python_allocated_blocks=sys.getallocatedblocks())

class Distribution:
    """Bounded 0.1ms histogram, with an explicit overflow bin at 10 seconds."""
    def __init__(self):self.hist=collections.Counter();self.n=0;self.total=0.;self.low=None;self.high=None
    def add(self,x):
        self.n+=1;self.total+=x;self.low=x if self.low is None else min(self.low,x);self.high=x if self.high is None else max(self.high,x)
        self.hist[min(100000,max(0,round(x*10)))]+=1
    def result(self):
        def q(p):
            upto=0
            for k,v in sorted(self.hist.items()):
                upto+=v
                if upto>=math.ceil(self.n*p):return k/10
        return dict(count=self.n,mean=self.total/self.n if self.n else None,min=self.low,max=self.high,
                    p50=q(.5) if self.n else None,p95=q(.95) if self.n else None,p99=q(.99) if self.n else None,
                    histogram_resolution_ms=.1,histogram_overflow_ms=10000)

class IdleJumpEvent(SimStopEvent):
    """Skip only known quiescent polls, never a pending deadline or ready scan.

    Wake one poll BEFORE a known change then resume the original wait loop.
    Preserves virtual 10ms sampling, not real OS scheduling. Differential tests
    allow <=one polling quantum numerical phase difference, equal cast counts.
    """
    def __init__(self,clock,end,bench):super().__init__(clock,end);self.bench=bench;self.skipped=0
    def wait(self,timeout):
        b=self.bench;w=b.worker
        if not self.stopped and b.case=='long' and not w.brain.pending and w.opener.pending is None and w.brain._inflight is None and not any(b.last_visible.values()):
            boundary=max(b.game.gcd_until,b.game.cast_until)
            ticks=max(0,math.floor((min(self.end,boundary)-self.clock())/w.interval)-1)
            if ticks>1:self.clock.advance((ticks-1)*w.interval);self.skipped+=ticks-1
        return super().wait(timeout)

class RobustBench(Bench):
    def __init__(self,profile,strategy,case,duration=4,width_ms=40,phase_ms=0,error_ms=0,
                 jitter_ms=20,accelerate=False,writer=None):
        if strategy not in ('cooldown_aware','state_transition'):raise ValueError(strategy)
        self.strategy=strategy;self.case=case;self.width=width_ms/1000;self.phase=phase_ms/1000
        self.offset=error_ms/1000;self.jitter=jitter_ms/1000
        self.game=SyntheticGame(passive=case in ('jitter','held_ready_starvation'))
        if case in ('error','stale_available','expired_unknown'):self.game.gcd_until=1.
        self.cache_time=None;self.cache=None;self.previous={n:False for n in NAMES};self.tickets=set();self.last_visible={n:False for n in NAMES}
        self.actual={};self.open={};self.opportunities=collections.Counter();self.served=collections.Counter();self.missed=collections.Counter()
        self.accepted=collections.Counter();self.rejected=collections.Counter();self.latency=Distribution()
        self.detected_windows=set();self.served_windows=set();self.window_latency=Distribution()
        self.first_ready={};self.last_service={};self.longest_wait=collections.Counter();self.waits={n:Distribution() for n in NAMES}
        self.trace=collections.deque(maxlen=16);self.memory=[];self.next_memory=0.;self.max_retained=0
        super().__init__(profile,f'{case}:{strategy}:w{width_ms}:p{phase_ms}:e{error_ms}:j{jitter_ms}:{duration:g}',duration,self.frame,enabled=tuple(NAMES),writer=writer)
        emit=self.worker.emit
        def checked_emit(event,**fields):
            if event=='DETECTOR_ERROR' and not self.expected_error:self.errors.append(fields.get('message','unclassified detector error'))
            return emit(event,**fields)
        self.worker.emit=checked_emit
        if accelerate:self.worker.stop_event=IdleJumpEvent(self.clock,duration,self)
    def desired(self,t):
        raw={n:False for n in NAMES};raw['Skill_4']=True
        if self.case=='window':
            age=t-self.phase;raw['Skill_4']=age>=0 and age%2<self.width-1e-12
        elif self.case=='jitter':raw['Skill_4']=int((t+1e-12)/self.jitter)%2==0
        elif self.case in ('starvation','held_ready_starvation'):raw={n:True for n in NAMES}
        return raw
    def truth_boundary(self,n,t):
        if self.case=='window':return self.phase+math.floor((t-self.phase)/2)*2
        if self.case=='jitter':return math.floor((t+1e-12)/self.jitter)*self.jitter
        return 0. if self.game.passive else max(self.game.gcd_until,self.game.cast_until,self.game.cooldowns[n],self.game.resource_ready_at if n=='Skill_6' else 0.)
    def frame(self,t):
        if self.cache_time==t:return self.cache
        raw=self.desired(t);gate=self.case!='gate_false';truth={n:gate and not self.game.unavailable(n,t,raw[n]) for n in NAMES}
        for n,ready in truth.items():
            if ready and n not in self.open:
                start=self.truth_boundary(n,t);self.open[n]=[start,False];self.opportunities[n]+=1
                self.first_ready.setdefault(n,start)
            elif not ready and n in self.open:
                self.missed[n]+=int(not self.open[n][1]);del self.open[n]
        if self.case=='window' and truth['Skill_4']:self.detected_windows.add(math.floor((t-self.phase)/2))
        observed=dict(truth)
        if self.case=='error':
            observed={n:gate and raw[n] and t+1e-12>=max(self.game.gcd_until,self.game.cast_until,self.game.cooldowns[n])+self.offset for n in NAMES}
        elif self.case=='stale_available':observed={n:raw[n] for n in NAMES}
        if self.case in ('unknown','expired_unknown') and t>=.2:
            self.cache_time=t;self.cache=states(Node_Target='unknown');return self.cache
        if self.strategy=='state_transition':
            for n,ready in observed.items():
                if ready and not self.previous[n]:self.tickets.add(n)
                if not ready:self.tickets.discard(n)
            self.previous=observed;visible={n:n in self.tickets for n in NAMES}
        else:visible=observed
        self.actual=truth;self.last_visible=visible;self.cache_time=t;self.cache=states(Node_Target=gate,**visible)
        return self.cache
    def observe(self,w,conditions,details):
        # Bounded observer, not another decision engine. No histories per scan.
        self.conditions=dict(conditions);self.observed_at=self.clock();self.track_pending(w)
        if w.brain._inflight is not None:raise AssertionError('inflight leaked across scans')
        if self.clock()>=self.next_memory:
            self.memory.append(dict(time=self.clock(),**own_memory()))
            self.next_memory=self.clock()+max(self.duration/4,1)
        retained=len(w.samples)+w.events.qsize()+len(self.trace)+len(self.latency.hist)
        self.max_retained=max(self.max_retained,retained)
    def send(self,command,source_node=None,schedule=None):
        self.guard.check();w=self.worker;n=source_node;t=self.clock();self.track_pending(w)
        if self.stopped or w.stop_event.is_set() or self.observed_at!=t or self.conditions is None:raise AssertionError('No valid fresh scan')
        if w.brain._inflight!=n or t+1e-12<schedule['deadline']:raise AssertionError('Bad in-flight/deadline')
        self.counts[n]+=1;self.sequence+=1
        why=self.game.unavailable(n,t,self.desired(t)[n]);accepted=not why
        if accepted:
            self.accepted[n]+=1
            if n in self.open and not self.open[n][1]:self.latency.add((t-self.open[n][0])*1000);self.open[n][1]=True;self.served[n]+=1
            anchor=self.last_service.get(n,self.first_ready.get(n,t));self.waits[n].add((t-anchor)*1000);self.longest_wait[n]=max(self.longest_wait[n],t-anchor);self.last_service[n]=t
            if self.case=='window':
                k=math.floor((t-self.phase)/2)
                if k not in self.served_windows:self.window_latency.add((t-(self.phase+k*2))*1000)
                self.served_windows.add(k)
            self.game.accept(n,t)
        else:self.rejected[n]+=1
        if self.strategy=='state_transition':self.tickets.discard(n)
        row=self.event('DECISION',node=n,command=command,schedule=schedule,conditions=self.conditions,
            true_available=self.actual,model_accepted=accepted,suppressed_reasons=why,
            blocked_output=True,inflight=w.brain._inflight,event_id=self.name+':'+str(self.sequence))
        self.trace.append(row);return 1
    def run(self):
        base=super().run();t=self.clock()
        self.memory.append(dict(time=t,after_stop=True,**own_memory()))
        if not self.expected_error and t!=self.duration:self.errors.append('Unexpected early stop')
        for n in self.first_ready:self.longest_wait[n]=max(self.longest_wait[n],t-self.last_service.get(n,self.first_ready[n]))
        misses={n:self.missed[n]+int(n in self.open and not self.open[n][1]) for n in NAMES}
        windows=max(0,math.ceil((self.duration-self.phase)/2)) if self.case=='window' else None
        self.tickets.clear()
        return {**base,'strategy':self.strategy,'case':self.case,'width_ms':self.width*1000,'phase_ms':self.phase*1000,'error_ms':self.offset*1000,
            'accepted':sum(self.accepted.values()),'suppressed':sum(self.rejected.values()),'per_skill_accepted':dict(self.accepted),
            'missed':sum(misses.values()),'latency_ms':self.latency.result(),'window_latency_ms':self.window_latency.result(),
            'truth_windows':windows,'detected_windows':len(self.detected_windows) if windows else None,'served_windows':len(self.served_windows) if windows else None,
            'detection_rate':len(self.detected_windows)/windows if windows else None,'decision_rate':len(self.served_windows)/windows if windows else None,
            'starvation':{n:{'eligible_windows':self.opportunities[n],'served_windows':self.served[n],
                'service_rate':self.served[n]/self.opportunities[n] if self.opportunities[n] else None,
                'longest_wall_wait_seconds':self.longest_wait[n],'served_wait_ms':self.waits[n].result()} for n in NAMES},
            'memory_samples':self.memory,'max_retained_items':self.max_retained,'trace_ring_max':16,
            'skipped_quiescent_polls':getattr(self.worker.stop_event,'skipped',0),'adapter_tickets_after_stop':len(self.tickets)}

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path(__file__).parent/'diagnostics/skill-cooldown-phase3');a=p.parse_args(argv);a.output.mkdir(parents=True,exist_ok=True)
    profile=profile_store.active(Path(__file__).with_name('config.json'));results=[]
    with (a.output/'events.jsonl').open('w',encoding='utf-8') as f:
        write=lambda e:f.write(json.dumps(e,separators=(',',':'))+'\n')
        for strategy in ('cooldown_aware','state_transition'):
            for width in (10,20,25,40,60,100):
                for phase in (0,2,5,9):results.append(RobustBench(profile,strategy,'window',20,width,phase,writer=write).run())
            for jitter in (10,20,60,100):results.append(RobustBench(profile,strategy,'jitter',4,jitter_ms=jitter,writer=write).run())
            for error in (-200,0,200):results.append(RobustBench(profile,strategy,'error',8,error_ms=error,writer=write).run())
            for case in ('stale_available','expired_unknown','starvation','held_ready_starvation','gate_false','unknown'):
                results.append(RobustBench(profile,strategy,case,30 if 'starvation' in case else 4,writer=write).run())
            for seconds in (3600,21600,86400):
                gc.collect()
                results.append(RobustBench(profile,strategy,'long',seconds,accelerate=True,writer=write).run())
    report={'candidate_only':True,'runs':results,'socket_attempts':results[-1]['socket_attempts'],'real_udp':0}
    (a.output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    ok=not report['socket_attempts'] and all(not r['errors'] and r['residual_pending_count']==0 for r in results)
    print(json.dumps({'success':ok,'runs':len(results)}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
