"""Tk-only calibration UI; sample worker never touches widgets or sender."""
import copy,queue,tkinter as tk
from tkinter import ttk
from brightness_calibration import CalibrationJob,analyze,apply_threshold
from vision import GameVision

def busy(app):return any(job.alive for job in getattr(app,'calibration_jobs',[]))
def cancel_all(app):
    for job in getattr(app,'calibration_jobs',[]):job.cancel()

class CalibrationPanel:
    def __init__(self,app,window,parent,skill,sample_var,ratio_var,vision_factory=GameVision):
        self.app=app;self.window=window;self.skill=skill;self.sample_var=sample_var;self.ratio_var=ratio_var;self.vision_factory=vision_factory
        self.samples={};self.analysis=None;self.context=None;self.job=None;self.generation=0;self.job_generation=0
        self.frame=ttk.LabelFrame(parent,text='亮度校正（僅 brightness）',padding=8)
        self.frame.grid(row=10,column=0,columnspan=2,sticky='ew',pady=(8,0))
        self.status=tk.StringVar(value='先停止 Monitor，讓技能處於暗狀態再擷取。')
        self.stats=tk.StringVar(value='暗：尚未擷取\n亮：尚未擷取')
        self.result_text=tk.StringVar(value='尚無建議 Threshold')
        row=ttk.Frame(self.frame);row.pack(fill='x')
        self.dark_button=ttk.Button(row,text='擷取暗值',command=lambda:self.capture('dark'));self.dark_button.pack(side='left',padx=(0,6))
        self.bright_button=ttk.Button(row,text='擷取亮值',command=lambda:self.capture('bright'));self.bright_button.pack(side='left',padx=(0,6))
        self.reset_button=ttk.Button(row,text='重新校正',command=self.reset);self.reset_button.pack(side='left')
        ttk.Label(self.frame,text='遊戲內快捷鍵：F9 = 擷取暗值；F10 = 擷取亮值').pack(fill='x',pady=(6,0))
        ttk.Label(self.frame,textvariable=self.stats,justify='left').pack(fill='x',pady=(6,0))
        ttk.Label(self.frame,textvariable=self.result_text,wraplength=550,justify='left').pack(fill='x',pady=(4,0))
        self.apply_button=ttk.Button(self.frame,text='套用建議 Threshold',command=self.apply);self.apply_button.pack(anchor='e',pady=(4,0))
        ttk.Label(self.frame,textvariable=self.status,wraplength=550,justify='left').pack(fill='x',pady=(4,0))
        window.bind('<Destroy>',self.destroyed,add='+')
        if getattr(app,'calibration_hotkeys',None):app.calibration_hotkeys.activate(self)
        self.tick()
    def node(self):
        n=copy.deepcopy(self.app.editing_nodes[self.skill])
        for key in ('x','y'):n[key]=int(self.app.config_entries[self.skill][key].get())
        n.update(mode=self.app.node_vars[self.skill]['mode'].get(),sample_mode=self.sample_var.get(),match_ratio=float(self.ratio_var.get()))
        if n['sample_mode'] not in ('single_pixel','3x3','5x5') or not 0<n['match_ratio']<=1:raise ValueError('取樣設定無效')
        return n
    def fingerprint(self,n):return (self.app.active_profile_name,n['x'],n['y'],n['mode'],n['sample_mode'],n['match_ratio'])
    def reset(self):
        self.generation+=1
        if self.job:self.job.cancel()
        self.samples={};self.analysis=None;self.context=None
        self.stats.set('暗：尚未擷取\n亮：尚未擷取');self.result_text.set('尚無建議 Threshold');self.status.set('已清除，請重新擷取。');self.refresh()
    def capture(self,state):
        if self.app.is_running:self.status.set('請先停止 Monitor');return False
        if self.job is not None or busy(self.app):self.status.set('取樣正在進行或結束中，請稍候。');return False
        try:n=self.node()
        except (ValueError,tk.TclError) as exc:self.status.set(str(exc));return False
        if n['mode']!='brightness':self.status.set('請自行選擇 Comparison Mode = brightness');return False
        context=self.fingerprint(n)
        if self.context!=context:self.samples={}
        self.context=context;self.samples.pop(state,None);self.analysis=None;self.render()
        self.generation+=1;self.job_generation=self.generation;self.capture_state=state
        self.job=CalibrationJob(n,self.vision_factory);self.app.calibration_jobs.append(self.job);self.job.start()
        self.status.set('取樣中：15 個畫面樣本，目標約 350–500 ms；請保持技能狀態。');self.refresh();return True
    def render(self):
        rows=[]
        from brightness_calibration import summarize
        for key,label in [('dark','暗'),('bright','亮')]:
            if key not in self.samples:rows.append(label+'：尚未擷取');continue
            s=summarize(self.samples[key]);rows.append(f"{label}：min {s['min']:.1f}  max {s['max']:.1f}  mean {s['mean']:.1f}  median {s['median']:.1f}")
        self.stats.set('\n'.join(rows));self.analysis=None
        if all(key in self.samples for key in ('dark','bright')):
            self.analysis=analyze(self.samples['dark'],self.samples['bright']);a=self.analysis
            if not a['valid']:self.result_text.set(f"亮度差 {a['separation']:.1f}；建議 Threshold：無\n"+a['warning'])
            else:self.result_text.set(f"亮度差 {a['separation']:.1f}；建議 Threshold {a['suggested_threshold']}；{a['quality']}\n"+('暗/亮樣本有重疊，Brightness 判斷可能不穩定' if a['overlap'] else '樣本分離良好'))
        else:self.result_text.set('請完成暗／亮兩組取樣。')
    def refresh(self):
        if not self.window.winfo_exists():return
        try:
            n=self.node();enabled=n['mode']=='brightness'
            if self.context and self.context!=self.fingerprint(n):self.reset();return
        except (ValueError,tk.TclError):enabled=False
        ready=enabled and not self.app.is_running and self.job is None and not busy(self.app)
        for button in (self.dark_button,self.bright_button,self.reset_button):button.configure(state='normal' if ready else 'disabled')
        self.apply_button.configure(state='normal' if ready and self.analysis and self.analysis['valid'] else 'disabled')
        if self.app.is_running:self.status.set('請先停止 Monitor')
        elif not enabled:self.status.set('請自行選擇 Comparison Mode = brightness，color/red 不會自動切換。')
    def apply(self):
        if self.app.is_running:self.status.set('請先停止 Monitor');return False
        if busy(self.app) or not self.analysis:return False
        try:
            n=self.node()
            if self.context!=self.fingerprint(n):self.reset();return False
            result=apply_threshold({self.skill:n},self.skill,self.analysis)
            entry=self.app.config_entries[self.skill]['threshold'];old=int(entry.get());value=result[self.skill]['threshold']
            entry.delete(0,tk.END);entry.insert(0,str(value))
            self.app.target_diag.emit('CALIBRATION_APPLY',skill=self.skill,old_threshold=old,new_threshold=value)
            self.status.set('已填入此技能 Threshold；請按主畫面的儲存設定。');return True
        except (ValueError,tk.TclError,KeyError) as exc:self.status.set(str(exc));return False
    def tick(self):
        if self.job and not self.job.alive:
            job=self.job;self.job=None
            if getattr(self.app,'calibration_hotkeys',None):self.app.calibration_hotkeys.completed(self)
            if job in self.app.calibration_jobs:self.app.calibration_jobs.remove(job)
            if self.window.winfo_exists() and not job.cancel_event.is_set() and self.job_generation==self.generation:
                try:data=job.result.get_nowait()
                except queue.Empty:data={'error':'取樣沒有回傳有效結果'}
                if 'error' in data:self.status.set('取樣失敗：'+data['error'])
                else:
                    try:valid=self.context==self.fingerprint(self.node()) and not self.app.is_running
                    except (ValueError,tk.TclError):valid=False
                    if valid:
                        self.samples[self.capture_state]=data['values'];self.render()
                        self.status.set(f"取樣完成：{len(data['values'])} samples / {data['duration_ms']:.0f} ms")
                        self.app.target_diag.emit('CALIBRATION',skill=self.skill,state=self.capture_state,**data['summary'],duration_ms=data['duration_ms'],sample_mode=job.node['sample_mode'],match_ratio=job.node['match_ratio'])
                        if self.analysis:self.app.target_diag.emit('CALIBRATION_RESULT',skill=self.skill,**self.analysis)
                    else:self.reset();self.status.set('座標/取樣/Profile 已變更，結果作廢，請重新校正。')
        if self.window.winfo_exists():self.refresh();self.app.root.after(100,self.tick)
        elif self.job:self.app.root.after(100,self.tick)
    def destroyed(self,event):
        if event.widget is self.window:
            if getattr(self.app,'calibration_hotkeys',None):self.app.calibration_hotkeys.deactivate(self)
            self.generation+=1
            if self.job:self.job.cancel()
