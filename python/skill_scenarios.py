"""Synthetic scenario fixtures only; never updates saved settings."""
from skill_model import SKILL_PRIORITY
FIELDS=('visual_match','cooldown_ready','in_range','usable')
SCENARIOS=('低資源20','滿資源100','選取格冷卻中','選取格距離不足','全部條件未知')

def scenario(name,selected='Skill_1'):
    if name not in SCENARIOS or selected not in SKILL_PRIORITY:raise ValueError('未知模擬情境或技能格')
    value=20 if name=='低資源20' else (100 if name=='滿資源100' else 50)
    state=None if name=='全部條件未知' else True
    gates={k:state for k in ('target','enemy','combat')}
    signals={n:{field:state for field in FIELDS} for n in SKILL_PRIORITY}
    if name=='選取格冷卻中':signals[selected]['cooldown_ready']=False
    if name=='選取格距離不足':signals[selected]['in_range']=False
    return {'value':value,'gates':gates,'signals':signals,'source':'synthetic_scenario'}
