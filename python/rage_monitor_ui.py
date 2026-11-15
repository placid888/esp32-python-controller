"""Independent, opt-in, read-only Tk display. Never feeds combat decisions."""
import tkinter as tk
from tkinter import ttk
import subprocess,sys,json,time
from pathlib import Path

def add_controls(app):
    from resource_overview_ui import add_overview
    add_overview(app,open_resource_monitor,open_resource_editor,open_resource_simulation)

def open_monitor(app):
    old=getattr(app,'rage_window',None)
    if old is not None and old.winfo_exists():old.lift();return
    w=tk.Toplevel(app.root);app.rage_window=w;w.title('怒氣唯讀監控');w.geometry('590x390+24+60');w.minsize(570,370);w.attributes('-topmost',True)
    box=ttk.Frame(w,padding=16);box.pack(fill='both',expand=True)
    buttons=ttk.Frame(box);buttons.pack(side='bottom',fill='x',pady=(10,0))
    value=tk.StringVar(value='未開始');status=tk.StringVar(value='按開始後點一下魔獸；此小窗會留在上方顯示。')
    ttk.Label(box,text='估算怒氣（非精確讀值）').pack(anchor='w')
    ttk.Label(box,textvariable=value,font=('Microsoft JhengHei UI',22)).pack(anchor='w',pady=8)
    ttk.Label(box,textvariable=status,wraplength=520).pack(anchor='w')
    ttk.Label(box,text='限定目前 Warrior Clean 版面、1920×1080、最大怒氣100。\n勿遮擋或移動怒氣條；遊戲內提示遮住也可能誤讀。',wraplength=520).pack(anchor='w',pady=8)
    from resource_calibration_ui import add_status
    add_status(box,'warrior')
    advisory=tk.StringVar(value='怒氣技能提示：尚未讀取')
    ttk.Label(box,textvariable=advisory,wraplength=520).pack(anchor='w',pady=8)
    running=False;proc=None;began=0.;after=None
    def stop():
        nonlocal running,proc,after
        running=False
        if after is not None:w.after_cancel(after);after=None
        if proc is not None:
            proc.kill();proc.communicate();proc=None
        advisory.set('怒氣技能提示：已停止')
        value.set('已停止');status.set('沒有保留舊值；不會送出任何按鍵。')
    def tick():
        nonlocal proc,began,after
        after=None
        if not running or not w.winfo_exists():return
        if getattr(app,'selected_class',None)!='warrior':stop();status.set('目前不是戰士設定，已停止。');return
        if proc is None:
            try:
                proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('rage_monitor.py'))],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));began=time.monotonic()
                if value.get() in ('未開始','已停止'):value.set('讀取中…')
            except Exception as e:status.set('無法啟動讀取：'+str(e));value.set('無法讀取')
        elif proc.poll() is not None:
            out,err=proc.communicate();proc=None
            try:
                result=json.loads(out)
                if result.get('status')!='ok':
                    reason=result.get('reason','讀取失敗')
                    if 'not foreground' in reason:reason='請點一下魔獸畫面；小窗會保持置頂，不必再點回來。'
                    elif 'belongs to another window' in reason:reason='怒氣條被其他視窗遮住，請移開視窗。'
                    raise ValueError(reason)
                value.set('約 %s / 100'%result['estimated_rage']);status.set('僅供觀察；未接入技能決策。')
                from rage_rules import describe
                from integrated_dryrun import live_result,brief
                advisory.set(brief(live_result(app.app_config_path,result)))
            except Exception as e:value.set('無法讀取');advisory.set('無有效怒氣，不產生技能提示');status.set(str(e)[:180])
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
    w.geometry('590x%d+24+60'%needed);w.minsize(570,needed)
    w.protocol('WM_DELETE_WINDOW',close)
    w.bind('<Destroy>',lambda e:stop() if e.widget==w else None)


def open_resource_monitor(app):
    if getattr(app,'selected_class',None)=='hunter':
        from focus_monitor_ui import open_monitor as action
    else:action=open_monitor
    return action(app)

def open_resource_editor(app):
    if getattr(app,'selected_class',None)=='hunter':
        from focus_rules_ui import open_editor as action
    else:
        from rage_rules_ui import open_editor as action
    return action(app)

def open_resource_simulation(app):
    if getattr(app,'selected_class',None)=='hunter':
        from focus_integrated_dryrun_ui import open_panel as action
    else:
        from integrated_dryrun_ui import open_panel as action
    return action(app)
