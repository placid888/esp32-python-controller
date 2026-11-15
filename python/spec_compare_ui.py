"""Side-by-side read-only saved spec comparison; never switches active profile."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk,scrolledtext,messagebox
import hashlib
import profile_store as store
from class_registry import CLASSES
from spec_compare import compare

def open_compare(app):
    old=getattr(app,'spec_compare_window',None)
    if old is not None and old.winfo_exists():old.lift();return old
    try:data=store.read(app.app_config_path)
    except Exception as e:messagebox.showerror('無法讀取設定',str(e),parent=app.root);return
    options={reg.name+'／'+spec.name:(reg.id,spec.id) for reg in CLASSES.values() for spec in reg.specs}
    active=next((name for name,pair in options.items() if pair==(getattr(app,'selected_class',None),getattr(app,'selected_spec',None))),next(iter(options)))
    alternatives=[name for name,pair in options.items() if pair[0]==options[active][0] and name!=active]
    w=tk.Toplevel(app.root);app.spec_compare_window=w;w.title('專精設定差異 — 唯讀，不覆蓋');w.geometry('960x720');w.minsize(860,620)
    footer=ttk.Frame(w,padding=10);footer.pack(side='bottom',fill='x')
    ttk.Button(footer,text='關閉',command=w.destroy).pack(side='right')
    body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
    ttk.Label(body,text='比較已儲存的專精設定',font=('Microsoft JhengHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(body,text='只比較，不切換、不複製、不覆蓋。未儲存的編輯內容不在比較內；相同不代表已通過實機測試。',wraplength=900).pack(anchor='w',pady=(5,12))
    line=ttk.Frame(body);line.pack(fill='x')
    profile=tk.StringVar(value=data['last_used']);left=tk.StringVar(value=active);right=tk.StringVar(value=alternatives[0] if alternatives else active)
    for title,var,values,width in [('設定檔',profile,list(data['profiles']),20),('左側',left,list(options),16),('右側',right,list(options),16)]:
        ttk.Label(line,text=title).pack(side='left',padx=(0,4));combo=ttk.Combobox(line,textvariable=var,values=values,state='readonly',width=width);combo.pack(side='left',padx=(0,10));combo.bind('<<ComboboxSelected>>',lambda e:invalidate('選項已變更，請重新比較'))
    status=tk.StringVar(value='尚未比較');ttk.Label(body,textvariable=status,wraplength=900).pack(anchor='w',pady=8)
    table=ttk.Frame(body);table.pack(fill='both',expand=True)
    tree=ttk.Treeview(table,columns=('item','field','left','right'),show='headings',height=14,selectmode='browse')
    for key,title,width in [('item','項目',90),('field','差異欄位',190),('left','左側值',260),('right','右側值',260)]:tree.heading(key,text=title);tree.column(key,width=width,minwidth=width,stretch=key in ('left','right'),anchor='w')
    y=ttk.Scrollbar(table,orient='vertical',command=tree.yview);y.pack(side='right',fill='y')
    x=ttk.Scrollbar(table,orient='horizontal',command=tree.xview);x.pack(side='bottom',fill='x');tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.pack(fill='both',expand=True)
    detail=scrolledtext.ScrolledText(body,height=5,wrap='word',font=('Microsoft JhengHei UI',10));detail.pack(fill='x',pady=(8,0));detail.configure(state='disabled')
    rows=[];stamp=None;timer=None
    def text(value):detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',value);detail.configure(state='disabled')
    def invalidate(message):
        nonlocal rows,stamp
        rows=[];stamp=None;tree.delete(*tree.get_children());status.set(message);text('未取得有效比較結果。')
    def run():
        nonlocal rows,stamp
        try:
            path=Path(app.app_config_path);before=hashlib.sha256(path.read_bytes()).hexdigest()
            rows=compare(path,profile.get(),options[left.get()],options[right.get()])
            if hashlib.sha256(path.read_bytes()).hexdigest()!=before:raise ValueError('讀取期間設定已變更，請重試')
            stamp=before;tree.delete(*tree.get_children());tree.heading('left',text=left.get());tree.heading('right',text=right.get())
            for i,row in enumerate(rows):tree.insert('','end',iid=str(i),values=(row['item'],row['field'],row['left'],row['right']))
            status.set(f'已儲存快照：{len(rows)} 項差異。只比較採色、資源條件與相關專精欄位；不代表實際戰鬥表現。')
            if rows:tree.selection_set('0');selected()
            else:text('所比較欄位沒有差異；並不表示技能花費、採色或實機測試已正確。')
        except Exception as e:invalidate('無法比較：'+str(e))
    def selected(event=None):
        if not tree.selection():return
        row=rows[int(tree.selection()[0])];text(row['item']+'／'+row['field']+'\n左側：'+row['left']+'\n右側：'+row['right'])
    tree.bind('<<TreeviewSelect>>',selected)
    ttk.Button(footer,text='比較已儲存設定',command=run).pack(side='left')
    def watch():
        nonlocal timer
        timer=None
        if not w.winfo_exists():return
        if stamp:
            try:
                if hashlib.sha256(Path(app.app_config_path).read_bytes()).hexdigest()!=stamp:invalidate('磁碟設定已變更，請重新比較')
            except Exception:invalidate('無法確認磁碟設定，請重新比較')
        timer=w.after(1000,watch)
    def destroy(event):
        nonlocal timer
        if event.widget==w and timer is not None:w.after_cancel(timer);timer=None
    w.bind('<Destroy>',destroy,add='+');run();timer=w.after(1000,watch)
    return w
