"""Tk profile and generic node editor. Network work stays in transport.py."""
import copy
import json
import tkinter as tk
from tkinter import ttk,simpledialog,messagebox
import profile_store as store
import endpoint_settings
import lcd_settings
import spec_ui
from mark_opener import mark_settings
MARK_LABELS={'off':'關閉','pre_combat':'A－開戰前印記','post_combat':'B－開戰後印記'}

class ProfileMixin:
    def create_profile_bar(self):
        bar=ttk.LabelFrame(self.root,text='情境設定檔 (Profile)',padding=10);bar.pack(fill='x',padx=10,pady=(8,4))
        self.profile_var=tk.StringVar(value=self.active_profile_name)
        self.profile_combo=ttk.Combobox(bar,textvariable=self.profile_var,state='readonly',values=list(self.profile_data['profiles']),width=24)
        self.profile_combo.pack(side='left',fill='x',expand=True,padx=(0,10))
        self.profile_combo.bind('<<ComboboxSelected>>',self.switch_profile)
        for text,cmd in [('新增設定檔',self.new_profile),('重新命名',self.rename_profile),('刪除設定檔',self.delete_profile)]:ttk.Button(bar,text=text,command=cmd).pack(side='left',padx=4)
        spec_ui.create_bar(self)
        mode_row=ttk.Frame(self.root);mode_row.pack(fill='x',padx=20,pady=(0,4))
        ttk.Label(mode_row,text='開戰方式').pack(side='left',padx=(0,8))
        self.combat_mode_var=tk.StringVar(value='自動開戰')
        self.combat_mode_combo=ttk.Combobox(mode_row,textvariable=self.combat_mode_var,values=('自動開戰','手動第一下'),state='readonly',width=18)
        self.combat_mode_combo.pack(side='left')
        mark_row=ttk.Frame(self.root);mark_row.pack(fill='x',padx=20,pady=(0,6))
        ttk.Label(mark_row,text='獵人印記模式').pack(side='left',padx=(0,8))
        self.hunter_mark_mode_var=tk.StringVar(value=MARK_LABELS['off'])
        self.hunter_mark_combo=ttk.Combobox(mark_row,textvariable=self.hunter_mark_mode_var,values=tuple(MARK_LABELS.values()),state='readonly',width=20)
        self.hunter_mark_combo.pack(side='left',padx=(0,14))
        ttk.Label(mark_row,text="Hunter's Mark Key").pack(side='left',padx=(0,6))
        self.hunter_mark_key_var=tk.StringVar(value='3')
        ttk.Entry(mark_row,textvariable=self.hunter_mark_key_var,width=5).pack(side='left',padx=(0,14))
        ttk.Label(mark_row,text='Retry Delay (ms)').pack(side='left',padx=(0,6))
        self.hunter_mark_retry_var=tk.StringVar(value='500')
        ttk.Entry(mark_row,textvariable=self.hunter_mark_retry_var,width=7).pack(side='left')
    def edited_mark_settings(self):
        mode={v:k for k,v in MARK_LABELS.items()}[self.hunter_mark_mode_var.get()]
        return mark_settings({'hunter_mark_mode':mode,'hunter_mark_key':self.hunter_mark_key_var.get(),
            'hunter_mark_retry_ms':int(self.hunter_mark_retry_var.get())})
    def edited_combat_mode(self):
        return {'自動開戰':'auto','手動第一下':'manual_first_hit'}[self.combat_mode_var.get()]
    def create_node_table(self,frame):
        headers=['節點','啟用','X','Y','Threshold','Min Delay\n(ms)','Max Delay\n(ms)','比對模式','F8 選取','進階','座標系']
        for col,text in enumerate(headers):ttk.Label(frame,text=text).grid(row=0,column=col,sticky='w',padx=4,pady=4)
        self.config_entries={};self.node_vars={};self.capture_radios={};self.coordinate_labels={}
        for row,name in enumerate(store.NODE_NAMES,1):
            ttk.Label(frame,text=name).grid(row=row,column=0,sticky='w',padx=4,pady=5)
            enabled=tk.BooleanVar();mode=tk.StringVar()
            self.node_vars[name]={'enabled':enabled,'mode':mode}
            ttk.Checkbutton(frame,variable=enabled).grid(row=row,column=1)
            fields={}
            for col,key in enumerate(('x','y','threshold','min_delay','max_delay'),2):
                entry=ttk.Entry(frame,width=6);entry.grid(row=row,column=col,sticky='ew',padx=4,pady=5);fields[key]=entry
            self.config_entries[name]=fields
            ttk.Combobox(frame,textvariable=mode,values=('brightness','red','color'),state='readonly',width=9).grid(row=row,column=7,padx=4)
            radio=ttk.Radiobutton(frame,variable=self.capture_target_var,value=name)
            radio.grid(row=row,column=8,padx=4);self.capture_radios[name]=radio
            ttk.Button(frame,text='設定',width=5,command=lambda n=name:self.edit_node(n)).grid(row=row,column=9,padx=4)
            label=tk.StringVar(value='Desktop');self.coordinate_labels[name]=label
            ttk.Label(frame,textvariable=label).grid(row=row,column=10,sticky='w',padx=4)
        for col in range(2,7):frame.columnconfigure(col,weight=1,minsize=95 if col>=4 else 60)
        ttk.Label(frame,text='brightness：RGB 平均 > Threshold；red：R > Threshold；color：依進階 RGB／Tolerance。Target / Combat / Mark 僅作 gate；固定技能鍵 4 > 5 > 6 > 7 > 8 > 9 > 0。',wraplength=920,justify='left').grid(row=len(store.NODE_NAMES)+1,column=0,columnspan=10,sticky='w',padx=4,pady=(8,4))
        buttons=ttk.Frame(frame);buttons.grid(row=len(store.NODE_NAMES)+2,column=0,columnspan=10,sticky='e',pady=(6,0))
        ttk.Button(buttons,text='重新載入目前 Profile',command=self.load_config_into_entries).pack(side='left',padx=4)
        ttk.Button(buttons,text='儲存設定（目前 Profile）',command=self.save_config_from_entries).pack(side='left',padx=4)
    def edited_nodes(self):
        nodes=copy.deepcopy(self.editing_nodes)
        for name,fields in self.config_entries.items():
            for key,entry in fields.items():nodes[name][key]=int(entry.get().strip())
            nodes[name]['enabled']=self.node_vars[name]['enabled'].get();nodes[name]['mode']=self.node_vars[name]['mode'].get()
            store.validate_node(nodes[name])
        return nodes
    def load_config_into_entries(self,show_log=True):
        if self.is_running:self.stop_loop()
        try:
            profile=store.active(self.app_config_path);spec_ui.refresh(self,profile);nodes=profile['nodes'];self.editing_nodes=copy.deepcopy(nodes)
            self.runtime_combat_mode=profile.get('combat_mode','auto')
            self.runtime_mark_settings=mark_settings(profile)
            self.hunter_mark_mode_var.set(MARK_LABELS[self.runtime_mark_settings['hunter_mark_mode']])
            self.hunter_mark_key_var.set(self.runtime_mark_settings['hunter_mark_key'])
            self.hunter_mark_retry_var.set(str(self.runtime_mark_settings['hunter_mark_retry_ms']))
            self.combat_mode_var.set({'auto':'自動開戰','manual_first_hit':'手動第一下'}[self.runtime_combat_mode])
            for name,fields in self.config_entries.items():
                self.coordinate_labels[name].set('WoW Client' if nodes[name].get('coordinate_mode','desktop_absolute')=='wow_client' else 'Desktop')
                for key,entry in fields.items():entry.delete(0,tk.END);entry.insert(0,str(nodes[name][key]))
                for key,var in self.node_vars[name].items():var.set(nodes[name][key])
            self.runtime_nodes=copy.deepcopy(nodes);self.brain.reset()
            if show_log:self.log_msg('已載入目前 Profile 的Target 與七個技能。')
            return True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.log_msg('載入失敗：'+str(exc));return False
    def save_config_from_entries(self):
        try:
            nodes=self.edited_nodes()
            if self.is_running:self.stop_loop()
            mode=self.edited_combat_mode()
            settings=self.edited_mark_settings()
            store.update_active(self.app_config_path,{'nodes':nodes,'combat_mode':mode,**settings})
            self.runtime_mark_settings=settings
            self.runtime_combat_mode=mode
            self.editing_nodes=copy.deepcopy(nodes);self.runtime_nodes=copy.deepcopy(nodes)
            self.brain.reset();self.current_conditions={}
            self.log_msg('已儲存目前 Profile；取消舊待送事件並套用新節點。')
            return True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.log_msg('儲存失敗：'+str(exc));return False
    def profile_guard(self):
        try:
            saved=store.active(self.app_config_path)
            dirty=self.edited_nodes()!=saved['nodes'] or self.edited_combat_mode()!=saved.get('combat_mode','auto') or self.edited_mark_settings()!=mark_settings(saved)
        except (OSError,ValueError,KeyError,TypeError):dirty=True
        if dirty:
            answer=messagebox.askyesnocancel('未儲存參數','是否先儲存目前 Profile 的節點修改？',parent=self.root)
            if answer is None or (answer and not self.save_config_from_entries()):return False
        if (self.lcd_editor and self.lcd_editor.window.winfo_exists()) or (getattr(self,'node_editor',None) and self.node_editor.winfo_exists()):
            if not messagebox.askyesno('關閉編輯視窗','切換會關閉進階／LCD 編輯視窗，尚未套用的內容將丟棄。繼續？',parent=self.root):return False
        return True
    def quiesce_profile(self):
        self.stop_loop();self.capture_generation+=1
        if self.is_tracking:self.toggle_tracking()
        if self.controller.is_open:self.disconnect_hw()
        if self.lcd_editor and self.lcd_editor.window.winfo_exists():self.lcd_editor.window.destroy()
        self.lcd_editor=None
        if getattr(self,'node_editor',None) and self.node_editor.winfo_exists():self.node_editor.destroy()
    def refresh_profile(self):
        self.profile_data=store.read(self.app_config_path);self.active_profile_name=self.profile_data['last_used']
        self.profile_combo.configure(values=list(self.profile_data['profiles']));self.profile_var.set(self.active_profile_name)
        self.load_config_into_entries(show_log=False)
        host,port=endpoint_settings.load(self.app_config_path);self.target_ip_var.set(host);self.target_port_var.set(str(port))
        power=self.load_lcd_power_config()
        for attr,key in [('screensaver_enabled_var','screensaver_enabled'),('screensaver_seconds_var','screensaver_seconds'),('lcd_sleep_enabled_var','sleep_enabled'),('lcd_sleep_seconds_var','sleep_seconds')]:getattr(self,attr).set(power[key])
        self.lcd_display=lcd_settings.load(self.app_config_path)
        self.capture_samples.clear();self.capture_target_var.set('Node_Target');self.on_capture_target_change()
        self.log_msg('目前 Profile：'+self.active_profile_name+'；監控已停止，網路需手動初始化。')
    def profile_operation(self,operation):
        if not self.profile_guard():self.profile_var.set(self.active_profile_name);return False
        try:
            self.quiesce_profile();operation();self.refresh_profile();return True
        except (OSError,ValueError,KeyError,TypeError) as exc:
            self.profile_var.set(self.active_profile_name);messagebox.showerror('Profile 操作失敗',str(exc),parent=self.root);return False
    def switch_profile(self,event=None):
        name=self.profile_var.get()
        if name!=self.active_profile_name:self.profile_operation(lambda:store.select(self.app_config_path,name))
    def new_profile(self):
        name=simpledialog.askstring('新增設定檔','新名稱（複製目前已儲存參數）',parent=self.root)
        if name is not None:self.profile_operation(lambda:store.create(self.app_config_path,name.strip()))
    def rename_profile(self):
        name=simpledialog.askstring('重新命名','Profile 新名稱',initialvalue=self.active_profile_name,parent=self.root)
        if name is not None:self.profile_operation(lambda:store.rename(self.app_config_path,name.strip()))
    def delete_profile(self):
        if len(store.read(self.app_config_path)['profiles'])<=1:
            messagebox.showinfo('無法刪除','至少需保留一個 Profile。',parent=self.root);return
        if messagebox.askyesno('刪除設定檔','確定刪除 '+self.active_profile_name+'？',parent=self.root):self.profile_operation(lambda:store.delete(self.app_config_path))
    def capture_node(self,name):
        self.capture_target_var.set(name)
        if not self.is_tracking:self.toggle_tracking()
    def edit_node(self,name):
        if getattr(self,'node_editor',None) and self.node_editor.winfo_exists():self.node_editor.destroy()
        window=self.node_editor=tk.Toplevel(self.root);window.title(name+' 進階設定');window.geometry('590x470')
        f=ttk.Frame(window,padding=14);f.pack(fill='both',expand=True);values={}
        self.node_editor_name=name;self.node_editor_vars=values
        for row,key in enumerate(('r','g','b','tolerance')):
            ttk.Label(f,text=key).grid(row=row,column=0,sticky='w',pady=5)
            v=tk.StringVar(value=str(self.editing_nodes[name][key]));values[key]=v;ttk.Entry(f,textvariable=v).grid(row=row,column=1,sticky='ew',pady=5)
        ttk.Label(f,text='單次 JSON 動作').grid(row=4,column=0,sticky='w',pady=5)
        command=tk.StringVar(value=json.dumps(self.editing_nodes[name]['command'],ensure_ascii=False));ttk.Entry(f,textvariable=command,width=52,state='readonly').grid(row=4,column=1,sticky='ew')
        coordinate_label='WoW Client' if self.editing_nodes[name].get('coordinate_mode','desktop_absolute')=='wow_client' else 'Desktop'
        ttk.Label(f,text='座標系：'+coordinate_label+'（唯讀）\nTarget / Combat / Mark command=null；技能鍵固定。color 使用 RGB/Tolerance。',justify='left',wraplength=550).grid(row=5,column=0,columnspan=2,sticky='w',pady=10)
        ttk.Label(f,text='Sample Mode').grid(row=6,column=0,sticky='w')
        sample=tk.StringVar(value=self.editing_nodes[name].get('sample_mode','single_pixel'))
        ttk.Combobox(f,textvariable=sample,values=('single_pixel','3x3','5x5'),state='readonly').grid(row=6,column=1,sticky='ew')
        ttk.Label(f,text='Match ratio (0 < ratio <= 1)').grid(row=7,column=0,sticky='w')
        ratio=tk.StringVar(value=str(self.editing_nodes[name].get('match_ratio',.30)))
        ttk.Entry(f,textvariable=ratio).grid(row=7,column=1,sticky='ew')
        message=tk.StringVar();ttk.Label(f,textvariable=message,wraplength=550).grid(row=8,column=0,columnspan=2,sticky='w');f.columnconfigure(1,weight=1)
        def apply():
            try:
                n=copy.deepcopy(self.editing_nodes[name]);n.update({k:int(v.get()) for k,v in values.items()});n['command']=json.loads(command.get());n['sample_mode']=sample.get();n['match_ratio']=float(ratio.get());store.validate_node(n)
                self.editing_nodes[name]=n;window.destroy();self.log_msg(name+' 進階內容已填入，請按儲存設定。')
            except (ValueError,TypeError,KeyError) as exc:message.set(str(exc))
        ttk.Button(f,text='填入（尚需儲存設定）',command=apply).grid(row=9,column=1,sticky='e',pady=8)
        if name in store.SKILL_PRIORITY:
            from calibration_ui import CalibrationPanel
            window.geometry('640x800')
            self.calibration_panel=CalibrationPanel(self,window,f,name,sample,ratio)
