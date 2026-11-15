"""Registry-driven character selector. No detector or transport logic."""
import tkinter as tk
from tkinter import ttk
import profile_store as store
from class_registry import CLASSES,definition,spec_definition

def create_bar(app):
    box=ttk.LabelFrame(getattr(app,'character_parent',app.root),text='角色 / 專精',padding=8);box.pack(fill='x',padx=10,pady=(0,4))
    line=ttk.Frame(box);line.pack(fill='x')
    ttk.Label(line,text='職業：').pack(side='left')
    app.class_var=tk.StringVar();app.spec_var=tk.StringVar();app.active_character_var=tk.StringVar()
    app.class_combo=ttk.Combobox(line,textvariable=app.class_var,values=[c.name for c in CLASSES.values()],state='readonly',width=16);app.class_combo.pack(side='left',padx=(0,12))
    ttk.Label(line,textvariable=app.active_character_var).pack(side='right')
    app.spec_buttons_frame=ttk.Frame(box);app.spec_buttons_frame.pack(fill='x',pady=(6,0))
    app.class_combo.bind('<<ComboboxSelected>>',lambda e:request_class(app))
    refresh(app,app.profile_data['profiles'][app.active_profile_name])

def refresh(app,profile):
    app.selected_class=profile['selected_class'];app.selected_spec=profile['selected_spec']
    reg=definition(app.selected_class);app.class_var.set(reg.name);app.spec_var.set(app.selected_spec)
    app.active_character_var.set('目前：'+reg.name+' / '+spec_definition(reg.id,app.selected_spec).name)
    for child in app.spec_buttons_frame.winfo_children():child.destroy()
    app.spec_buttons={}
    for spec in reg.specs:
        button=ttk.Radiobutton(app.spec_buttons_frame,text=spec.name,variable=app.spec_var,value=spec.id,
            command=lambda cid=reg.id,sid=spec.id:request(app,cid,sid))
        button.pack(side='left',padx=(0,18));app.spec_buttons[spec.id]=button

def request_class(app):
    reg=next(c for c in CLASSES.values() if c.name==app.class_var.get())
    return request(app,reg.id,reg.default_spec)

def request(app,class_id,spec_id):
    if app.is_running:
        app.class_var.set(definition(app.selected_class).name);app.spec_var.set(app.selected_spec)
        app.log_msg('請先停止 Monitor 再切換職業或專精');return False
    if (class_id,spec_id)==(app.selected_class,app.selected_spec):return True
    if not app.profile_guard():
        app.class_var.set(definition(app.selected_class).name);app.spec_var.set(app.selected_spec);return False
    try:
        # Stop F8 and destroy calibration context before selecting new data.
        app.capture_generation+=1
        if app.is_tracking:app.stop_tracking()
        else:app._hotkey_epoch+=1
        for name in ('node_editor','lcd_editor'):
            editor=getattr(app,name,None)
            window=getattr(editor,'window',editor)
            if window is not None and window.winfo_exists():window.destroy()
        store.select_character(app.app_config_path,class_id,spec_id)
        app.profile_data=store.read(app.app_config_path)
        if not app.load_config_into_entries(show_log=False):raise ValueError('專精已儲存，但畫面載入失敗，請重新載入')
        app.capture_samples.clear();app.capture_target_var.set('Node_Target');app.on_capture_target_change()
        app.log_msg(app.active_character_var.get()+'；監控仍停止，UDP連線保持原樣。');return True
    except (OSError,ValueError,KeyError,TypeError) as exc:
        app.class_var.set(definition(app.selected_class).name);app.spec_var.set(app.selected_spec)
        app.log_msg('切換失敗：'+str(exc));return False
