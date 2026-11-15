"""Presentation only: tabs and saved-setting summary, no dispatch changes."""
import tkinter as tk
from tkinter import ttk
from skill_model import SKILL_PRIORITY

def shell(app):
    header=ttk.Frame(app.root,padding=(14,10));header.pack(fill='x')
    ttk.Label(header,text='角色控制台',font=('Microsoft JhengHei UI',17,'bold')).pack(side='left')
    ttk.Label(header,text='先確認角色，再查看技能；硬體工具在進階頁。').pack(side='left',padx=16)
    tk.Button(header,text='停止監控與 UDP',command=app.stop_all,bg='#a51d27',fg='white',padx=12,pady=5).pack(side='right')
    from view_mode import add_switch,set_mode
    add_switch(app)
    app._view_mode='simple';app._view_widgets=[]
    app.main_tabs=ttk.Notebook(app.root);app.main_tabs.pack(fill='both',expand=True,padx=10,pady=(0,10))
    canvases={};bodies={};app.view_pages={}
    for key,title in [('overview','角色與狀態'),('skills','技能與採色'),('advanced','進階工具')]:
        page=ttk.Frame(app.main_tabs);app.main_tabs.add(page,text=title);app.view_pages[key]=page
        canvas=tk.Canvas(page,highlightthickness=0);bar=ttk.Scrollbar(page,orient='vertical',command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
        body=ttk.Frame(canvas);item=canvas.create_window((0,0),window=body,anchor='nw')
        body.bind('<Configure>',lambda e,c=canvas:c.configure(scrollregion=c.bbox('all')))
        canvas.bind('<Configure>',lambda e,c=canvas,i=item:c.itemconfigure(i,width=e.width))
        canvases[key]=canvas;bodies[key]=body
    def wheel(e):
        current=app.main_tabs.index(app.main_tabs.select());c=list(canvases.values())[current]
        c.yview_scroll(int(-e.delta/120),'units')
    app.root.bind('<MouseWheel>',wheel,add='+')
    app.overview_body=bodies['overview'];app.skills_body=bodies['skills'];app.advanced_body=bodies['advanced']
    app.profile_parent=app.overview_body;app.character_parent=app.overview_body
    app.advanced_parent=app.advanced_body;app.rage_controls_parent=app.overview_body
    app.body=app.advanced_body;app.body_canvas=canvases['advanced']
    def tab_changed(event):
        if app.main_tabs.select()!=str(app.view_pages['overview']) and app._view_mode=='simple':set_mode(app,'advanced')
    app.main_tabs.bind('<<NotebookTabChanged>>',tab_changed)
    set_mode(app,'simple')

def summary(app):
    from skill_overview_ui import summary as render
    return render(app)
