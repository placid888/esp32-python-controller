"""Phase5 memory-only feedback, reset proofs, and consensus research.

No transport, GUI, network or game sampling. CONFIRMED is synthetic evidence,
never a claim of an actual WoW cast. Only simulation adapter instances change.
"""
from dataclasses import dataclass,asdict
from enum import Enum
import argparse, collections, gc, heapq, json, math, uuid
from pathlib import Path
from skill_cooldown_phase4 import State,Datum,Trust
from skill_cooldown_phase3 import RobustBench,Distribution
from skill_cooldown_adapter import NAMES
from skill_simulation_bench import SimStopEvent,states
import profile_store

class Feedback(str,Enum):
    ACCEPTED='ACCEPTED';CONFIRMED='CONFIRMED';REJECTED='REJECTED';UNKNOWN='UNKNOWN'

@dataclass(frozen=True)
class Reply:
    request_id:str
    version:tuple
    sequence:int
    state:Feedback
    timestamp:float

class FeedbackSimulator:
    """One outstanding request, bounded64 terminal records; no external IO."""
    def __init__(self,session=None):
        self.session=session or uuid.uuid4().hex;self.serial=0;self.active=None
        self.records=collections.OrderedDict();self.jobs=[];self.job_serial=0
        self.confirmed=0;self.invalidated=0;self.duplicates=0;self.ignored=0
        self.halted=False;self.stopped=False;self.notifications=collections.deque()
    def issue(self,node,version,now,timeout=.5):
        if self.active or self.stopped or self.halted:raise RuntimeError('Feedback lane unavailable')
        self.serial+=1;rid=f'{self.session}:{self.serial}'
        r=dict(id=rid,node=node,version=tuple(version),issued=now,deadline=now+timeout,
               state=None,sequence=0,confirmed=False,invalidated=False)
        self.records[rid]=r;self.active=rid
        while len(self.records)>64:self.records.popitem(last=False)
        return rid
    def schedule(self,reply):
        self.job_serial+=1;heapq.heappush(self.jobs,(reply.timestamp,self.job_serial,reply))
    def unknown(self,r,reason):
        if r['confirmed'] and not r['invalidated']:self.invalidated+=1;r['invalidated']=True
        r['state']=Feedback.UNKNOWN;self.halted=True
        if self.active==r['id']:self.active=None
        self.notifications.append((r['id'],r['node'],Feedback.UNKNOWN,reason))
    def apply(self,m,now):
        if self.stopped:self.ignored+=1;return
        r=self.records.get(m.request_id)
        if r is None:self.ignored+=1;return  # unrelated ID never updates active request
        if not isinstance(m.state,Feedback) or not isinstance(m.sequence,int) or m.sequence<1 or not math.isfinite(m.timestamp) or m.timestamp<r['issued'] or m.timestamp>now+1e-12:
            self.unknown(r,'invalid_metadata');return
        if tuple(m.version)!=r['version']:self.unknown(r,'request_version_mismatch');return
        if r['state']==Feedback.UNKNOWN:self.ignored+=1;return
        if r['state'] in (Feedback.CONFIRMED,Feedback.REJECTED):
            if m.state==r['state']:self.duplicates+=1;return
            if m.state==Feedback.ACCEPTED and m.sequence<r['sequence']:self.ignored+=1;return
            self.unknown(r,'contradictory_terminal_feedback');return
        if now>=r['deadline'] or m.timestamp>=r['deadline']:
            self.unknown(r,'confirmation_timeout');return
        if m.sequence<=r['sequence']:
            if m.sequence==r['sequence'] and m.state==r['state']:self.duplicates+=1;return
            self.unknown(r,'out_of_order_feedback');return
        if m.state==Feedback.CONFIRMED and r['state']!=Feedback.ACCEPTED:
            self.unknown(r,'confirmation_without_acceptance');return
        if m.state==Feedback.ACCEPTED and r['state']==Feedback.ACCEPTED:
            r['sequence']=m.sequence;self.duplicates+=1;return
        r['state']=m.state;r['sequence']=m.sequence
        if m.state==Feedback.UNKNOWN:self.unknown(r,'explicit_unknown');return
        if m.state in (Feedback.CONFIRMED,Feedback.REJECTED):
            self.active=None
            if m.state==Feedback.CONFIRMED:r['confirmed']=True;self.confirmed+=1
            self.notifications.append((r['id'],r['node'],m.state,'validated'))
    def advance(self,now):
        while self.jobs and self.jobs[0][0]<=now+1e-12:
            delivered_at,_,m=heapq.heappop(self.jobs)
            # Heap time is the simulator's authoritative local arrival time.
            # Direct apply() also checks local now; an old remote timestamp
            # cannot revive a request that is already past its deadline.
            self.apply(m,delivered_at)
        if self.active:
            r=self.records[self.active]
            if now>=r['deadline']:self.unknown(r,'confirmation_timeout')
    def next_event(self):
        times=[self.jobs[0][0]] if self.jobs else []
        if self.active:times.append(self.records[self.active]['deadline'])
        return min(times) if times else math.inf
    def stop(self):
        if self.active:self.unknown(self.records[self.active],'stopped_with_unresolved_feedback')
        self.active=None;self.jobs.clear();self.stopped=True

