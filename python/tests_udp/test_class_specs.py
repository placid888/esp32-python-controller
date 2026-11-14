import sys,unittest,tempfile,copy,json,time,hashlib
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parents[1];sys.path.insert(0,str(P))
import profile_store as store
import spec_ui
from class_registry import CLASSES,ClassDefinition,SpecDefinition,register
from detector import DetectorWorker

def legacy():
    nodes=store.default_nodes();nodes['Skill_4'].update(enabled=True,x=100,y=200,threshold=120,r=23,tolerance=17,min_delay=40,max_delay=80)
    nodes['Skill_5']['threshold']=121
    return {'nodes':nodes,'combat_mode':'manual_first_hit','hunter_mark_mode':'pre_combat','hunter_mark_key':'3','hunter_mark_retry_ms':500,
        'udp_endpoint':{'host':'192.168.1.2','port':8888},'lcd_power':{'sleep_enabled':True},'custom':{'keep':1}}
class Data(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'config.json';self.old=legacy();self.path.write_text(json.dumps(self.old))
    def tearDown(self):self.tmp.cleanup()
    def active(self):return store.active(self.path)
    def select(self,spec):store.select_character(self.path,'hunter',spec)
    def test01_registry_ids(self):
        self.assertEqual(CLASSES['hunter'].name,'獵人');self.assertEqual([s.id for s in CLASSES['hunter'].specs],['beast_mastery','marksmanship','survival'])
    def test02_migrate_to_mm(self):
        p=self.active();self.assertEqual((p['selected_class'],p['selected_spec']),('hunter','marksmanship'));self.assertEqual(p['nodes'],self.old['nodes'])
    def test03_shared_preserved(self):
        p=self.active()
        for name in ('Node_Target','Node_Combat','Node_Mark'):self.assertEqual(p['classes']['hunter']['shared']['nodes'][name],self.old['nodes'][name])
        for key in ('combat_mode','hunter_mark_mode','hunter_mark_key','hunter_mark_retry_ms'):self.assertEqual(p[key],self.old[key])
    def test04_profiles_not_deleted(self):
        self.path.write_text(json.dumps({'last_used':'B','profiles':{'A':legacy(),'B':legacy()}}));d=store.read(self.path);store.write(self.path,d)
        self.assertEqual(list(store.read(self.path)['profiles']),['A','B']);self.assertEqual(store.read(self.path)['last_used'],'B')
    def test05_bm_independent_all_parameters(self):
        self.select('beast_mastery');nodes=self.active()['nodes'];nodes['Skill_4'].update(x=450,y=550,threshold=170,r=42,tolerance=30,min_delay=99,max_delay=120,enabled=True,sample_mode='5x5',match_ratio=.6)
        store.update_active(self.path,{'nodes':nodes});self.select('marksmanship');self.assertEqual(self.active()['nodes']['Skill_4'],self.old['nodes']['Skill_4'])
        self.select('beast_mastery');self.assertEqual(self.active()['nodes']['Skill_4'],nodes['Skill_4'])
    def test06_survival_isolation(self):
        self.select('survival');nodes=self.active()['nodes'];nodes['Skill_5'].update(threshold=77,x=333,y=444,r=88,tolerance=5,min_delay=200,max_delay=300)
        store.update_active(self.path,{'nodes':nodes});self.select('marksmanship');self.assertEqual(self.active()['nodes']['Skill_5'],self.old['nodes']['Skill_5'])
        self.select('beast_mastery');self.assertEqual(self.active()['nodes']['Skill_5']['threshold'],200)
    def test07_no_mutable_aliases(self):
        p=self.active();specs=p['classes']['hunter']['specs'];specs['survival']['nodes']['Skill_4']['threshold']=1
        self.assertEqual(specs['marksmanship']['nodes']['Skill_4']['threshold'],120);self.assertEqual(specs['beast_mastery']['nodes']['Skill_4']['threshold'],200)
    def test08_global_shared_and_canonical_disk(self):
        store.update_active(self.path,{'udp_endpoint':{'host':'192.168.1.3','port':9999}})
        for spec in ('beast_mastery','marksmanship','survival'):
            self.select(spec);self.assertEqual(self.active()['udp_endpoint']['port'],9999)
        raw=json.loads(self.path.read_text());p=raw['profiles']['Default'];self.assertNotIn('nodes',p);self.assertNotIn('udp_endpoint',p)
        self.assertEqual(p['global']['udp_endpoint']['port'],9999)
        for spec in p['classes']['hunter']['specs'].values():self.assertNotIn('udp_endpoint',spec)
    def test09_shared_gates_apply_across_specs(self):
        self.select('survival');n=self.active()['nodes'];n['Node_Target']['x']=999;store.update_active(self.path,{'nodes':n})
        self.select('marksmanship');self.assertEqual(self.active()['nodes']['Node_Target']['x'],999)
    def test10_selection_survives_restart(self):
        self.select('survival');self.assertEqual(store.read(self.path)['profiles']['Default']['selected_spec'],'survival')
    def test11_future_registry_not_hardcoded(self):
        register(ClassDefinition('priest','牧師',(SpecDefinition('discipline','戒律'),SpecDefinition('holy','神聖'),SpecDefinition('shadow','暗影')),'shadow'))
        try:
            store.select_character(self.path,'priest','holy');p=self.active();self.assertEqual(p['selected_class'],'priest');self.assertIn('state_inputs',p['classes']['priest']['specs']['holy'])
        finally:CLASSES.pop('priest')
    def test12_extension_data_preserved(self):
        d=store.read(self.path);spec=d['profiles']['Default']['classes']['hunter']['specs']['survival'];spec['metadata']['future']='reserved';spec['actions'].append({'kind':'ability','ability':'future','metadata':{}})
        store.write(self.path,d);self.select('survival');s=self.active()['classes']['hunter']['specs']['survival'];self.assertEqual(s['metadata']['future'],'reserved');self.assertEqual(s['actions'][0]['kind'],'ability')
    def test13_migrated_decisions_identical(self):
        self.old['nodes']['Node_Target'].update(x=1,mode='color',r=0,g=0,b=255)
        self.old['nodes']['Node_Combat']['x']=2;self.old['nodes']['Node_Mark']['x']=3;self.old['nodes']['Skill_4'].update(x=4,min_delay=50,max_delay=50)
        self.path.write_text(json.dumps(self.old));new=self.active()
        class Clock:
            t=0
            def __call__(self):return self.t
        class V:
            values={1:(0,0,255),2:(0,0,0),3:(0,0,0),4:(255,255,255)}
            def get_region_rgb(self,x,y,size):return [self.values.get(x,(0,0,0))]*(size*size)
        outputs=[]
        for config in (self.old,new):
            c=Clock();v=V();v.values=dict(V.values);sent=[]
            w=DetectorWorker(config['nodes'],lambda cmd,**kw:sent.append(cmd) or True,lambda:v,clock=c,combat_mode=config['combat_mode'],hunter_mark_mode=config['hunter_mark_mode'])
            w.step(v);v.values[3]=(0,255,0);c.t=.01;w.step(v);v.values[2]=(255,0,0);c.t=.02;w.step(v);c.t=.071;w.step(v);outputs.append(sent)
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual([x['key'] for x in outputs[1]],['3','4'])
    def test22_legacy_read_modify_write_view(self):
        data=store.read(self.path);data['profiles']['Default']['nodes']['Skill_4']['threshold']=83
        store.write(self.path,data);self.assertEqual(self.active()['nodes']['Skill_4']['threshold'],83)
        self.select('survival');self.assertEqual(self.active()['nodes']['Skill_4']['threshold'],200)
    def test23_canonical_edit_not_overwritten_by_view(self):
        data=store.read(self.path);data['profiles']['Default']['classes']['hunter']['specs']['marksmanship']['nodes']['Skill_4']['threshold']=84
        store.write(self.path,data);self.assertEqual(self.active()['nodes']['Skill_4']['threshold'],84)
class UI(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from gui import MacroDashboard
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'config.json';self.path.write_text(json.dumps(legacy()))
        self.root=tk.Tk();self.root.withdraw();self.app=MacroDashboard(self.root,config_path=self.path)
        self.guard=patch.object(self.app,'profile_guard',return_value=True);self.guard.start()
    def tearDown(self):
        import calibration_ui
        calibration_ui.cancel_all(self.app)
        for job in self.app.calibration_jobs:
            if job.thread:job.thread.join(2)
        self.app.is_running=False
        if self.app.node_editor and self.app.node_editor.winfo_exists():self.app.node_editor.destroy()
        self.app.stop_loop();self.app.restore_output()
        t=self.app.calibration_hotkeys.listener._thread
        if t:t.join(2)
        self.app.vision.close()
        for ident in self.root.tk.call('after','info'):self.root.after_cancel(ident)
        self.root.destroy();self.guard.stop();self.tmp.cleanup()
    def select(self,spec):self.assertTrue(spec_ui.request(self.app,'hunter',spec))
    def test14_switch_refresh_and_return(self):
        self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'100')
        self.select('beast_mastery');self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'0')
        e=self.app.config_entries['Skill_4']['x'];e.delete(0,'end');e.insert(0,'555');self.app.save_config_from_entries()
        self.select('marksmanship');self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'100')
        self.select('survival');self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'0')
        self.select('beast_mastery');self.assertEqual(self.app.config_entries['Skill_4']['x'].get(),'555')
    def test15_running_blocks_switch(self):
        self.app.is_running=True;self.assertFalse(spec_ui.request(self.app,'hunter','survival'));self.assertEqual(self.app.selected_spec,'marksmanship');self.assertIn('請先停止 Monitor',self.app.txt_log.get('1.0','end'))
    def test16_f8_current_spec_stale_rejected(self):
        self.app.capture_target_var.set('Skill_5');old=self.app.capture_context();self.select('survival');self.app.capture_target_var.set('Skill_5');self.app.is_tracking=True
        self.assertFalse(self.app.apply_capture_event({'context':old,'x':500,'y':600,'rgb':(1,2,3)}))
        self.assertTrue(self.app.apply_capture_event({'context':self.app.capture_context(),'x':321,'y':432,'rgb':(10,20,30)}));self.app.is_tracking=False
        self.app.save_config_from_entries();self.select('marksmanship');self.assertEqual(self.app.config_entries['Skill_5']['x'].get(),'0')
        self.select('survival');self.assertEqual(self.app.config_entries['Skill_5']['x'].get(),'321')
    def test17_f9_f10_apply_current_spec(self):
        self.select('survival');self.app.edit_node('Skill_5');self.app.node_editor.withdraw();panel=self.app.calibration_panel;manager=self.app.calibration_hotkeys
        class V:
            value=30
            def get_region_rgb(self,x,y,size):return [(V.value,)*3]*(size*size)
            def close(self):pass
        panel.vision_factory=V
        for key in ('F9','F10'):
            event=dict(kind='calibration_hotkey',key=key,type='dark' if key=='F9' else 'bright',context=manager.token,timestamp=time.monotonic())
            self.assertTrue(manager.handle(event));end=time.monotonic()+2
            while panel.job and time.monotonic()<end:self.root.update();time.sleep(.005)
            self.assertIsNone(panel.job);V.value=110
        self.assertTrue(panel.apply());self.app.save_config_from_entries();self.select('marksmanship');self.assertEqual(self.app.config_entries['Skill_5']['threshold'].get(),'121')
        self.select('survival');self.assertEqual(self.app.config_entries['Skill_5']['threshold'].get(),'70')
    def test18_advanced_dialog_uses_selected_spec(self):
        self.select('survival');self.app.editing_nodes['Skill_4']['r']=88;self.app.edit_node('Skill_4');self.app.node_editor.withdraw();self.assertEqual(self.app.node_editor_vars['r'].get(),'88')
    def test19_stale_hotkey_after_spec_switch(self):
        self.app.edit_node('Skill_4');self.app.node_editor.withdraw();m=self.app.calibration_hotkeys;event=dict(key='F9',type='dark',context=m.token,timestamp=time.monotonic())
        self.select('survival');self.app.edit_node('Skill_4');self.app.node_editor.withdraw();self.assertFalse(m.handle(event));self.assertIsNone(self.app.calibration_panel.job)
    def test20_registry_generated_controls(self):
        self.assertEqual(tuple(self.app.spec_buttons),('beast_mastery','marksmanship','survival'));self.assertEqual(self.app.spec_var.get(),'marksmanship');self.assertIn('射擊',self.app.active_character_var.get())
    def test21_unsaved_cancel_no_switch(self):
        self.app.profile_guard.return_value=False;self.assertFalse(spec_ui.request(self.app,'hunter','survival'));self.assertEqual(self.app.selected_spec,'marksmanship')
    def test24_running_blocks_class_change(self):
        self.app.is_running=True
        self.assertFalse(spec_ui.request(self.app,'future_class','future_spec'))
        self.assertEqual(self.app.selected_class,'hunter')
    def test25_active_spec_logged_once_on_start(self):
        from unittest.mock import PropertyMock
        self.select('survival')
        with patch.object(type(self.app.controller),'is_open',new_callable=PropertyMock,return_value=True),patch('gui.DetectorWorker') as worker,patch.object(self.app.target_diag,'emit') as emit:
            self.app.start_loop()
            records=[c for c in emit.call_args_list if c.args and c.args[0]=='ACTIVE_SPEC']
            self.assertEqual(len(records),1);self.assertEqual(records[0].kwargs,{'class':'hunter','spec':'survival'})
            self.app.stop_loop()
if __name__=='__main__':unittest.main(verbosity=2)
