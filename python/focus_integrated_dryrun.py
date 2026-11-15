"""Fail-closed advisory integration. No commands, sender, sockets, or dispatch."""
import time
from skill_model import SKILL_PRIORITY
from focus_rules import validate
FIELDS=('visual_match','cooldown_ready','in_range','usable')
def evaluate(rules,snapshot,now=None,max_age=2.0):
    validate(rules);now=time.monotonic() if now is None else now
    result={'mode':'dry_run_only','candidate':None,'blocked':{},'output_allowed':False,'source':snapshot.get('source','unknown')}
    global_reasons=[]
    if snapshot.get('source','').startswith('live') and snapshot.get('calibration_status')!='validated':global_reasons.append('focus_calibration_unknown')
    age=now-snapshot.get('timestamp',float('-inf'))
    if not 0<=age<=max_age:global_reasons.append('snapshot_stale_or_invalid')
    for k in ('target','enemy','combat'):
        if snapshot.get(k) is not True:global_reasons.append(k+('_unknown' if snapshot.get(k) is None else '_false'))
    focus=snapshot.get('focus')
    if type(focus) is not int or not 0<=focus<=100:global_reasons.append('focus_unknown')
    for n in SKILL_PRIORITY:
        r=rules[n];why=list(global_reasons)
        if not r['enabled']:why.append('rule_disabled')
        if type(focus) is int and not r['min_focus']<=focus<=r['max_focus']:why.append('focus_outside_interval')
        evidence=snapshot.get('skills',{}).get(n,{})
        for k in FIELDS:
            v=evidence.get(k)
            if v is not True:why.append(k+('_unknown' if v is None else '_false'))
        result['blocked'][n]=why
        if not why and result['candidate'] is None:result['candidate']=n
    return result

def live_result(path,result):
    import focus_rules
    identity,rules=focus_rules.load(path)
    snapshot=result.get('integrated_snapshot',{})
    if tuple(snapshot.get('identity',()))!=identity:return {'candidate':None,'output_allowed':False,'reason':'profile_changed_or_missing'}
    return evaluate(rules,snapshot)

def brief(result):
    from advisory_messages import explain
    return explain(result,'集中值')
