"""Read-only native Win32 tests; post thread messages, never inject key/mouse input."""
from pathlib import Path
import sys,os,time,ctypes,unittest,queue,threading
from ctypes import wintypes
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
from hotkey_capture import F8Capture,WM_HOTKEY,HOTKEY_ID

def wait_events(worker,kind,timeout=3):
    end=time.monotonic()+timeout;seen=[]
    while time.monotonic()<end:
        seen.extend(worker.poll())
        if any(e['kind']==kind for e in seen):return seen
        time.sleep(.005)
    raise AssertionError('No '+kind+': '+str(seen))

def post_hotkey(worker):
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.PostThreadMessageW.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
    user.PostThreadMessageW.restype=wintypes.BOOL
    assert user.PostThreadMessageW(worker._tid,WM_HOTKEY,HOTKEY_ID,0)

def finish(worker):
    worker.stop()
    if worker._thread:worker._thread.join(3)
    assert not worker.alive

@unittest.skipUnless(os.name=='nt','Windows native hotkey API')
class Native(unittest.TestCase):
 def test_register_capture_context_change_and_unregister(self):
  main=threading.get_ident();calls=[]
  def capture():calls.append(threading.get_ident());return -100,200,(1,2,3)
  w=F8Capture(capture=capture)
  try:
   self.assertTrue(w.start((1,'A','Action_1')));wait_events(w,'ready');post_hotkey(w)
   e=next(e for e in wait_events(w,'capture') if e['kind']=='capture')
   self.assertEqual(e['context'],(1,'A','Action_1'));self.assertEqual((e['x'],e['y'],e['rgb']),(-100,200,(1,2,3)));self.assertNotEqual(calls[0],main)
   w.set_context((1,'A','Node_HP'));post_hotkey(w);e=next(e for e in wait_events(w,'capture') if e['kind']=='capture');self.assertEqual(e['context'][2],'Node_HP')
  finally:finish(w)
  try:self.assertTrue(w.start((2,'B','Action_2')));wait_events(w,'ready')
  finally:finish(w)
 def test_conflict_is_reported(self):
  a=F8Capture(capture=lambda:(0,0,(0,0,0)));b=F8Capture(capture=lambda:(0,0,(0,0,0)))
  try:
   a.start((1,'A','Action_1'));wait_events(a,'ready');b.start((1,'B','Action_1'));events=wait_events(b,'error');self.assertTrue(any('F8' in e.get('message','') for e in events))
  finally:finish(a);finish(b)
 def test_real_cursor_and_mss_pixel(self):
  w=F8Capture()
  try:
   w.start((1,'A','Action_1'));wait_events(w,'ready');post_hotkey(w);e=next(e for e in wait_events(w,'capture') if e['kind']=='capture')
   self.assertEqual(len(e['rgb']),3);self.assertTrue(all(0<=c<=255 for c in e['rgb']))
  finally:finish(w)
 def test_stop_during_start(self):
  w=F8Capture(capture=lambda:(0,0,(1,2,3)));w.start((1,'A','Node_HP'));finish(w);self.assertFalse(w.alive)
class Queues(unittest.TestCase):
 def test_bounded_events(self):
  w=F8Capture()
  for i in range(100):w._emit({'kind':'test','value':i})
  self.assertLessEqual(w.events.qsize(),32);self.assertEqual(w.poll()[-1]['value'],99)
if __name__=='__main__':unittest.main(verbosity=2)
