"""Read-only projection of sampling and saved advisory rules; never dispatches."""
import tkinter as tk
from tkinter import ttk
from skill_model import SKILL_PRIORITY

def rows_for(app):
    character=getattr(app,'selected_class',None)
    resource={'warrior':'怒氣','hunter':'集中值'}.get(character,'資源')
    rules=None
    try:
        if character=='warrior':
            from rage_rules import load
            low,high='min_rage','max_rage'
        elif character=='hunter':
            from focus_rules import load
            low,high='min_focus','max_focus'
        else:raise ValueError('unsupported')
        identity,rules=load(app.app_config_path)
        if identity[1:]!=(character,getattr(app,'selected_spec',None)):raise ValueError('context changed')
        profile=getattr(app,'active_profile_name',identity[0])
        if identity[0]!=profile:raise ValueError('profile changed')
    except Exception:rules=None
    nodes=getattr(app,'runtime_nodes',{})
    rows=[]
    for priority,node in enumerate(SKILL_PRIORITY,1):
        sample='已啟用／待測試' if nodes.get(node,{}).get('enabled',False) else '停用'
        if rules is None:name='待確認';kind='待確認';interval='無法確認';advisory='待確認'
        else:
            rule=rules[node];name=rule.get('name','').strip() or '未命名';kind=rule['kind']
            interval=f"{rule[low]}–{rule[high]}"
            advisory='已啟用／待測試' if rule['enabled'] else '停用'
        rows.append((node[6:],priority,name,kind,sample,interval,advisory))
    return resource,rows

def summary(app):
    frame=ttk.LabelFrame(app.overview_body,text='技能概覽（設定狀態，不是即時技能可用性）',padding=10)
    frame.pack(fill='x',padx=10,pady=8)
    ttk.Label(frame,text='採色開關與資源提示是兩套設定；任一啟用都不代表技能可施放。此表顯示已儲存的資源條件。',wraplength=860).pack(anchor='w',pady=(0,8))
    table=ttk.Frame(frame);table.pack(fill='x')
    tree=ttk.Treeview(table,columns=('key','priority','name','kind','sample','resource','advisory'),show='headings',height=10)
    columns=[('key','按鍵',55),('priority','優先',55),('name','技能名稱',160),('kind','分類',110),('sample','採色設定',155),('resource','資源區間',110),('advisory','資源提示',155)]
    for name,title,width in columns:
        tree.heading(name,text=title);tree.column(name,width=width,minwidth=width,anchor='w',stretch=name=='name')
    tree.pack(fill='x')
    scroll=ttk.Scrollbar(table,orient='horizontal',command=tree.xview);scroll.pack(fill='x');tree.configure(xscrollcommand=scroll.set)
    from view_mode import register
    ttk.Label(frame,text='要編輯名稱／資源條件或採色，請切到「技能與採色」頁。此表只顯示已儲存設定。',wraplength=860).pack(anchor='w',pady=(8,0))
    from skill_flow_ui import open_preview
    analysis=ttk.LabelFrame(app.advanced_parent,text='技能分析工具（唯讀與模擬）',padding=10);analysis.pack(fill='x',padx=10,pady=8)
    analysis_actions=ttk.Frame(analysis);analysis_actions.pack(fill='x')
    ttk.Button(analysis_actions,text='技能流程預覽…',command=lambda:open_preview(app)).pack(side='left')
    from spec_compare_ui import open_compare
    ttk.Button(analysis_actions,text='專精差異比較…',command=lambda:open_compare(app)).pack(side='left',padx=8)
    from rage_monitor_ui import open_resource_simulation
    ttk.Button(analysis_actions,text='進階逐格訊號模擬…',command=lambda:getattr(app,'_resource_simulation_callback',open_resource_simulation)(app)).pack(side='left')
    ttk.Label(analysis,text='流程預覽用來理解優先順序與原因；逐格訊號模擬供細部核對。兩者都使用假資料，不會按鍵。',wraplength=900).pack(anchor='w',pady=(6,0))
    app.overview_conditions=tk.StringVar(value='目標：未監控　　戰鬥：未監控')
    ttk.Label(frame,textvariable=app.overview_conditions).pack(anchor='w',pady=(6,0))
    register(app,frame)
    last=None
    def refresh():
        nonlocal last
        if not frame.winfo_exists():return
        resource,rows=rows_for(app)
        state=(resource,rows)
        if state!=last:
            tree.heading('resource',text=resource+'區間');tree.heading('advisory',text=resource+'提示')
            for values,node in zip(rows,SKILL_PRIORITY):
                if tree.exists(node):tree.item(node,values=values)
                else:tree.insert('','end',iid=node,values=values)
            last=state
        c=getattr(app,'current_conditions',{})
        def label(n):return ('符合' if c.get(n) else '不符合') if getattr(app,'is_running',False) and n in c else '未監控'
        app.overview_conditions.set('目標：'+label('Node_Target')+'　　戰鬥：'+label('Node_Combat'))
        frame.after(1000,refresh)
    refresh()
    return tree
