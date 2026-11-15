"""Explicit advisory-only editor, saved independently per Warrior specialization."""
import tkinter as tk
from tkinter import ttk,messagebox
import rage_rules as rules

def open_editor(app):
    try:identity,saved=rules.load(app.app_config_path)
    except Exception as e:messagebox.showerror('讀取失敗',str(e),parent=app.root);return
    if identity[1]!='warrior':messagebox.showinfo('先選戰士','請先在主畫面選戰士，再開怒氣設定。',parent=app.root);return
    old=getattr(app,'rage_rules_window',None)
    if old is not None and old.winfo_exists():old.lift();return
    w=tk.Toplevel(app.root);app.rage_rules_window=w;w.title('怒氣條件設定 — 僅提示');w.geometry('790x620');w.minsize(760,600)
    body=ttk.Frame(w,padding=14);body.pack(fill='both',expand=True)
    ttk.Label(body,text='怒氣條件設定',font=('Microsoft JhengHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(body,text='設定檔：'+identity[0]+'／戰士／'+identity[2]).pack(anchor='w',pady=(4,8))
    ttk.Label(body,text='只保存提示條件，不會啟用技能按鍵。分類含產／消資源、防禦、位移、中斷，只作標記；順序仍為1→0。\n最低與最高均包含；請依技能說明填寫，估算值可能有誤差。',wraplength=730).pack(anchor='w')
    table=ttk.Frame(body);table.pack(fill='x',pady=12)
    for j,t in enumerate(('按鍵','提示啟用','技能名稱','分類','最低怒氣','最高怒氣')):ttk.Label(table,text=t).grid(row=0,column=j,sticky='w',padx=5,pady=5)
    fields={}
    for i,(n,r) in enumerate(saved.items(),1):
        v={'enabled':tk.BooleanVar(value=r['enabled']),'name':tk.StringVar(value=r['name']),'kind':tk.StringVar(value=r['kind']),'min_rage':tk.StringVar(value=str(r['min_rage'])),'max_rage':tk.StringVar(value=str(r['max_rage']))};fields[n]=v
        ttk.Label(table,text=n[6:]).grid(row=i,column=0,padx=5,pady=5)
        ttk.Checkbutton(table,variable=v['enabled']).grid(row=i,column=1)
        ttk.Entry(table,textvariable=v['name'],width=22).grid(row=i,column=2,padx=5,sticky='ew')
        ttk.Combobox(table,textvariable=v['kind'],values=rules.KINDS,state='readonly',width=12).grid(row=i,column=3,padx=5)
        for j,k in ((4,'min_rage'),(5,'max_rage')):ttk.Entry(table,textvariable=v[k],width=7).grid(row=i,column=j,padx=5)
    table.columnconfigure(2,weight=1)
    def collect():
        r={n:{k:(int(v.get()) if k in ('min_rage','max_rage') else v.get()) for k,v in vs.items()} for n,vs in fields.items()}
        return rules.validate(r)
    def refresh_dirty(*args):
        from editing_status import editor_event
        try:current=collect();editor_event(app,identity,w,current!=saved,True)
        except Exception:editor_event(app,identity,w,True,False)
    for row_vars in fields.values():
        for variable in row_vars.values():variable.trace_add('write',refresh_dirty)
    refresh_dirty()
    result=tk.StringVar(value='尚未測試；怒氣不足時不會自行換成產怒技能，需設定對應區間。')
    line=ttk.Frame(body);line.pack(fill='x',pady=6);test=tk.StringVar(value='50')
    ttk.Label(line,text='手動模擬怒氣').pack(side='left');ttk.Entry(line,textvariable=test,width=6).pack(side='left',padx=8)
    def simulate():
        try:
            r=collect();v=int(test.get())
            if not 0<=v<=100:raise ValueError('模擬怒氣需0至100')
            n=rules.choose(r,v);result.set(('僅怒氣符合：按鍵 '+n[6:]+'／'+r[n]['name']) if n else '沒有符合條件的技能；不送按鍵')
        except Exception as e:result.set('設定有誤：'+str(e))
    ttk.Button(line,text='測試提示（不按鍵）',command=simulate).pack(side='left')
    ttk.Label(body,textvariable=result,wraplength=730).pack(anchor='w',pady=8)
    def save():
        try:
            r=collect();rules.save(app.app_config_path,identity,r);saved.clear();saved.update(r);refresh_dirty();result.set('已保存目前專精的提示條件；自動按鍵設定未改動。')
        except Exception as e:messagebox.showerror('無法保存',str(e),parent=w)
    footer=ttk.Frame(body);footer.pack(side='bottom',fill='x',pady=8)
    ttk.Button(footer,text='儲存怒氣條件',command=save).pack(side='right')
    def close():
        try:dirty=collect()!=saved
        except Exception:dirty=True
        if dirty and not messagebox.askyesno('尚未儲存','放棄這次未儲存的怒氣條件？',parent=w,default='no'):return
        w.destroy()
    ttk.Button(footer,text='關閉',command=close).pack(side='right',padx=8);w.protocol('WM_DELETE_WINDOW',close)
    w.update_idletasks();w.minsize(760,max(600,body.winfo_reqheight()+20))
