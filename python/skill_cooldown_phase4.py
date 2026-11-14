"""Phase 4 research adapters only. No live sampling, input or transport."""
from dataclasses import dataclass
from enum import Enum
import argparse, gc, json, math
from pathlib import Path
from skill_cooldown_phase3 import RobustBench
from skill_cooldown_adapter import NAMES
from skill_simulation_bench import states, SimStopEvent
import profile_store

class State(str,Enum):READY='READY';NOT_READY='NOT_READY';UNKNOWN='UNKNOWN'

@dataclass(frozen=True)
class Datum:
    value:State
    timestamp:float
    expires:float
    sequence:int
    conflicting:bool=False

class Trust:
    def __init__(self):self.latest={};self.reason='uninitialized'
    def read(self,key,data,now):
        if data is None:self.reason='missing';return State.UNKNOWN
        if not isinstance(data,Datum) or not isinstance(data.value,State):self.reason='invalid_type';return State.UNKNOWN
        if not all(math.isfinite(x) for x in (data.timestamp,data.expires,now)) or data.sequence<0:self.reason='invalid_metadata';return State.UNKNOWN
        previous=self.latest.get(key)
        if data.conflicting:self.reason='contradiction';return State.UNKNOWN
        if data.timestamp>now+1e-12:self.reason='future_timestamp';return State.UNKNOWN
        if data.expires<=data.timestamp or now>=data.expires:self.reason='expired';return State.UNKNOWN
        if previous and (data.sequence<previous.sequence or data.timestamp<previous.timestamp):self.reason='out_of_order';return State.UNKNOWN
        if previous and data.sequence==previous.sequence and data!=previous:self.reason='same_version_conflict';return State.UNKNOWN
        self.latest[key]=data;self.reason='explicit_unknown' if data.value==State.UNKNOWN else 'valid'
        return data.value

class Retry:
    """Four attempts per failure streak, including the initial attempt.

    Fresh READY never replenishes this budget. Success resets it; exhausted
    streak needs an explicit NEW simulation session, not an implicit data reset.
    """
    def __init__(self,mode,limit=4):
        if mode not in ('fixed','exponential','resync'):raise ValueError(mode)
        self.mode=mode;self.limit=limit;self.failures=0;self.until=0.;self.version=None;self.retries=0;self.max_failures=0
    def allowed(self,t,version):
        if self.failures>=self.limit:return False
        if not self.failures:return True
        return version!=self.version if self.mode=='resync' else t+1e-12>=self.until
    def attempted(self,t,version,accepted):
        if self.failures:self.retries+=1
        self.version=version
        if accepted:self.failures=0;self.until=0.;return
        self.failures+=1;self.max_failures=max(self.max_failures,self.failures)
        self.until=t+(.1 if self.mode=='fixed' else min(.8,.1*2**(self.failures-1)))

class ResearchJump(SimStopEvent):
    """Phase4-specific empty-poll acceleration; retry and provider wakeups count."""
    def __init__(self,clock,end,bench):super().__init__(clock,end);self.bench=bench;self.skipped=0
    def wait(self,timeout):
        b=self.bench;w=b.worker;t=self.clock()
        if not self.stopped and not w.brain.pending and w.opener.pending is None and w.brain._inflight is None and not any(b.last_visible.values()):
            desired=[n for n,v in b.desired(t).items() if v]
            if all(b.retry[n].failures>=b.retry[n].limit for n in desired):boundary=self.end
            elif all(b.packet_cache.get(n) and b.packet_cache[n].value==State.NOT_READY for n in desired) and b.scenario4 in ('long_fairness','normal'):
                # Provider truth cannot become ready before shared GCD completion.
                boundary=max(b.game.gcd_until,b.game.cast_until)
                if boundary<=t:boundary=(math.floor((t+1e-9)/.1)+1)*.1
            else:
                boundaries=[(math.floor((t+1e-9)/.1)+1)*.1]
                boundaries += [r.until for n,r in b.retry.items() if n in desired and r.failures and r.failures<r.limit and r.mode!='resync' and r.until>t]
                boundary=min(boundaries)
            ticks=max(0,math.floor((min(self.end,boundary)-t)/w.interval)-1)
            if ticks>1:self.clock.advance((ticks-1)*w.interval);self.skipped+=ticks-1
        return super().wait(timeout)