class Consensus:
    """All required independent sources must be fresh and agree, no quorum fallthrough."""
    def __init__(self,sources=('ui','audit')):
        if len(set(sources))<2:raise ValueError('At least two required sources')
        self.sources=tuple(sources);self.readers={s:Trust() for s in sources};self.reason=None
        self.epochs={}
    def read(self,node,packets,now):
        values=[];versions=[];epochs=[]
        for source in self.sources:
            item=packets.get(source)
            if item is None:self.reason='source_missing:'+source;return State.UNKNOWN,None
            data,epoch=item;v=self.readers[source].read(node,data,now)
            if type(epoch) is not int or epoch<0 or epoch<self.epochs.get((source,node),-1):
                self.reason='source_epoch_regression';return State.UNKNOWN,None
            if v==State.UNKNOWN:self.reason=source+':'+self.readers[source].reason;return State.UNKNOWN,None
            self.epochs[source,node]=epoch
            values.append(v);versions.append(data.sequence);epochs.append(epoch)
        if len(set(values))!=1 or len(set(epochs))!=1:
            self.reason='source_disagreement_or_epoch_conflict';return State.UNKNOWN,None
        self.reason='all_sources_agree';return values[0],tuple(versions)+(epochs[0],)

@dataclass(frozen=True)
class ResetProof:
    kind:str
    node:str
    epoch:int
    timestamp:float
    expires:float
    nonce:str
    authorized:bool=False
    stable_cycle:bool=False
    independent_health_passes:int=0

class SafeBudget:
    """Four attempts; at most TWO explicit replenishments per node/session.

    ACCEPTED never resets it. Only validated CONFIRMED or a fresh reset proof.
    Proof authority is a synthetic harness assumption, NOT cryptographic auth.
    """
    def __init__(self,node,policy):
        if policy not in ('manual','state_cycle','health'):raise ValueError(policy)
        self.node=node;self.policy=policy;self.used=0;self.max_used=0;self.epoch=-1
        self.resets=0;self.nonces=set();self.next_try=0.
    def issue(self,now,epoch):
        if self.used>=4 or now+1e-12<self.next_try:raise RuntimeError('Budget not available')
        self.used+=1;self.max_used=max(self.max_used,self.used);self.epoch=max(self.epoch,epoch)
    def result(self,state,now):
        if state==Feedback.CONFIRMED:self.used=0;self.next_try=now
        elif state==Feedback.UNKNOWN:self.used=4;self.max_used=4
        elif state==Feedback.REJECTED:self.next_try=now+min(.8,.1*2**max(0,self.used-1))
    def reset(self,proof,now,pending=False):
        if self.used<4 or pending or self.resets>=2:return False
        if proof.kind!=self.policy or proof.node!=self.node or not proof.nonce or proof.nonce in self.nonces:return False
        if not all(math.isfinite(x) for x in (proof.timestamp,proof.expires,now)) or proof.timestamp>now or now>=proof.expires or proof.epoch<=self.epoch:return False
        valid=(proof.authorized if self.policy=='manual' else proof.stable_cycle if self.policy=='state_cycle' else proof.independent_health_passes>=2)
        if not valid:return False
        self.used=0;self.epoch=proof.epoch;self.resets+=1;self.nonces.add(proof.nonce);self.next_try=now
        return True

