"""Synthetic advisory self-check. No capture, config writes, transport or input."""
import copy,json,hashlib
from pathlib import Path
from datetime import datetime
from skill_model import SKILL_PRIORITY

def run_checks():
    import rage_rules,focus_rules,integrated_dryrun,focus_integrated_dryrun
    from advisory_messages import explain
    failures=[];passed=0;total=0
    def check(name,call,expected):
        nonlocal total,passed
        total+=1
        try:
            actual=call()
            if actual!=expected:raise AssertionError('expected %r; got %r'%(expected,actual))
            passed+=1
        except Exception as e:failures.append({'case':name,'error':str(e)[:250]})
    for character,rules_module,engine,key,label in [('warrior',rage_rules,integrated_dryrun,'rage','怒氣'),('hunter',focus_rules,focus_integrated_dryrun,'focus','集中值')]:
        def rules():
            result=rules_module.defaults()
            for n in SKILL_PRIORITY:result[n].update(enabled=True,name='離線測試_'+n)
            return result
        def snapshot(value=50):
            return {'timestamp':100.,'source':'manual_simulation','target':True,'enemy':True,'combat':True,key:value,
                    'skills':{n:{k:True for k in engine.FIELDS} for n in SKILL_PRIORITY}}
        def candidate(r,s):
            result=engine.evaluate(r,s,now=100.)
            if result.get('output_allowed') is not False:raise AssertionError('output not blocked')
            if any(k in result for k in ('command','commands','sender','action','key')):raise AssertionError('unexpected output fields')
            return result['candidate']
        for value in range(101):
            r=rules()
            for n in SKILL_PRIORITY:r[n]['enabled']=False
            for n,low,high in [('Skill_1',0,30),('Skill_2',31,69),('Skill_3',70,100)]:r[n].update(enabled=True,**{'min_'+key:low,'max_'+key:high})
            expected='Skill_1' if value<=30 else 'Skill_2' if value<=69 else 'Skill_3'
            check(f'{character}/資源{value}',lambda r=r,value=value:candidate(r,snapshot(value)),expected)
        for mask in range(1024):
            r=rules()
            for index,n in enumerate(SKILL_PRIORITY):r[n]['enabled']=bool(mask&(1<<index))
            expected=next((n for n in SKILL_PRIORITY if r[n]['enabled']),None)
            check(f'{character}/優先組合{mask}',lambda r=r:candidate(r,snapshot()),expected)
        for gate in ('target','enemy','combat'):
            for value in (False,None,0,1,'true'):
                s=snapshot();s[gate]=value
                check(f'{character}/{gate}/{value!r}',lambda s=s:candidate(rules(),s),None)
        for field in engine.FIELDS:
            for value in (False,None,0,1,'true'):
                s=snapshot();s['skills']['Skill_1'][field]=value
                check(f'{character}/{field}/{value!r}',lambda s=s:candidate(rules(),s),'Skill_2')
        for value in (None,-1,101,True,False,50.5,'50'):
            check(f'{character}/無效資源{value!r}',lambda value=value:candidate(rules(),snapshot(value)),None)
        for stamp in (97.9,100.1,float('nan'),float('inf')):
            s=snapshot();s['timestamp']=stamp
            check(f'{character}/無效時間{stamp}',lambda s=s:candidate(rules(),s),None)
        s=snapshot();s['skills']={}
        check(character+'/缺少技能證據',lambda s=s:candidate(rules(),s),None)
        r=rules();r['Skill_1'].update(**{'min_'+key:30,'max_'+key:70})
        for value,fragment in [(0,'不足'),(100,'超過設定上限')]:
            result=engine.evaluate(r,snapshot(value),now=100.)
            # Disable fallback skills so the blocked interval is the displayed reason.
            for n in SKILL_PRIORITY[1:]:r[n]['enabled']=False
            result=engine.evaluate(r,snapshot(value),now=100.)
            check(character+'/中文'+fragment,lambda result=result,value=value,fragment=fragment:fragment in explain(result,label,r,value),True)
        if character=='hunter':
            for calibrated in (None,'unverified','validated'):
                s=snapshot();s.update(source='live_pixels_partial',calibration_status=calibrated)
                check('hunter/校準'+str(calibrated),lambda s=s:candidate(rules(),s),'Skill_1' if calibrated=='validated' else None)
    modules=('resource_selfcheck.py','rage_rules.py','focus_rules.py','integrated_dryrun.py','focus_integrated_dryrun.py','advisory_messages.py','skill_model.py')
    base=Path(__file__).resolve().parent
    return {'format':'resource-selfcheck-v1','timestamp':datetime.now().astimezone().isoformat(),
            'total':total,'passed':passed,'failed':total-passed,'failures':failures,'mode':'offline_synthetic',
            'live_calibration':False,'output_allowed':False,
            'files':{name:hashlib.sha256((base/name).read_bytes()).hexdigest() for name in modules}}

if __name__=='__main__':
    import socket,subprocess
    def denied(*args,**kwargs):raise RuntimeError('離線檢查禁止網路連線與啟動子程序')
    socket.socket=denied;socket.create_connection=denied;subprocess.Popen=denied
    result=run_checks();print(json.dumps(result,ensure_ascii=True))
    raise SystemExit(bool(result['failed']))
