import sys,unittest,tempfile,json,subprocess,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
import lcd_settings as lcd,profile_store
CASES=[['KEY'],['CNT'],['KEY','RATE'],['CNT','RATE'],['KEY','CNT','RATE'],['UDP','HID','RATE'],list(lcd.DIAGNOSTIC_ITEMS)]
class Items(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'config.json';self.path.write_text(json.dumps({'nodes':profile_store.default_nodes()}))
 def tearDown(self):self.temp.cleanup()
 def test_defaults_and_legacy(self):
  d=lcd.defaults();self.assertEqual(d['diagnostic_items'],['KEY','CNT','RATE']);d.pop('diagnostic_items');d['rows']['title']['text']='keep';profile_store.update_active(self.path,{'lcd_display':d})
  loaded=lcd.load(self.path);self.assertEqual(loaded['diagnostic_items'],['KEY','CNT','RATE']);self.assertEqual(loaded['rows']['title']['text'],'keep')
 def test_combinations_sizes_persistence_and_payload(self):
  for items in CASES:
   for size in lcd.DIAGNOSTIC_SIZES:
    with self.subTest(items=items,size=size):
     d=lcd.defaults();d.update(diagnostic_items=items,diagnostic_size=size);lcd.validate(d);profile_store.update_active(self.path,{'lcd_display':d})
     self.assertEqual(lcd.load(self.path)['diagnostic_items'],items)
     payload=lcd.commands(lcd.load(self.path))[0];self.assertEqual(payload['diagnostic_items'],items);self.assertEqual(payload['diagnostic_size'],size);self.assertNotIn('key',payload)
 def test_restart(self):
  d=lcd.defaults();d['diagnostic_items']=['CNT','RATE'];profile_store.update_active(self.path,{'lcd_display':d})
  code='import json,lcd_settings;print(json.dumps(lcd_settings.load('+repr(str(self.path))+')["diagnostic_items"]))'
  self.assertEqual(json.loads(subprocess.check_output([sys.executable,'-c',code],cwd=P,text=True)),['CNT','RATE'])
 def test_invalid_selections(self):
  for items in ([],['BAD'],['KEY','KEY'],'KEY',None,[1]):
   d=lcd.defaults();d['diagnostic_items']=items
   with self.assertRaises(ValueError):lcd.validate(d)
 def test_default_independent(self):
  a=lcd.defaults();a['diagnostic_items'].append('IP');self.assertEqual(lcd.defaults()['diagnostic_items'],['KEY','CNT','RATE'])
 def test_gui_and_presets(self):
  root=tk.Tk();root.withdraw();app=SimpleNamespace(root=root,lcd_display=lcd.defaults(),app_config_path=self.path,send_lcd_display_config=lambda:False)
  try:
   ed=lcd.LcdEditor(app)
   for items in CASES:
    ed.set_diagnostic_items(items);ed.apply();self.assertEqual(set(lcd.load(self.path)['diagnostic_items']),set(items))
   before=self.path.read_bytes();ed.set_diagnostic_items([]);ed.apply();self.assertEqual(self.path.read_bytes(),before)
   ed.reset();self.assertEqual([k for k,v in ed.diagnostic_items.items() if v.get()],['KEY','CNT','RATE']);root.update()
  finally:root.destroy()
 def test_layout_all_cases_sizes_and_maxima(self):
  values={'KEY':'KEY 0xFF','CNT':'CNT 4294967295','RATE':'RATE 4294967295/s','HID':'HID 4294967295','UDP':'UDP 4294967295','IP':'IP 255.255.255.255:8888'}
  for items in CASES:
   for size in lcd.DIAGNOSTIC_SIZES:
    columns=240//(size//2);capacity=135//size
    lines=[values[k][i:i+columns] for k in lcd.DIAGNOSTIC_ITEMS if k in items for i in range(0,len(values[k]),columns)]
    self.assertLessEqual(len(lines),18)
    for i in range(0,len(lines),capacity):
     page=lines[i:i+capacity];top=(135-len(page)*size)//2
     self.assertGreaterEqual(top,0);self.assertLessEqual(top+len(page)*size,135)
     self.assertTrue(all(len(line)*(size//2)<=240 for line in page))
if __name__=='__main__':unittest.main()
