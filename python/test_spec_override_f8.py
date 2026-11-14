"""Sparse spec overrides and mode-aware F8. No live input, UDP, or migration."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import copy,ctypes,json,tempfile,unittest
from unittest.mock import Mock,patch
import profile_store as store
import spec_data
from wow_window import WowClient,WindowError
from wow_calibration import calibration_coordinates,capture_wow_calibration


def document():
    return store.migrate({'nodes':store.default_nodes()})

def profile(d):return d['profiles']['Default']

def bm(p):return p['classes']['hunter']['specs']['beast_mastery']

def select(p,spec):
    p['selected_class']='hunter';p['selected_spec']=spec;spec_data.materialize(p)
    return copy.deepcopy(p['nodes']['Node_Target'])


class Overrides(unittest.TestCase):
    def test_legacy_no_rewrite(self):
        path=Path(__file__).with_name('config.json')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')),store.disk_document(store.read(path)))

    def test_only_beast_mastery(self):
        p=profile(document());shared=copy.deepcopy(p['classes']['hunter']['shared']['nodes']['Node_Target'])
        bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client','x':32,'y':277}}
        self.assertEqual(select(p,'beast_mastery')['coordinate_mode'],'wow_client')
        for s in ['marksmanship','survival']:
            self.assertEqual(select(p,s),shared)

    def test_mode_only_inherits_xy(self):
        p=profile(document());p['classes']['hunter']['shared']['nodes']['Node_Target'].update(x=32,y=277)
        bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client'}}
        node=select(p,'beast_mastery');self.assertEqual((node['x'],node['y']),(32,277))

    def test_xy_only_inherits_mode(self):
        p=profile(document());p['classes']['hunter']['shared']['nodes']['Node_Target']['coordinate_mode']='wow_client'
        bm(p)['node_overrides']={'Node_Target':{'x':20,'y':30}}
        self.assertEqual(select(p,'beast_mastery')['coordinate_mode'],'wow_client')

    def test_shared_future_edits_still_inherited(self):
        p=profile(document());bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client'}}
        select(p,'beast_mastery')
        p['classes']['hunter']['shared']['nodes']['Node_Target'].update(x=88,tolerance=33)
        node=select(p,'beast_mastery');self.assertEqual((node['x'],node['tolerance']),(88,33))

    def test_defaults_if_shared_missing_fields(self):
        p=profile(document());p['classes']['hunter']['shared']['nodes']['Node_Target']={}
        self.assertEqual(select(p,'beast_mastery'),store.default_nodes()['Node_Target'])

    def test_invalid_inactive_override_rejected(self):
        bad=[None,[],{'Skill_4':{}},{'Node_Target':None},{'Node_Target':{'bogus':1}},
             {'Node_Target':{'coordinate_mode':'bad'}},{'Node_Target':{'x':'32'}},
             {'Node_Target':{'command':{'action':'tap','key':'3'}}}]
        for override in bad:
            with self.subTest(override=override):
                d=document();bm(profile(d))['node_overrides']=override
                with self.assertRaises((ValueError,TypeError)):store.migrate(d)

    def test_gui_save_sparse_and_isolated(self):
        d=document();p=profile(d);bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client'}}
        select(p,'beast_mastery');shared=copy.deepcopy(p['classes']['hunter']['shared'])
        effective=copy.deepcopy(p['nodes'])
        spec_data.apply_changes(p,{'nodes':effective})
        self.assertEqual(bm(p)['node_overrides'],{'Node_Target':{'coordinate_mode':'wow_client'}})
        effective['Node_Target']['x']=32;effective['Node_Target']['r']=11
        spec_data.apply_changes(p,{'nodes':effective})
        self.assertEqual(bm(p)['node_overrides']['Node_Target'],{'coordinate_mode':'wow_client','x':32,'r':11})
        self.assertEqual(p['classes']['hunter']['shared'],shared)
        self.assertNotEqual(select(p,'marksmanship')['x'],32)

    def test_persist_roundtrip_without_shared_copy(self):
        d=document();p=profile(d);bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client'}}
        select(p,'beast_mastery')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json';store.write(path,d);loaded=store.read(path)
            self.assertEqual(bm(profile(loaded))['node_overrides'],{'Node_Target':{'coordinate_mode':'wow_client'}})
            self.assertEqual(profile(loaded)['nodes']['Node_Target']['coordinate_mode'],'wow_client')

    def test_other_profile_unaffected(self):
        d=document();d['profiles']['Other']=copy.deepcopy(profile(d));before=copy.deepcopy(d['profiles']['Other'])
        p=profile(d);bm(p)['node_overrides']={'Node_Mark':{'coordinate_mode':'wow_client'}}
        select(p,'beast_mastery');self.assertEqual(d['profiles']['Other'],before)


class Calibration(unittest.TestCase):
    def setUp(self):
        self.client=WowClient(1,2,'mock','Wow.exe',500,500,100,200,(100,200,600,700))

    def test_desktop(self):self.assertEqual(calibration_coordinates('desktop_absolute',100,200),(100,200))
    def test_wow_inverse(self):self.assertEqual(calibration_coordinates('wow_client',132,477,self.client),(32,277))
    def test_outside(self):
        for x,y in [(99,200),(600,200),(100,700)]:
            with self.assertRaises(WindowError):calibration_coordinates('wow_client',x,y,self.client)
    def test_mode_or_missing_window_no_fallback(self):
        for mode in ['wow_client','bad']:
            with self.assertRaises(WindowError):calibration_coordinates(mode,132,477)

    def test_failures_do_not_capture(self):
        for code in ['multiple_candidates','minimized','not_found','invalid_client']:
            with patch('wow_calibration.physical_pixels',return_value=nullcontext()), \
                 patch('wow_calibration.find_wow_client',side_effect=WindowError(code,'mock')), \
                 patch('wow_calibration.mss.MSS') as mss:
                with self.assertRaises(WindowError):capture_wow_calibration()
                mss.assert_not_called()

    def test_unreliable_dpi(self):
        with patch('wow_calibration.physical_pixels',side_effect=WindowError('dpi_unverified','mock')), \
             patch('wow_calibration.find_wow_client') as find:
            with self.assertRaises(WindowError):capture_wow_calibration()
            find.assert_not_called()

    def test_os_conversion_and_desktop_rgb(self):
        class Fn:
            def __init__(self,fn):self.fn=fn
            def __call__(self,*args):return self.fn(*args)
        def cursor(p):p._obj.x,p._obj.y=132,477;return 1
        def convert(hwnd,p):p._obj.x-=100;p._obj.y-=200;return 1
        user=SimpleNamespace(GetCursorPos=Fn(cursor),ScreenToClient=Fn(convert))
        sct=Mock();sct.monitors=[dict(left=0,top=0,width=1920,height=1080)]
        sct.__enter__=Mock(return_value=sct);sct.__exit__=Mock(return_value=False)
        sct.grab.return_value.pixel.return_value=(0,0,255)
        with patch('wow_calibration.physical_pixels',return_value=nullcontext()), \
             patch('wow_calibration.find_wow_client',return_value=self.client), \
             patch('wow_geometry_trace.snapshot',return_value={'client':self.client.to_dict()}), \
             patch('wow_calibration._libraries',return_value=(user,None)), \
             patch('wow_calibration._check_visible_owner'), \
             patch('wow_calibration.mss.MSS',return_value=sct):
            x,y,rgb,meta=capture_wow_calibration()
        self.assertEqual((x,y,rgb),(32,277,(0,0,255)))
        self.assertEqual((meta['screen_x'],meta['screen_y']),(132,477))
        sct.grab.assert_called_once_with(dict(left=132,top=477,width=1,height=1))


class NativeF8Routing(unittest.TestCase):
    """Posts only to our listener thread, never sends keyboard input to WoW."""
    def test_wow_route_and_error_events(self):
        from tests_udp.test_hotkey_capture import wait_events,post_hotkey,finish
        from hotkey_capture import F8Capture
        desktop_capture=Mock(return_value=(100,200,(1,2,3)))
        worker=F8Capture(capture=desktop_capture)
        context=(1,'temp','Node_Target','hunter','beast_mastery','wow_client')
        try:
            worker.start(context);wait_events(worker,'ready')
            with patch('wow_calibration.capture_wow_calibration',return_value=(32,277,(0,0,255),{'coordinate_mode':'wow_client','screen_x':132,'screen_y':477})):
                post_hotkey(worker)
                event=next(e for e in wait_events(worker,'capture') if e['kind']=='capture')
                self.assertEqual((event['x'],event['y'],event['coordinate_mode']),(32,277,'wow_client'))
                desktop_capture.assert_not_called()
            for code in ['out_of_bounds','multiple_candidates','minimized','dpi_unverified']:
                with patch('wow_calibration.capture_wow_calibration',side_effect=WindowError(code,'mock '+code)):
                    post_hotkey(worker);events=wait_events(worker,'capture_error')
                    self.assertFalse(any(e['kind']=='capture' for e in events))
            worker.set_context((2,'temp','Node_Target','hunter','beast_mastery','desktop_absolute'))
            post_hotkey(worker);event=next(e for e in wait_events(worker,'capture') if e['kind']=='capture')
            self.assertEqual((event['x'],event['y']),(100,200))
        finally:finish(worker)


class GuiModeAndPersistence(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from gui import MacroDashboard
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'config.json'
        d=document();p=profile(d);bm(p)['node_overrides']={'Node_Target':{'coordinate_mode':'wow_client'}}
        select(p,'beast_mastery');store.write(self.path,d)
        self.shared=copy.deepcopy(store.active(self.path)['classes']['hunter']['shared'])
        self.root=tk.Tk();self.root.withdraw()
        self.guard=patch('calibration_hotkeys.CalibrationHotkeys.start');self.guard.start()
        self.app=MacroDashboard(self.root,config_path=self.path)

    def tearDown(self):
        self.app.is_tracking=False;self.app.calibration_hotkeys.stop()
        self.app.hotkey_capture.stop();self.app.restore_output();self.app.vision.close()
        for ident in self.root.tk.call('after','info'):self.root.after_cancel(ident)
        self.root.destroy();self.guard.stop();self.temp.cleanup()

    def test_mode_label_and_context(self):
        self.app.capture_target_var.set('Node_Target')
        self.assertEqual(self.app.coordinate_labels['Node_Target'].get(),'WoW Client')
        self.assertEqual(self.app.coordinate_labels['Node_Mark'].get(),'Desktop')
        self.assertEqual(self.app.capture_context()[-1],'wow_client')
        self.assertIn('WoW Client',self.app.capture_hint_var.get())

    def test_gui_save_does_not_leak_override(self):
        self.app.capture_target_var.set('Node_Target');self.app.is_tracking=True
        event=dict(context=self.app.capture_context(),coordinate_mode='wow_client',x=32,y=277,rgb=(0,0,255))
        self.assertTrue(self.app.apply_capture_event(event));self.app.is_tracking=False
        self.assertTrue(self.app.save_config_from_entries())
        p=store.active(self.path)
        self.assertEqual(p['classes']['hunter']['shared'],self.shared)
        self.assertEqual((p['nodes']['Node_Target']['x'],p['nodes']['Node_Target']['y']),(32,277))
        self.assertEqual(bm(p)['node_overrides']['Node_Target']['coordinate_mode'],'wow_client')
        self.assertNotIn('threshold',bm(p)['node_overrides']['Node_Target'])
        self.assertEqual(select(p,'marksmanship')['coordinate_mode'] if 'coordinate_mode' in select(p,'marksmanship') else 'desktop_absolute','desktop_absolute')

    def test_reject_desktop_result_for_client_node(self):
        self.app.capture_target_var.set('Node_Target');self.app.is_tracking=True
        before=self.app.config_entries['Node_Target']['x'].get()
        self.assertFalse(self.app.apply_capture_event(dict(context=self.app.capture_context(),x=132,y=477,rgb=(0,0,255))))
        self.assertEqual(self.app.config_entries['Node_Target']['x'].get(),before)


if __name__=='__main__':unittest.main(verbosity=2)
