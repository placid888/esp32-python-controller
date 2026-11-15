"""Explicit manual checklist UI. Reports never count as automated calibration."""
import tkinter as tk
from tkinter import ttk,messagebox,scrolledtext
import manual_test_checklist as model

def open_checklist(app):
    old=getattr(app,'manual_checklist_window',None)
    if old is not None and old.winfo_exists():old.lift();return old
    w=tk.Toplevel(app.root);app.manual_checklist_window=w;w.title('待實測清單 — 手動回報，不是程式驗證');w.geometry('900x740');w.minsize(820,680)
    footer=ttk.Frame(w,padding=10);footer.pack(side='bottom',fill='x')
    body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
    ttk.Label(body,text='下次進遊戲再測，現在不需要操作',font=('Microsoft JhengHei UI',14,'bold')).pack(anchor='w')
    ttk.Label(body,text='清單預設全部待測。手動回報不會改變校準標記、技能開關或輸出模式；不用為填清單啟動UDP。',wraplength=820).pack(anchor='w',pady=6)
    heading=tk.StringVar();ttk.Label(body,textvariable=heading,wraplength=820).pack(anchor='w',pady=4)
    table=ttk.Frame(body);table.pack(fill='both',expand=True,pady=6)
    tree=ttk.Treeview(table,columns=('title','status','time'),show='headings',height=10,selectmode='browse')
    for col,title,width in [('title','待實測項目',250),('status','手動紀錄狀態',310),('time','回報時間',230)]:tree.heading(col,text=title);tree.column(col,width=width,minwidth=width,anchor='w',stretch=col=='title')
    y=ttk.Scrollbar(table,orient='vertical',command=tree.yview);y.pack(side='right',fill='y');x=ttk.Scrollbar(table,orient='horizontal',command=tree.xview);x.pack(side='bottom',fill='x');tree.configure(yscrollcommand=y.set,xscrollcommand=x.set);tree.pack(fill='both',expand=True)
    detail=tk.StringVar();ttk.Label(body,textvariable=detail,wraplength=820,justify='left').pack(anchor='w',pady=6)
    line=ttk.Frame(body);line.pack(fill='x');ttk.Label(line,text='手動狀態：').pack(side='left');status=tk.StringVar(value='待測');ttk.Combobox(line,textvariable=status,values=model.STATUSES,state='readonly',width=24).pack(side='left')
    ttk.Label(body,text='備註（例如遊戲值／估計值、格號、使用預覽或實際組隊，最多1000字）').pack(anchor='w',pady=(6,2))
    note=scrolledtext.ScrolledText(body,height=4,wrap='word',font=('Microsoft JhengHei UI',10));note.pack(fill='x')
    info=tk.StringVar(value='尚未載入');ttk.Label(body,textvariable=info,wraplength=820).pack(anchor='w',pady=6)
    identity=None;fingerprint=None;items={};current=None;baseline=('待測','');timer=None;suppress=False
    def dirty():return (status.get(),note.get('1.0','end-1c'))!=baseline
    def discard():return not dirty() or messagebox.askyesno('未儲存的手動備註','放棄這次尚未記錄的狀態與備註？',parent=w,default='no')
    def app_context(expected):
        if expected[1:]!=(getattr(app,'selected_class',None),getattr(app,'selected_spec',None)) or expected[0]!=getattr(app,'active_profile_name',expected[0]):raise ValueError('角色切換中，請稍後重載')
    def choose(event=None):
        nonlocal current,baseline,suppress
        if suppress or not tree.selection():return
        target=tree.selection()[0]
        if target==current:return
        if target!=current and current is not None and not discard():
            suppress=True;tree.selection_set(current);suppress=False;return
        current=target;item=items[target];record=item['record'];detail.set(item['steps']+'\n預期：'+item['expected'])
        status.set('待測' if item['stale'] or record is None else record['status']);note.delete('1.0','end');note.insert('1.0',record['note'] if record else '')
        baseline=(status.get(),note.get('1.0','end-1c'))
    def reload():
        nonlocal identity,fingerprint,items,current,suppress
        if current is not None and not discard():return
        try:
            new_identity,new_fingerprint,rows=model.rows(app.app_config_path);app_context(new_identity)
            identity,fingerprint=new_identity,new_fingerprint;items={item['id']:item for item in rows};current=None;suppress=True;tree.delete(*tree.get_children())
            for item in rows:
                record=item['record'];tree.insert('','end',iid=item['id'],values=(item['title'],item['status'],record.get('updated_at','') if record else '未記錄'))
            suppress=False;heading.set('／'.join(identity)+'；資料與技能設定分開保存。');save_button.configure(state='normal');info.set('沒有自動完成任何項目。程式測試與手動回報是兩回事。')
            if rows:tree.selection_set(rows[0]['id']);choose()
        except Exception as e:
            suppress=False;save_button.configure(state='disabled');info.set('無法載入：'+str(e))
    def save():
        nonlocal baseline
        try:
            if current is None:raise ValueError('請先選擇項目')
            app_context(identity)
            text=note.get('1.0','end-1c')
            if len(text)>1000:raise ValueError('備註最多1000字')
            if not messagebox.askyesno('儲存手動回報',items[current]['title']+'\n狀態：'+status.get()+'\n這不是程式驗證，不會解除任何校準限制。是否記錄？',parent=w,default='no'):return
            record=model.save(app.app_config_path,identity,fingerprint,current,status.get(),text,items[current]['record'])
            items[current]['record']=record;items[current]['stale']=False;items[current]['status']=record['status'];tree.item(current,values=(items[current]['title'],record['status'],record['updated_at']));baseline=(status.get(),text);info.set('手動紀錄已儲存；沒有變更技能設定或校準狀態。')
        except Exception as e:info.set('未儲存：'+str(e))
    def export():
        try:
            app_context(identity)
            if model.scope(app.app_config_path)!=(identity,fingerprint):raise ValueError('設定已變更，請先重載')
            path=model.export_report(app.app_config_path);info.set('已匯出已儲存的手動清單（不含未儲存備註）：'+str(path))
        except Exception as e:info.set('無法匯出：'+str(e))
    def close():
        if discard():w.destroy()
    ttk.Button(footer,text='重新載入目前專精',command=reload).pack(side='left')
    ttk.Button(footer,text='匯出已儲存清單…',command=export).pack(side='left',padx=8)
    save_button=ttk.Button(footer,text='儲存此項手動回報',command=save);save_button.pack(side='left')
    ttk.Button(footer,text='關閉',command=close).pack(side='right')
    tree.bind('<<TreeviewSelect>>',choose);w.protocol('WM_DELETE_WINDOW',close)
    def watch():
        nonlocal timer
        timer=None
        if not w.winfo_exists():return
        try:
            current_scope=model.scope(app.app_config_path)
            if current_scope!=(identity,fingerprint):
                save_button.configure(state='disabled');info.set('角色或設定已變更，舊回報不適用；請重新載入。')
                for item_id in tree.get_children():
                    values=list(tree.item(item_id)['values']);values[1]='設定已變更，請重載';tree.item(item_id,values=values)
        except Exception:save_button.configure(state='disabled');info.set('目前設定無法確認，請重載；沒有標記完成。')
        timer=w.after(1000,watch)
    def destroyed(event):
        nonlocal timer
        if event.widget==w and timer is not None:w.after_cancel(timer);timer=None
    w.bind('<Destroy>',destroyed,add='+');reload();timer=w.after(1000,watch);return w
