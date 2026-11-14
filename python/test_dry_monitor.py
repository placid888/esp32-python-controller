"""Synthetic decisions + final-boundary socket guards. No real UDP/input."""
import copy,json,socket,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from detector import DetectorWorker
from profile_store import default_nodes
from transport import ESP32Controller
from dry_monitor import DryDiagnostics
from output_guard import ProcessOutputGuard,OutputBypassError
from wow_window import WindowError

class Clock:
    value=0
    def __call__(self):return self.value
class Pixels:
    def __init__(self):self.states={};self.error=None
    def get_region_rgb(self,x,y,size):
        if self.error:raise self.error
        return [(255,255,255) if self.states.get(x,True) else (0,0,0)]*(size*size)
    def close(self):pass

class DryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'dry.jsonl'
        self.diag=DryDiagnostics(self.path,{'profile':'test','class':'hunter','spec':'beast_mastery'})
        self.c=ESP32Controller(output_mode='dry_run');self.c.dry_diagnostics=self.diag
        self.c._record_tx=Mock(side_effect=AssertionError('real TX evidence prohibited'))
        self.nodes=default_nodes()
        for i,(name,n) in enumerate(self.nodes.items()):n.update(x=i,mode='brightness',threshold=200,min_delay=40,max_delay=40,enabled=name=='Node_Target' or name=='Skill_4' or name in ('Node_Combat','Node_Mark'))
        self.clock=Clock();self.v=Pixels()
        self.w=DetectorWorker(self.nodes,self.c.send_command,lambda:self.v,clock=self.clock,output_observer=self.diag)
    def tearDown(self):self.tmp.cleanup()
    def step(self,t):self.clock.value=t;self.w.step(self.v)
    def records(self):return [json.loads(l) for l in self.path.read_text(encoding='utf-8').splitlines()] if self.path.exists() else []
    def sends(self):return [r for r in self.records() if r['would_send']]

    def test_gate_false(self):
        self.v.states[self.nodes['Node_Target']['x']]=False;self.step(0);self.step(1)
        self.assertEqual(self.sends(),[])
    def test_skill_false(self):
        self.v.states[self.nodes['Skill_4']['x']]=False;self.step(0);self.step(1)
        self.assertEqual(self.sends(),[])
    def test_due_command_final_boundary_and_id(self):
        with patch.object(socket.socket,'sendto',side_effect=AssertionError('UDP prohibited')) as wire:
            self.step(0);self.step(.039);self.assertEqual(self.sends(),[]);self.step(.040)
        r=self.sends()[0];self.assertEqual(r['command'],{'action':'tap','key':'4'})
        self.assertTrue(r['blocked_by_dry_run']);self.assertTrue(r['gate_state']);self.assertTrue(r['skill_match'])
        self.assertEqual(r['delay_ms'],40);self.assertEqual(len(r['tx_id']),32);wire.assert_not_called();self.c._record_tx.assert_not_called()
    def test_continuous_true_uses_existing_repeat_not_edge_latch(self):
        for t in (0,.04,.041,.08,.081,.12):self.step(t)
        self.assertEqual(len(self.sends()),3)
    def test_false_then_true_fresh_delay(self):
        self.step(0);self.v.states[self.nodes['Skill_4']['x']]=False;self.step(.02)
        self.assertFalse(self.w.brain.pending)
        self.v.states[self.nodes['Skill_4']['x']]=True;self.step(.1);self.step(.139)
        self.assertEqual(self.sends(),[]);self.step(.141);self.assertEqual(len(self.sends()),1)
    def test_sampling_unknown_not_false_or_rearm(self):
        self.step(0);pending=copy.deepcopy(self.w.brain.pending)
        self.v.error=WindowError('dpi_unverified','mock')
        with patch.object(self.w.brain,'observe',wraps=self.w.brain.observe) as observe:
            with self.assertRaises(WindowError):self.step(.02)
            observe.assert_not_called()
        self.assertEqual(self.w.brain.pending,pending);self.assertEqual(self.sends(),[])
        r=self.records()[-1];self.assertEqual(r['event'],'SAMPLING_UNKNOWN');self.assertEqual(r['gate_state'],'unknown')
        self.assertEqual(self.c.send_command({'action':'tap','key':'4'},source_node='Skill_4'),0)
    def test_worker_window_invalid_stops_without_output(self):
        self.v.error=WindowError('not_found','mock');self.w.run()
        self.assertTrue(self.w.stop_event.is_set());self.assertFalse(self.w.brain.pending);self.assertEqual(self.sends(),[])
    def test_surface_unknown_stops_before_scan_or_output(self):
        with patch('dry_monitor.verify_surface',side_effect=WindowError('occluded','mock')):
            self.w.run()
        self.assertEqual(self.sends(),[]);self.assertTrue(self.w.stop_event.is_set())
        self.assertEqual(self.records()[0]['gate_state'],'unknown')
    def test_final_boundary_also_blocks_disconnect_release(self):
        sock=Mock()
        self.assertEqual(self.c._transmit_packet(sock,b'{"action":"release_all"}',('127.0.0.1',9),'transport.disconnect.release_all'),0)
        sock.sendto.assert_not_called();self.c._record_tx.assert_not_called()
    def test_no_udp_connect_in_dry(self):
        with patch('transport.socket.socket') as factory:
            self.assertFalse(self.c.connect());factory.assert_not_called()
    def test_output_mode_sticky(self):
        with self.assertRaises(RuntimeError):self.c.set_output_mode('normal')
        with self.assertRaises(AttributeError):self.c.output_mode='normal'
        c=ESP32Controller();c._session=Mock()
        with self.assertRaises(RuntimeError):c.set_output_mode('dry_run')
    def test_schema_complete_and_no_sender_for_unknown(self):
        self.step(0)
        required={'timestamp','profile','class','spec','output_mode','node','gate_state','target_state','combat_state','mark_state','skill','skill_match','delay_ms','command','decision','reason','would_send','blocked_by_dry_run','tx_id'}
        self.assertTrue(required.issubset(self.records()[0]))
    def test_existing_mark_opener_has_distinct_gate(self):
        self.nodes['Node_Mark']['enabled']=True
        self.v.states[self.nodes['Node_Mark']['x']]=False
        self.w=DetectorWorker(self.nodes,self.c.send_command,lambda:self.v,clock=self.clock,output_observer=self.diag,hunter_mark_mode='pre_combat')
        self.step(0);r=self.sends()[0]
        self.assertEqual(r['node'],'Opener_Mark');self.assertTrue(r['gate_state']);self.assertFalse(r['normal_gate_state'])
        self.assertEqual(r['command']['key'],'3')
    def test_normal_final_boundary_unchanged_with_fake_socket(self):
        c=ESP32Controller();c._record_tx=Mock(return_value='existing-id');c._record_tx_result=Mock()
        sock=Mock();sock.sendto.return_value=2
        self.assertEqual(c._transmit_packet(sock,b'{}',('127.0.0.1',9)),2)
        sock.sendto.assert_called_once_with(b'{}',('127.0.0.1',9))
        c._record_tx_result.assert_called_once_with('existing-id','sent_to_os',sent_bytes=2)

