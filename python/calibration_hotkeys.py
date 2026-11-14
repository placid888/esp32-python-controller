"""F9/F10 use the same RegisterHotKey worker as F8. All routing is on Tk."""
import time
from hotkey_capture import F8Capture
from skill_model import SKILL_PRIORITY
from calibration_ui import busy

CALIBRATION_KEYS={0x7b13:('F9',0x78,'dark'),0x7b14:('F10',0x79,'bright')}
class CalibrationHotkeys:
    def __init__(self,app,listener=None):
        self.app=app;self.listener=listener or F8Capture(hotkeys=CALIBRATION_KEYS)
        self.panel=None;self.token=None;self.serial=0;self.after_id=None;self.stopped=False
        self.ignore_before=0;self.last_ignored={}
    @property
    def alive(self):return self.listener.alive
    def start(self):
        self.listener.start(None);self.after_id=self.app.root.after(50,self.poll)
    def stop(self):
        self.stopped=True;self.listener.stop()
        if self.after_id is not None:
            self.app.root.after_cancel(self.after_id);self.after_id=None
    def activate(self,panel):
        self.serial+=1;self.panel=panel
        self.token=(self.app.active_profile_name,panel.skill,self.serial)
        self.ignore_before=time.monotonic();self.listener.set_context(self.token)
    def deactivate(self,panel):
        if self.panel is panel:
            self.panel=None;self.token=None;self.listener.set_context(None)
    def completed(self,panel):
        # Drop key events queued during a capture/blocked GUI, even if delivered
        # after the worker has finished and its result has just been rendered.
        if self.panel is panel:self.ignore_before=time.monotonic()
    def diag(self,event,outcome,reason=None):
        now=time.monotonic();skill=self.panel.skill if self.panel else None
        if outcome=='ignored':
            signature=(event.get('key'),skill,reason)
            if now-self.last_ignored.get(signature,-100)<.75:return
            self.last_ignored[signature]=now
        self.app.target_diag.emit('CALIBRATION_HOTKEY',skill=skill,key=event.get('key'),type=event.get('type'),outcome=outcome,reason=reason)
    def handle(self,event):
        panel=self.panel;reason=None
        if event.get('key') not in ('F9','F10') or event.get('type')!={'F9':'dark','F10':'bright'}.get(event.get('key')):return False
        if panel is None or not panel.window.winfo_exists() or self.app.node_editor is not panel.window or panel.skill not in SKILL_PRIORITY:
            reason='no_active_calibration_skill'
        elif event.get('context')!=self.token or self.token[0]!=self.app.active_profile_name:reason='stale_calibration_context'
        elif event.get('timestamp',0)<self.ignore_before:reason='stale_or_busy_key_event'
        elif self.app.is_running:reason='monitor_running'
        elif panel.job is not None or busy(self.app):reason='calibration_busy'
        elif self.app.node_vars[panel.skill]['mode'].get()!='brightness':reason='mode_not_brightness'
        if reason:
            if panel and panel.window.winfo_exists():
                if reason=='monitor_running':panel.status.set('請先停止 Monitor')
                elif reason=='mode_not_brightness':panel.status.set('請先將 Comparison Mode 設為 brightness')
            self.diag(event,'ignored',reason);return False
        # Exactly the same function as both existing GUI buttons; no sampler here.
        accepted=panel.capture(event['type'])
        self.diag(event,'accepted' if accepted else 'ignored',None if accepted else 'capture_rejected')
        return accepted
    def poll(self):
        self.after_id=None
        if self.stopped:return
        for event in self.listener.poll():
            if event.get('kind')=='calibration_hotkey':self.handle(event)
            elif event.get('kind')=='error':
                self.app.target_diag.emit('CALIBRATION_HOTKEY',outcome='registration_error',reason=event.get('message'))
        self.after_id=self.app.root.after(50,self.poll)