class FeedbackJump(SimStopEvent):
    def __init__(self,clock,end,bench):super().__init__(clock,end);self.bench=bench;self.skipped=0
    def wait(self,timeout):
        b=self.bench;w=b.worker;t=self.clock()
        if b.long_mode and not w.brain.pending and w.brain._inflight is None and not any(b.last_visible.values()):
            boundary=min(b.feedback.next_event(),max(b.game.gcd_until,b.game.cast_until))
            if boundary<=t:boundary=t+w.interval
            ticks=max(0,math.floor((min(self.end,boundary)-t)/w.interval)-1)
            if ticks>1:self.clock.advance((ticks-1)*w.interval);self.skipped+=ticks-1
        return super().wait(timeout)

class FeedbackBench(RobustBench):
    def __init__(self,profile,case='normal',policy='health',fairness='strict',duration=8,writer=None,long_mode=False):
        self.case5=case;self.policy=policy;self.fairness5=fairness;self.long_mode=long_mode
        self.feedback=FeedbackSimulator();self.consensus=Consensus();self.budgets={n:SafeBudget(n,policy) for n in NAMES}
        self.versions={};self.epoch=0;self.rr=0;self.confirmed_nodes=collections.Counter()
        self.down_since=None;self.cycle_epoch=None;self.health_since=None;self.reset_log=[]
        self.handoff_pending_max=0;self.feedback_timeout_count=0
        self.confirmation_latency=Distribution()
        self.source_version=0
        super().__init__(profile,'cooldown_aware','long' if long_mode else 'feedback5',duration,writer=writer)
        self.name=f'{case}:{policy}:{fairness}:{duration:g}'
        if long_mode:self.worker.stop_event=FeedbackJump(self.clock,duration,self)
    def fault(self,t):
        if self.case5 in ('permanent','lying_cycle'):return True
        if self.case5=='temporary':return t<2
        if self.case5=='recovery_then_fault':return t<2 or 4<=t<7
        return False
    def desired(self,t):return {n:self.case5 in ('fairness','fairness_delayed','fairness_slow','long') or n=='Skill_4' for n in NAMES}
    def deliver(self,t):
        self.feedback.advance(t)
        while self.feedback.notifications:
            rid,n,status,reason=self.feedback.notifications.popleft()
            self.budgets[n].result(status,t)
            if status==Feedback.CONFIRMED:
                self.confirmed_nodes[n]+=1
                self.confirmation_latency.add((t-self.feedback.records[rid]['issued'])*1000)
                if self.fairness5=='round_robin':self.rr=(list(NAMES).index(n)+1)%len(NAMES)
            if reason=='confirmation_timeout':self.feedback_timeout_count+=1
            self.event('FEEDBACK',request_id=rid,node=n,status=status.value,reason=reason)
    def reset_checks(self,t,agreed):
        if agreed==State.NOT_READY:
            if self.down_since is None:self.down_since=t
            if t-self.down_since>=.2:self.cycle_epoch=self.epoch
        elif agreed==State.UNKNOWN:self.down_since=None;self.cycle_epoch=None
        if not self.fault(t):
            if self.health_since is None:self.health_since=t
        else:self.health_since=None
        for n,b in self.budgets.items():
            proof=ResetProof(self.policy,n,self.epoch,t,t+.2,f'{self.policy}:{n}:{self.epoch}',
                authorized=self.policy=='manual' and self.epoch>=2 and self.epoch%2==0,
                stable_cycle=agreed==State.READY and self.cycle_epoch==self.epoch,
                independent_health_passes=2 if self.health_since is not None and t-self.health_since>=.1 else 0)
            if b.reset(proof,t,pending=self.feedback.active is not None):
                self.reset_log.append(dict(node=n,time=t,epoch=self.epoch,policy=self.policy))
                self.event('BUDGET_RESET',node=n,epoch=self.epoch,policy=self.policy)
        if agreed==State.READY:self.down_since=None;self.cycle_epoch=None
    def frame(self,t):
        if t==self.cache_time:return self.cache
        self.source_version+=1  # Never derive a unique revision from rounded float time.
        self.deliver(t)
        if self.feedback.halted:
            self.cache_time=t;self.cache=states(Node_Target='unknown');return self.cache
        self.epoch=int(t+1e-9);raw=self.desired(t)
        truth={n:raw[n] and not self.fault(t) and not self.game.unavailable(n,t,raw[n]) for n in NAMES}
        for n,ready in truth.items():
            if ready and n not in self.open:
                start=max(self.game.gcd_until,self.game.cast_until,self.game.cooldowns[n],self.game.resource_ready_at if n=='Skill_6' else 0.)
                if self.case5 in ('temporary','recovery_then_fault'):start=max(start,2 if t<4 else 7)
                self.open[n]=[start,False];self.opportunities[n]+=1;self.first_ready.setdefault(n,start)
            elif not ready and n in self.open:self.missed[n]+=int(not self.open[n][1]);del self.open[n]
        eligible=[];a_state=State.UNKNOWN
        cycle_down=self.case5 in ('lying_cycle','temporary','recovery_then_fault') and (int(t)%2==1 and t-int(t)<.4)
        for n in NAMES:
            reported=raw[n] if self.fault(t) else truth[n]
            if cycle_down:reported=False
            value=State.READY if reported else State.NOT_READY
            seq=self.source_version
            packets={s:(Datum(value,t,t+.3,seq),self.epoch) for s in self.consensus.sources}
            if self.case5=='source_conflict':packets['audit']=(Datum(State.NOT_READY,t,t+.3,seq),self.epoch)
            if self.case5=='source_expired':packets['audit']=(Datum(value,0,.01,0),self.epoch)
            if self.case5=='source_missing':packets.pop('audit')
            if self.case5=='source_reordered' and t>=.1:packets['audit']=(Datum(value,0,10,0),self.epoch)
            state,version=self.consensus.read(n,packets,t)
            if state==State.UNKNOWN:
                self.event('CONSENSUS_UNKNOWN',node=n,reason=self.consensus.reason,
                           packets={k:[asdict(v[0]),v[1]] for k,v in packets.items()},
                           latest={k:asdict(v.latest[n]) if n in v.latest else None for k,v in self.consensus.readers.items()})
                self.cache_time=t;self.cache=states(Node_Target='unknown');return self.cache
            if n=='Skill_4':a_state=state
            self.versions[n]=version
            b=self.budgets[n]
            if state==State.READY and b.used<4 and t+1e-12>=b.next_try:eligible.append(n)
        self.reset_checks(t,a_state)
        # Eligibility after a reset starts on the next fresh scan, never a shortcut.
        if self.feedback.active:chosen=None
        elif self.fairness5=='strict':chosen=eligible[0] if eligible else None
        elif eligible:chosen=next(n for n in list(NAMES)[self.rr:]+list(NAMES)[:self.rr] if n in eligible)
        else:chosen=None
        self.last_visible={n:n==chosen for n in NAMES};self.actual=truth
        self.cache_time=t;self.cache=states(**self.last_visible);return self.cache
    def send(self,command,source_node=None,schedule=None):
        w=self.worker;n=source_node;t=self.clock();self.guard.check()
        if self.stopped or self.feedback.active or w.brain._inflight!=n or self.observed_at!=t or t+1e-12<schedule['deadline']:
            raise AssertionError('Invalid feedback handoff')
        self.budgets[n].issue(t,self.epoch)
        rid=self.feedback.issue(n,self.versions[n],t,timeout=2.5 if self.case5=='fairness_slow' else .5)
        self.counts[n]+=1;self.sequence+=1
        physical=not self.fault(t) and not self.game.unavailable(n,t,self.desired(t)[n])
        if physical:
            self.accepted[n]+=1
            if n in self.open and not self.open[n][1]:self.open[n][1]=True;self.served[n]+=1;self.latency.add((t-self.open[n][0])*1000)
            anchor=self.last_service.get(n,self.first_ready.get(n,t));self.waits[n].add((t-anchor)*1000);self.longest_wait[n]=max(self.longest_wait[n],t-anchor);self.last_service[n]=t
            self.game.accept(n,t)
        else:self.rejected[n]+=1
        r=self.feedback.records[rid];ver=r['version']
        if physical:
            self.feedback.schedule(Reply(rid,ver,1,Feedback.ACCEPTED,t+.01))
            delay=2. if self.case5=='fairness_slow' else .35 if self.case5 in ('delayed','fairness_delayed') else .8 if self.case5=='timeout' else .05
            if self.case5!='lost':self.feedback.schedule(Reply(rid,ver,2,Feedback.CONFIRMED,t+delay))
            if self.case5=='duplicate':self.feedback.schedule(Reply(rid,ver,2,Feedback.CONFIRMED,t+delay+.01))
            if self.case5=='contradictory':self.feedback.schedule(Reply(rid,ver,3,Feedback.REJECTED,t+.06))
            if self.case5=='reordered':
                self.feedback.jobs.clear();self.feedback.schedule(Reply(rid,ver,2,Feedback.CONFIRMED,t+.005));self.feedback.schedule(Reply(rid,ver,1,Feedback.ACCEPTED,t+.01))
        else:self.feedback.schedule(Reply(rid,ver,1,Feedback.REJECTED,t+.01))
        self.event('REQUEST',request_id=rid,node=n,command=command,schedule=schedule,version=ver,
                   model_accepted=physical,blocked_output=True,inflight=w.brain._inflight)
        # Simulation-only local handoff: use the unchanged public reset API so
        # complete_dispatch cannot pre-arm a second command while feedback waits.
        w.brain.reset();self.handoff_pending_max=max(self.handoff_pending_max,1)
        return 1
    def observe(self,w,conditions,details):
        super().observe(w,conditions,details)
        count=len(w.brain.pending)+int(self.feedback.active is not None)
        if count>1:raise AssertionError('Combined decision+feedback pending exceeds one')
        self.handoff_pending_max=max(self.handoff_pending_max,count)
    def run(self):
        r=super().run();unresolved=int(self.feedback.active is not None);self.feedback.stop()
        while self.feedback.notifications:
            rid,n,status,reason=self.feedback.notifications.popleft();self.budgets[n].result(status,self.clock())
            self.event('FEEDBACK_CLEANUP',request_id=rid,node=n,status=status.value,reason=reason)
        if self.case5 in ('normal','delayed','duplicate','fairness','fairness_delayed','fairness_slow','long') and self.clock()!=self.duration:
            r['errors'].append('Unexpected early stop: '+str(self.consensus.reason))
        r.update(case5=self.case5,reset_policy=self.policy,fairness=self.fairness5,consensus_reason=self.consensus.reason,
            feedback_confirmed=self.feedback.confirmed,invalidated_confirmations=self.feedback.invalidated,
            trusted_confirmations=self.feedback.confirmed-self.feedback.invalidated,
            duplicate_feedback=self.feedback.duplicates,ignored_feedback=self.feedback.ignored,
            feedback_timeout_count=self.feedback_timeout_count,confirmed_per_node=dict(self.confirmed_nodes),
            combined_pending_max=self.handoff_pending_max,feedback_pending_after_stop=int(self.feedback.active is not None),
            feedback_jobs_after_stop=len(self.feedback.jobs),feedback_history_size=len(self.feedback.records),
            resets=self.reset_log,max_used=max(b.max_used for b in self.budgets.values()),
            budget_used={n:b.used for n,b in self.budgets.items()},unresolved_at_stop=unresolved,
            request_confirmation_latency_ms=self.confirmation_latency.result())
        return r

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=Path(__file__).parent/'diagnostics/skill-cooldown-phase5');a=p.parse_args(argv);a.output.mkdir(parents=True,exist_ok=True)
    profile=profile_store.active(Path(__file__).with_name('config.json'));runs=[]
    with (a.output/'events.jsonl').open('w') as f:
        writer=lambda e:f.write(json.dumps(e,separators=(',',':'))+'\n')
        for case in ('normal','delayed','lost','duplicate','reordered','contradictory','timeout','source_conflict','source_expired','source_missing','source_reordered'):
            runs.append(FeedbackBench(profile,case,duration=8,writer=writer).run())
        for policy in ('manual','state_cycle','health'):
            for case in ('permanent','temporary','recovery_then_fault','lying_cycle'):
                runs.append(FeedbackBench(profile,case,policy,duration=12,writer=writer).run())
        for fairness in ('strict','round_robin'):
            for case in ('fairness','fairness_delayed','fairness_slow'):
                runs.append(FeedbackBench(profile,case,fairness=fairness,duration=30,writer=writer).run())
            for duration in (3600,21600,86400):
                gc.collect();runs.append(FeedbackBench(profile,'long',fairness=fairness,duration=duration,writer=writer,long_mode=True).run())
    report={'candidate_only':True,'runs':runs,'socket_attempts':runs[-1]['socket_attempts'],'real_udp':0}
    (a.output/'summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    ok=not report['socket_attempts'] and all(not r['errors'] and r['combined_pending_max']<=1 and r['feedback_pending_after_stop']==0 and r['max_used']<=4 for r in runs)
    print(json.dumps({'success':ok,'runs':len(runs)}));return 0 if ok else 1
if __name__=='__main__':raise SystemExit(main())
