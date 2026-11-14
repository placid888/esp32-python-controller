"""Read-only Mark evidence. Bounded queue; all file I/O on a daemon writer.
DEBUG_VERBOSE_MARK=1 adds one scan record per detector step; default is transitions only.
Wire JSON and transport.py are unchanged. A send sequence means sent_to_os, not HID ACK.
"""
import atexit,json,os,queue,threading,time,uuid,sys
from pathlib import Path
from datetime import datetime
from transport import ESP32Controller

class MarkTrace:
    def __init__(self,path=None,verbose=None):
        self.path=Path(path) if path else Path(__file__).resolve().parent/'logs/mark_trace.log'
        self.verbose=verbose;self.queue=queue.Queue(maxsize=8192);self.stop_event=threading.Event()
        self.thread=None;self.session=None;self.states={};self.last_attempt=None;self.attempt_seq=0
        self.send_sequences={};self.ended_sessions=set();self.error=None;self.dropped=0;self.before_scan=None
        atexit.register(self.close)
    def emit(self,event,**data):
        try:
            record={'event':event,'session':self.session,'monotonic':time.monotonic(),
                'wall_time':datetime.now().astimezone().isoformat(timespec='milliseconds'),**data}
            self.queue.put_nowait(record)
        except Exception as exc:
            self.dropped+=1;self.error=str(exc)
    def _writer(self):
        while not self.stop_event.is_set() or not self.queue.empty():
            try:record=self.queue.get(timeout=.1)
            except queue.Empty:continue
            try:
                self.path.parent.mkdir(parents=True,exist_ok=True)
                with self.path.open('a',encoding='utf-8') as f:f.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
            except Exception as exc:self.error=str(exc)
    def begin(self,worker):
        self.session=uuid.uuid4().hex;self.states={};self.last_attempt=None;self.attempt_seq=0
        self.verbose_enabled=self.verbose if self.verbose is not None else os.getenv('DEBUG_VERBOSE_MARK','0').lower() in ('1','true','yes')
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear();self.thread=threading.Thread(target=self._writer,name='mark-trace-writer',daemon=True);self.thread.start()
        self.emit('SESSION START',pid=os.getpid(),gui_source=str(Path(__file__).with_name('gui.py')),mark_mode=worker.mark_mode,
            retry_ms=worker.opener.retry_ms,verbose=self.verbose_enabled,target_identity_supported=False,
            executable=sys.executable,**getattr(self,"gui_context",{}))
    def end(self,**data):
        self.ended_sessions.add(self.session)
        self.emit('SESSION END',mark_attempt_seq=self.attempt_seq,dropped_records=self.dropped,logging_error=self.error,**data)
    def close(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():self.thread.join(timeout=1)
    def snapshot(self,w,c,d):
        pending={k:{'deadline':v[0],'delay_ms':v[2]} for k,v in w.brain.pending.items()}
        n=w.nodes.get('Node_Mark',{});detail=d.get('Node_Mark',{})
        return dict(target=c.get('Node_Target'),combat=c.get('Node_Combat'),mark=c.get('Node_Mark'),
            normal_gate=w.normal_allowed(c),gate_reason=w.gate_reason(c),sampled_nodes=list(d),combat_observed='Node_Combat' in d,mark_observed='Node_Mark' in d,
            mark_mode=w.mark_mode,retry_ms=w.opener.retry_ms,pending_mark_deadline=w.opener.pending,
            selected_skill=w.brain.chosen_skill,normal_skill_pending=pending,
            mark_detector={'x':n.get('x'),'y':n.get('y'),'enabled':n.get('enabled'),
                'comparison_mode':n.get('mode'),'expected_rgb':[n.get(k) for k in ('r','g','b')],
                'tolerance':n.get('tolerance'),'threshold':n.get('threshold'),
                'sample_mode':n.get('sample_mode','single_pixel'),'match_ratio':n.get('match_ratio',.30),
                'actual_rgb':detail.get('actual_rgb'),'matching_pixels':detail.get('matching_pixels'),
                'total_pixels':detail.get('total_pixels'),'observed_ratio':detail.get('ratio'),'final_match':c.get('Node_Mark')})
    def scan(self,w,c,d):
        snap=self.snapshot(w,c,d);self.before_scan=snap
        for name in ('Node_Target','Node_Combat','Node_Mark'):
            # Missing means NOT SAMPLED, never a fabricated false/transition.
            if name not in d:continue
            value=c.get(name);previous=self.states.get(name)
            if name not in self.states or previous!=value:
                self.emit('MARK_STATE' if name=='Node_Mark' else 'TARGET_STATE' if name=='Node_Target' else 'COMBAT_STATE',
                    node=name,previous=previous,current=value,initial=name not in self.states,**snap)
            self.states[name]=value
        if getattr(self,'verbose_enabled',False):self.emit('MARK_SCAN',**snap)
    def attempt(self,w,c,d,now,deadline):
        self.attempt_seq+=1
        was_pending=(self.before_scan or {}).get('pending_mark_deadline') is not None
        reason=('mark_missing_first_attempt' if self.last_attempt is None else 'mark_missing_retry' if was_pending else 'mark_missing_rearmed_after_cancel')
        snap=self.snapshot(w,c,d)
        snap.update(mark_attempt_seq=self.attempt_seq,elapsed_ms=None if self.last_attempt is None else (now-self.last_attempt)*1000,
            reason=reason,key=w.opener.key,decision_monotonic=now,deadline=deadline,
            cancellation_revalidation='fresh_scan_opener_allowed_and_deadline_due',
            opener_allowed=w.opener_allowed(c),pending_mark_before_scan=(self.before_scan or {}).get('pending_mark_deadline'),normal_pending_before_scan=(self.before_scan or {}).get('normal_skill_pending'),
            previous_selected_skill=(self.before_scan or {}).get('selected_skill'))
        self.last_attempt=now
        self.emit('MARK_TRACE',action='SEND_3_PREPARE' if w.opener.key=='3' else 'MARK_SEND_PREPARE',**snap)
        if reason=='mark_missing_retry':self.emit('MARK_RETRY',**snap)
        return {'session':self.session,**snap}
    def cancel(self,w,c,d,event,**extra):
        if event=='MARK_PENDING_CANCEL':
            extra['original_gate_reason']=extra.get('reason')
            extra['reason']=('target_false' if not c.get('Node_Target') else
                'mark_mode_off' if w.mark_mode=='off' else
                'mark_node_disabled' if not w.nodes.get('Node_Mark',{}).get('enabled',False) else
                'mark_detected_success' if c.get('Node_Mark') else
                'combat_false' if w.mark_mode=='post_combat' and not c.get('Node_Combat') else 'opener_not_allowed')
        if event=='NORMAL_PENDING_CANCEL':
            extra['original_cancel_reason']=extra.get('reason')
            extra['reason']=('target_false' if not c.get('Node_Target') else
                'mark_missing_normal_gate_closed' if w.mark_mode!='off' and not c.get('Node_Mark') else
                'combat_gate_closed' if (w.combat_mode=='manual_first_hit' or w.mark_mode=='post_combat') and not c.get('Node_Combat') else
                'skill_condition_or_priority_changed')
            extra['pending_before_scan']=(self.before_scan or {}).get('normal_skill_pending')
        self.emit(event,**self.snapshot(w,c,d),**extra)

class TracedESP32Controller(ESP32Controller):
    """Observer subclass. Parent owns serialization, socket, retries and return values."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.mark_trace=MarkTrace();self._mark_tx={}
    def _record_tx(self,payload,destination,source_node=None):
        tx_id=super()._record_tx(payload,destination,source_node)
        try:
            command=json.loads(bytes(payload).decode('utf-8'))
            if command.get('action') in ('tap','press') and command.get('key')=='3':
                context=getattr(payload,'context',{});meta=dict(context.get('schedule',{}).get('mark_trace',{}))
                meta.setdefault('session',self.mark_trace.session);meta.setdefault('reason','non_opener_or_missing_trace_context')
                if 'mark_attempt_seq' not in meta:
                    meta.update({k:v for k,v in (self.mark_trace.before_scan or {}).items() if k not in meta})
                    meta['context_freshness']='latest_scan_only_not_revalidated_for_manual_send'
                for k in ('target','combat','mark'):meta.setdefault(k,None)
                meta.update(key='3',tx_id=tx_id,source_node=source_node or getattr(payload,'source_node','UNSPECIFIED'),
                    payload_raw=repr(bytes(payload)),destination=list(destination))
                self._mark_tx[tx_id]=meta;self.mark_trace.emit('MARK_UDP_BEFORE_SENDTO',**meta)
        except Exception:pass
        return tx_id
    def _record_tx_result(self,tx_id,outcome,**detail):
        result=super()._record_tx_result(tx_id,outcome,**detail)
        try:
            meta=self._mark_tx.pop(tx_id,None)
            if meta is not None:
                if outcome=='sent_to_os':
                    session=meta.get('session');seq=self.mark_trace.send_sequences.get(session,0)+1;self.mark_trace.send_sequences[session]=seq
                    self.mark_trace.emit('MARK_SEND',MARK_SEND_SEQ=seq,outcome=outcome,after_session_end=session in self.mark_trace.ended_sessions,**meta,**detail)
                else:self.mark_trace.emit('MARK_UDP_RESULT',outcome=outcome,**meta,**detail)
        except Exception:pass
        return result
