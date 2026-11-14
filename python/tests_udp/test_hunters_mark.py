import sys,unittest,time,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from detector import DetectorWorker
from profile_store import default_nodes,migrate,write,read
from mark_opener import mark_settings
from skill_model import SKILL_PRIORITY,skill_command
class Clock:
    t=0.
    def __call__(self):return self.t
class Pixels:
    def __init__(self):self.values={0:(0,0,255),1:(255,0,0),2:(0,0,0),24:(255,255,255)};self.reads=[]
    def get_region_rgb(self,x,y,size):self.reads.append(x);return [self.values.get(x,(0,0,0))]*(size*size)
    def close(self):pass
class MarkTests(unittest.TestCase):
    def setUp(self):
        self.nodes=default_nodes();self.nodes['Node_Target'].update(x=0,mode='color',r=0,g=0,b=255)
        self.nodes['Node_Combat'].update(x=1);self.nodes['Node_Mark'].update(x=2)
        for name in SKILL_PRIORITY:self.nodes[name].update(x=20+int(name[-1]),enabled=name=='Skill_4',min_delay=50,max_delay=50)
        self.c=Clock();self.v=Pixels();self.sent=[]
    def worker(self,mode='pre_combat',combat='auto',sender=None):
        return DetectorWorker(self.nodes,sender or (lambda cmd,**kw:self.sent.append((cmd,kw['source_node'])) or True),lambda:self.v,clock=self.c,combat_mode=combat,hunter_mark_mode=mode)
    def step(self,w,t):self.c.t=t;w.step(self.v)
    def marked(self,yes=True):self.v.values[2]=(0,255,0) if yes else (0,0,0)
    def combat(self,yes):self.v.values[1]=(255,0,0) if yes else (0,0,0)
    def keys(self):return [cmd['key'] for cmd,source in self.sent]
    def test01_off_preserves_auto_manual(self):
        for combat in ('auto','manual_first_hit'):
            self.sent=[];self.v.reads=[];self.combat(False);w=self.worker('off',combat);self.step(w,0);self.step(w,.051)
            self.assertEqual(self.keys(),['4'] if combat=='auto' else []);self.assertNotIn(2,self.v.reads)
    def test02_pre_missing_opener(self):
        w=self.worker();self.step(w,0);self.assertEqual(self.keys(),['3']);self.assertEqual(self.sent[0][1],'Opener_Mark')
    def test03_pre_marked_no_opener(self):
        self.marked();w=self.worker();self.step(w,0);self.assertFalse(self.sent);self.assertIsNone(w.opener.pending)
    def test04_pre_auto_no_skill_before_mark(self):
        w=self.worker();self.step(w,0);self.step(w,.051);self.assertEqual(self.keys(),['3']);self.assertNotIn(24,self.v.reads)
    def test05_pre_auto_marked_skills(self):
        self.marked();w=self.worker();self.step(w,0);self.step(w,.051);self.assertEqual(self.keys(),['4'])
    def test06_pre_manual_opens_before_combat(self):
        self.combat(False);w=self.worker(combat='manual_first_hit');self.step(w,0);self.assertEqual(self.keys(),['3']);self.assertNotIn(1,self.v.reads)
    def test07_pre_manual_wait_combat(self):
        self.marked();self.combat(False);w=self.worker(combat='manual_first_hit');self.step(w,0);self.step(w,.1);self.assertFalse(self.sent);self.assertEqual(w.last_snapshot['reason'],'waiting_for_combat')
    def test08_pre_manual_all_true(self):
        self.marked();w=self.worker(combat='manual_first_hit');self.step(w,0);self.step(w,.051);self.assertEqual(self.keys(),['4'])
    def test09_post_wait_combat_no_mark_read(self):
        self.combat(False);w=self.worker('post_combat');self.step(w,0);self.assertFalse(self.sent);self.assertEqual(self.v.reads,[0,1])
    def test10_post_missing_opener_first(self):
        w=self.worker('post_combat');self.step(w,0);self.assertEqual(self.keys(),['3']);self.assertNotIn(24,self.v.reads)
    def test11_post_no_skill_while_waiting(self):
        w=self.worker('post_combat');self.step(w,0)
        for i in range(1,40):self.step(w,i*.01)
        self.assertEqual(self.keys(),['3']);self.assertFalse(w.last_snapshot['Gate'])
    def test12_post_mark_confirmation(self):
        w=self.worker('post_combat');self.step(w,0);self.marked();self.step(w,.01);self.step(w,.061);self.assertEqual(self.keys(),['3','4']);self.assertTrue(w.last_snapshot['opener_complete'])
    def test13_retry_not_scan_spam(self):
        w=self.worker();self.step(w,0)
        for i in range(1,50):self.step(w,i*.01)
        self.assertEqual(self.keys(),['3']);self.step(w,.5);self.assertEqual(self.keys(),['3','3']);self.step(w,.501);self.assertEqual(len(self.sent),2)
    def test14_target_loss_cancel_retry(self):
        w=self.worker();self.step(w,0);self.v.values[0]=(0,0,0);self.step(w,.5);self.assertIsNone(w.opener.pending);self.assertEqual(self.keys(),['3']);self.assertFalse(w.brain.pending)
    def test15_post_combat_loss_cancel_retry(self):
        w=self.worker('post_combat');self.step(w,0);self.combat(False);self.step(w,.5);self.assertIsNone(w.opener.pending);self.assertEqual(self.keys(),['3'])
    def test16_mark_true_at_retry_deadline(self):
        w=self.worker();self.step(w,0);self.marked();self.step(w,.5);self.assertEqual(self.keys(),['3']);self.assertIsNone(w.opener.pending)
    def test17_already_marked_target(self):
        self.marked();w=self.worker();self.step(w,0);self.step(w,.051);self.assertNotIn('3',self.keys())
    def test18_mark_loss_pauses_normal(self):
        self.marked();w=self.worker();self.step(w,0);self.step(w,.051);self.marked(False);self.step(w,.102)
        self.assertEqual(self.keys(),['4','3']);self.assertFalse(w.brain.pending);self.assertFalse(w.last_snapshot['Gate'])
    def test19_priority_unchanged(self):
        for mode in ('off','pre_combat','post_combat'):
            self.sent=[];self.marked();w=self.worker(mode)
            for name in SKILL_PRIORITY:w.nodes[name]['enabled']=True;self.v.values[w.nodes[name]['x']]=(255,255,255)
            self.step(w,0);self.step(w,.051);self.assertEqual(self.keys(),['4'])
    def test20_repeat_unchanged(self):
        self.marked();w=self.worker();self.step(w,0)
        for t in (.051,.102,.153):self.step(w,t)
        self.assertEqual(self.keys(),['4','4','4'])
    def test21_legacy_migrate_off(self):
        old={k:v for k,v in self.nodes.items() if k!='Node_Mark'}
        d=migrate({'nodes':old,'combat_mode':'manual_first_hit','custom':123});profile=d['profiles']['Default']
        self.assertEqual(profile['hunter_mark_mode'],'off');self.assertEqual(profile['hunter_mark_key'],'3');self.assertEqual(profile['hunter_mark_retry_ms'],500)
        for name,n in old.items():self.assertEqual(profile['nodes'][name],n)
        self.assertEqual(profile['custom'],123);self.assertIsNone(profile['nodes']['Node_Mark']['command'])
    def test22_stop_cancels_opener_and_normal(self):
        for marked in (False,True):
            self.sent=[];self.marked(marked)
            for name in SKILL_PRIORITY:self.nodes[name].update(min_delay=1000,max_delay=1000)
            w=DetectorWorker(self.nodes,lambda cmd,**kw:self.sent.append((cmd,kw['source_node'])) or True,lambda:self.v,hunter_mark_mode='pre_combat');w.start()
            end=time.monotonic()+1
            while w.scan_count<1 and time.monotonic()<end:time.sleep(.002)
            w.stop();count=len(self.sent);time.sleep(.02);self.assertEqual(count,len(self.sent));self.assertFalse(w.brain.pending);self.assertIsNone(w.opener.pending);self.assertFalse(w.thread.is_alive())
    def test23_existing_json_shape(self):
        w=self.worker();self.step(w,0)
        self.assertEqual(json.dumps(self.sent[0][0],separators=(',',':')).encode(),b'{"action":"tap","key":"3"}')
    def test24_mark_disabled_fail_closed(self):
        self.nodes['Node_Mark']['enabled']=False;w=self.worker();self.step(w,0);self.step(w,.6);self.assertFalse(self.sent);self.assertEqual(w.last_snapshot['reason'],'mark_node_disabled')
    def test25_queue_failure_obeys_retry(self):
        attempts=[];w=self.worker(sender=lambda *a,**k:attempts.append(a) and False);self.step(w,0);self.step(w,.01);self.assertEqual(len(attempts),1);self.step(w,.5);self.assertEqual(len(attempts),2)
    def test26_gui_save_f8_reload(self):
        import tkinter as tk
        from gui import MacroDashboard
        from profile_ui import MARK_LABELS
        with tempfile.TemporaryDirectory() as tmp:
            f=Path(tmp)/'config.json';write(f,{'nodes':self.nodes});root=tk.Tk();root.withdraw();app=MacroDashboard(root,config_path=f)
            try:
                self.assertIn('Node_Mark',app.capture_radios);app.hunter_mark_mode_var.set(MARK_LABELS['pre_combat']);app.hunter_mark_key_var.set('2');app.hunter_mark_retry_var.set('750')
                app.capture_target_var.set('Node_Mark');app.is_tracking=True
                self.assertTrue(app.apply_capture_event({'context':app.capture_context(),'x':345,'y':456,'rgb':(1,250,2)}));app.is_tracking=False
                self.assertTrue(app.save_config_from_entries());app.load_config_into_entries(False)
                self.assertEqual(app.runtime_mark_settings,dict(hunter_mark_mode='pre_combat',hunter_mark_key='2',hunter_mark_retry_ms=750))
                n=read(f)['profiles']['Default']['nodes']['Node_Mark'];self.assertEqual((n['x'],n['y'],n['g']),(345,456,250));self.assertIsNone(n['command'])
            finally:app.stop_loop();app.restore_output();app.vision.close();root.destroy()
    def test27_preserve_custom_mark_profile(self):
        self.nodes['Node_Mark'].update(x=999,sample_mode='5x5',match_ratio=.6)
        d=migrate({'nodes':self.nodes,'hunter_mark_mode':'post_combat','hunter_mark_key':'2','hunter_mark_retry_ms':700})['profiles']['Default']
        self.assertEqual(d['nodes']['Node_Mark'],self.nodes['Node_Mark']);self.assertEqual(d['hunter_mark_retry_ms'],700)
    def test28_validation(self):
        for bad in ({'hunter_mark_key':''},{'hunter_mark_key':'F1'},{'hunter_mark_retry_ms':0},{'hunter_mark_mode':'bad'}):
            with self.assertRaises(ValueError):mark_settings(bad)
    def test29_target_cycle_new_mark_state(self):
        w=self.worker();self.step(w,0);self.v.values[0]=(0,0,0);self.step(w,.01);self.v.values[0]=(0,0,255);self.marked();self.step(w,.02);self.step(w,.071);self.assertEqual(self.keys(),['3','4'])
    def test30_retry_custom_key_and_interval(self):
        w=DetectorWorker(self.nodes,lambda cmd,**kw:self.sent.append((cmd,kw['source_node'])) or True,lambda:self.v,clock=self.c,hunter_mark_mode='pre_combat',hunter_mark_key='2',hunter_mark_retry_ms=750)
        self.step(w,0);self.step(w,.749);self.assertEqual(self.keys(),['2']);self.step(w,.75);self.assertEqual(self.keys(),['2','2'])
    def test31_localhost_opener_ack_protocol(self):
        import socket
        from transport import ESP32Controller
        with tempfile.TemporaryDirectory() as temp, socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(('127.0.0.1',0));server.settimeout(2)
            c=ESP32Controller('127.0.0.1',server.getsockname()[1]);c.evidence_path=Path(temp)/'tx.jsonl'
            self.assertTrue(c.connect())
            try:
                w=self.worker(sender=c.send_command);self.step(w,0)
                raw,addr=server.recvfrom(1024);self.assertEqual(raw,b'{"action":"tap","key":"3"}')
                server.sendto(b'{"status":"ok","action":"tap"}',addr)
                events=[];end=time.monotonic()+1
                while not any(e['kind']=='ack' for e in events) and time.monotonic()<end:
                    events+=c.poll_events();time.sleep(.005)
                self.assertTrue(any(e['kind']=='ack' and e['reply']=={'status':'ok','action':'tap'} for e in events))
            finally:
                c.disconnect();c._thread.join(3)
                self.assertFalse(c._thread.is_alive());self.assertFalse(c._evidence_thread.is_alive())
if __name__=='__main__':unittest.main(verbosity=2)
