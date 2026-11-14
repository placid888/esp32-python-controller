"""Deadline worker. No Tk, file writes, ACK waits, or GUI callbacks in hot path."""
import copy, queue, threading, time
from decision import DecisionEngine, node_matches
from mark_opener import OpenerMark, mark_settings, MARK_SPELL_ID
from skill_model import SKILL_PRIORITY, skill_command

def sample_node(vision, node, pixels=None):
    size={'single_pixel':1,'3x3':3,'5x5':5}[node.get('sample_mode','single_pixel')]
    coordinate_mode=node.get('coordinate_mode','desktop_absolute')
    metadata={}
    if coordinate_mode=='wow_client':
        # Exceptions must propagate to worker.run -> DETECTOR_ERROR / STOPPED.
        # Do NOT turn an invalid Mark sample into False (which could request a cast).
        pixels,metadata=vision.get_node_pixels(node,size)
    elif coordinate_mode=='desktop_absolute':
        if pixels is None:pixels=vision.get_region_rgb(node['x'],node['y'],size)
    else:raise ValueError('Unknown coordinate_mode')
    hits=sum(node_matches(rgb,node) for rgb in pixels)
    ratio=hits/len(pixels)
    return ratio>=node.get('match_ratio',.30), {'actual_rgb':list(pixels[len(pixels)//2]),
        'brightness':sum(pixels[len(pixels)//2])/3, 'matching_pixels':hits,
        'total_pixels':len(pixels),'ratio':ratio,'mode':node['mode'],**metadata}

class DetectorWorker:
    def __init__(self,nodes,sender,vision_factory,interval=.01,clock=time.monotonic,combat_mode='auto',hunter_mark_mode='off',hunter_mark_key='3',hunter_mark_retry_ms=500,mark_trace=None,output_observer=None):
        if combat_mode not in ('auto','manual_first_hit'):raise ValueError('Unknown combat_mode')
        self.mark_config=mark_settings(dict(hunter_mark_mode=hunter_mark_mode,hunter_mark_key=hunter_mark_key,hunter_mark_retry_ms=hunter_mark_retry_ms))
        self.mark_trace=mark_trace
        self.mark_mode=hunter_mark_mode
        self.opener=OpenerMark(hunter_mark_key,hunter_mark_retry_ms)
        self.combat_mode=combat_mode
        self.nodes=copy.deepcopy(nodes)  # Immutable session snapshot; updates stop/restart worker.
        self.sender=sender;self.vision_factory=vision_factory;self.interval=interval;self.clock=clock
        self.brain=DecisionEngine(clock=clock);self.stop_event=threading.Event()
        self.events=queue.Queue(maxsize=256);self.thread=None;self.lock=threading.Lock()
        self.scan_count=0;self.dispatch_count=0;self.cancel_count=0;self.samples=[]
        self.started=None;self.last_snapshot=None
        self.output_observer=output_observer
    def trace_call(self,method,*args,**kwargs):
        # Evidence failure must never change a decision or block command submission.
        try:
            if self.mark_trace is not None:return getattr(self.mark_trace,method)(*args,**kwargs)
        except Exception:pass
        return None
    def emit(self,event,**data):
        try:self.events.put_nowait({'event':event,**data})
        except queue.Full:pass  # Telemetry loss must never stall sampling.
    def start(self):
        self.thread=threading.Thread(target=self.run,name='visual-detector',daemon=False);self.thread.start()
    def stop(self):
        # Synchronizes with final queue submission. Already queued UDP cannot be recalled.
        with self.lock:self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():self.thread.join()
        self.opener.cancel()
    def normal_allowed(self, conditions):
        return bool(conditions.get('Node_Target') and
            (self.combat_mode=='auto' or conditions.get('Node_Combat')) and
            (self.mark_mode=='off' or conditions.get('Node_Mark')) and
            (self.mark_mode!='post_combat' or conditions.get('Node_Combat')))
    def opener_allowed(self, conditions):
        return bool(self.mark_mode!='off' and conditions.get('Node_Target') and
            self.nodes.get('Node_Mark',{}).get('enabled',False) and
            not conditions.get('Node_Mark') and
            (self.mark_mode!='post_combat' or conditions.get('Node_Combat')))
    def scan(self,vision):
        conditions={};details={}
        def read(name):
            node=self.nodes.get(name,{})
            if node.get('enabled',False):conditions[name],details[name]=sample_node(vision,node)
            else:conditions[name]=False
        read('Node_Target')
        if not conditions['Node_Target']:return conditions,details
        if self.mark_mode=='pre_combat':
            read('Node_Mark')
            if not conditions['Node_Mark']:return conditions,details
        # B always needs Combat, even when the normal combat mode is Auto.
        if self.combat_mode=='manual_first_hit' or self.mark_mode=='post_combat':
            read('Node_Combat')
            if not conditions['Node_Combat']:return conditions,details
        if self.mark_mode=='post_combat':
            read('Node_Mark')
            if not conditions['Node_Mark']:return conditions,details
        enabled={name:self.nodes[name] for name in SKILL_PRIORITY if self.nodes[name]['enabled']}
        batch=vision.capture_nodes(enabled) if hasattr(vision,'capture_nodes') else {}
        for name in SKILL_PRIORITY:
            node=self.nodes[name]
            if node['enabled']:conditions[name],details[name]=sample_node(vision,node,batch.get(name))
        return conditions,details
    def gate_reason(self, conditions):
        if not conditions.get('Node_Target'):return 'target_false'
        if self.mark_mode=='post_combat' and not conditions.get('Node_Combat'):return 'waiting_for_combat'
        if self.mark_mode!='off' and not self.nodes.get('Node_Mark',{}).get('enabled',False):return 'mark_node_disabled'
        if self.mark_mode!='off' and not conditions.get('Node_Mark'):
            return 'waiting_for_post_combat_mark' if self.mark_mode=='post_combat' else 'waiting_for_hunters_mark'
        if self.combat_mode=='manual_first_hit' and not conditions.get('Node_Combat'):return 'waiting_for_combat'
        return 'gate_open'
    def step(self,vision):
        t=self.clock();before=dict(self.brain.pending)
        try:
            if self.output_observer:self.output_observer.verify_sampling_surface(self,vision)
            conditions,details=self.scan(vision)
            if self.output_observer:self.output_observer.verify_sampling_surface(self,vision)
        except Exception as exc:
            if self.output_observer:self.output_observer.unknown(self,exc)
            raise  # Unknown never reaches observe(False), poll, or sender.
        self.trace_call("scan",self,conditions,details)
        self.brain.observe(conditions,self.nodes,self.combat_mode)
        if self.output_observer:self.output_observer.observe(self,conditions,details)
        if before and next(iter(before))!=self.brain.chosen_skill:
            self.trace_call('cancel',self,conditions,details,'NORMAL_PENDING_CANCEL',reason='Target/Combat/skill/priority_changed',cancelled_skill=next(iter(before)))
            self.cancel_count+=1;self.emit('PENDING_CANCEL',skill=next(iter(before)),reason='Target/Combat/skill/priority_changed')
        # Opener is outside Skill priority. A missing Mark scan supplies no Skill
        # matches, so observe above cancels every normal pending event first.
        if self.opener.observe(self.opener_allowed(conditions),self.clock()):
            self.trace_call('cancel',self,conditions,details,'MARK_PENDING_CANCEL',reason=self.gate_reason(conditions))
            self.cancel_count+=1;self.emit('OPENER_CANCEL',node='Opener_Mark',reason=self.gate_reason(conditions))
        opener_sent=False
        if self.opener.is_due(self.clock()):
            deadline=self.opener.pending
            with self.lock:
                if self.stop_event.is_set():self.opener.cancel();self.brain.reset();return
                actual=self.clock()
                trace_context=self.trace_call('attempt',self,conditions,details,actual,deadline)
                schedule={'deadline':deadline,'chosen_delay_ms':0,'first_detected_time':deadline}
                if trace_context is not None:schedule['mark_trace']=trace_context
                queued=bool(self.sender(self.opener.command(),source_node='Opener_Mark',schedule=schedule))
                # Retry after accepted OR rejected queue attempt; never busy retry.
                self.opener.attempted(self.clock())
            self.trace_call('cancel',self,conditions,details,'MARK_QUEUE_RESULT',queued=queued,reason='queue_accepted' if queued else 'queue_rejected')
            opener_sent=True;self.dispatch_count+=int(queued)
            self.emit('OPENER_DISPATCH',node='Opener_Mark',key=self.opener.key,
                hunter_mark_mode=self.mark_mode,spell_id=MARK_SPELL_ID,
                reason='hunters_mark_missing',retry_delay_ms=self.opener.retry_ms,
                deadline=deadline,actual_dispatch_time=actual,outcome='queued' if queued else 'queue_rejected')
        # This scan is the expiry re-check, not a cached GUI observation.
        pending=dict(self.brain.pending)
        for event in ([] if opener_sent or not self.normal_allowed(conditions) else self.brain.poll()):
            name=event['node'];deadline=pending[name][0]
            with self.lock:
                if self.stop_event.is_set():self.brain.reset();return
                actual=self.clock()
                queued=bool(self.sender(skill_command(name),source_node=name, schedule={'deadline':deadline,'chosen_delay_ms':event['delay_ms'],'first_detected_time':deadline-event['delay_ms']/1000}))
            self.dispatch_count+=int(queued)
            self.emit('GATE_DISPATCH',hunter_mark_mode=self.mark_mode,Node_Mark=conditions.get('Node_Mark'),combat_mode=self.combat_mode,Node_Target=bool(conditions.get('Node_Target')),Node_Combat=conditions.get('Node_Combat'),skill=name,key=skill_command(name)['key'],Gate=True,
                first_detected_time=deadline-event['delay_ms']/1000,
                chosen_delay_ms=event['delay_ms'],deadline=deadline,actual_dispatch_time=actual,
                scheduling_error_ms=(actual-deadline)*1000,outcome='queued' if queued else 'queue_rejected')
            # Next loop resamples every enabled skill; no remembered winner bypass.
            self.brain.complete_dispatch(name)
        self.scan_count+=1;self.samples.append((self.clock()-t)*1000)
        self.last_snapshot={'combat_mode':self.combat_mode,'hunter_mark_mode':self.mark_mode,
            'opener_key':self.opener.key,'spell_id':MARK_SPELL_ID,'Node_Target':bool(conditions.get('Node_Target')),
            'Node_Combat':conditions.get('Node_Combat'),'Node_Mark':conditions.get('Node_Mark'),
            'opener_complete':self.mark_mode!='off' and bool(conditions.get('Node_Mark')),
            'Gate':self.normal_allowed(conditions),'reason':self.gate_reason(conditions),
            'conditions':conditions,'details':details,'priority_selected':self.brain.chosen_skill,
            'arbitration':dict(self.brain.arbitration)}
    def performance(self):
        now=self.clock();pending=self.brain.pending
        return dict(hunter_mark_mode=self.mark_mode,opener_pending_deadline=self.opener.pending,combat_mode=self.combat_mode,scan_count=self.scan_count,scan_hz=self.scan_count/max(now-self.started,1e-9),
            avg_scan_ms=sum(self.samples)/max(len(self.samples),1),max_scan_ms=max(self.samples,default=0),
            enabled_skill_count=sum(self.nodes[n]['enabled'] for n in SKILL_PRIORITY),
            pending_skill=next(iter(pending),None),
            pending_remaining_ms=max(0,(next(iter(pending.values()))[0]-now)*1000) if pending else 0,
            dispatch_count=self.dispatch_count,cancel_count=self.cancel_count)
    def run(self):
        vision=None;self.started=self.clock();next_diag=self.started+.5;next_perf=self.started+1
        self.trace_call("begin",self)
        try:
            vision=self.vision_factory()  # MSS MUST be created and used on this same thread.
            while not self.stop_event.is_set():
                begin=self.clock();self.step(vision);now=self.clock()
                if now>=next_diag:
                    self.emit('VISION_SNAPSHOT',**self.last_snapshot);next_diag=now+.5
                if now>=next_perf:
                    self.emit('PERFORMANCE',**self.performance());self.samples.clear();next_perf=now+1
                deadline=next(iter(self.brain.pending.values()))[0] if self.brain.pending else now+self.interval
                if self.opener.pending is not None:deadline=min(deadline,self.opener.pending)
                self.stop_event.wait(max(0,min(begin+self.interval,deadline)-self.clock()))
        except Exception as exc:self.emit('DETECTOR_ERROR',message=str(exc));self.stop_event.set()
        finally:
            if self.opener.pending is not None or self.brain.pending:
                self.trace_call('cancel',self,(self.last_snapshot or {}).get('conditions',{}),(self.last_snapshot or {}).get('details',{}),'MARK_CANCEL_ON_STOP',reason='monitor_stopped_or_error')
            if self.brain.pending:self.cancel_count+=1
            if self.opener.cancel():self.cancel_count+=1
            self.brain.reset()
            if vision and hasattr(vision,'close'):vision.close()
            self.trace_call('end',reason='monitor_stopped_or_error',scan_count=self.scan_count,dispatch_count=self.dispatch_count)
            self.emit('DETECTOR_STOPPED',scan_count=self.scan_count,dispatch_count=self.dispatch_count,cancel_count=self.cancel_count)
