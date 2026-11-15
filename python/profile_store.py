"""Versioned profile config with migration and atomic, latest-file updates."""
import copy
import json
import os
import tempfile
import spec_data
from class_registry import CLASSES
from pathlib import Path

from mark_opener import MARK_DEFAULTS, mark_settings
from skill_model import NODE_NAMES, SKILL_PRIORITY, skill_command, GATE_NAMES

def default_nodes():
    nodes={name:{'enabled':name in GATE_NAMES,'x':0,'y':0,'threshold':200,
          'min_delay':25,'max_delay':60,'mode':'brightness',
          'r':255,'g':255,'b':255,'tolerance':20,'sample_mode':'single_pixel','match_ratio':0.30,
          'command':None if name in GATE_NAMES else skill_command(name)} for name in NODE_NAMES}
    nodes['Node_Combat'].update(mode='color',r=255,g=0,b=0)
    nodes['Node_Mark'].update(mode='color',r=0,g=255,b=0)
    return nodes

def validate_node(n):
    if not isinstance(n,dict):raise ValueError('節點必須是物件')
    # Missing mode is intentionally implicit: do not migrate/write old configs.
    if n.get('coordinate_mode','desktop_absolute') not in ('desktop_absolute','wow_client'):
        raise ValueError('Unknown coordinate_mode')
    if type(n.get('enabled')) is not bool:raise ValueError('enabled 必須是布林值')
    for k in ('x','y','threshold','min_delay','max_delay','r','g','b','tolerance'):
        if type(n.get(k)) is not int:raise ValueError(k+' 必須是整數')
    if not -100000<=n['x']<=100000 or not -100000<=n['y']<=100000:raise ValueError('座標超出範圍')
    for k in ('threshold','r','g','b','tolerance'):
        if not 0<=n[k]<=255:raise ValueError(k+' 範圍 0–255')
    if not 0<=n['min_delay']<=n['max_delay']<=60000:raise ValueError('延遲必須符合 0 ≤ Min ≤ Max ≤ 60000 ms')
    if n['mode'] not in ('brightness','red','color'):raise ValueError('未知比對模式')
    if n.get('sample_mode','single_pixel') not in ('single_pixel','3x3','5x5'):raise ValueError('Invalid sample mode')
    ratio=n.get('match_ratio',.30)
    if type(ratio) not in (int,float) or not 0<ratio<=1:raise ValueError('match_ratio must be > 0 and <= 1')
    c=n['command']
    if c is not None and (not isinstance(c,dict) or c.get('action')!='tap' or not isinstance(c.get('key'),str) or c.get('key') not in '1234567890' or len(c.get('key',''))!=1):
        raise ValueError('技能 command 僅允許固定數字 tap')
    return n

def validate_profile(p):
    if not isinstance(p,dict) or set(p.get('nodes',{}))!=set(NODE_NAMES):raise ValueError('需有完整十三個節點')
    mark_settings(p)
    if p.get('combat_mode','auto') not in ('auto','manual_first_hit'):raise ValueError('Unknown combat_mode')
    for name,n in p['nodes'].items():
        expected=None if name in GATE_NAMES else skill_command(name)
        if n.get('command')!=expected:raise ValueError(name+' command 與固定映射不符')
        try:validate_node(n)
        except (ValueError,KeyError,TypeError) as e:raise ValueError(name+': '+str(e)) from e
    return p

