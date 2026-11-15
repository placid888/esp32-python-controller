"""Per-spec advisory focus rules. Never produces a command or imports transport."""
import copy
import profile_store as store
import spec_data
from skill_model import SKILL_PRIORITY
KINDS=('不分類','產生集中值','消耗集中值','防禦','位移','中斷')
def defaults():return {n:{'enabled':False,'name':'','kind':'不分類','min_focus':0,'max_focus':100} for n in SKILL_PRIORITY}
def validate(rules):
    if set(rules)!=set(SKILL_PRIORITY):raise ValueError('需要完整1至0技能條件')
    for n,r in rules.items():
        if type(r.get('enabled')) is not bool:raise ValueError('啟用必須為布林值')
        if not isinstance(r.get('name'),str) or len(r['name'])>40:raise ValueError('技能名稱最多40字')
        if r.get('kind') not in KINDS:raise ValueError('未知技能分類')
        if any(type(r.get(k)) is not int for k in ('min_focus','max_focus')) or not 0<=r['min_focus']<=r['max_focus']<=100:raise ValueError(n+'：需符合0 ≤ 最低 ≤ 最高 ≤ 100')
        if r['enabled'] and not r['name'].strip():raise ValueError(n+'：啟用提示前請填技能名稱')
    return rules

def load(path):
    d=store.read(path);p=d['profiles'][d['last_used']];identity=(d['last_used'],p['selected_class'],p['selected_spec'])
    sp=p['classes'][identity[1]]['specs'][identity[2]]
    rules=defaults();rules.update(copy.deepcopy(sp['metadata'].get('focus_advisory_v1',{})))
    return identity,validate(rules)

def save(path,identity,rules):
    validate(rules);d=store.read(path);p=d['profiles'][d['last_used']]
    if identity!=(d['last_used'],p['selected_class'],p['selected_spec']):raise ValueError('角色或專精已切換，請關閉後重開集中值設定')
    if identity[1]!='hunter':raise ValueError('此設定僅支援獵人')
    p['classes']['hunter']['specs'][identity[2]]['metadata']['focus_advisory_v1']=copy.deepcopy(rules)
    spec_data.materialize(p);store.write(path,d)

def choose(rules,focus):
    validate(rules)
    if type(focus) is not int or not 0<=focus<=100:return None
    return next((n for n in SKILL_PRIORITY if rules[n]['enabled'] and rules[n]['min_focus']<=focus<=rules[n]['max_focus']),None)

def describe(path,focus):
    identity,rules=load(path)
    if identity[1]!='hunter':return '非獵人設定，不產生提示'
    n=choose(rules,focus)
    if n is None:return '沒有符合集中值區間的提示技能（或尚未設定）'
    return '僅集中值條件符合：按鍵 '+n[6:]+'／'+rules[n]['name']+'；冷卻、距離、亮暗未判斷，不送按鍵'
