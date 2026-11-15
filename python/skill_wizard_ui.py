"""Five-step opt-in wizard. No screen sampling or output. Saves one disabled slot."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
import skill_wizard as model
from skill_flow import modules
from skill_model import SKILL_PRIORITY
import settings_backup as backup

def busy(app,own=None):
    controller=getattr(app,'controller',None);worker=getattr(controller,'_thread',None)
    if (getattr(app,'is_running',False) or getattr(app,'is_tracking',False) or getattr(app,'dry_start_after_id',None) is not None
        or getattr(controller,'is_open',False) or (worker and worker.is_alive())
        or any(job.alive for job in getattr(app,'calibration_jobs',[]))):return '請先停止監控、UDP、採色與校準，再設定技能。'
    if any(isinstance(w,tk.Toplevel) and w is not own and w.winfo_exists() for w in app.root.winfo_children()):return '請先關閉其他監控、預覽或編輯小窗，避免舊內容覆寫。'
    return None

class Wizard:
    TITLES=('選擇技能格與名稱','選擇分類','填寫資源區間','採色座標（可稍後設定）','檢查與儲存')
    def __init__(self,app):
        self.app=app;self.step=0;self.snapshot=None;self.dirty=False;self.origin=(app.selected_class,app.selected_spec)
        self.module,_,self.resource,self.label=modules(app.selected_class)
        w=self.window=tk.Toplevel(app.root);w.title('技能設定精靈 — 儲存後保持停用');w.geometry('740x580');w.minsize(700,550)
        footer=ttk.Frame(w,padding=12);footer.pack(side='bottom',fill='x')
        body=ttk.Frame(w,padding=16);body.pack(fill='both',expand=True)
        self.heading=tk.StringVar();ttk.Label(body,textvariable=self.heading,font=('Microsoft JhengHei UI',15,'bold')).pack(anchor='w')
        ttk.Label(body,text='不猜技能花費、不擷取畫面、不按鍵。只儲存目前專精的一格；採色與資源提示都會先停用。',wraplength=660).pack(anchor='w',pady=(8,14))
        self.context=tk.StringVar();ttk.Label(body,textvariable=self.context,wraplength=660).pack(anchor='w',pady=(0,8))
        self.pages=[ttk.Frame(body) for _ in self.TITLES]
        self.key=tk.StringVar(value='1');self.name=tk.StringVar();self.kind=tk.StringVar(value='不分類');self.low=tk.StringVar(value='0');self.high=tk.StringVar(value='100')
        self.manual=tk.BooleanVar(value=False);self.x=tk.StringVar();self.y=tk.StringVar();self.coordinate=tk.StringVar(value='desktop_absolute')
        p=self.pages[0]
        ttk.Label(p,text='技能按鍵（優先順序固定1→0）').pack(anchor='w');combo=ttk.Combobox(p,textvariable=self.key,values=[n[6:] for n in SKILL_PRIORITY],state='readonly',width=8);combo.pack(anchor='w',pady=(4,14));combo.bind('<<ComboboxSelected>>',lambda e:self.change_slot())
        ttk.Label(p,text='技能名稱（請填真正學到的技能，最多40字）').pack(anchor='w');ttk.Entry(p,textvariable=self.name,width=42).pack(anchor='w',pady=6)
        p=self.pages[1];ttk.Label(p,text='分類只作標記，不會自動決定保命、位移或中斷時機。',wraplength=640).pack(anchor='w',pady=(0,12));ttk.Combobox(p,textvariable=self.kind,values=self.module.KINDS,state='readonly',width=22).pack(anchor='w')
        p=self.pages[2]
        ttk.Label(p,text=self.label+'必須落在此區間內，才符合資源提示條件；上下限都包含。\n請依真實技能說明填寫。不了解花費時可先保留0–100，仍會維持停用。',wraplength=640).pack(anchor='w',pady=(0,12))
        for title,v in [('最低'+self.label,self.low),('最高'+self.label,self.high)]:
            row=ttk.Frame(p);row.pack(fill='x',pady=5);ttk.Label(row,text=title,width=16).pack(side='left');ttk.Entry(row,textvariable=v,width=8).pack(side='left')
        p=self.pages[3]
        ttk.Label(p,text='預設保留原採色設定，之後回到「技能與採色」使用F8或校準工具。\n這裡不會驗證採色是否正確，也不會更動原本RGB／亮度等比對方式。',wraplength=640).pack(anchor='w',pady=(0,12))
        ttk.Checkbutton(p,text='我知道座標，要手動修改（不等於校準完成）',variable=self.manual,command=self.toggle_coordinates).pack(anchor='w')
        self.coordinate_fields=[]
        for title,v in [('X',self.x),('Y',self.y)]:
            row=ttk.Frame(p);row.pack(fill='x',pady=5);ttk.Label(row,text=title,width=12).pack(side='left');field=ttk.Entry(row,textvariable=v,width=12,state='disabled');field.pack(side='left');self.coordinate_fields.append(field)
        self.coordinate_combo=ttk.Combobox(p,textvariable=self.coordinate,values=('desktop_absolute','wow_client'),state='disabled',width=24);self.coordinate_combo.pack(anchor='w',pady=5)
        ttk.Label(p,text='desktop_absolute＝桌面絕對座標；wow_client＝魔獸視窗內座標。',wraplength=640).pack(anchor='w')
        self.review=tk.StringVar();ttk.Label(self.pages[4],textvariable=self.review,wraplength=650,justify='left').pack(anchor='w')
        self.message=tk.StringVar(value='');ttk.Label(body,textvariable=self.message,wraplength=650).pack(anchor='w',pady=12)
        self.back=ttk.Button(footer,text='上一步',command=self.previous);self.back.pack(side='left')
        self.next=ttk.Button(footer,text='下一步',command=self.advance);self.next.pack(side='left',padx=8)
        self.save_button=ttk.Button(footer,text='備份並儲存為停用',command=self.save);self.save_button.pack(side='right')
        ttk.Button(footer,text='取消',command=self.close).pack(side='right',padx=8)
        for v in (self.name,self.kind,self.low,self.high,self.manual,self.x,self.y,self.coordinate):v.trace_add('write',lambda *args:self.mark_dirty())
        w.protocol('WM_DELETE_WINDOW',self.close);self.change_slot();self.show()
    def mark_dirty(self):self.dirty=True
    def current_context(self):
        if (self.app.selected_class,self.app.selected_spec)!=self.origin:raise ValueError('職業或專精已切換，請重新開啟精靈')
        identity=self.module.load(self.app.app_config_path)[0]
        if identity[1:]!=self.origin or identity[0]!=getattr(self.app,'active_profile_name',identity[0]):raise ValueError('設定檔已切換，請重新開啟精靈')
        if self.snapshot and identity!=self.snapshot['identity']:raise ValueError('設定檔已切換，請重新開啟精靈')
    def change_slot(self):
        try:
            if self.snapshot and self.dirty and not messagebox.askyesno('切換技能格','放棄目前未儲存的精靈內容，載入另一格？',parent=self.window,default='no'):
                self.key.set(self.snapshot['key'][6:]);return
            self.current_context();self.snapshot=model.load_slot(self.app.app_config_path,'Skill_'+self.key.get())
            rule=self.snapshot['rule'];node=self.snapshot['node']
            self.name.set(rule['name']);self.kind.set(rule['kind']);self.low.set(str(rule['min_'+self.resource]));self.high.set(str(rule['max_'+self.resource]));self.x.set(str(node['x']));self.y.set(str(node['y']));self.coordinate.set(node.get('coordinate_mode','desktop_absolute'));self.manual.set(False);self.toggle_coordinates()
            self.context.set('／'.join(self.snapshot['identity'])+'／按鍵'+self.key.get());self.dirty=False;self.message.set('')
        except Exception as e:self.snapshot=None;self.message.set(str(e))
    def toggle_coordinates(self):
        for field in self.coordinate_fields:field.configure(state='normal' if self.manual.get() else 'disabled')
        self.coordinate_combo.configure(state='readonly' if self.manual.get() else 'disabled')
    def number(self,var):
        text=var.get().strip()
        if not text or (text.startswith('-') and not text[1:].isascii()) or not text.lstrip('-').isascii() or not text.lstrip('-').isdecimal():raise ValueError('請輸入整數，不使用小數或字母')
        return int(text)
    def draft(self):
        if self.snapshot is None:raise ValueError('未能載入技能格，請重新開啟')
        self.current_context()
        coordinates={'x':self.number(self.x),'y':self.number(self.y),'coordinate_mode':self.coordinate.get()} if self.manual.get() else None
        return model.make_draft(self.snapshot,self.name.get(),self.kind.get(),self.number(self.low),self.number(self.high),coordinates)
    def show(self):
        for page in self.pages:page.pack_forget()
        self.pages[self.step].pack(fill='both',expand=True)
        self.heading.set(f'{self.step+1}/5　'+self.TITLES[self.step]);self.back.configure(state='normal' if self.step else 'disabled');self.next.configure(state='disabled' if self.step==4 else 'normal');self.save_button.configure(state='normal' if self.step==4 else 'disabled')
    def advance(self):
        try:
            self.current_context()
            if self.step==0 and (not self.name.get().strip() or len(self.name.get().strip())>40):raise ValueError('請先填寫1至40字技能名稱')
            if self.step==1 and self.kind.get() not in self.module.KINDS:raise ValueError('請選擇分類')
            if self.step>=2:
                draft=self.draft()
                if self.step==3:
                    node=draft['node'];rule=draft['rule'];pending='採色座標(0,0)疑似尚未設定；請稍後確認。' if (node['x'],node['y'])==(0,0) else '採色未驗證，仍需遊戲內確認。'
                    self.review.set(f"按鍵 {self.key.get()}／{rule['name']}\n分類：{rule['kind']}\n{self.label}：{rule['min_'+self.resource]}–{rule['max_'+self.resource]}\n座標：({node['x']},{node['y']})／{node.get('coordinate_mode','desktop_absolute')}\n\n{pending}\n儲存前自動備份目前設定。\n只更新此專精的這一格，採色與資源提示均停用。\n沒有執行校準或技能測試。")
            if self.step<4:self.step+=1
            self.message.set('');self.show()
        except Exception as e:self.message.set('請修正：'+str(e))
    def previous(self):
        self.step=max(0,self.step-1);self.message.set('');self.show()
    def save(self):
        result=None
        try:
            if self.step!=4:return
            reason=busy(self.app,self.window)
            if reason:raise ValueError(reason)
            draft=self.draft()
            if not messagebox.askyesno('確認儲存並停用此格','只更新目前專精的按鍵'+self.key.get()+'。\n這一格的採色及資源提示都會停用（即使原本已啟用）。\n儲存前先自動備份；不校準、不啟動監控。是否繼續？',parent=self.window,default='no'):return
            if not self.app.profile_guard():return
            self.current_context()
            reason=busy(self.app,self.window)
            if reason:raise ValueError(reason)
            result=model.save_draft(self.app.app_config_path,self.snapshot,draft,Path(self.app.app_config_path).parent/'settings-backups')
            self.app.refresh_profile()
            if not self.app.load_config_into_entries(show_log=False):raise ValueError('新設定載入失敗')
            self.dirty=False
            messagebox.showinfo('已儲存，保持停用','此格已保存，採色與資源提示仍停用。\n請稍後確認技能與採色，再自行啟用。\n備份：'+str(result['backup']),parent=self.window)
            self.window.destroy()
        except Exception as e:
            extra=''
            if result is not None:
                try:
                    backup.replace_config(self.app.app_config_path,backup.read_backup(result['backup']),result['after_hash']);self.app.refresh_profile();extra='\n已回復儲存前的設定。'
                except Exception as error:extra='\n自動回復未完成：'+str(error)+'\n備份：'+str(result['backup'])
            self.message.set('未完成：'+str(e)+extra)
    def close(self):
        if self.dirty and not messagebox.askyesno('放棄未儲存內容','關閉精靈並放棄這次修改？',parent=self.window,default='no'):return
        self.window.destroy()

def open_wizard(app):
    old=getattr(app,'skill_wizard',None)
    if old is not None and old.window.winfo_exists():old.window.lift();return old
    reason=busy(app)
    if reason:messagebox.showwarning('請先停止或關閉小窗',reason,parent=app.root);return
    if not app.profile_guard():return
    try:instance=Wizard(app);app.skill_wizard=instance;return instance
    except Exception as e:messagebox.showerror('無法開啟精靈',str(e),parent=app.root)