class GuardTests(unittest.TestCase):
    def test_bypass_raises_before_socket_send(self):
        guard=ProcessOutputGuard().install()
        try:
            with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
                with self.assertRaises(OutputBypassError):sock.sendto(b'blocked',('127.0.0.1',9))
            self.assertEqual(len(guard.attempts),1)
            with self.assertRaises(OutputBypassError):guard.check()
        finally:guard.close()

class DryGuiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk,profile_store
        from gui import MacroDashboard
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'config.json'
        profile_store.write(self.path,{'nodes':default_nodes()});self.before=self.path.read_bytes()
        self.root=tk.Tk();self.root.withdraw()
        self.keys=patch('calibration_hotkeys.CalibrationHotkeys.start');self.keys.start()
        self.app=MacroDashboard(self.root,config_path=self.path,output_mode='dry_run')
    def tearDown(self):
        self.app.stop_loop();self.app.calibration_hotkeys.stop();self.app.restore_output();self.app.vision.close()
        for ident in self.root.tk.call('after','info'):self.root.after_cancel(ident)
        self.root.destroy();self.keys.stop();self.tmp.cleanup()
    def test_dry_gui_banner_connection_and_formal_config(self):
        self.assertIn('DRY RUN / OUTPUT BLOCKED',self.app.output_banner.cget('text'))
        self.app.connect_hw();self.assertFalse(self.app.controller.is_open)
        self.assertFalse(self.app.controller.evidence_path.exists())
        self.assertEqual(self.path.read_bytes(),self.before)
    def test_start_dry_uses_worker_and_timer_without_udp_or_save(self):
        with patch('dry_monitor.wow_foreground_ready',return_value=True), \
             patch('gui.DetectorWorker') as worker, \
             patch.object(self.app,'save_config_from_entries',side_effect=AssertionError('No config save')):
            self.app.start_loop()
            self.assertTrue(self.app.is_running);worker.return_value.start.assert_called_once()
            self.assertIs(worker.call_args.kwargs['output_observer'],self.app.dry_diagnostics)
            self.assertIsNotNone(self.app.dry_stop_after_id);self.app.stop_loop()
        self.assertEqual(self.path.read_bytes(),self.before);self.assertFalse(self.app.controller.is_open)
    def test_wait_foreground_does_not_start_worker(self):
        with patch('dry_monitor.wow_foreground_ready',return_value=False),patch('gui.DetectorWorker') as worker:
            self.app.start_loop();worker.assert_not_called();self.assertFalse(self.app.is_running)
            self.assertIsNotNone(self.app.dry_start_after_id)
            self.app.stop_loop();self.assertIsNone(self.app.dry_start_after_id)
    def test_guard_replacement_fails_closed(self):
        guard=ProcessOutputGuard().install()
        try:
            with patch.object(socket.socket,'sendto'):
                with self.assertRaises(OutputBypassError):guard.check()
        finally:guard.close()

if __name__=='__main__':unittest.main(verbosity=2)
