import copy,sys,unittest,tempfile,json,time,threading,hashlib,random
from pathlib import Path
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
from brightness_calibration import analyze,apply_threshold,region_brightness,CalibrationJob
from profile_store import default_nodes,write,read,migrate
from skill_model import SKILL_PRIORITY,skill_command
from detector import sample_node
class Unit(unittest.TestCase):
    def setUp(self):self.nodes=default_nodes();self.result=analyze([30]*15,[110]*15)
    def test01_threshold70(self):self.assertEqual(self.result['suggested_threshold'],70)
    def test02_median_not_last(self):
        r=analyze([30]*14+[99],[110]*14+[200]);self.assertEqual(r['suggested_threshold'],70);self.assertEqual(r['dark']['max'],99);self.assertEqual(r['dark']['samples'],15)
    def test03_reverse_and_equal_invalid(self):
        for bright in ([30],[20]):
            r=analyze([30],bright);self.assertFalse(r['valid']);self.assertIsNone(r['suggested_threshold'])
            with self.assertRaises(ValueError):apply_threshold(self.nodes,'Skill_4',r)
    def test04_no_overlap(self):self.assertFalse(analyze([28,35,39],[108,119,127])['overlap'])
    def test05_overlap_warning(self):
        r=analyze([10,30,100],[90,110,120]);self.assertTrue(r['overlap']);self.assertTrue(r['valid']);self.assertEqual(r['suggested_threshold'],70)
    def test06_skill4_only(self):
        updated=apply_threshold(self.nodes,'Skill_4',self.result)
        for name in self.nodes:
            if name!='Skill_4':self.assertEqual(updated[name],self.nodes[name])
        self.assertEqual(self.nodes['Skill_4']['threshold'],200)
    def test07_skill0_only(self):
        updated=apply_threshold(self.nodes,'Skill_0',self.result)
        for name in self.nodes:
            if name!='Skill_0':self.assertEqual(updated[name],self.nodes[name])
    def test08_only_threshold_field_changes(self):
        before=copy.deepcopy(self.nodes['Skill_4']);after=apply_threshold(self.nodes,'Skill_4',self.result)['Skill_4']
        self.assertEqual([k for k in before if before[k]!=after[k]],['threshold'])
    def test09_color_not_switched(self):
        self.nodes['Skill_4']['mode']='color'
        with self.assertRaises(ValueError):apply_threshold(self.nodes,'Skill_4',self.result)
        self.assertEqual(self.nodes['Skill_4']['mode'],'color')
    def test10_red_not_switched(self):
        self.nodes['Skill_4']['mode']='red'
        with self.assertRaises(ValueError):apply_threshold(self.nodes,'Skill_4',self.result)
        self.assertEqual(self.nodes['Skill_4']['mode'],'red')
    def test11_legacy_no_calibration_data(self):
        d=migrate({'nodes':self.nodes});self.assertNotIn('calibration',d['profiles']['Default']);self.assertEqual(d['profiles']['Default']['nodes'],self.nodes)
    def test12_profile_roundtrip(self):
        nodes=apply_threshold(self.nodes,'Skill_4',self.result)
        with tempfile.TemporaryDirectory() as t:
            p=Path(t)/'config.json';write(p,{'nodes':nodes});self.assertEqual(read(p)['profiles']['Default']['nodes']['Skill_4']['threshold'],70)
    def test13_gate_nodes_unchanged(self):
        updated=apply_threshold(self.nodes,'Skill_5',self.result)
        for name in ('Node_Target','Node_Combat','Node_Mark'):self.assertEqual(updated[name],self.nodes[name])
    def test14_protected_source_byte_identical(self):
        before=json.loads((P/'backups/brightness-calibration-20261101/SHA256-before.json').read_text())
        for name in ('detector.py','decision.py','vision.py','mark_opener.py','skill_model.py','profile_store.py','transport.py','hotkey_capture.py'):
            self.assertEqual(hashlib.sha256((P/name).read_bytes()).hexdigest(),('9ed430c720266047d0a2a731cae424dfd0dd952cb3e8ec76f70a3b995bce092e' if name=='hotkey_capture.py' else '14faff783b8c7f993539bdb429cc9d1bb839722d174208e13f66cb86773a880a' if name=='profile_store.py' else before[name]),name)
        for name,sha in before.items():
            if name.startswith('C:'):self.assertEqual(hashlib.sha256(Path(name).read_bytes()).hexdigest(),sha)
    def test15_priority_mapping_unchanged(self):
        self.assertEqual(SKILL_PRIORITY,tuple('Skill_'+k for k in '4567890'))
        self.assertEqual([skill_command(n)['key'] for n in SKILL_PRIORITY],list('4567890'))
    def test16_ratio_equivalence_all_thresholds(self):
        rng=random.Random(20)
        for size in (1,3,5):
            pixels=[tuple(rng.randrange(256) for _ in range(3)) for i in range(size*size)]
            for ratio in (.1,.3,.5,1.):
                value=region_brightness(pixels,ratio)
                node=self.nodes['Skill_4']|{'enabled':True,'mode':'brightness','match_ratio':ratio,'sample_mode':{1:'single_pixel',3:'3x3',5:'5x5'}[size]}
                for threshold in range(256):
                    node['threshold']=threshold
                    self.assertEqual(value>threshold,sample_node(None,node,pixels)[0])
    def test17_not_area_average(self):
        pixels=[(255,255,255)]*3+[(0,0,0)]*6
        self.assertEqual(region_brightness(pixels,.30),255)
    def test18_worker_same_thread_and_count(self):
        seen=[]
        class Vision:
            def __init__(self):seen.append(('create',threading.get_ident()))
            def get_region_rgb(self,x,y,size):seen.append(('read',threading.get_ident(),x,y,size));return [(30,30,30)]*(size*size)
            def close(self):seen.append(('close',threading.get_ident()))
        n=self.nodes['Skill_4']|{'x':50,'y':60,'sample_mode':'3x3'};job=CalibrationJob(n,Vision);job.start();job.thread.join(2)
        self.assertFalse(job.alive);result=job.result.get_nowait();self.assertEqual(len(result['values']),15)
        self.assertTrue(all(r[1]!=threading.get_ident() for r in seen));self.assertEqual(len({r[1] for r in seen}),1)
        self.assertTrue(all(r[2:]==(50,60,3) for r in seen if r[0]=='read'))
        self.assertGreaterEqual(result['duration_ms'],300)
    def test19_worker_error_no_partial_success(self):
        class Bad:
            def get_region_rgb(self,*args):raise OSError('screenshot failed')
            def close(self):pass
        job=CalibrationJob(self.nodes['Skill_4'],Bad);job.start();job.thread.join(1);self.assertIn('error',job.result.get_nowait())
    def test20_cancel_worker(self):
        class V:
            def get_region_rgb(self,*args):return [(30,30,30)]
            def close(self):pass
        job=CalibrationJob(self.nodes['Skill_4'],V);job.start();job.cancel();job.thread.join(1);self.assertFalse(job.alive)
