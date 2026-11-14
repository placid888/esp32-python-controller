import unittest,tempfile,json,sys,copy,subprocess,tkinter as tk
from pathlib import Path
from types import SimpleNamespace
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
import lcd_settings as lcd
import profile_store
class DiagnosticFont(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'config.json'
  self.path.write_text(json.dumps({'nodes':profile_store.default_nodes()}))
 def tearDown(self):self.tmp.cleanup()
 def test_default(self):self.assertEqual(lcd.defaults()['diagnostic_size'],24)
 def test_legacy(self):
  d=lcd.defaults();d.pop('diagnostic_size');profile_store.update_active(self.path,{'lcd_display':d})
  self.assertEqual(lcd.load(self.path)['diagnostic_size'],24)
 def test_sizes_persist_reload(self):
  for size in (16,20,24,28,32):
   d=lcd.defaults();d['diagnostic_size']=size;lcd.validate(d)
   profile_store.update_active(self.path,{'lcd_display':d})
   self.assertEqual(lcd.load(self.path)['diagnostic_size'],size)
   code='import lcd_settings;print(lcd_settings.load('+repr(str(self.path))+')["diagnostic_size"])'
   self.assertEqual(subprocess.check_output([sys.executable,'-c',code],cwd=P,text=True).strip(),str(size))
   self.assertEqual(lcd.commands(lcd.load(self.path))[0]['diagnostic_size'],size)
 def test_invalid(self):
  for size in (0,18,40,48,64,'32',True):
   d=lcd.defaults();d['diagnostic_size']=size
   with self.assertRaises(ValueError):lcd.validate(d)
 def test_control_format_unchanged(self):
  a,b=lcd.commands(lcd.defaults());self.assertEqual(a['action'],'lcd_style');self.assertEqual(b['action'],'lcd_labels')
  self.assertEqual(a['rows'],lcd.DEFAULT_ROWS);self.assertNotIn('key',a)
 def test_legacy_commands_default(self):
  d=lcd.defaults();d.pop('diagnostic_size');self.assertEqual(lcd.commands(d)[0]['diagnostic_size'],24)
 def test_gui_save_reset_and_choices(self):
  root=tk.Tk();root.withdraw()
  app=SimpleNamespace(root=root,lcd_display=lcd.defaults(),app_config_path=self.path,send_lcd_display_config=lambda:False)
  try:
   ed=lcd.LcdEditor(app)
   for size in (16,20,24,28,32):
    ed.diagnostic_size.set(str(size));ed.apply();self.assertEqual(lcd.load(self.path)['diagnostic_size'],size)
   ed.reset();self.assertEqual(ed.diagnostic_size.get(),'24')
   combos=[]
   def walk(w):
    for child in w.winfo_children():
     if isinstance(child,lcd.ttk.Combobox):combos.append(child)
     walk(child)
   walk(ed.window)
   self.assertTrue(any(str(c.cget('textvariable'))==str(ed.diagnostic_size) and tuple(map(str,c.cget('values')))==('16','20','24','28','32') for c in combos))
   root.update();
  finally:root.destroy()
 def test_font_cell_bounds(self):
  for size in (16,20,24,28,32):
   y=87 if size==16 else 39
   self.assertLessEqual(y+3*size,135)
   self.assertEqual(size//2,{16:8,20:10,24:12,28:14,32:16}[size])
   self.assertLessEqual(len('CNT 4294967295')*(size//2),240)
 def test_oversized_migration_preserves_other_fields(self):
  for size in (40,48):
   d=lcd.defaults();d['diagnostic_size']=size;d['rows']['title']['text']='Keep me'
   profile_store.update_active(self.path,{'lcd_display':d})
   loaded=lcd.load(self.path)
   self.assertEqual(loaded['diagnostic_size'],32)
   self.assertEqual(loaded['rows']['title']['text'],'Keep me')
if __name__=='__main__':unittest.main()

