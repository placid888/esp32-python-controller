import sys,unittest,tempfile,json,time,socket
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
import test_hunters_mark as fixtures
from detector import DetectorWorker
from profile_store import default_nodes
from mark_trace import MarkTrace,TracedESP32Controller
from transport import TxBytes
class Memory(MarkTrace):
 def __init__(self):super().__init__(verbose=False);self.records=[];self.session='test';self.verbose_enabled=False
 def emit(self,event,**data):self.records.append(dict(event=event,**data))
class Evidence(unittest.TestCase):
 def setUp(self):
  f=fixtures.MarkTests();f.setUp();self.f=f;self.trace=Memory()
  self.w=f.worker();self.w.mark_trace=self.trace
 def step(self,t):self.f.step(self.w,t)
 def test01_send_reason_retry_elapsed(self):
  self.step(0);self.step(.527)
  traces=[r for r in self.trace.records if r['event']=='MARK_TRACE']
  self.assertEqual([r['reason'] for r in traces],['mark_missing_first_attempt','mark_missing_retry'])
  self.assertAlmostEqual(traces[-1]['elapsed_ms'],527);self.assertEqual(traces[-1]['mark_attempt_seq'],2)
  self.assertEqual(traces[-1]['combat'],None);self.assertFalse(traces[-1]['combat_observed'])
  self.assertTrue(any(r['event']=='MARK_RETRY' for r in self.trace.records))
 def test02_mark_both_transitions_raw(self):
  self.step(0);self.f.marked();self.step(.01);self.f.marked(False);self.step(.02)
  rows=[r for r in self.trace.records if r['event']=='MARK_STATE']
  self.assertEqual([r['current'] for r in rows],[False,True,False])
  self.assertEqual([r for r in self.trace.records if r['event']=='MARK_PENDING_CANCEL'][0]['reason'],'mark_detected_success')
  d=rows[-1]['mark_detector'];self.assertEqual(d['actual_rgb'],[0,0,0]);self.assertIn('matching_pixels',d);self.assertIn('expected_rgb',d)
  self.assertEqual([r for r in self.trace.records if r['event']=='MARK_TRACE'][-1]['reason'],'mark_missing_rearmed_after_cancel')
 def test03_target_transition(self):
  self.step(0);self.f.v.values[0]=(0,0,0);self.step(.1)
  rows=[r for r in self.trace.records if r['event']=='TARGET_STATE'];self.assertEqual([r['current'] for r in rows],[True,False])
 def test04_combat_transition_only_when_sampled(self):
  self.w=self.f.worker('post_combat');self.w.mark_trace=self.trace
  self.step(0);self.f.combat(False);self.step(.1)
  self.assertEqual([r['current'] for r in self.trace.records if r['event']=='COMBAT_STATE'],[True,False])
 def test05_no_change_every_tick_spam(self):
  for t in (0,.01,.02,.03):self.step(t)
  self.assertEqual(len([r for r in self.trace.records if r['event']=='MARK_STATE']),1)
  self.assertFalse(any(r['event']=='MARK_SCAN' for r in self.trace.records))
 def test06_logging_failure_does_not_change_decisions(self):
  class Broken:
   def __getattr__(self,k):raise OSError('disk broken')
  self.w.mark_trace=Broken();self.step(0);self.step(.5);self.assertEqual(self.f.keys(),['3','3'])
 def test07_trace_decision_and_sampling_equivalence(self):
  for traced in (False,True):
   f=fixtures.MarkTests();f.setUp();w=f.worker();w.mark_trace=Memory() if traced else None
   for t,marked,target in ((0,False,True),(.3,True,True),(.36,True,True),(.4,False,True),(.91,False,True),(1.,False,False)):
    f.marked(marked);f.v.values[0]=(0,0,255) if target else (0,0,0);f.step(w,t)
   state=(f.sent,f.v.reads,w.brain.pending,w.opener.pending,w.dispatch_count,w.cancel_count)
   if not traced:baseline=state
   else:self.assertEqual(state,baseline)
 def test08_actual_send_sequence_not_would_block(self):
  c=TracedESP32Controller();c.mark_trace=self.trace;c._append_evidence=lambda r:None
  for outcome in ('would_block','sent_to_os','sent_to_os'):
   raw=TxBytes(b'{"action":"tap","key":"3"}','Opener_Mark',{'schedule':{'deadline':0,'mark_trace':{'session':'test','reason':'mark_missing_retry'}}})
   tx=c._record_tx(raw,('127.0.0.1',8888));c._record_tx_result(tx,outcome)
  rows=[r for r in self.trace.records if r['event']=='MARK_SEND'];self.assertEqual([r['MARK_SEND_SEQ'] for r in rows],[1,2]);self.assertEqual(rows[0]['payload_raw'],repr(bytes(raw)))
 def test09_non_mark_packets_not_counted(self):
  c=TracedESP32Controller();c.mark_trace=self.trace;c._append_evidence=lambda r:None
  tx=c._record_tx(b'{"action":"tap","key":"4"}',('127.0.0.1',8888));c._record_tx_result(tx,'sent_to_os')
  self.assertFalse(self.trace.records)
 def test10_file_io_failure_async_safe(self):
  with tempfile.TemporaryDirectory() as d:
   blocker=Path(d)/'file';blocker.write_text('not a directory');t=MarkTrace(blocker/'trace.log');t.begin(self.w);t.emit('anything');t.end();t.close();self.assertIsNotNone(t.error)
 def test11_session_start_end(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'trace.log';t=MarkTrace(path);t.begin(self.w);t.end();t.close();rows=[json.loads(x) for x in path.read_text().splitlines()]
   self.assertEqual([r['event'] for r in rows],['SESSION START','SESSION END']);self.assertEqual(rows[0]['session'],rows[1]['session'])
 def test12_no_target_identity_signal(self):
  self.step(0);self.f.marked();self.step(.1);self.f.marked(False);self.step(.2)
  self.assertEqual(len([r for r in self.trace.records if r['event']=='TARGET_STATE']),1)
 def test13_wire_loopback_unchanged(self):
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server,tempfile.TemporaryDirectory() as d:
   server.bind(('127.0.0.1',0));server.settimeout(2);c=TracedESP32Controller('127.0.0.1',server.getsockname()[1]);c.evidence_path=Path(d)/'udp.jsonl';c.mark_trace=MarkTrace(Path(d)/'mark.log');c.mark_trace.begin(self.w)
   try:
    self.assertTrue(c.connect());c.send_command({'action':'tap','key':'3'},source_node='Opener_Mark',schedule={'deadline':0,'mark_trace':{'session':c.mark_trace.session,'reason':'test'}})
    self.assertEqual(server.recvfrom(1024)[0],b'{"action":"tap","key":"3"}')
    deadline=time.monotonic()+2
    while not c.mark_trace.send_sequences and time.monotonic()<deadline:time.sleep(.01)
    self.assertEqual(list(c.mark_trace.send_sequences.values()),[1])
   finally:
    c.disconnect()
    if c._thread:c._thread.join(timeout=2)
    c.mark_trace.end();c.mark_trace.close()
 def test14_verbose_opt_in(self):
  self.trace.verbose_enabled=True;self.step(0);self.step(.01)
  self.assertEqual(len([r for r in self.trace.records if r['event']=='MARK_SCAN']),2)
 def test15_full_logging_queue_does_not_block_decision(self):
  import queue
  trace=MarkTrace();trace.queue=queue.Queue(maxsize=1);self.w.mark_trace=trace
  self.step(0);self.step(.5)
  self.assertEqual(self.f.keys(),['3','3']);self.assertGreater(trace.dropped,0)
 def test16_transport_logging_exception_cannot_block_wire(self):
  class Bad(MarkTrace):
   def emit(self,*a,**kw):raise OSError('logging unavailable')
  with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server,tempfile.TemporaryDirectory() as d:
   server.bind(('127.0.0.1',0));server.settimeout(2);c=TracedESP32Controller('127.0.0.1',server.getsockname()[1]);c.evidence_path=Path(d)/'udp.jsonl';c.mark_trace=Bad()
   try:
    self.assertTrue(c.connect());c.send_command({'action':'tap','key':'3'},source_node='Opener_Mark')
    self.assertEqual(server.recvfrom(1024)[0],b'{"action":"tap","key":"3"}')
   finally:
    c.disconnect()
    if c._thread:c._thread.join(timeout=2)
 def test17_sampling_and_gate_source_unchanged(self):
  import ast
  old=ast.parse((P/'backups/mark-trace-20261101/detector.py').read_text(encoding='utf-8'));new=ast.parse((P/'detector.py').read_text(encoding='utf-8'))
  def functions(tree):
   out={}
   for n in tree.body:
    if isinstance(n,ast.FunctionDef):out[n.name]=n
    if isinstance(n,ast.ClassDef):out.update({n.name+'.'+m.name:m for m in n.body if isinstance(m,ast.FunctionDef)})
   return out
  a,b=functions(old),functions(new)
  for name in ('sample_node','DetectorWorker.scan','DetectorWorker.normal_allowed','DetectorWorker.opener_allowed','DetectorWorker.gate_reason'):
   self.assertEqual(ast.dump(a[name]),ast.dump(b[name]),name)
 def test18_scope_hashes_unchanged(self):
  import hashlib
  old=json.loads((P/'backups/mark-trace-20261101/before-hashes.json').read_text());changed=[]
  for f,sha in old.items():
   if hashlib.sha256(Path(f).read_bytes()).hexdigest()!=sha:changed.append(Path(f).name)
  self.assertEqual(set(changed),{'detector.py','gui.py'})
if __name__=='__main__':unittest.main()
