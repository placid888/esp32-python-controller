"""Class-aware presentation and truthful saved-setting progress. No dispatch."""
from tkinter import ttk
from skill_model import SKILL_PRIORITY
from resource_calibration_ui import status_text

def progress_rows(app):
    character=getattr(app,'selected_class',None)
    resource={'warrior':'怒氣','hunter':'集中值'}.get(character,'資源')
    identity=(getattr(app,'active_profile_name',None),character,getattr(app,'selected_spec',None))
    heading,detail=status_text(character,identity=identity,config_path=app.app_config_path)
    state='已完成' if '已完成' in heading else ('部分驗證' if '滿值已核對' in heading else '待校準')
    nodes=getattr(app,'runtime_nodes',{})
    enabled=sum(bool(nodes.get(n,{}).get('enabled',False)) for n in SKILL_PRIORITY)
    configured=sum(bool(nodes.get(n,{}).get('enabled',False)) for n in ('Node_Target','Node_Combat'))
    rows=[(resource+'讀值驗證',state,detail),
          ('目標／戰鬥採色','待測試',f'{configured}/2 項已啟用；啟用不等於採色已驗證。'),
          ('技能格設定','待測試' if enabled else '待設定',f'{enabled}/10 格已啟用；技能可用性尚未驗證。')]
    try:
        if character=='warrior':from rage_rules import load
        elif character=='hunter':from focus_rules import load
        else:raise ValueError('請先選擇職業')
        identity,rules=load(app.app_config_path)
        if identity[1]!=character or identity[2]!=getattr(app,'selected_spec',None):raise ValueError('角色切換中，稍後更新')
        count=sum(bool(r.get('enabled')) for r in rules.values())
        rows.append((resource+'條件設定','待測試' if count else '待設定',f'{count}/10 格已儲存啟用；只提供提示。'))
    except Exception:
        rows.append((resource+'條件設定','待確認','暫時無法確認已儲存條件；請開啟條件設定檢查。'))
    rows.extend([('冷卻／距離／技能可用性','未完成','尚未整合，不會因資源足夠就認定可以施放。'),
                 ('資源功能自動按鍵','未接入','怒氣／集中值功能僅監控與提示；不控制 ESP32。')])
    return resource,rows

def add_overview(app,monitor,editor,simulation):
    app._resource_simulation_callback=simulation
    parent=getattr(app,'rage_controls_parent',app.root)
    section=ttk.LabelFrame(parent,text='資源監控',padding=10);section.pack(fill='x',padx=10,pady=8)
    toolbar=ttk.Frame(section);toolbar.pack(fill='x')
    read=ttk.Button(toolbar,command=lambda:monitor(app));read.pack(side='left')
    from view_mode import register
    settings_section=ttk.LabelFrame(app.skills_body,text='技能名稱與資源條件',padding=10);settings_section.pack(fill='x',padx=10,pady=8)
    settings=ttk.Button(settings_section,command=lambda:editor(app));settings.pack(anchor='w')
    ttk.Label(settings_section,text='技能名稱、分類與資源區間在此設定；採色座標與亮暗比對使用下方原有工具。儲存與啟用是不同步驟。',wraplength=900).pack(anchor='w',pady=(6,0))
    from skill_wizard_ui import open_wizard
    ttk.Button(toolbar,text='技能設定精靈…',command=lambda:open_wizard(app)).pack(side='left',padx=8)
    from manual_checklist_ui import open_checklist
    ttk.Button(toolbar,text='待實測清單…',command=lambda:open_checklist(app)).pack(side='left')
    ttk.Label(section,text='只顯示目前職業的資源。讀值驗證與技能測試分開計算。',wraplength=800).pack(anchor='w',pady=(8,0))
    editing=ttk.LabelFrame(parent,text='編輯與測試狀態',padding=10);editing.pack(fill='x',padx=10,pady=8)
    editing_label=ttk.Label(editing,wraplength=850,justify='left');editing_label.pack(anchor='w',fill='x')
    editing.bind('<Configure>',lambda event:editing_label.configure(wraplength=max(260,event.width-30)))
    progress=ttk.LabelFrame(parent,text='設定進度總覽',padding=10);progress.pack(fill='x',padx=10,pady=8)
    ttk.Label(progress,text='「已完成」只代表該項驗證，不代表整套作戰功能完成。',wraplength=800).pack(anchor='w',pady=(0,8))
    compact=ttk.Label(progress,wraplength=830,justify='left');compact.pack(anchor='w',pady=6);register(app,compact,'simple')
    grid=ttk.Frame(progress);grid.pack(fill='x');grid.columnconfigure(2,weight=1)
    for col,text in enumerate(('項目','狀態','說明')):
        ttk.Label(grid,text=text,font=('Microsoft JhengHei UI',10,'bold')).grid(row=0,column=col,sticky='w',padx=(0,12),pady=(0,6))
    cells=[]
    for row in range(1,7):
        group=[]
        for col in range(3):
            label=ttk.Label(grid,wraplength=490 if col==2 else 180)
            label.grid(row=row,column=col,sticky='nw',padx=(0,12),pady=6);group.append(label)
        cells.append(group)
    def resize(event):
        width=max(230,event.width-340)
        for group in cells:group[2].configure(wraplength=width)
    grid.bind('<Configure>',resize)
    register(app,grid)
    reminders=ttk.LabelFrame(parent,text='設定提醒（不會自動更改設定）',padding=10);reminders.pack(fill='x',padx=10,pady=8)
    hint=ttk.Label(reminders,wraplength=850,justify='left');hint.pack(anchor='w',fill='x')
    reminders.bind('<Configure>',lambda event:hint.configure(wraplength=max(260,event.width-30)))
    from selfcheck_tools_ui import add_tools
    add_tools(app)
    from settings_backup_ui import add_controls
    add_controls(app)
    last=None
    def refresh():
        nonlocal last
        if not section.winfo_exists():return
        from editing_status import status_lines
        editing_label.configure(text='\n'.join(status_lines(app)))
        from settings_hints import warnings_for
        hint.configure(text='\n'.join('• '+message for message in warnings_for(app)))
        resource,rows=progress_rows(app)
        compact.configure(text=rows[0][0]+'：'+rows[0][1]+'\n'+rows[0][2]+'\n技能整合與實機技能測試仍未完成；不會自動按鍵。')
        current=(resource,rows)
        if current!=last:
            section.configure(text=resource+'監控')
            read.configure(text=resource+'唯讀監控…');settings.configure(text=resource+'條件設定…')
            for group,values in zip(cells,rows):
                for label,text in zip(group,values):label.configure(text=text)
            last=current
        section.after(1000,refresh)
    refresh()
    return section,progress
