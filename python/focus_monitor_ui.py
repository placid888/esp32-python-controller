"""Independent, opt-in, read-only Tk display. Never feeds combat decisions."""
import tkinter as tk
from tkinter import ttk
import subprocess,sys,json,time
from pathlib import Path

def add_controls(app):
    row=ttk.Frame(getattr(app,'focus_controls_parent',app.root));row.pack(fill='x',padx=20,pady=(0,4))
    ttk.Button(row,text='集中值唯讀監控…',command=lambda:open_monitor(app)).pack(side='left')
    from focus_rules_ui import open_editor
    ttk.Button(row,text='集中值條件設定…',command=lambda:open_editor(app)).pack(side='left',padx=8)
    from focus_integrated_dryrun_ui import open_panel
    ttk.Button(row,text='整合判斷模擬…',command=lambda:open_panel(app)).pack(side='left',padx=8)
    ttk.Label(row,text='僅提示，不控制技能或ESP32').pack(side='left',padx=10)

def open_monitor(app):
    old=getattr(app,'focus_window',None)
    if old is not None and old.winfo_exists():old.lift();return
    w=tk.Toplevel(app.root);app.focus_window=w;w.title('集中值唯讀監控 — 讀取與驗證');w.geometry('590x390+%d+60'%max(24,w.winfo_screenwidth()-590-24));w.minsize(570,370);w.attributes('-topmost',True)
    box=ttk.Frame(w,padding=16);box.pack(fill='both',expand=True)
    buttons=ttk.Frame(box);buttons.pack(side='bottom',fill='x',pady=(10,0))
    value=tk.StringVar(value='未開始');status=tk.StringVar(value='按開始後點一下魔獸；此小窗會留在上方顯示。')
    ttk.Label(box,text='集中值唯讀監控（讀取狀態與驗證進度分開）').pack(anchor='w')
    ttk.Label(box,textvariable=value,font=('Microsoft JhengHei UI',22)).pack(anchor='w',pady=8)
    ttk.Label(box,textvariable=status,wraplength=520).pack(anchor='w')
    ttk.Label(box,text='限定目前 Hunter Clean 版面、1920×1080、暫以最大集中值100估算。\n勿遮擋或移動集中值條；遊戲內提示遮住也可能誤讀。',wraplength=520).pack(anchor='w',pady=8)
    from resource_calibration_ui import add_status
    add_status(box,'hunter',identity=lambda:(getattr(app,'active_profile_name',None),getattr(app,'selected_class',None),getattr(app,'selected_spec',None)),config_path=app.app_config_path)
    advisory=tk.StringVar(value='集中值技能提示：尚未讀取')
    ttk.Label(box,textvariable=advisory,wraplength=520).pack(anchor='w',pady=8)
    running=False;proc=None;began=0.;after=None
    def stop():
        nonlocal running,proc,after
        running=False
        if after is not None:w.after_cancel(after);after=None
        if proc is not None:
            proc.kill();proc.communicate();proc=None
        advisory.set('集中值技能提示：已停止')
        value.set('已停止');status.set('沒有保留舊值；不會送出任何按鍵。')
    def tick():
        nonlocal proc,began,after
        after=None
        if not running or not w.winfo_exists():return
        if getattr(app,'selected_class',None)!='hunter':stop();status.set('目前不是獵人設定，已停止。');return
        if proc is None:
            try:
                proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('focus_monitor.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));began=time.monotonic()
                if value.get() in ('未開始','已停止'):value.set('讀取中…')
            except Exception as e:status.set('無法啟動讀取：'+str(e));value.set('無法讀取')
        elif proc.poll() is not None:
            out,err=proc.communicate();proc=None
            try:
                result=json.loads(out)
                if result.get('status')!='ok':
                    reason=result.get('reason','讀取失敗')
                    if 'not foreground' in reason:reason='請點一下魔獸畫面；小窗會保持置頂，不必再點回來。'
                    elif 'belongs to another window' in reason:reason='集中值條被其他視窗遮住，請移開視窗。'
                    raise ValueError(reason)
                value.set('估算：約 %s / 100'%result['estimated_focus']);status.set('讀取狀態：正常。完整校準進度請看下方；不控制按鍵。')
                from focus_rules import describe
                from focus_integrated_dryrun import live_result,brief
                advisory.set(brief(live_result(app.app_config_path,result)))
            except Exception as e:value.set('無法讀取');advisory.set('無有效集中值，不產生技能提示');status.set(str(e)[:180])
        elif time.monotonic()-began>4:
            proc.kill();proc.communicate();proc=None;value.set('無法讀取');advisory.set('讀取逾時，不產生提示');status.set('讀取逾時，將重試。')
        w.update_idletasks()
        w.minsize(570,max(390,box.winfo_reqheight()+24))
        after=w.after(500,tick)
    def start():
        nonlocal running
        if running:return
        running=True;tick()
    ttk.Button(buttons,text='開始唯讀監控',command=start).pack(side='left')
    ttk.Button(buttons,text='停止',command=stop).pack(side='left',padx=8)
    def close():stop();w.destroy()
    w.update_idletasks()
    needed=max(390,box.winfo_reqheight()+24)
    w.geometry('590x%d+%d+60'%(needed,max(24,w.winfo_screenwidth()-590-24)));w.minsize(570,needed)
    w.protocol('WM_DELETE_WINDOW',close)
    w.bind('<Destroy>',lambda e:stop() if e.widget==w else None)
