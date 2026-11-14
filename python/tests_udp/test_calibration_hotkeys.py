import sys,time,unittest,tempfile,threading,ctypes,os
from pathlib import Path
from unittest.mock import Mock,patch
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
from calibration_hotkeys import CalibrationHotkeys,CALIBRATION_KEYS
from hotkey_capture import F8Capture,HOTKEY_ID,WM_HOTKEY,MOD_NOREPEAT
import profile_store
class Listener:
    alive=False
    def __init__(self):self.events=[];self.context=None
    def start(self,c):self.context=c;return True
    def stop(self):pass
    def set_context(self,c):self.context=c
    def poll(self):r=self.events;self.events=[];return r
class UI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from gui import MacroDashboard
        self.temp=tempfile.TemporaryDirectory();f=Path(self.temp.name)/'config.json';profile_store.write(f,{'nodes':profile_store.default_nodes()})
        self.root=tk.Tk();self.root.withdraw();self.app=MacroDashboard(self.root,config_path=f)
        old=self.app.calibration_hotkeys;old.stop()
        if old.listener._thread:old.listener._thread.join(2)
        self.manager=CalibrationHotkeys(self.app,Listener());self.app.calibration_hotkeys=self.manager
        self.app.edit_node('Skill_4');self.app.node_editor.withdraw();self.panel=self.app.calibration_panel
        self.app.controller.send_command=Mock(side_effect=AssertionError('Hotkey must not use UDP/HID'))
    def tearDown(self):
        import calibration_ui
        calibration_ui.cancel_all(self.app)
        for job in self.app.calibration_jobs:
            if job.thread:job.thread.join(2)
        self.app.is_running=False
        if self.app.node_editor.winfo_exists():self.app.node_editor.destroy()
        self.app.stop_loop();self.app.restore_output();self.app.vision.close()
        for ident in self.root.tk.call('after','info'):self.root.after_cancel(ident)
        self.root.destroy();self.temp.cleanup()
    def event(self,key='F9',**changes):
        event=dict(kind='calibration_hotkey',key=key,type='dark' if key=='F9' else 'bright',context=self.manager.token,timestamp=time.monotonic());event.update(changes);return event
    def drain(self):
        end=time.monotonic()+2
        while self.panel.job is not None and time.monotonic()<end:self.root.update();time.sleep(.005)
        self.assertIsNone(self.panel.job)
    def factory(self,value):
        class V:
            def get_region_rgb(self,x,y,size):return [(value,value,value)]*(size*size)
            def close(self):pass
        return V
    def test01_f9_f10_collect_same_skill(self):
        self.panel.vision_factory=self.factory(30);self.assertTrue(self.manager.handle(self.event()));self.drain()
        self.panel.vision_factory=self.factory(110);self.assertTrue(self.manager.handle(self.event('F10')));self.drain()
        self.assertEqual(self.panel.samples,{'dark':[30.]*15,'bright':[110.]*15});self.assertEqual(self.panel.analysis['suggested_threshold'],70)
        self.app.controller.send_command.assert_not_called()
    def test02_buttons_and_hotkey_same_capture(self):
        self.panel.vision_factory=self.factory(30)
        with patch.object(self.panel,'capture',wraps=self.panel.capture) as capture:
            self.panel.dark_button.invoke();self.assertEqual(capture.call_args.args,('dark',));self.drain()
            self.manager.handle(self.event('F10'));self.assertEqual(capture.call_args.args,('bright',));self.drain()
        self.app.controller.send_command.assert_not_called()
    def test03_color_red_rejected_no_switch(self):
        self.panel.vision_factory=Mock(side_effect=AssertionError('No sampling'))
        for mode in ('color','red'):
            self.app.node_vars['Skill_4']['mode'].set(mode)
            self.assertFalse(self.manager.handle(self.event()));self.assertFalse(self.manager.handle(self.event('F10')))
            self.assertEqual(self.app.node_vars['Skill_4']['mode'].get(),mode)
        self.panel.vision_factory.assert_not_called()
    def test04_monitor_rejected(self):
        self.app.is_running=True;self.panel.vision_factory=Mock(side_effect=AssertionError('No sampling'))
        self.assertFalse(self.manager.handle(self.event()));self.panel.vision_factory.assert_not_called();self.assertIn('停止 Monitor',self.panel.status.get())
    def test05_no_window_rejected(self):
        self.app.node_editor.destroy();self.assertIsNone(self.manager.panel);self.assertFalse(self.manager.handle(self.event()))
    def test06_busy_no_second_worker(self):
        self.panel.vision_factory=self.factory(30);self.assertTrue(self.manager.handle(self.event()));job=self.panel.job
        for i in range(10):self.assertFalse(self.manager.handle(self.event('F10')))
        self.assertIs(self.panel.job,job);self.assertEqual(len(self.app.calibration_jobs),1);self.drain();self.assertNotIn('bright',self.panel.samples)
    def test07_skill_switch_rejects_old_event(self):
        old=self.event();self.app.edit_node('Skill_7');self.app.node_editor.withdraw();self.panel=self.app.calibration_panel
        self.assertFalse(self.manager.handle(old));self.panel.vision_factory=self.factory(50)
        self.assertTrue(self.manager.handle(self.event()));self.drain();self.assertEqual(self.manager.panel.skill,'Skill_7')
    def test08_queued_busy_event_dropped_after_completion(self):
        self.panel.vision_factory=self.factory(30);self.manager.handle(self.event());queued=self.event('F10');self.drain()
        self.assertFalse(self.manager.handle(queued));self.assertIsNone(self.panel.job);self.assertNotIn('bright',self.panel.samples)
    def test09_f8_coordinate_entry_unchanged(self):
        self.app.capture_target_var.set('Skill_4');self.app.is_tracking=True
        self.assertTrue(self.app.apply_capture_event({'context':self.app.capture_context(),'x':123,'y':234,'rgb':(1,2,3)}))
        self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'123');self.assertEqual(self.app.config_entries['Skill_4']['y'].get(),'234')
        self.assertEqual(self.app.editing_nodes['Skill_4']['r'],1);self.app.is_tracking=False
    def test10_diagnostics_rate_limit(self):
        self.manager.deactivate(self.panel)
        with patch.object(self.app.target_diag,'emit') as emit:
            for i in range(10):self.manager.handle(self.event())
            self.assertEqual(emit.call_count,1);self.assertEqual(emit.call_args.kwargs['reason'],'no_active_calibration_skill')
    def test11_main_thread_only_routing(self):
        main=threading.get_ident();calls=[]
        self.manager.listener.events.append(self.event())
        with patch.object(self.panel,'capture',side_effect=lambda state:calls.append((threading.get_ident(),state)) or True):self.manager.poll()
        self.assertEqual(calls,[(main,'dark')])
    def test12_gate_editor_not_active(self):
        self.app.edit_node('Node_Target');self.app.node_editor.withdraw();self.assertIsNone(self.manager.panel);self.assertFalse(self.manager.handle(self.event()))
    def test13_sampler_algorithm_file_unchanged(self):
        import hashlib,json
        old=json.loads((P/'backups/calibration-hotkeys-20261101/SHA256-before.json').read_text())
        for name in ('brightness_calibration.py','detector.py','decision.py','transport.py','vision.py','mark_opener.py','profile_store.py','skill_model.py'):
            self.assertEqual(hashlib.sha256((P/name).read_bytes()).hexdigest(),('14faff783b8c7f993539bdb429cc9d1bb839722d174208e13f66cb86773a880a' if name=='profile_store.py' else old[name]))
    def test14_profile_change_rejected(self):
        e=self.event();self.app.active_profile_name='Different';self.assertFalse(self.manager.handle(e));self.assertIsNone(self.panel.job)
