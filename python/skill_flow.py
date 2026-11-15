"""Pure manual skill-flow projection. Categories are labels, never automatic gates."""
import copy
from skill_model import SKILL_PRIORITY
from advisory_messages import reason_text

def modules(character):
    if character=='warrior':
        import rage_rules as rules,integrated_dryrun as engine
        return rules,engine,'rage','怒氣'
    if character=='hunter':
        import focus_rules as rules,focus_integrated_dryrun as engine
        return rules,engine,'focus','集中值'
    raise ValueError('請先選擇戰士或獵人')

def demo_rules(character):
    module,_,key,_=modules(character);rules=module.defaults()
    kinds=('產怒','消怒','防禦','位移','中斷') if character=='warrior' else ('產生集中值','消耗集中值','防禦','位移','中斷')
    for index,kind in enumerate(kinds):
        name=SKILL_PRIORITY[index];low,high=(0,39) if index==0 else ((40,100) if index==1 else (0,100))
        rules[name].update(enabled=True,name='示範：'+kind,kind=kind,**{'min_'+key:low,'max_'+key:high})
    return rules

def preview(character,rules,value,gates,signals):
    module,engine,key,label=modules(character);module.validate(rules)
    if type(value) is not int or not 0<=value<=100:raise ValueError(label+'需為0至100整數')
    snapshot={'timestamp':100.,'source':'manual_flow_preview',key:value,'skills':copy.deepcopy(signals),**{k:gates.get(k) for k in ('target','enemy','combat')}}
    result=engine.evaluate(rules,snapshot,now=100.)
    rows=[]
    for rank,n in enumerate(SKILL_PRIORITY,1):
        rule=rules[n];codes=result['blocked'][n]
        if not rule['enabled']:state='提示停用';reasons=['此格的資源提示未啟用']
        elif n==result['candidate']:state='本次候選';reasons=['目前手動條件符合，且在符合者中優先序最高；不送按鍵。']
        elif not codes:state='符合但順位較後';reasons=['條件符合，但前面已有優先候選；不送按鍵。']
        else:state='被阻擋';reasons=[reason_text(code,label,rule,value) for code in codes]
        rows.append({'node':n,'priority':rank,'name':rule['name'] or '未命名','kind':rule['kind'],
                     'interval':f"{rule['min_'+key]}–{rule['max_'+key]}",'state':state,'reasons':reasons})
    return {'candidate':result['candidate'],'rows':rows,'output_allowed':False,'source':'manual_flow_preview'}