class ResearchBench(RobustBench):
    def __init__(self,profile,retry='fixed',fairness='strict',scenario='normal',duration=8,writer=None,accelerate=False):
        if fairness not in ('strict','round_robin','aging'):raise ValueError(fairness)
        self.retry_mode=retry;self.fairness=fairness;self.scenario4=scenario
        self.trust=Trust();self.retry={n:Retry(retry) for n in NAMES};self.versions={};self.rr=0;self.packet_cache={}
        self.first_rejection=None;self.recovered=None;self.last_accept=None;self.max_stall=0.
        self.trust_counts={s.value:0 for s in State};self.unknown_reason=None;self.current_choice=None
        super().__init__(profile,'cooldown_aware','long' if accelerate else 'normal4',duration,accelerate=accelerate,writer=writer)
        self.name=f'{scenario}:{retry}:{fairness}:{duration:g}'
        if accelerate:self.worker.stop_event=ResearchJump(self.clock,duration,self)
        if scenario in ('early','late','stale','recover','missing','contradictory'):self.game.gcd_until=1.
        if scenario=='permanent_lie':self.game.gcd_until=1e6
    def desired(self,t):
        return {n:self.scenario4 in ('fairness','long_fairness') or n=='Skill_4' for n in NAMES}
    def packet(self,n,t,truth):
        seq=math.floor((t+1e-9)/.1);stamp=seq*.1
        if self.scenario4=='missing':return None
        conflict=self.scenario4=='contradictory'
        if self.scenario4=='stale':return Datum(State.READY,0,.3,0)
        if n in self.packet_cache and self.packet_cache[n].sequence==seq:return self.packet_cache[n]
        if self.scenario4=='recover' and t<.7:
            data=Datum(State.READY,t,t+.3,seq);self.packet_cache[n]=data;return data
        offset=-.2 if self.scenario4=='early' else .2 if self.scenario4=='late' else 0.
        reported=truth
        if self.scenario4 in ('early','late'):
            reported=self.desired(t)[n] and t+1e-12>=max(self.game.gcd_until,self.game.cast_until,self.game.cooldowns[n])+offset and not (n=='Skill_6' and self.game.resource<40)
        if self.scenario4=='permanent_lie':reported=self.desired(t)[n]
        data=Datum(State.READY if reported else State.NOT_READY,t,t+.3,seq,conflict)
        self.packet_cache[n]=data;return data
    def frame(self,t):
        if self.cache_time==t:return self.cache
        raw=self.desired(t);truth={n:not self.game.unavailable(n,t,raw[n]) for n in NAMES}
        for n,ready in truth.items():
            if ready and n not in self.open:
                start=self.truth_boundary(n,t);self.open[n]=[start,False];self.opportunities[n]+=1;self.first_ready.setdefault(n,start)
            elif not ready and n in self.open:self.missed[n]+=int(not self.open[n][1]);del self.open[n]
        eligible=[]
        for n in NAMES:
            data=self.packet(n,t,truth[n]);state=self.trust.read(n,data,t);self.trust_counts[state.value]+=1
            if state==State.UNKNOWN:
                self.unknown_reason=self.trust.reason;self.cache_time=t;self.cache=states(Node_Target='unknown');return self.cache
            self.versions[n]=data.sequence
            if state==State.READY and self.retry[n].allowed(t,data.sequence):eligible.append(n)
        w=self.worker;pending=next(iter(w.brain.pending),None)
        if pending in eligible:chosen=pending  # Never reshuffle a valid pending delay.
        elif not eligible:chosen=None
        elif self.fairness=='strict':chosen=eligible[0]
        elif self.fairness=='round_robin':chosen=next(n for n in list(NAMES)[self.rr:]+list(NAMES)[:self.rr] if n in eligible)
        else:chosen=min(eligible,key=lambda n:(self.last_service.get(n,self.first_ready.get(n,t)),list(NAMES).index(n)))
        visible={n:n==chosen for n in NAMES};self.current_choice=chosen
        self.actual=truth;self.last_visible=visible;self.cache_time=t;self.cache=states(**visible);return self.cache
    def send(self,command,source_node=None,schedule=None):
        n=source_node;t=self.clock();count=self.accepted[n]
        result=super().send(command,source_node,schedule);ok=self.accepted[n]>count
        if not ok and self.first_rejection is None:self.first_rejection=t
        if ok:
            if self.first_rejection is not None and self.recovered is None:self.recovered=t
            anchor=self.last_accept if self.last_accept is not None else 0.;self.max_stall=max(self.max_stall,t-anchor);self.last_accept=t
            if self.fairness=='round_robin':self.rr=(list(NAMES).index(n)+1)%len(NAMES)
        self.retry[n].attempted(t,self.versions[n],ok)
        self.event('RETRY_STATE',node=n,model_accepted=ok,failures=self.retry[n].failures,
                   limit=self.retry[n].limit,next_retry=self.retry[n].until,version=self.versions[n],mode=self.retry_mode)
        return result
    def run(self):
        r=super().run();self.max_stall=max(self.max_stall,self.clock()-(self.last_accept if self.last_accept is not None else 0.))
        r.update(retry_strategy=self.retry_mode,fairness=self.fairness,scenario4=self.scenario4,
            retry_count=sum(x.retries for x in self.retry.values()),max_failure_streak=max(x.max_failures for x in self.retry.values()),
            exhausted_nodes=[n for n,x in self.retry.items() if x.failures>=x.limit],
            recovery_time_seconds=self.recovered-self.first_rejection if self.recovered is not None else None,
            recovery_absolute_time=self.recovered,longest_stall_seconds=self.max_stall,
            trusted_states=self.trust_counts,unknown_reason=self.unknown_reason,
            starvation_events={n:int(v['longest_wall_wait_seconds']>=5) for n,v in r['starvation'].items()})
        return r

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path(__file__).parent/'diagnostics/skill-cooldown-phase4');a=p.parse_args(argv);a.output.mkdir(parents=True,exist_ok=True)
    profile=profile_store.active(Path(__file__).with_name('config.json'));runs=[]
    with (a.output/'events.jsonl').open('w') as f:
        writer=lambda e:f.write(json.dumps(e,separators=(',',':'))+'\n')
        for retry in ('fixed','exponential','resync'):
            for case in ('early','late','permanent_lie','stale','recover','missing','contradictory','normal'):
                runs.append(ResearchBench(profile,retry,'strict',case,8,writer).run())
        for fairness in ('strict','round_robin','aging'):
            runs.append(ResearchBench(profile,'fixed',fairness,'fairness',60,writer).run())
        for retry,fairness in zip(('fixed','exponential','resync'),('strict','round_robin','aging')):
            for duration in (3600,21600,86400):
                gc.collect();runs.append(ResearchBench(profile,retry,fairness,'long_fairness',duration,writer,True).run())
            runs.append(ResearchBench(profile,retry,fairness,'permanent_lie',86400,writer,True).run())
    report={'runs':runs,'candidate_only':True,'real_udp':0,'socket_attempts':runs[-1]['socket_attempts']}
    (a.output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    ok=not report['socket_attempts'] and all(not x['errors'] and x['residual_pending_count']==0 and x['max_failure_streak']<=4 for x in runs)
    print(json.dumps({'success':ok,'runs':len(runs)}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