@unittest.skipUnless(os.name=='nt','Windows native hotkeys')
class Native(unittest.TestCase):
    def test15_same_native_worker_f9_f10_no_screenshot(self):
        from ctypes import wintypes
        calls=[];w=F8Capture(capture=lambda:calls.append(1),hotkeys=CALIBRATION_KEYS)
        try:
            self.assertTrue(w.start(None));events=[];end=time.monotonic()+3
            while not any(e['kind'] in ('ready','error') for e in events) and time.monotonic()<end:events+=w.poll();time.sleep(.005)
            self.assertTrue(any(e['kind']=='ready' for e in events),events)
            user=ctypes.WinDLL('user32',use_last_error=True);user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];user.PostThreadMessageW.restype=wintypes.BOOL
            for ident in CALIBRATION_KEYS:self.assertTrue(user.PostThreadMessageW(w._tid,WM_HOTKEY,ident,0))
            events=[];end=time.monotonic()+2
            while len([e for e in events if e['kind']=='calibration_hotkey'])<2 and time.monotonic()<end:events+=w.poll();time.sleep(.005)
            keys=[e for e in events if e['kind']=='calibration_hotkey'];self.assertEqual([e['key'] for e in keys],['F9','F10']);self.assertEqual([e['type'] for e in keys],['dark','bright']);self.assertTrue(all(e['context'] is None for e in keys));self.assertFalse(calls)
            self.assertEqual(MOD_NOREPEAT,0x4000)
        finally:
            w.stop()
            if w._thread:w._thread.join(3)
            self.assertFalse(w.alive)
    def test16_default_f8_registration_unchanged(self):
        w=F8Capture();self.assertEqual(w.hotkeys,{HOTKEY_ID:('F8',0x77,'capture')})
if __name__=='__main__':unittest.main(verbosity=2)
