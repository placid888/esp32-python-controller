import sys,unittest,time,tempfile,json,threading,statistics
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from detector import DetectorWorker,sample_node
from profile_store import default_nodes,migrate,write,read
from skill_model import SKILL_PRIORITY,skill_command

class Clock:
    t=0.
    def __call__(self):return self.t
class Pixels:
    def __init__(self):self.values={0:True,1:True};self.reads=[]
    def get_region_rgb(self,x,y,size):
        self.reads.append(x);return [(255,255,255) if self.values.get(x,False) else (0,0,0)]*(size*size)
    def close(self):pass
class Tests(unittest.TestCase):
    def setUp(self):
        self.nodes=default_nodes()
        for i,n in enumerate(self.nodes.values()):n.update(x=i,min_delay=50,max_delay=50,enabled=i in (0,1))
        self.c=Clock();self.v=Pixels();self.sent=[]
        self.w=DetectorWorker(self.nodes,lambda cmd,**kw:self.sent.append(cmd) or True,lambda:self.v,clock=self.c)
    def step(self,t):self.c.t=t;self.w.step(self.v)
    def test01_gate_false(self):
        self.v.values[0]=False;self.step(0);self.step(.1);self.assertFalse(self.sent);self.assertEqual(self.v.reads,[0,0])
    def test02_four(self):self.step(0);self.step(.051);self.assertEqual(self.sent,[skill_command('Skill_4')])
    def test03_repeat(self):
        self.step(0)
        for t in (.051,.102,.153):self.step(t)
        self.assertEqual(len(self.sent),3)
    def test04_own_false(self):self.v.values[1]=False;self.step(0);self.step(.1);self.assertFalse(self.sent)
    def test05_gate_loss(self):self.step(0);self.v.values[0]=False;self.step(.051);self.assertFalse(self.sent);self.assertEqual(self.w.cancel_count,1)
    def test06_skill_loss(self):self.step(0);self.v.values[1]=False;self.step(.051);self.assertFalse(self.sent)
    def test07_priority(self):
        self.w.nodes['Skill_6']['enabled']=True;self.v.values[3]=True;self.step(0);self.step(.051);self.step(.102)
        self.assertEqual([c['key'] for c in self.sent],['4','4'])
    def test08_handover(self):
        self.w.nodes['Skill_6']['enabled']=True;self.v.values[3]=True;self.step(0);self.step(.051);self.v.values[1]=False;self.step(.06);self.step(.111)
        self.assertEqual([c['key'] for c in self.sent],['4','6'])
    def test09_disabled(self):self.w.nodes['Skill_4']['enabled']=False;self.step(0);self.step(.1);self.assertFalse(self.sent);self.assertNotIn(1,self.v.reads)
    def test10_single_cycle(self):
        for n in self.w.nodes.values():n['enabled']=True
        self.v.values.update({i:True for i in range(8)});self.step(0);self.step(.051);self.assertEqual(len(self.sent),1)
    def test11_no_letters(self):
        for name in SKILL_PRIORITY:
            self.w.nodes=default_nodes()
            for i,(key,n) in enumerate(self.w.nodes.items()):n.update(enabled=key in ('Node_Target',name),x=i,min_delay=50,max_delay=50,command={'action':'tap','key':'e'} if key!='Node_Target' else None)
            self.w.brain.reset();self.v.values={i:True for i in range(8)};self.step(0);self.step(.051)
        self.assertEqual([x['key'] for x in self.sent],list('4567890'))
    def test12_region(self):
        for size,good,bad in [('3x3',3,2),('5x5',8,7)]:
            n=default_nodes()['Skill_4'];n.update(enabled=True,sample_mode=size,match_ratio=.3,mode='color',r=0,g=0,b=255,tolerance=0)
            count=int(size[0])**2
            class Region:
                def get_region_rgb(self,*a):return [(0,0,255)]*self.hits+[(255,0,0)]*(count-self.hits)
            v=Region();v.hits=good;self.assertTrue(sample_node(v,n)[0]);v.hits=bad;self.assertFalse(sample_node(v,n)[0])
            n.update(mode='brightness',threshold=200);v.hits=good
            v.get_region_rgb=lambda *a:[(255,255,255)]*v.hits+[(0,0,0)]*(count-v.hits)
            self.assertTrue(sample_node(v,n)[0]);v.hits=bad;self.assertFalse(sample_node(v,n)[0])
    def test13_legacy_profiles(self):
        old=default_nodes()
        for n in old.values():n.pop('sample_mode');n.pop('match_ratio')
        d=migrate({'nodes':old});self.assertEqual(d['profiles']['Default']['nodes']['Skill_4']['sample_mode'],'single_pixel')
        with tempfile.TemporaryDirectory() as t:
            f=Path(t)/'c.json';write(f,d);self.assertEqual(read(f),d)
    def test14_stop(self):
        self.w=DetectorWorker(self.nodes,lambda *a,**k:self.sent.append(a) or True,lambda:self.v)
        self.w.start();time.sleep(.015);self.w.stop();time.sleep(.07)
        self.assertFalse(self.sent);self.assertFalse(self.w.brain.pending);self.assertFalse(self.w.thread.is_alive())
    def test15_gui_stall_timing(self):
        # Real Tk exists but intentionally receives no event processing for 1.4s.
        import tkinter as tk
        root=tk.Tk();root.withdraw()
        self.w=DetectorWorker(self.nodes,lambda cmd,**kw:self.sent.append(cmd) or True,lambda:self.v)
        try:
            self.w.start();time.sleep(1.4);self.w.stop()
            records=[]
            while not self.w.events.empty():records.append(self.w.events.get_nowait())
            dispatch=[r for r in records if r['event']=='GATE_DISPATCH'];errors=[r['scheduling_error_ms'] for r in dispatch]
            self.assertGreaterEqual(len(errors),20)
            result={'dispatches':len(errors),'average_scheduling_error_ms':statistics.mean(errors),'maximum_scheduling_error_ms':max(errors),'scan_hz':self.w.scan_count/(time.monotonic()-self.w.started),'test':'synthetic pixels + fake sender; real Tk main thread blocked 1.4 seconds; no ESP32','errors_ms':errors}
            out=Path(__file__).resolve().parents[1]/'backups/detector-worker-20261101/timing-result.json';out.write_text(json.dumps(result,indent=2))
            self.assertLess(max(errors),500)
        finally:self.w.stop();root.destroy()
    def test16_gui_region_save_reload(self):
        import tkinter as tk
        from gui import MacroDashboard
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json';write(path,{'nodes':default_nodes()})
            root=tk.Tk();root.withdraw();app=MacroDashboard(root,config_path=path)
            try:
                app.edit_node('Skill_4');frame=app.node_editor.winfo_children()[0]
                for widget in frame.winfo_children():
                    info=widget.grid_info()
                    if info.get('row')==6 and info.get('column')==1:widget.set('5x5')
                    if info.get('row')==7 and info.get('column')==1:widget.delete(0,tk.END);widget.insert(0,'0.4')
                [w for w in frame.winfo_children() if w.grid_info().get('row')==9][0].invoke()
                self.assertTrue(app.save_config_from_entries())
                n=read(path)['profiles']['Default']['nodes']['Skill_4']
                self.assertEqual((n['sample_mode'],n['match_ratio']),('5x5',.4))
                self.assertEqual(n['command'],skill_command('Skill_4'))
            finally:
                app.stop_loop();app.restore_output();app.vision.close();root.destroy()
if __name__=='__main__':unittest.main(verbosity=2)
