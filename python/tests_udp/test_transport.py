import ast
import importlib.util
import json
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import unittest
from unittest import mock

P = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P))
from transport import ESP32Controller

class TransportTests(unittest.TestCase):
    def finish(self, c):
        c.disconnect()
        if c._thread: c._thread.join(2)
        self.assertFalse(c._thread and c._thread.is_alive())
    def test_literal_ip_and_port_validation(self):
        for host, port in [("",8888),("example.com",8888),("0.0.0.0",8888),("255.255.255.255",8888),("224.0.0.1",8888),("127.0.0.1",0),("127.0.0.1",65536),("127.0.0.1","x")]:
            c=ESP32Controller(host,port);self.assertFalse(c.connect());self.assertTrue(c.last_error)
    def test_disconnected_send(self):
        self.assertEqual(ESP32Controller().send_command({"action":"tap"}),0)
    def test_real_udp_roundtrip_utf8_and_release(self):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1",0));server.settimeout(2)
            c=ESP32Controller("127.0.0.1",server.getsockname()[1]);self.assertTrue(c.connect())
            try:
                cmd={"action":"lcd_test","message":"區域網路測試"}
                self.assertGreater(c.send_command(cmd),0)
                payload,source=server.recvfrom(2048);self.assertEqual(json.loads(payload),cmd)
                self.assertNotIn(b"\n",payload)
                server.sendto(b'{"status":"ok","action":"lcd_test"}',source)
                events=[];deadline=time.monotonic()+2
                while time.monotonic()<deadline and not any(e['kind']=='ack' for e in events):
                    events+=c.poll_events();time.sleep(.005)
                self.assertTrue(any(e['kind']=='ack' for e in events))
                c.disconnect();data,_=server.recvfrom(2048)
                self.assertEqual(json.loads(data),{"action":"release_all"})
            finally:self.finish(c)
    def test_payload_limits(self):
        c=ESP32Controller("127.0.0.1",8888);self.assertTrue(c.connect())
        try:
            for command in [[],{"x":"x"*1030},{"x":float('nan')},{"x":object()}]:
                self.assertEqual(c.send_command(command),0)
        finally:self.finish(c)
    def test_async_queue_backpressure(self):
        entered=threading.Event();unblock=threading.Event()
        class FakeSocket:
            def setblocking(self,b):self.blocking=b
            def bind(self,a):pass
            def sendto(self,p,a):entered.set();unblock.wait(2);return len(p)
            def recvfrom(self,n):raise BlockingIOError()
            def close(self):pass
        fake=FakeSocket();c=ESP32Controller("127.0.0.1",8888,queue_size=2)
        with mock.patch('transport.socket.socket',return_value=fake):
            self.assertTrue(c.connect());self.assertFalse(fake.blocking)
            try:
                self.assertGreater(c.send_command({"action":"lcd_test"}),0);self.assertTrue(entered.wait(1))
                start=time.monotonic()
                self.assertGreater(c.send_command({"action":"lcd_test"}),0)
                self.assertGreater(c.send_command({"action":"lcd_test"}),0)
                self.assertEqual(c.send_command({"action":"lcd_test"}),0)
                c.disconnect();self.assertLess(time.monotonic()-start,.2)
            finally:unblock.set();self.finish(c)
    def test_source_no_serial_and_ui_contract(self):
        for name in ['transport.py','gui.py','main.py']:
            text=(P/name).read_text(encoding='utf-8');tree=ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):self.assertTrue(all(not a.name.startswith('serial') for a in node.names))
                if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith('serial'))
        gui=(P/'gui.py').read_text(encoding='utf-8')
        for token in ['目標 IP','初始化 UDP 通訊','self.target_port_var = tk.StringVar(value=str(saved_port))','def poll_udp(']:self.assertIn(token,gui)
        for token in ['port_combo','refresh_ports','controller.ser']:self.assertNotIn(token,gui)
        transport=(P/'transport.py').read_text(encoding='utf-8')
        self.assertIn('session.sock.sendto(pending, session.endpoint)',transport)
        self.assertIn('session.tx.put_nowait(payload)',transport)
        self.assertNotIn('tkinter',transport)
    def test_udp_transport_unchanged(self):
        import hashlib
        self.assertEqual(hashlib.sha256((P/'transport.py').read_bytes()).hexdigest(),'93bd6eb2639d4e7162741fc5955aaeb1f16bda712321fcf6354e201dff0a1210')

if __name__=='__main__':unittest.main(verbosity=2)
