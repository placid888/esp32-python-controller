"""Source-level regression checks, NOT hardware/network integration tests."""
from pathlib import Path
import importlib.util
import re
import unittest
P = Path(__file__).resolve().parents[1]
B = P / "backups/before-udp-20261031"
S = (P / "src/main.cpp").read_text(encoding="utf-8")
O = (B / "src/main.cpp").read_text(encoding="utf-8-sig")
I = (P / "platformio.ini").read_text(encoding="utf-8")
spec = importlib.util.spec_from_file_location("udp_send", P / "tools/udp_send.py")
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
def body(source, name):
    start = source.index("void " + name + "() {")
    pos = source.index("{", start)
    depth = 1
    end = pos + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]
class Regression(unittest.TestCase):
    def test_cdc_disabled(self):
        self.assertIn("-D ARDUINO_USB_CDC_ON_BOOT=0", I)
        self.assertIn("-D ARDUINO_USB_MODE=0", I)
        self.assertNotRegex(S, r"\bSerial(?:[0-9]*)\s*\.")
        self.assertNotIn("USBCDC ", S)
    def test_hid_initializers_preserved(self):
        self.assertIn("Keyboard.begin();\n  Mouse.begin();\n  USB.begin();", S)
    def test_action_dispatch_preserved(self):
        pattern = r'action == "([a-z_]+)"'
        self.assertEqual(re.findall(pattern, O), re.findall(pattern, S))
        for item in ['deserializeJson(doc, jsonStr)', 'Keyboard.releaseAll();', 'Mouse.release(MOUSE_ALL);', 'Mouse.move(x, y);', 'Mouse.move(0, 0, y);']:
            self.assertIn(item, S)
    def test_lcd_idle_logic_unchanged(self):
        for name in ['wakeLcdIfNeeded', 'updateLcdIdleMode']:
            self.assertEqual(body(O, name), body(S, name))
    def test_background_queue_handoff(self):
        worker = S[S.index('static void udpTask('):S.index('static void randomKeyTap(')]
        self.assertNotIn('Keyboard.', worker)
        self.assertNotIn('Mouse.', worker)
        self.assertNotIn('tft.', worker)
        self.assertIn('xQueueSend(commandQueue', worker)
        self.assertIn('processCommand(String(packet.json))', S)
        self.assertIn('UDP_PORT = 8888', S)
        self.assertIn('WiFi.mode(WIFI_STA)', S)
    def test_random_hold(self):
        self.assertIn('delay(25U + (esp_random() % 36U))', S)
        self.assertEqual({25 + x % 36 for x in range(72)}, set(range(25, 61)))
        self.assertLess(S.index('Keyboard.press(key);'), S.index('Keyboard.release(key);'))
    def test_client_payload(self):
        self.assertEqual(client.encode_command('{"action":"release_all"}'), b'{"action":"release_all"}')
        self.assertEqual(client.encode_command('{"action":"lcd_test","message":"UDP OK"}'), b'{"action":"lcd_test","message":"UDP OK"}')
        for value in ['not json', '[]', '{"message":"' + 'x'*1030 + '"}']:
            with self.assertRaises(ValueError): client.encode_command(value)
if __name__ == '__main__':
    unittest.main(verbosity=2)
