"""Candidate strategies ONLY. Synthetic cooldowns are not WoW facts or live APIs."""
import argparse
import json
from pathlib import Path
from skill_simulation_bench import Bench, states
import profile_store

NAMES={'Skill_4':'Skill_A','Skill_5':'Skill_B','Skill_6':'Skill_C','Skill_7':'Skill_D'}


class SyntheticGame:
    """Seconds; shared 1.5s GCD, B=6s CD, C=40 resource, D=2s cast.

    Resources: initial20, max100, regenerate10/s. All assumed test data.
    B cooldown starts on accepted decision; D cast starts immediately and blocks
    new decisions until completion (GCD overlaps cast). No real-game inference.
    """
    def __init__(self, passive=False):
        self.gcd_until=0.;self.cooldowns={n:0. for n in NAMES};self.cast_until=0.
        self.resource=20.;self.last_time=0.;self.passive=passive
        self.resource_ready_at=2.
    def tick(self,t):
        if t<self.last_time:raise ValueError('Time reversal')
        self.resource=min(100.,self.resource+(t-self.last_time)*10);self.last_time=t
    def unavailable(self,n,t,desired=True):
        self.tick(t);why=[]
        if not desired:why.append('signal_unavailable')
        if not self.passive:
            if t+1e-12<self.gcd_until:why.append('gcd')
            if t+1e-12<self.cast_until:why.append('casting')
            if t+1e-12<self.cooldowns[n]:why.append('individual_cooldown')
            if n=='Skill_6' and self.resource+1e-9<40:why.append('resource')
        return why
    def accept(self,n,t):
        if self.passive:return
        self.gcd_until=t+1.5
        if n=='Skill_5':self.cooldowns[n]=t+6
        if n=='Skill_6':
            self.resource-=40
            if self.resource<40:self.resource_ready_at=t+(40-self.resource)/10
        if n=='Skill_7':self.cast_until=t+2


def workload(name,t):
    all_false={n:False for n in NAMES}
    def selected(*names):return {**all_false,**{n:True for n in names}}
    if name=='mixed':return selected(tuple(NAMES)[int(t/3)%4])
    if name=='two_available':return selected('Skill_4','Skill_5')
    if name=='multiple_priority':return {n:True for n in NAMES}
    if name in ('single_available','gcd_becomes_available','persistent_available','gate_false','unknown','short_window'):return selected('Skill_4')
    if name=='cooldown_completion':return selected('Skill_5')
    if name=='resource_recovery':return selected('Skill_6')
    if name=='casting':return selected('Skill_7')
    raise ValueError('Unknown workload '+name)