class GUI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from gui import MacroDashboard
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'config.json';write(self.path,{'nodes':default_nodes()})
        self.root=tk.Tk();self.root.withdraw();self.app=MacroDashboard(self.root,config_path=self.path);self.app.edit_node('Skill_4');self.app.node_editor.withdraw();self.panel=self.app.calibration_panel
    def tearDown(self):
        from calibration_ui import cancel_all
        self.app.is_running=False;cancel_all(self.app)
        for j in self.app.calibration_jobs:
            if j.thread:j.thread.join(2)
        if self.app.node_editor.winfo_exists():self.app.node_editor.destroy()
        self.app.stop_loop();self.app.restore_output();self.app.vision.close();self.root.destroy();self.temp.cleanup()
    def test21_monitor_blocks_sampling(self):
        calls=[];self.panel.vision_factory=lambda:calls.append(1)
        self.app.is_running=True;self.assertFalse(self.panel.capture('dark'));self.assertEqual(calls,[]);self.assertEqual(self.app.calibration_jobs,[])
        self.assertIn('請先停止',self.panel.status.get())
    def test22_gui_apply_only_threshold_and_roundtrip(self):
        before=self.app.edited_nodes();self.panel.samples={'dark':[30]*15,'bright':[110]*15};self.panel.context=self.panel.fingerprint(self.panel.node());self.panel.render()
        self.assertTrue(self.panel.apply());after=self.app.edited_nodes()
        expected=copy.deepcopy(before);expected['Skill_4']['threshold']=70;self.assertEqual(after,expected)
        self.assertTrue(self.app.save_config_from_entries());self.app.load_config_into_entries(False);self.assertEqual(int(self.app.config_entries['Skill_4']['threshold'].get()),70)
    def test23_gui_color_red_disabled(self):
        for mode in ('color','red'):
            self.app.node_vars['Skill_4']['mode'].set(mode);self.panel.refresh();self.assertTrue(self.panel.dark_button.instate(['disabled']))
            self.assertFalse(self.panel.capture('dark'));self.assertEqual(self.app.node_vars['Skill_4']['mode'].get(),mode)
    def test24_gui_async_capture_and_monitor_start_block(self):
        from calibration_ui import busy
        class V:
            def get_region_rgb(self,*args):return [(30,30,30)]
            def close(self):pass
        self.panel.vision_factory=V;self.assertTrue(self.panel.capture('dark'));self.assertTrue(busy(self.app))
        from unittest.mock import patch,PropertyMock
        with patch.object(type(self.app.controller),'is_open',new_callable=PropertyMock,return_value=True):
            self.app.start_loop();self.assertFalse(self.app.is_running)
        self.assertIn('校正',self.app.txt_log.get('1.0','end'))
        beats=[];self.root.after(25,lambda:beats.append(1));end=time.monotonic()+2
        while self.panel.job is not None and time.monotonic()<end:self.root.update();time.sleep(.005)
        self.assertTrue(beats);self.assertEqual(len(self.panel.samples['dark']),15)
    def test25_changed_coordinates_invalidates_result(self):
        self.panel.samples={'dark':[30]*15,'bright':[110]*15};self.panel.context=self.panel.fingerprint(self.panel.node());self.panel.render()
        entry=self.app.config_entries['Skill_4']['x'];entry.delete(0,'end');entry.insert(0,'123');self.assertFalse(self.panel.apply());self.assertIsNone(self.panel.analysis)
    def test26_gate_editor_no_calibration(self):
        for name in ('Node_Target','Node_Combat','Node_Mark'):
            self.app.edit_node(name);self.app.node_editor.withdraw();frames=self.app.node_editor.winfo_children()[0].winfo_children()
            self.assertFalse(any(w.winfo_class()=='TLabelframe' for w in frames))
    def test27_reverse_gui_apply_disabled(self):
        self.panel.samples={'dark':[110]*15,'bright':[30]*15};self.panel.context=self.panel.fingerprint(self.panel.node());self.panel.render();self.panel.refresh()
        before=self.app.edited_nodes();self.assertTrue(self.panel.apply_button.instate(['disabled']));self.assertFalse(self.panel.apply());self.assertEqual(self.app.edited_nodes(),before)
if __name__=='__main__':unittest.main(verbosity=2)
