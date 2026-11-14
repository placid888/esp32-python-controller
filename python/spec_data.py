"""Canonical per-profile tree and detached legacy runtime view. No dispatch logic."""
import copy,hashlib,json
from class_registry import CLASSES,MIGRATION_CLASS,MIGRATION_SPEC,definition,spec_definition
from skill_model import SKILL_PRIORITY,GATE_NAMES,NODE_NAMES,skill_command
from mark_opener import MARK_DEFAULTS
COMBAT_KEYS=('combat_mode',)+tuple(MARK_DEFAULTS)
CANONICAL=('profile_version','selected_class','selected_spec','global','classes')

def gate_override(spec,name):
    """Absent override remains absent on disk. Only gate-node field patches allowed."""
    overrides=spec.get('node_overrides',{})
    if not isinstance(overrides,dict) or any(n not in GATE_NAMES for n in overrides):
        raise ValueError('node_overrides must contain gate node names only')
    allowed={'enabled','x','y','threshold','min_delay','max_delay','mode','r','g','b',
             'tolerance','sample_mode','match_ratio','command','coordinate_mode'}
    for patch in overrides.values():
        if not isinstance(patch,dict) or any(k not in allowed for k in patch):
            raise ValueError('Invalid gate override fields')
        if 'command' in patch and patch['command'] is not None:
            raise ValueError('Gate override command must remain null')
    return overrides.get(name,{})

def resolve_gate_node(shared,spec,name,defaults=None):
    if defaults is None:
        from profile_store import default_nodes
        defaults=default_nodes()
    node=copy.deepcopy(defaults[name])
    node.update(copy.deepcopy(shared.get('nodes',{}).get(name,{})))
    node.update(copy.deepcopy(gate_override(spec,name)))
    from profile_store import validate_node
    validate_node(node)
    if node.get('command') is not None:raise ValueError('Gate command must remain null')
    return node
def fresh_spec(defaults):
    return {'nodes':{n:copy.deepcopy(defaults[n]) for n in SKILL_PRIORITY},'state_inputs':{},'decision_rules':[],'actions':[],'metadata':{}}
def fresh_class(reg,defaults):
    return {'shared':{'nodes':{n:copy.deepcopy(defaults[n]) for n in GATE_NAMES},'combat_mode':'auto',**MARK_DEFAULTS},
            'specs':{s.id:fresh_spec(defaults) for s in reg.specs}}
def upgrade_flat(p,defaults):
    original=copy.deepcopy(p)
    classes={reg.id:fresh_class(reg,defaults) for reg in CLASSES.values()}
    cls=classes[MIGRATION_CLASS];cls['shared']['nodes']={n:copy.deepcopy(p['nodes'][n]) for n in GATE_NAMES}
    for k in COMBAT_KEYS:cls['shared'][k]=copy.deepcopy(p[k])
    cls['specs'][MIGRATION_SPEC]['nodes']={n:copy.deepcopy(p['nodes'][n]) for n in SKILL_PRIORITY}
    p.update(profile_version=2,selected_class=MIGRATION_CLASS,selected_spec=MIGRATION_SPEC,
             classes=classes,**{'global':{k:v for k,v in original.items() if k not in ('nodes',)+COMBAT_KEYS}})
def ensure_tree(p,defaults):
    for reg in CLASSES.values():
        cls=p['classes'].setdefault(reg.id,fresh_class(reg,defaults));shared=cls.setdefault('shared',{})
        shared.setdefault('nodes',{})
        for name in GATE_NAMES:
            n=copy.deepcopy(defaults[name]);n.update(shared['nodes'].get(name,{}));n['command']=None;shared['nodes'][name]=n
        shared.setdefault('combat_mode','auto')
        for k,v in MARK_DEFAULTS.items():shared.setdefault(k,v)
        specs=cls.setdefault('specs',{})
        for spec in reg.specs:
            saved=specs.setdefault(spec.id,fresh_spec(defaults));saved.setdefault('nodes',{})
            for name in GATE_NAMES:resolve_gate_node(shared,saved,name,defaults)
            for name in SKILL_PRIORITY:
                n=copy.deepcopy(defaults[name]);n.update(saved['nodes'].get(name,{}));n['command']=skill_command(name);saved['nodes'][name]=n
            for k,v in fresh_spec(defaults).items():saved.setdefault(k,copy.deepcopy(v))
    p.setdefault('global',{});p['profile_version']=2
    definition(p['selected_class']);spec_definition(p['selected_class'],p['selected_spec'])
def materialize(p):
    base={k:copy.deepcopy(p[k]) for k in CANONICAL}
    cls=base['classes'][base['selected_class']];shared=cls['shared'];spec=cls['specs'][base['selected_spec']]
    view={k:copy.deepcopy(v) for k,v in base['global'].items() if k not in CANONICAL};view.update({k:copy.deepcopy(shared[k]) for k in COMBAT_KEYS})
    view['nodes']={n:resolve_gate_node(shared,spec,n) if n in GATE_NAMES else copy.deepcopy(spec['nodes'][n]) for n in NODE_NAMES}
    p.clear();p.update(base);p.update(view);p['_runtime_view_hash']=view_hash(view)
def apply_changes(p,changes):
    cls=p['classes'][p['selected_class']];spec=cls['specs'][p['selected_spec']]
    for key,value in changes.items():
        if key=='nodes':
            for name,node in value.items():
                if name in GATE_NAMES:
                    # GUI sends complete materialized nodes. Never copy inherited
                    # fields back into a sparse override or leak overrides to shared.
                    if name in spec.get('node_overrides',{}):
                        before=resolve_gate_node(cls['shared'],spec,name)
                        delta={k:copy.deepcopy(v) for k,v in node.items() if k not in before or v!=before[k]}
                        patch=spec['node_overrides'][name]
                        patch.update(delta)
                        resolve_gate_node(cls['shared'],spec,name)  # validate merged result
                    else:cls['shared']['nodes'][name]=copy.deepcopy(node)
                elif name in SKILL_PRIORITY:spec['nodes'][name]=copy.deepcopy(node)
                else:raise ValueError('Unknown node')
        elif key in COMBAT_KEYS:cls['shared'][key]=copy.deepcopy(value)
        elif key in CANONICAL:raise ValueError('Use select_character / explicit tree APIs')
        else:p['global'][key]=copy.deepcopy(value)
    materialize(p)
def disk_profile(p):return {k:copy.deepcopy(p[k]) for k in CANONICAL}

def view_hash(view):return hashlib.sha256(json.dumps(view,sort_keys=True,ensure_ascii=False).encode('utf-8')).hexdigest()
def commit_view_edits(p):
    baseline=p.get('_runtime_view_hash')
    if baseline is None:return
    flat={k:v for k,v in p.items() if k not in CANONICAL and k!='_runtime_view_hash'}
    if view_hash(flat)==baseline:return
    projection=copy.deepcopy(p);materialize(projection)
    if projection['_runtime_view_hash']!=baseline:
        raise ValueError('Both canonical and compatibility view changed; use update_active')
    apply_changes(p,flat)
