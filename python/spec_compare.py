"""Read-only diff of two saved specializations, never copies or switches them."""
import copy,json
import profile_store as store
import spec_data
from skill_model import SKILL_PRIORITY,GATE_NAMES
from skill_flow import modules
LABELS={'name':'技能名稱','kind':'分類','enabled':'啟用','x':'X座標','y':'Y座標','coordinate_mode':'座標系','mode':'比對方式','r':'紅','g':'綠','b':'藍','tolerance':'色差容許','threshold':'亮度門檻','sample_mode':'取樣方式','match_ratio':'符合比例','min_delay':'最短延遲','max_delay':'最長延遲','command':'固定按鍵指令','combat_mode':'開戰模式'}

def display(value):
    if isinstance(value,bool):return '啟用' if value else '停用'
    if value is None:return '未設定'
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,sort_keys=True)
    return str(value)

def projection(profile,character,spec_id):
    module,_,resource,_=modules(character);cls=profile['classes'][character];spec=cls['specs'][spec_id]
    rules=module.defaults();rules.update(copy.deepcopy(spec['metadata'].get(resource+'_advisory_v1',{})));module.validate(rules)
    result={}
    for n in SKILL_PRIORITY:
        for field,value in rules[n].items():
            label='最低資源' if field.startswith('min_') else ('最高資源' if field.startswith('max_') else LABELS.get(field,field))
            result[('按鍵'+n[6:],'資源提示／'+label)]=value
        node=copy.deepcopy(spec['nodes'][n]);node.setdefault('coordinate_mode','desktop_absolute')
        for field,value in node.items():result[('按鍵'+n[6:],'採色／'+LABELS.get(field,field))]=value
    for n in GATE_NAMES:
        node=copy.deepcopy(spec_data.resolve_gate_node(cls['shared'],spec,n));node.setdefault('coordinate_mode','desktop_absolute')
        for field,value in node.items():result[({'Node_Target':'目標','Node_Combat':'戰鬥','Node_Mark':'獵人印記'}.get(n,n),LABELS.get(field,field))]=value
    result[('共同條件','開戰模式')]=cls['shared']['combat_mode']
    for field in ('state_inputs','decision_rules','actions'):result[('額外條件',field)]=copy.deepcopy(spec.get(field))
    return result

def compare(path,profile_name,left,right):
    data=store.read(path)
    if profile_name not in data['profiles']:raise ValueError('設定檔已不存在，請重新開啟')
    p=data['profiles'][profile_name];a=projection(p,*left);b=projection(p,*right);rows=[]
    order={('按鍵'+n[6:]):i for i,n in enumerate(SKILL_PRIORITY)}
    for item,field in sorted(set(a)|set(b),key=lambda pair:(order.get(pair[0],99),pair[0],pair[1])):
        va=a.get((item,field));vb=b.get((item,field))
        if va!=vb:rows.append({'item':item,'field':field,'left':display(va),'right':display(vb)})
    return rows
