import sys,unittest,tempfile,json,time,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from detector import DetectorWorker
from profile_store import default_nodes,migrate,write,read
from skill_model import SKILL_PRIORITY,skill_command
class Clock:
    t=0.
    def __call__(self):return self.t
class Pixels:
    def __init__(self):self.values={0:(0,0,255),1:(255,0,0),4:(255,255,255)};self.reads=[]
    def get_region_rgb(self,x,y,size):self.reads.append(x);return [self.values.get(x,(0,0,0))]*(size*size)
    def close(self):pass
class Combat(unittest.TestCase):
    def setUp(self):
        self.nodes=default_nodes()
        self.nodes['Node_Target'].update(x=0,mode='color',r=0,g=0,b=255)
        self.nodes['Node_Combat'].update(x=1)
        for name in SKILL_PRIORITY:self.nodes[name].update(x=int(name[-1]),enabled=name=='Skill_4',min_delay=50,max_delay=50)
        self.c=Clock();self.v=Pixels();self.sent=[]
    def worker(self,mode):return DetectorWorker(self.nodes,lambda cmd,**kw:self.sent.append(cmd) or True,lambda:self.v,clock=self.c,combat_mode=mode)
    def step(self,w,t):self.c.t=t;w.step(self.v)
    def test01_auto_ignores_combat(self):
        self.v.values[1]=(0,0,0);w=self.worker('auto');self.step(w,0);self.step(w,.051)
        self.assertEqual(self.sent,[skill_command('Skill_4')]);self.assertNotIn(1,self.v.reads)
    def test02_manual_wait(self):
        self.v.values[1]=(0,0,0);w=self.worker('manual_first_hit');self.step(w,0);self.step(w,.1)
        self.assertFalse(self.sent);self.assertEqual(w.last_snapshot['reason'],'waiting_for_combat');self.assertFalse(w.last_snapshot['Gate'])
    def test03_manual_open(self):
        w=self.worker('manual_first_hit');self.step(w,0);self.step(w,.051);self.assertEqual(self.sent,[skill_command('Skill_4')])
    def test04_combat_loss_cancels(self):
        w=self.worker('manual_first_hit');self.step(w,0);self.assertTrue(w.brain.pending)
        self.v.values[1]=(0,0,0);self.step(w,.051);self.assertFalse(self.sent);self.assertFalse(w.brain.pending);self.assertEqual(w.cancel_count,1)
    def test05_target_false_always_blocks(self):
        self.v.values[0]=(0,0,0)
        for mode in ('auto','manual_first_hit'):
            for color in ((255,0,0),(0,0,0)):
                self.v.values[1]=color;w=self.worker(mode);self.step(w,0);self.step(w,.1);self.assertFalse(w.brain.pending)
        self.assertFalse(self.sent);self.assertTrue(all(x==0 for x in self.v.reads))
    def test06_manual_no_skill_sampling(self):
        self.v.values[1]=(0,0,0);w=self.worker('manual_first_hit');self.step(w,0);self.assertEqual(self.v.reads,[0,1])
    def test07_priority_unchanged(self):
        for name in SKILL_PRIORITY:self.nodes[name]['enabled']=True;self.v.values[int(name[-1])]=(255,255,255)
        # Skill_0 coordinate must not overlap the blue Target.
        self.nodes['Skill_0']['x']=10;self.v.values[10]=(255,255,255);self.v.values[0]=(0,0,255)
        w=self.worker('manual_first_hit');self.step(w,0);self.step(w,.051);self.assertEqual(self.sent,[skill_command('Skill_4')])
    def test08_continuous_repeat(self):
        w=self.worker('manual_first_hit');self.step(w,0)
        for t in (.051,.102,.153):self.step(w,t)
        self.assertEqual([x['key'] for x in self.sent],['4','4','4'])
    def test09_legacy_migration(self):
        self.nodes.pop('Node_Combat');old={'nodes':self.nodes,'custom':'preserved'};d=migrate(old);profile=d['profiles']['Default']
        self.assertEqual(profile['combat_mode'],'auto');self.assertEqual(profile['nodes']['Node_Target'],self.nodes['Node_Target']);self.assertEqual(profile['custom'],'preserved')
        self.nodes=profile['nodes'];self.v.values[1]=(0,0,0);w=self.worker(profile['combat_mode']);self.step(w,0);self.step(w,.051);self.assertEqual(len(self.sent),1)
    def test10_stop_pending(self):
        self.nodes['Skill_4'].update(min_delay=1000,max_delay=1000)
        w=DetectorWorker(self.nodes,lambda *a,**k:self.sent.append(a) or True,lambda:self.v,combat_mode='manual_first_hit');w.start()
        end=time.monotonic()+1
        while w.scan_count<1 and time.monotonic()<end:time.sleep(.002)
        w.stop();self.assertFalse(self.sent);self.assertFalse(w.brain.pending);self.assertFalse(w.thread.is_alive())
    def test11_combat_disabled_fail_closed(self):
        self.nodes['Node_Combat']['enabled']=False;w=self.worker('manual_first_hit');self.step(w,0);self.step(w,.1);self.assertFalse(self.sent);self.assertEqual(self.v.reads,[0,0])
    def test12_reenter_fresh_delay(self):
        w=self.worker('manual_first_hit');self.step(w,0);self.v.values[1]=(0,0,0);self.step(w,.04)
        self.v.values[1]=(255,0,0);self.step(w,.05);self.step(w,.06);self.assertFalse(self.sent);self.step(w,.101);self.assertEqual(len(self.sent),1)
    def test13_preserve_custom_combat(self):
        self.nodes['Node_Combat'].update(x=123,sample_mode='5x5',match_ratio=.6,r=240,tolerance=30)
        d=migrate({'nodes':self.nodes,'combat_mode':'manual_first_hit'})
        self.assertEqual(d['profiles']['Default']['nodes']['Node_Combat'],self.nodes['Node_Combat'])
        self.assertIsNone(d['profiles']['Default']['nodes']['Node_Combat']['command'])
    def test14_gui_save_reload_capture(self):
        import tkinter as tk
        from gui import MacroDashboard
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'config.json';write(f,{'nodes':self.nodes})
            root=tk.Tk();root.withdraw();app=MacroDashboard(root,config_path=f)
            try:
                self.assertIn('Node_Combat',app.capture_radios);app.combat_mode_var.set('手動第一下');app.capture_target_var.set('Node_Combat')
                app.is_tracking=True
                self.assertTrue(app.apply_capture_event({'context':app.capture_context(),'x':123,'y':234,'rgb':(250,1,2)}))
                app.is_tracking=False;self.assertTrue(app.save_config_from_entries());app.load_config_into_entries(False)
                self.assertEqual(app.runtime_combat_mode,'manual_first_hit');self.assertEqual(app.combat_mode_var.get(),'手動第一下')
                n=read(f)['profiles']['Default']['nodes']['Node_Combat'];self.assertEqual((n['x'],n['y'],n['r']),(123,234,250));self.assertIsNone(n['command'])
            finally:app.stop_loop();app.restore_output();app.vision.close();root.destroy()
if __name__=='__main__':unittest.main(verbosity=2)
