"""Rate-limited pixel, gate, arbitration and bytes-dispatch observability."""
import json
import time
from pathlib import Path
from datetime import datetime
from skill_model import SKILL_PRIORITY, SKILL_KEYS

class TargetDiagnostics:
    def __init__(self,sink=None,path=None,clock=time.monotonic,interval=.75):
        self.sink=sink;self.path=Path(path) if path else None;self.clock=clock;self.interval=interval;self.last_error=None;self.reset()
    def reset(self):
        self.last_snapshot=float('-inf');self.fingerprints={}
    def emit(self,event,**fields):
        record={'time':datetime.now().astimezone().isoformat(timespec='milliseconds'),'event':event,**fields}
        line=json.dumps(record,ensure_ascii=False,separators=(',',':'))
        try:
            if self.path:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.open('a',encoding='utf-8') as f:f.write(line+'\n')
            if self.sink:self.sink('[DIAG] '+line)
        except Exception as exc:self.last_error=str(exc)
    def scan(self,nodes,pixels,conditions,brain,before_states,before_pending):
        now=self.clock();periodic=now-self.last_snapshot>=self.interval
        target=bool(nodes.get('Node_Target',{}).get('enabled',False) and conditions.get('Node_Target',False))
        for name,n in nodes.items():
            actual=pixels.get((n['x'],n['y']));actual=tuple(int(v) for v in actual) if actual is not None else None
            match=bool(conditions.get(name,False));reason=brain.arbitration.get(name,'Target_gate_only')
            pending=brain.pending.get(name);selected=brain.chosen_skill
            fingerprint=(n['enabled'],match,target,reason,selected,bool(pending),brain.latched.get(name,False))
            if periodic or self.fingerprints.get(name)!=fingerprint:
                wanted=tuple(n[k] for k in ('r','g','b'))
                self.emit('SKILL_TRACE' if name in SKILL_PRIORITY else 'Node_Target_SAMPLE',node=name,
                    x=n['x'],y=n['y'],enabled=n['enabled'],actual_rgb=actual,target_rgb=wanted,
                    diff=tuple(abs(a-b) for a,b in zip(actual,wanted)) if actual is not None else None,
                    brightness=sum(actual)/3 if actual else None,mode=n['mode'],threshold=n['threshold'],
                    tolerance=n['tolerance'],match=match,Node_Target=target,Gate=bool(target and match and n['enabled']),
                    priority_selected=selected,blocked_by_priority=selected if reason.startswith('blocked_by_priority=') else None,
                    key=SKILL_KEYS.get(name),latched=brain.latched.get(name,False),reason=reason,
                    min_delay_ms=n['min_delay'],max_delay_ms=n['max_delay'],
                    chosen_delay_ms=pending[2] if pending else None,remaining_ms=round(max(0,pending[0]-now)*1000,1) if pending else None)
                self.fingerprints[name]=fingerprint
        if periodic:self.last_snapshot=now
    def dispatch(self,event,outcome,reason=None):
        self.emit('DISPATCH_TRACE',node=event['node'],command=event['command'],key=event['command'].get('key') if event['command'] else None,
            priority_selected=event['node'],chosen_delay_ms=event['delay_ms'],outcome=outcome,reason=reason,
            note='queued is local queue acceptance, not remote execution confirmation')
