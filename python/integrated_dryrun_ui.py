"""Manual signal simulation, explicitly not live-game validation."""
import tkinter as tk,time
from tkinter import ttk,messagebox
import rage_rules
from integrated_dryrun import evaluate,FIELDS
VALUES=('未知','符合','不符合')
def state(text):return {'未知':None,'符合':True,'不符合':False}[text]
def open_panel(app):
    w=tk.Toplevel(app.root);w.title('整合判斷模擬 — 不送按鍵');w.geometry('800x650');w.minsize(780,620)
    body=ttk.Frame(w,padding=14);body.pack(fill='both',expand=True)
    ttk.Label(body,text='整合判斷模擬',font=('Microsoft JhengHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(body,text='以下全部是手動測試值，不代表遊戲真實狀態；不會儲存或送按鍵。\n先在「怒氣條件設定」儲存要測試的技能名稱、區間與提示啟用。',wraplength=750).pack(anchor='w',pady=8)
    line=ttk.Frame(body);line.pack(fill='x');global_vars={}
    for k,label in [('target','目標'),('enemy','敵方'),('combat','戰鬥')]:
        ttk.Label(line,text=label).pack(side='left');v=tk.StringVar(value='未知');global_vars[k]=v;ttk.Combobox(line,textvariable=v,values=VALUES,state='readonly',width=7).pack(side='left',padx=5)
    rage=tk.StringVar(value='50');ttk.Label(line,text='怒氣').pack(side='left');ttk.Entry(line,textvariable=rage,width=5).pack(side='left',padx=5)
    table=ttk.Frame(body);table.pack(fill='x',pady=12);fields={}
    for j,label in enumerate(('格子','採色訊號','冷卻完成','距離符合','技能可用')):ttk.Label(table,text=label).grid(row=0,column=j,padx=12,pady=5)
    for i,n in enumerate(rage_rules.defaults(),1):
        ttk.Label(table,text=n[6:]).grid(row=i,column=0,pady=6);fields[n]={}
        for j,k in enumerate(FIELDS,1):
            v=tk.StringVar(value='未知');fields[n][k]=v;ttk.Combobox(table,textvariable=v,values=VALUES,state='readonly',width=9).grid(row=i,column=j,padx=10)
    text=tk.StringVar(value='尚未測試；預設未知，不會產生候選。')
    ttk.Label(body,textvariable=text,wraplength=750).pack(anchor='w',pady=8)
    def run():
        try:
            identity,rules=rage_rules.load(app.app_config_path)
            if identity[1]!='warrior':raise ValueError('請先選戰士設定')
            v=int(rage.get())
            if not 0<=v<=100:raise ValueError('怒氣需0至100')
            snap={'timestamp':time.monotonic(),'rage':v,'source':'manual_simulation',**{k:state(x.get()) for k,x in global_vars.items()},'skills':{n:{k:state(x.get()) for k,x in vs.items()} for n,vs in fields.items()}}
            r=evaluate(rules,snap)
            from editing_status import record_simulation
            record_simulation(app,identity,rules,r,'saved')
            from advisory_messages import explain
            text.set('手動模擬：'+explain(r,'怒氣',rules,v))
        except Exception as e:
            from editing_status import clear_simulation
            clear_simulation(app)
            text.set('無法測試：'+str(e))
        w.update_idletasks();w.minsize(780,max(620,body.winfo_reqheight()+20))
    footer=ttk.Frame(body);footer.pack(side='bottom',fill='x',pady=8)
    ttk.Button(footer,text='執行模擬（不按鍵）',command=run).pack(side='left');ttk.Button(footer,text='關閉',command=w.destroy).pack(side='right')
    w.update_idletasks();w.minsize(780,max(620,body.winfo_reqheight()+20))