class StrategyBench(Bench):
    def __init__(self,profile,strategy,duration,scenario='mixed',writer=None):
        if strategy not in ('fixed_40','fixed_100','fixed_250','fixed_500','cooldown_aware','state_transition'):
            raise ValueError('Unknown strategy')
        self.strategy=strategy;self.scenario=scenario;self.game=SyntheticGame(passive=scenario=='persistent_available')
        if scenario=='gcd_becomes_available':self.game.gcd_until=1.
        if scenario=='casting':self.game.cast_until=1.
        self.cache_time=None;self.cache=None;self.previous={n:False for n in NAMES};self.tickets=set()
        self.open={};self.missed=0;self.latencies=[];self.accepted={n:0 for n in NAMES};self.suppressed=0
        self.reason_counts={};self.all_times=[];self.accepted_times=[];self.candidate_log=[]
        delay=int(strategy.split('_')[1]) if strategy.startswith('fixed_') else 40
        super().__init__(profile,f'{scenario}:{strategy}:{duration:g}s',duration,self.frame,
                         enabled=tuple(NAMES),writer=writer,min_delay=delay,max_delay=delay)
    def signals(self,t):
        raw=workload(self.scenario,t)
        if self.scenario=='gcd_becomes_available':raw['Skill_4']=t>=.3
        if self.scenario=='short_window':raw['Skill_4']=t<.025
        return raw
    def update_opportunities(self,t,raw,gate):
        for n in NAMES:
            ready=gate and not self.game.unavailable(n,t,raw[n])
            if ready and n not in self.open:
                # Known analytic readiness boundary, not the later polling time.
                signal_start=(int(t/3)*3 if self.scenario=='mixed' else
                              .3 if self.scenario=='gcd_becomes_available' else 0.)
                boundary=signal_start if self.game.passive else max(signal_start,self.game.gcd_until,
                    self.game.cast_until,self.game.cooldowns[n],
                    self.game.resource_ready_at if n=='Skill_6' else 0.)
                self.open[n]=[boundary,False]
            if not ready and n in self.open:
                self.missed+=int(not self.open[n][1]);del self.open[n]
    def frame(self,t):
        if t==self.cache_time:return self.cache
        raw=self.signals(t);gate=self.scenario!='gate_false'
        if self.scenario=='unknown' and t>=.02:
            self.cache_time=t;self.cache=states(Node_Target='unknown');return self.cache
        self.update_opportunities(t,raw,gate)
        ready={n:gate and not self.game.unavailable(n,t,raw[n]) for n in NAMES}
        if self.strategy=='state_transition':
            for n,value in ready.items():
                if value and not self.previous[n]:self.tickets.add(n)
                if not value:self.tickets.discard(n)
            self.previous=ready
            visible={n:n in self.tickets for n in NAMES}
        elif self.strategy=='cooldown_aware':visible=ready
        else:visible=raw
        # C tickets survive delay until decision or readiness falls, not one-frame
        # pulses (which would be cancelled by the real engine's expiry recheck).
        self.cache=states(Node_Target=gate,**visible);self.cache_time=t
        return self.cache
    def send(self,command,source_node=None,schedule=None):
        # Original production step constructs every candidate and enforces delay.
        accepted_local=super().send(command,source_node,schedule)
        t=self.clock();raw=self.signals(t);n=source_node
        why=self.game.unavailable(n,t,raw[n]);accepted=not why
        self.all_times.append(t)
        if accepted:
            self.accepted[n]+=1;self.accepted_times.append(t)
            if n in self.open and not self.open[n][1]:
                self.latencies.append((t-self.open[n][0])*1000);self.open[n][1]=True
            self.game.accept(n,t)
        else:
            self.suppressed+=1
            for reason in why:self.reason_counts[reason]=self.reason_counts.get(reason,0)+1
        if self.strategy=='state_transition':self.tickets.discard(n)
        record={'node':n,'skill':NAMES[n],'accepted_by_synthetic_model':accepted,
                'suppressed_reasons':why,'game':{'gcd_until':self.game.gcd_until,
                'cast_until':self.game.cast_until,'cooldown_until':self.game.cooldowns[n],
                'resource':self.game.resource},'simulated_time':t}
        self.event('MODEL_DECISION',**record);self.candidate_log.append(record)
        return accepted_local  # local sink acceptance != synthetic cast acceptance
    def run(self):
        r=super().run()
        # Right-censored, unserved windows at Stop are reported, not silently lost.
        missed=self.missed+sum(not served for _,served in self.open.values())
        avg=lambda values:sum(values)/len(values) if values else None
        intervals=[(b-a)*1000 for a,b in zip(self.all_times,self.all_times[1:])]
        r.update(strategy=self.strategy,workload=self.scenario,total_decisions=r['decision_count'],
                 accepted_decisions=sum(self.accepted.values()),suppressed_decisions=self.suppressed,
                 per_skill_count={NAMES[n]:r['per_skill_count'][n] for n in NAMES},
                 per_skill_accepted={NAMES[n]:v for n,v in self.accepted.items()},
                 average_decision_interval_ms=avg(intervals),
                 earliest_available_to_decision_latency_ms={'mean':avg(self.latencies),
                    'max':max(self.latencies) if self.latencies else None,'samples':len(self.latencies)},
                 missed_opportunities=missed,maximum_pending=r['maximum_pending_count'],
                 suppressed_reasons=self.reason_counts)
        assert r['total_decisions']==r['accepted_decisions']+r['suppressed_decisions']
        return r


STRATEGIES=('fixed_40','fixed_100','fixed_250','fixed_500','cooldown_aware','state_transition')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=Path(__file__).parent/'diagnostics/skill-cooldown-bench')
    args=p.parse_args(argv);args.output.mkdir(parents=True,exist_ok=True)
    path=Path(__file__).with_name('config.json');original=path.read_bytes();profile=profile_store.active(path)
    baselines=[];results=[]
    with (args.output/'events.jsonl').open('w',encoding='utf-8') as f:
        def write(e):f.write(json.dumps(e,ensure_ascii=False,separators=(',',':'))+'\n')
        for duration,expected in ((30,749),(300,7499),(1800,44999)):
            b=Bench(profile,f'baseline_{duration}',duration,lambda t:states(Skill_4=True),writer=write)
            r=b.run();r['expected_decisions']=expected;r['reproduced']=r['decision_count']==expected;baselines.append(r)
        for duration in (30,300,1800):
            for strategy in STRATEGIES:
                results.append(StrategyBench(profile,strategy,duration,writer=write).run())
        for scenario in ('single_available','two_available','gcd_becomes_available','cooldown_completion',
                         'resource_recovery','casting','gate_false','unknown','multiple_priority','persistent_available','short_window'):
            for strategy in STRATEGIES:results.append(StrategyBench(profile,strategy,8,scenario,write).run())
        for strategy in STRATEGIES:
            for i in range(2):results.append(StrategyBench(profile,strategy,.3,'persistent_available',write).run())
    report={'baseline':baselines,'runs':results,'config_unchanged':original==path.read_bytes(),
            'candidate_only':True,'real_udp':0,'socket_attempts':len(b.guard.attempts)}
    (args.output/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    ok=report['config_unchanged'] and not report['socket_attempts'] and all(r['reproduced'] for r in baselines) and all(not r['errors'] for r in results)
    print(json.dumps({'success':ok,'baseline_runs':len(baselines),'strategy_runs':len(results)},ensure_ascii=False))
    return 0 if ok else 1

if __name__=='__main__':raise SystemExit(main())
