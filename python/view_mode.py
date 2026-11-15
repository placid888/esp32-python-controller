"""Session-only presentation modes. Never changes config, transport or monitoring."""
import tkinter as tk
from tkinter import ttk
from pathlib import Path

def set_mode(app,mode):
    if mode not in ('simple','advanced'):raise ValueError('Unknown view mode')
    app._view_mode=mode
    if hasattr(app,'view_mode_var'):app.view_mode_var.set(mode)
    pages=getattr(app,'view_pages',{})
    if pages:
        if mode=='simple':app.main_tabs.select(pages['overview'])
        for key,page in pages.items():app.main_tabs.tab(page,state='normal' if key=='overview' or mode=='advanced' else 'hidden')
    for widget,visible_mode,options in getattr(app,'_view_widgets',[]):
        if not widget.winfo_exists():continue
        if mode==visible_mode:widget.pack(**options)
        else:widget.pack_forget()

def register(app,widget,visible_mode='advanced'):
    if not hasattr(app,'_view_widgets'):app._view_widgets=[]
    app._view_widgets.append((widget,visible_mode,widget.pack_info()))
    if getattr(app,'_view_mode','simple')!=visible_mode:widget.pack_forget()
    return widget

def show_tab(app,key):
    if key!='overview':set_mode(app,'advanced')
    app.main_tabs.select(app.view_pages[key])

def add_switch(app):
    row=ttk.Frame(app.root,padding=(14,0,14,8));row.pack(fill='x')
    app.view_mode_var=tk.StringVar(value='simple')
    ttk.Label(row,text='介面顯示：').pack(side='left')
    for mode,title in [('simple','簡易'),('advanced','進階')]:ttk.Radiobutton(row,text=title,variable=app.view_mode_var,value=mode,command=lambda m=mode:set_mode(app,m)).pack(side='left',padx=(0,8))
    def guide():
        from selfcheck_tools_ui import show_document
        from tkinter import messagebox
        try:text=Path(__file__).with_name('QUICK_START_zh-TW.txt').read_text(encoding='utf-8-sig')
        except Exception as e:messagebox.showerror('說明未取得',str(e),parent=app.root);return
        show_document(app,'新手操作說明',text)
    ttk.Button(row,text='新手說明…',command=guide).pack(side='left',padx=(0,12))
    state=tk.StringVar();label=ttk.Label(row,textvariable=state,wraplength=570);label.pack(side='left',fill='x',expand=True)
    row.bind('<Configure>',lambda event:label.configure(wraplength=max(250,event.width-380)))
    def refresh():
        if not row.winfo_exists():return
        controller=getattr(app,'controller',None)
        output='Dry Run／輸出封鎖' if getattr(controller,'output_mode','dry_run')=='dry_run' else 'UDP測試／可能輸出'
        connection='UDP已初始化' if getattr(controller,'is_open',False) else 'UDP未初始化'
        state.set(output+'；'+connection+'。切換介面不會停止監控或改變輸出模式。')
        row.after(750,refresh)
    refresh();return row
