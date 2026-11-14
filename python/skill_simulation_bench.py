"""Production DetectorWorker.run with synthetic pixels/time and an output-only sink.

No GUI/vision/transport imports. No live window queries, sockets or game input.
All enabling and 40ms delay fixtures affect a deepcopy, never the formal config.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
from detector import DetectorWorker
from decision import DecisionEngine
from output_guard import install_process_output_guard
from skill_model import SKILL_PRIORITY, GATE_NAMES
from wow_window import WindowError
import profile_store


class SimClock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, seconds):
        if seconds < 0: raise ValueError('Clock cannot move backwards')
        self.now += seconds


class SimStopEvent:
    """Same run-loop wait deadlines; only wall-clock waiting is substituted.

    A zero wait advances 1ns (scheduler progress), never fires a positive delay
    early. The endpoint is exclusive, as a stop arriving at that time would be.
    """
    def __init__(self, clock, end): self.clock=clock; self.end=end; self.stopped=False
    def is_set(self): return self.stopped
    def set(self): self.stopped=True
    def wait(self, timeout):
        if not self.stopped:
            self.clock.advance(min(max(timeout, 1e-9), max(0, self.end-self.clock())))
            if self.clock() >= self.end: self.set()
        return self.stopped


def states(**changes):
    return {**{n: True for n in GATE_NAMES}, **{n: False for n in SKILL_PRIORITY}, **changes}


class SyntheticVision:
    def __init__(self, nodes, clock, timeline):
        self.names={node['x']:name for name,node in nodes.items()}
        self.clock=clock; self.timeline=timeline; self.closed=False
    def get_region_rgb(self, x, y, size):
        frame=self.timeline(self.clock())
        if frame.get('window_error'): raise WindowError('not_found','Synthetic invalid WoW window')
        value=frame.get(self.names[x], False)
        if value == 'unknown': raise WindowError('sampling_unknown','Synthetic unknown '+self.names[x])
        if type(value) is not bool: raise ValueError('Synthetic states must be bool or unknown')
        return [(255,255,255) if value else (0,0,0)] * (size*size)
    def close(self): self.closed=True


class Bench:
    def __init__(self, profile, name, duration, timeline, enabled=('Skill_4',),
                 writer=None, min_delay=40, max_delay=40, seed=17):
        self.guard=install_process_output_guard();self.guard.check()
        if duration <= 0: raise ValueError('Positive duration required')
        self.profile=copy.deepcopy(profile);self.name=name;self.duration=duration
        self.clock=SimClock();self.writer=writer;self.timeline=timeline
        self.conditions=None;self.details=None;self.observed_at=None;self.fingerprint=None
        self.counts={n:0 for n in (*SKILL_PRIORITY,'Opener_Mark')};self.last={};self.intervals={}
        self.delays={};self.recent=[];self.max_pending=0;self.unknowns=0;self.errors=[]
        self.unexpected=0;self.stopped=False;self.expected_error=None;self.sequence=0
        self.inflight_observed=0;self.inflight_leaked=False
        nodes=self.profile['nodes']
        for i,(name,node) in enumerate(nodes.items()):
            node.update(x=i,y=0,coordinate_mode='desktop_absolute',mode='brightness',threshold=200,
                        min_delay=min_delay,max_delay=max_delay,sample_mode='single_pixel',
                        enabled=name in GATE_NAMES or name in enabled)
        self.vision=SyntheticVision(nodes,self.clock,timeline)
        self.worker=DetectorWorker(nodes,self.send,lambda:self.vision,clock=self.clock,
            combat_mode='manual_first_hit',hunter_mark_mode='pre_combat',
            hunter_mark_key='3',hunter_mark_retry_ms=500,output_observer=self)
        # Use the real engine with a local reproducible random source; no global
        # random/time monkeypatching and no change to the production bounds logic.
        self.worker.brain=DecisionEngine(clock=self.clock,randint=random.Random(seed).randint)
        self.worker.stop_event=SimStopEvent(self.clock,duration)
        self.worker.started=0
    def event(self,event,**fields):
        record={'scenario':self.name,'simulated_time':self.clock(),'event':event,
                'output_mode':'dry_run','blocked':True,**fields}
        if self.writer:self.writer(record)
        return record
    def track_pending(self,w):
        count=len(w.brain.pending)+int(w.opener.pending is not None)
        self.max_pending=max(self.max_pending,count)
        if len(w.brain.pending)>1:raise AssertionError('Multiple normal pending events')
    def verify_sampling_surface(self,w,vision):
        self.guard.check()  # Synthetic fixture only: no real OS or pixel reads.
    def observe(self,w,conditions,details):
        self.conditions=copy.deepcopy(conditions);self.details=details;self.observed_at=self.clock()
        self.track_pending(w)
        if w.brain._inflight is not None:self.inflight_leaked=True;raise AssertionError('In-flight leaked between scans')
        fp=json.dumps(conditions,sort_keys=True)
        if fp!=self.fingerprint:
            self.event('STATE',conditions=conditions,normal_gate=w.normal_allowed(conditions),
                       opener_gate=w.opener_allowed(conditions),reason=w.gate_reason(conditions))
            self.fingerprint=fp
    def unknown(self,w,exc):
        self.unknowns+=1;self.conditions=None;self.observed_at=None
        self.expected_error=getattr(exc,'code',type(exc).__name__)
        self.event('UNKNOWN',reason=self.expected_error,conditions='unknown')
    def send(self,command,source_node=None,schedule=None):
        """Accept only a local simulated submission; no transport module exists."""
        self.guard.check();w=self.worker;self.track_pending(w)
        if self.stopped or w.stop_event.is_set() or self.observed_at!=self.clock() or self.conditions is None:
            self.unexpected+=1;raise AssertionError('Output without fresh valid running scan')
        # The real step constructed this command; audit, do not select a command.
        if source_node in SKILL_PRIORITY:
            if w.brain._inflight!=source_node:raise AssertionError('Missing production in-flight state')
            self.inflight_observed+=1
        n=source_node;t=self.clock();previous=self.last.get(n)
        if previous is not None:self.intervals.setdefault(n,[]).append((t-previous)*1000)
        self.last[n]=t;self.counts[n]+=1
        delay=schedule['chosen_delay_ms'];self.delays.setdefault(n,[]).append(delay)
        if t+1e-12 < schedule['deadline']:raise AssertionError('Output before actual deadline')
        self.sequence+=1
        record=self.event('WOULD_SEND',event_id=self.name+':'+str(self.sequence),node=n,command=command,
            conditions=self.conditions,skill_states={k:self.conditions.get(k,'not_sampled') for k in SKILL_PRIORITY},
            normal_gate=w.normal_allowed(self.conditions),opener_gate=w.opener_allowed(self.conditions),
            reason='mark_opener_due' if n=='Opener_Mark' else 'normal_skill_due',schedule=schedule,
            would_send=True,blocked_output=True,pending_count=len(w.brain.pending)+int(w.opener.pending is not None),
            inflight=w.brain._inflight)
        self.recent.append(record)
        if len(self.recent)>20:self.recent.pop(0)
        return 1  # Same local-accept truth value; never a remote delivery claim.
    def run(self):
        if self.stopped:raise RuntimeError('Restart creates a new Bench/worker session')
        self.event('START',requested_duration=self.duration)
        self.worker.run()  # Reuse production loop, scan, Gate, Opener, poll and cleanup.
        self.stopped=True;w=self.worker;self.guard.check()
        while not w.events.empty():
            e=w.events.get_nowait()
            if e['event']=='DETECTOR_ERROR':
                if self.expected_error:self.event('EXPECTED_STOP',detector_event=e)
                else:self.errors.append(e['message'])
        if w.brain.pending or w.opener.pending is not None or w.brain._inflight is not None:
            self.errors.append('Residual pending/inflight after stop')
        if not self.vision.closed:self.errors.append('Synthetic vision was not closed')
        self.event('STOP',reason=self.expected_error or 'duration_elapsed')
        minimum={n:min(v) for n,v in self.intervals.items() if v}
        maximum={n:max(v) for n,v in self.intervals.items() if v}
        result=dict(scenario=self.name,simulated_duration=self.clock(),requested_duration=self.duration,
            scan_count=w.scan_count,decision_count=sum(self.counts.values()),blocked_output_count=sum(self.counts.values()),
            per_skill_count=self.counts,minimum_interval_ms=minimum,maximum_interval_ms=maximum,
            maximum_pending_count=self.max_pending,unknown_count=self.unknowns,cancelled_pending_count=w.cancel_count,
            unexpected_output_count=self.unexpected,errors=self.errors,stop_reason=self.expected_error or 'duration_elapsed',
            residual_pending_count=len(w.brain.pending)+int(w.opener.pending is not None),
            inflight_after_stop=w.brain._inflight,inflight_observed=self.inflight_observed,
            inflight_leaked=self.inflight_leaked,socket_attempts=len(self.guard.attempts),
            delay_ranges_ms={n:[min(v),max(v)] for n,v in self.delays.items() if v})
        return result


def scenarios():
    alternating=lambda t:states(**{n:i==int(t/.2)%len(SKILL_PRIORITY) for i,n in enumerate(SKILL_PRIORITY)})
    return [
        ('all_gates_false',2,lambda t:states(**{n:False for n in GATE_NAMES})),
        ('mark_missing_retry',3,lambda t:states(Node_Mark=False)),
        ('combat_false',2,lambda t:states(Node_Combat=False,Skill_4=True)),
        ('single_repeat',2,lambda t:states(Skill_4=True)),
        ('false_true',2,lambda t:states(Skill_4=t>=.2)),
        ('two_priority',2,lambda t:states(Skill_4=True,Skill_5=True)),
        ('alternating',7,alternating),
        ('gate_cancel_during_delay',1,lambda t:states(Node_Target=t<.02,Skill_4=True)),
        ('sampling_unknown',1,lambda t:states(Skill_4=True,Node_Target='unknown' if t>=.02 else True)),
        ('window_invalid',1,lambda t:dict(states(Skill_4=True),window_error=t>=.02)),
        *[(f'long_repeat_{duration}s',duration,lambda t:states(Skill_4=True)) for duration in (30,300,1800)],
    ]


def main(argv=None):
    # Opt-in simulation-only adapter; default benchmark behavior is unchanged.
    import sys
    arguments=list(sys.argv[1:] if argv is None else argv)
    if '--cooldown-comparison' in arguments:
        arguments.remove('--cooldown-comparison')
        from skill_cooldown_adapter import main as cooldown_main
        return cooldown_main(arguments)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path(__file__).parent/'diagnostics/skill-bench')
    args=parser.parse_args(argv);args.output.mkdir(parents=True,exist_ok=True)
    config=Path(__file__).with_name('config.json');before=config.read_bytes()
    profile=profile_store.active(config);results=[]
    # Opening with 'w' makes repeat execution independent of preceding results.
    with (args.output/'events.jsonl').open('w',encoding='utf-8') as stream:
        def write(record):stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
        for name,duration,timeline in scenarios():
            enabled=SKILL_PRIORITY if name in ('alternating','two_priority') else ('Skill_4',)
            results.append(Bench(profile,name,duration,timeline,enabled,write).run())
        for i in range(3):results.append(Bench(profile,f'restart_{i}',.15,lambda t:states(Skill_4=True),writer=write).run())
    unchanged=before==config.read_bytes()
    report={'runs':results,'config_unchanged':unchanged,'config_sha256':hashlib.sha256(before).hexdigest(),
            'output':'BLOCKED / synthetic sink only','real_udp_transmissions':0,
            'socket_guard_attempts':len(install_process_output_guard().attempts),
            'formal_skill_enabled':{n:profile['nodes'][n]['enabled'] for n in SKILL_PRIORITY},
            'limitations':'Simulated-time decision correctness, not OS scheduling, real RGB, remote ACK, or physical throughput.'}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    ok=unchanged and not report['socket_guard_attempts'] and all(not r['errors'] and not r['unexpected_output_count'] for r in results)
    print(json.dumps({'runs':len(results),'success':ok,'output':str(args.output)},ensure_ascii=False))
    return 0 if ok else 1


if __name__=='__main__':raise SystemExit(main())
