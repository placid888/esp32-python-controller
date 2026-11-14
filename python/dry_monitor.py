"""Decision evidence for a real DetectorWorker with final output blocked."""
import json,threading,time
from datetime import datetime
from pathlib import Path
from skill_model import SKILL_PRIORITY,skill_command

class DryDiagnostics:
    def __init__(self,path=None,context=None,guard=None):
        self.path=Path(path) if path else Path(__file__).resolve().parent/'diagnostics/dry_monitor_runtime.jsonl'
        self.context=dict(context or {});self.guard=guard;self.lock=threading.RLock()
        self.current=None;self.last_fingerprint=None;self.last_log=0;self.last_error=None
        self.would_send_count=0;self.records_count=0
    def verify_sampling_surface(self,w,vision):
        if self.guard:self.guard.check()
        verify_surface(w.nodes,vision)
    def record(self,event,**fields):
        if self.guard:self.guard.check()
        record={'timestamp':datetime.now().astimezone().isoformat(timespec='milliseconds'),
                'profile':None,'class':None,'spec':None,**self.context,'output_mode':'dry_run','event':event,'tx_id':None,'node':None,
                'gate_state':'unknown','target_state':'unknown','combat_state':'unknown','mark_state':'unknown',
                'skill':None,'skill_match':'unknown','delay_ms':None,'command':None,
                'decision':'observe','reason':event,'would_send':False,'blocked_by_dry_run':True,**fields}
        with self.lock:
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.open('a',encoding='utf-8') as out:out.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
                self.records_count+=1
            except Exception as exc:self.last_error=str(exc);raise
        return record
    def runtime_source(self,record):
        self.context.update(profile=record.get('profile'),**{'class':record.get('selected_class'),'spec':record.get('selected_spec')})
        self.record('GUI_RUNTIME_SOURCE',runtime=record)
    def observe(self,w,c,d):
        if self.guard:self.guard.check()
        def state(n):
            if not w.nodes.get(n,{}).get('enabled',False):return False
            return c[n] if n in d else 'unknown'
        fields={'session':getattr(w.mark_trace,'session',None),
                'target_state':state('Node_Target'),'combat_state':state('Node_Combat'),
                'mark_state':state('Node_Mark'),'gate_state':w.normal_allowed(c),'normal_gate_state':w.normal_allowed(c),
                'reason':w.gate_reason(c),'priority_selected':w.brain.chosen_skill,
                'skill_states':{n:{'enabled':w.nodes[n]['enabled'],
                                  'match':c.get(n,'not_sampled') if w.nodes[n]['enabled'] else False,
                                  'reason':w.brain.arbitration.get(n,'not_sampled')} for n in SKILL_PRIORITY},
                'pending':{n:{'deadline':v[0],'delay_ms':v[2]} for n,v in w.brain.pending.items()},
                'details':d}
        with self.lock:self.current=(w,dict(c),fields,time.monotonic(),threading.get_ident())
        fingerprint=json.dumps({k:v for k,v in fields.items() if k not in ('details','pending')},sort_keys=True)
        now=time.monotonic()
        if fingerprint!=self.last_fingerprint or now-self.last_log>=.5:
            self.record('STATE',**fields);self.last_fingerprint=fingerprint;self.last_log=now
    def unknown(self,w,exc):
        with self.lock:self.current=None
        self.record('SAMPLING_UNKNOWN',session=getattr(w.mark_trace,'session',None),
                    decision='stop',reason=getattr(exc,'code',type(exc).__name__),error=str(exc),
                    geometry_evidence=getattr(exc,'geometry_evidence',None))
    def block_payload(self,payload,source_node=None):
        name=source_node or getattr(payload,'source_node','UNSPECIFIED')
        command=json.loads(bytes(payload).decode('utf-8'));schedule=getattr(payload,'context',{}).get('schedule',{})
        with self.lock:current=self.current
        valid=False;fields={};reason='no_fresh_valid_monitor_decision';gate='unknown';skill_match='unknown'
        if current:
            w,c,fields,stamp,tid=current
            if tid==threading.get_ident() and time.monotonic()-stamp<=.5 and not w.stop_event.is_set():
                if name in SKILL_PRIORITY:
                    gate=w.normal_allowed(c);skill_match=c.get(name,'unknown')
                    valid=bool(gate and c.get(name) is True and w.nodes[name]['enabled'] and command==skill_command(name))
                    reason='normal_skill_due' if valid else 'skill_or_gate_not_valid'
                elif name=='Opener_Mark':
                    # Existing opener has its OWN gate; normal Skill gate may be
                    # false while Mark is missing. Do not change that rule.
                    gate=w.opener_allowed(c);skill_match=c.get('Node_Mark','unknown')
                    valid=bool(gate and command==w.opener.command())
                    reason='mark_opener_due' if valid else 'opener_gate_not_valid'
        fields={k:v for k,v in fields.items() if k not in ('reason','gate_state')}
        self.record('WOULD_SEND' if valid else 'OUTPUT_REJECTED',**fields,
                    tx_id=getattr(payload,'tx_id',None),node=name,skill=name,command=command,
                    gate_state=gate,skill_match=skill_match,delay_ms=schedule.get('chosen_delay_ms'),
                    schedule=schedule,decision='would_send' if valid else 'reject',reason=reason,
                    would_send=valid,blocked_by_dry_run=True)
        self.would_send_count+=int(valid)
        return valid

def wow_foreground_ready():
    import ctypes as c
    from ctypes import wintypes as w
    from wow_window import physical_pixels,find_wow_client,_libraries
    with physical_pixels():
        client=find_wow_client();u,_=_libraries()
        u.GetForegroundWindow.argtypes,u.GetForegroundWindow.restype=[],w.HWND
        return u.GetForegroundWindow()==client.hwnd

def verify_surface(nodes,vision):
    # Synthetic vision fixtures have no desktop surface. Real GameVision does.
    if not hasattr(vision,'sct'):return
    from wow_window import physical_pixels,find_wow_client,_libraries
    from wow_sampling import resolve_roi,_check_visible_owner
    with physical_pixels():
        client=find_wow_client();u,_=_libraries()
        for node in nodes.values():
            if not node.get('enabled'):continue
            relative=dict(node)
            if node.get('coordinate_mode','desktop_absolute')=='desktop_absolute':
                relative.update(x=node['x']-client.client_origin_screen_x,y=node['y']-client.client_origin_screen_y)
            size={'single_pixel':1,'3x3':3,'5x5':5}[node.get('sample_mode','single_pixel')]
            roi=resolve_roi(client,relative,size,vision.sct.monitors)
            _check_visible_owner(u,client,roi)