def migrate(data):
    if not isinstance(data,dict):raise ValueError('config 根節點必須是物件')
    result=copy.deepcopy(data) if 'profiles' in data else {'last_used':'Default','profiles':{'Default':copy.deepcopy(data)}}
    if not isinstance(result.get('profiles'),dict) or not result['profiles']:raise ValueError('至少需一個 Profile')
    for name,p in result['profiles'].items():
        validate_name(name)
        if 'classes' in p:
            spec_data.commit_view_edits(p)
            spec_data.ensure_tree(p,default_nodes());spec_data.materialize(p)
        old_nodes=p.get('nodes',{})
        if not isinstance(old_nodes,dict):raise ValueError('nodes 必須是物件')
        nodes=default_nodes()
        target=old_nodes.get('Node_Target',p.get('target'))
        if target is not None:nodes['Node_Target'].update(copy.deepcopy(target))
        nodes['Node_Target']['command']=None
        if 'Node_Combat' in old_nodes:nodes['Node_Combat'].update(copy.deepcopy(old_nodes['Node_Combat']))
        nodes['Node_Combat']['command']=None
        p.setdefault('combat_mode','auto')
        if 'Node_Mark' in old_nodes:nodes['Node_Mark'].update(copy.deepcopy(old_nodes['Node_Mark']))
        nodes['Node_Mark']['command']=None
        for key,value in MARK_DEFAULTS.items():p.setdefault(key,value)
        for skill in SKILL_PRIORITY:
            if skill in old_nodes:nodes[skill].update(copy.deepcopy(old_nodes[skill]))
            nodes[skill]['command']=skill_command(skill)  # Never trust an old/edited letter command.
        for legacy in ('hp_bar','target','skill_q','skill_e'):p.pop(legacy,None)
        p['nodes']=nodes;validate_profile(p)
        if 'classes' not in p:spec_data.upgrade_flat(p,default_nodes())
        spec_data.ensure_tree(p,default_nodes())
        for reg in CLASSES.values():
            cls=p['classes'][reg.id];mark_settings(cls['shared'])
            if cls['shared']['combat_mode'] not in ('auto','manual_first_hit'):raise ValueError('Unknown combat_mode')
            for spec in cls['specs'].values():
                for node in spec['nodes'].values():validate_node(node)
            for node in cls['shared']['nodes'].values():validate_node(node)
        spec_data.materialize(p)
    result['schema_version']=4
    if result.get('last_used') not in result['profiles']:result['last_used']=next(iter(result['profiles']))
    return result

def validate_name(name):
    if not isinstance(name,str) or not name.strip() or name!=name.strip() or len(name)>64 or any(ord(c)<32 for c in name):raise ValueError('名稱需為 1–64 字且不能包含控制字元或前後空白')
    return name

def read(path):return migrate(json.loads(Path(path).read_text(encoding='utf-8')))

def write(path,data):
    path=Path(path);data=migrate(data)
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(disk_document(data),f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def active(path):
    data=read(path);return copy.deepcopy(data['profiles'][data['last_used']])

def update_active(path,changes):
    data=read(path);p=data['profiles'][data['last_used']];spec_data.apply_changes(p,changes);validate_profile(p);write(path,data)

def select(path,name):
    data=read(path)
    if name not in data['profiles']:raise ValueError('Profile 不存在')
    data['last_used']=name;write(path,data)

def create(path,name):
    validate_name(name);data=read(path)
    if name in data['profiles']:raise ValueError('名稱已存在')
    data['profiles'][name]=copy.deepcopy(data['profiles'][data['last_used']]);data['last_used']=name;write(path,data)

def rename(path,name):
    validate_name(name);data=read(path);old=data['last_used']
    if name!=old and name in data['profiles']:raise ValueError('名稱已存在')
    data['profiles']={name if k==old else k:v for k,v in data['profiles'].items()};data['last_used']=name;write(path,data)

def delete(path):
    data=read(path)
    if len(data['profiles'])<=1:raise ValueError('不能刪除最後一個 Profile')
    del data['profiles'][data['last_used']];data['last_used']=next(iter(data['profiles']));write(path,data)

def disk_document(data):
    result=copy.deepcopy(data)
    result['profiles']={name:spec_data.disk_profile(p) for name,p in result['profiles'].items()}
    return result

def select_character(path,class_id,spec_id):
    from class_registry import spec_definition
    spec_definition(class_id,spec_id)
    data=read(path);p=data['profiles'][data['last_used']]
    p['selected_class']=class_id;p['selected_spec']=spec_id
    spec_data.materialize(p);write(path,data)
