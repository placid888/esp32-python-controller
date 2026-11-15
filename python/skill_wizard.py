"""Validated single-slot setup, always disabled, isolated by profile/class/spec."""
import copy,json
from pathlib import Path
import profile_store as store,spec_data
import settings_backup as backup
from skill_flow import modules
from skill_model import SKILL_PRIORITY

def document(path):
    raw=Path(path).read_bytes();return raw,store.migrate(json.loads(raw.decode('utf-8-sig')))

def slot_from(data,key):
    if key not in SKILL_PRIORITY:raise ValueError('請選擇1至0技能格')
    p=data['profiles'][data['last_used']];identity=(data['last_used'],p['selected_class'],p['selected_spec'])
    module,_,resource,_=modules(identity[1]);spec=p['classes'][identity[1]]['specs'][identity[2]]
    rules=module.defaults();rules.update(copy.deepcopy(spec['metadata'].get(resource+'_advisory_v1',{})));module.validate(rules)
    return {'identity':identity,'key':key,'rule':copy.deepcopy(rules[key]),'node':copy.deepcopy(spec['nodes'][key])}

def load_slot(path,key):return slot_from(document(path)[1],key)

def make_draft(snapshot,name,kind,low,high,coordinates=None):
    name=name.strip()
    if not name or len(name)>40 or any(ord(c)<32 for c in name):raise ValueError('請填寫1至40字技能名稱，不含換行或控制字元')
    module,_,resource,_=modules(snapshot['identity'][1])
    rule=copy.deepcopy(snapshot['rule']);rule.update(enabled=False,name=name,kind=kind,**{'min_'+resource:low,'max_'+resource:high})
    rules=module.defaults();rules[snapshot['key']]=rule;module.validate(rules)
    node=copy.deepcopy(snapshot['node']);node['enabled']=False
    if coordinates is not None:
        if set(coordinates)!={'x','y','coordinate_mode'}:raise ValueError('座標欄位不完整')
        node.update(coordinates)
    store.validate_node(node)
    return {'rule':rule,'node':node}

def validate_draft(snapshot,draft):
    rule=draft['rule'];_,_,resource,_=modules(snapshot['identity'][1])
    expected=make_draft(snapshot,rule['name'],rule['kind'],rule['min_'+resource],rule['max_'+resource],
                        {k:draft['node'].get(k,'desktop_absolute' if k=='coordinate_mode' else None) for k in ('x','y','coordinate_mode')})
    # Normalize the legacy absent coordinate mode only for comparison.
    node=copy.deepcopy(draft['node']);node.setdefault('coordinate_mode','desktop_absolute')
    expected['node'].setdefault('coordinate_mode','desktop_absolute')
    if rule!=expected['rule'] or node!=expected['node']:raise ValueError('精靈只允許修改指定欄位，且儲存後必須停用')
    return copy.deepcopy(draft)

def save_draft(path,snapshot,draft,directory):
    validate_draft(snapshot,draft)
    raw,data=document(path);current=slot_from(data,snapshot['key'])
    if current!=snapshot:raise ValueError('此格或角色設定已變更，請重新開啟精靈，避免覆寫其他修改')
    p=data['profiles'][data['last_used']];_,_,resource,_=modules(snapshot['identity'][1])
    spec=p['classes'][p['selected_class']]['specs'][p['selected_spec']]
    module=modules(p['selected_class'])[0]
    rules=module.defaults();rules.update(copy.deepcopy(spec['metadata'].get(resource+'_advisory_v1',{})))
    rules[snapshot['key']]=copy.deepcopy(draft['rule']);module.validate(rules)
    spec['metadata'][resource+'_advisory_v1']=rules
    spec['nodes'][snapshot['key']]=copy.deepcopy(draft['node']);spec_data.materialize(p)
    payload=(json.dumps(store.disk_document(data),ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    safety=backup.create_backup(path,directory)
    if backup.digest(backup.read_backup(safety))!=backup.digest(raw):raise ValueError('設定檔已改變，未寫入；請重新開啟精靈')
    backup.replace_config(path,payload,backup.digest(raw))
    return {'backup':safety,'after_hash':backup.digest(payload)}
