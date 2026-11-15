"""Manual flow explorer only. No capture, saving, transport or input dispatch."""
import tkinter as tk
from tkinter import ttk,messagebox,scrolledtext
import copy
from skill_model import SKILL_PRIORITY
from skill_flow import modules,demo_rules,preview
VALUES=('未知','符合','不符合')
BOOL={'未知':None,'符合':True,'不符合':False}
FIELDS=(('visual_match','採色'),('cooldown_ready','冷卻'),('in_range','距離'),('usable','技能可用'))

def open_preview(app):
    old=getattr(app,'skill_flow_window',None)
    if old is not None and old.winfo_exists():old.lift();return old
    character=getattr(app,'selected_class',None)
    try:rule_module,_,resource,label=modules(character)
    except ValueError as e:messagebox.showinfo('先選擇職業',str(e),parent=app.root);return
    origin=(character,getattr(app,'selected_spec',None))
    w=tk.Toplevel(app.root);app.skill_flow_window=w;w.title('技能流程預覽 — 全部為模擬，不送按鍵');w.geometry('920x790');w.minsize(860,760)
    footer=ttk.Frame(w,padding=(12,8));footer.pack(side='bottom',fill='x')
    body=ttk.Frame(w,padding=12);body.pack(fill='both',expand=True)
    ttk.Label(body,text='技能流程預覽',font=('Microsoft JhengHei UI',15,'bold')).pack(anchor='w')
    ttk.Label(body,text='所有輸入都是模擬值，不讀取遊戲、不儲存、不按鍵。分類只是標記，不會自動改變條件或優先順序。',wraplength=860).pack(anchor='w',pady=(4,8))
    source=tk.StringVar(value='尚未載入');ttk.Label(body,textvariable=source,wraplength=860,font=('Microsoft JhengHei UI',10,'bold')).pack(anchor='w')
    note=tk.StringVar(value='');ttk.Label(body,textvariable=note,wraplength=860).pack(anchor='w',pady=(2,6))
    tools=ttk.Frame(body);tools.pack(fill='x',pady=(0,6))
    controls=ttk.Frame(body);controls.pack(fill='x',pady=4)
    ttk.Label(controls,text='模擬'+label).pack(side='left');value=tk.StringVar(value='50');entry=ttk.Entry(controls,textvariable=value,width=5);entry.pack(side='left',padx=6)
    gates={}
    for name,title in (('target','目標'),('enemy','敵方'),('combat','戰鬥')):
        ttk.Label(controls,text=title).pack(side='left',padx=(8,2));v=tk.StringVar(value='未知');gates[name]=v
        ttk.Combobox(controls,textvariable=v,values=VALUES,state='readonly',width=6).pack(side='left')
    scenario_bar=ttk.Frame(body);scenario_bar.pack(fill='x',pady=(5,0))
    scenario_note=tk.StringVar(value='一鍵情境會重設假狀態，不改動已儲存的規則或啟用狀態。')
    ttk.Label(body,textvariable=scenario_note,wraplength=860).pack(anchor='w',pady=(3,0))
    table=ttk.Frame(body);table.pack(fill='both',expand=True,pady=(6,8))
    tree=ttk.Treeview(table,columns=('key','name','kind','interval','state'),show='headings',height=10,selectmode='browse')
    for name,title,width in [('key','按鍵／順序',85),('name','技能名稱',245),('kind','分類',125),('interval',label+'區間',100),('state','模擬判斷',180)]:
        tree.heading(name,text=title);tree.column(name,width=width,minwidth=width,stretch=name=='name',anchor='w')
    horizontal=ttk.Scrollbar(table,orient='horizontal',command=tree.xview);horizontal.pack(side='bottom',fill='x')
    vertical=ttk.Scrollbar(table,orient='vertical',command=tree.yview);vertical.pack(side='right',fill='y')
    tree.configure(xscrollcommand=horizontal.set,yscrollcommand=vertical.set);tree.pack(side='left',fill='both',expand=True)
    editor=ttk.LabelFrame(body,text='選取一格，修改該格的假狀態',padding=8);editor.pack(fill='x')
    signals={n:{field:None for field,_ in FIELDS} for n in SKILL_PRIORITY}
    field_vars={};rules=None;identity=None;mode=None;latest=None;timer=None;interactive=False
    for col,(field,title) in enumerate(FIELDS):
        ttk.Label(editor,text=title).grid(row=0,column=col*2,padx=(0,4),sticky='w')
        v=tk.StringVar(value='未知');field_vars[field]=v
        combo=ttk.Combobox(editor,textvariable=v,values=VALUES,state='readonly',width=6);combo.grid(row=0,column=col*2+1,padx=(0,12));combo.bind('<<ComboboxSelected>>',lambda event:apply_selected())
    detail=scrolledtext.ScrolledText(body,height=4,wrap='word',font=('Microsoft JhengHei UI',10));detail.pack(fill='x',pady=(8,4));detail.configure(state='disabled')
    summary=tk.StringVar(value='尚未預覽');ttk.Label(body,textvariable=summary,wraplength=860).pack(anchor='w',pady=(2,4))
    def show_detail(text):
        detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',text);detail.configure(state='disabled')
    def same_context():
        if (getattr(app,'selected_class',None),getattr(app,'selected_spec',None))!=origin:return False
        current,_=rule_module.load(app.app_config_path)
        if current[0]!=getattr(app,'active_profile_name',current[0]):return False
        return identity is None or current==identity
    def invalidate(message):
        nonlocal latest
        from editing_status import clear_simulation
        if identity is not None:clear_simulation(app,identity)
        latest=None;tree.delete(*tree.get_children());summary.set(message+'；無有效候選，不送按鍵。');show_detail(message)
    def selected():
        choices=tree.selection();return choices[0] if choices else None
    def selection_changed(event=None):
        n=selected()
        if n is None:return
        for field,v in field_vars.items():v.set({None:'未知',True:'符合',False:'不符合'}[signals[n][field]])
        if latest:
            row=next(row for row in latest['rows'] if row['node']==n)
            show_detail('按鍵'+n[6:]+'／'+row['state']+'\n'+'\n'.join('• '+reason for reason in row['reasons']))
    def update():
        nonlocal latest
        try:
            if rules is None:raise ValueError('請先載入已儲存設定或示範資料')
            if not same_context():raise ValueError('角色或設定檔已切換，請關閉後重新開啟預覽')
            raw=value.get().strip()
            if not raw.isascii() or not raw.isdecimal():raise ValueError(label+'需為0至100整數')
            latest=preview(character,rules,int(raw),{k:BOOL[v.get()] for k,v in gates.items()},signals)
            if interactive:
                from editing_status import record_simulation
                record_simulation(app,identity,rules,latest,'demo' if mode=='demo' else 'saved')
            for row in latest['rows']:
                n=row['node'];values=(n[6:],row['name'],row['kind'],row['interval'],row['state'])
                if tree.exists(n):tree.item(n,values=values)
                else:tree.insert('','end',iid=n,values=values)
            if not tree.selection():tree.selection_set('Skill_1')
            candidate=latest['candidate'];summary.set(('模擬候選：按鍵'+candidate[6:] if candidate else '沒有完整符合的技能')+'；只解釋本次假條件，不送按鍵。')
            selection_changed()
        except Exception as e:invalidate(str(e))
    def apply_selected():
        nonlocal interactive
        interactive=True
        n=selected()
        if n is not None:
            signals[n]={k:BOOL[v.get()] for k,v in field_vars.items()};update()
    def reset_signals(state):
        for n in signals:signals[n]={field:state for field,_ in FIELDS}
        for v in gates.values():v.set({None:'未知',True:'符合'}[state])
    def load_saved():
        nonlocal rules,identity,mode,interactive
        try:
            if (getattr(app,'selected_class',None),getattr(app,'selected_spec',None))!=origin:raise ValueError('角色已切換，請重新開啟')
            current,saved=rule_module.load(app.app_config_path)
            if current[1:]!=origin or current[0]!=getattr(app,'active_profile_name',current[0]):raise ValueError('角色或設定檔切換中，請重新開啟')
            identity=current;rules=copy.deepcopy(saved);mode='saved';interactive=False;reset_signals(None)
            scenario_note.set('一鍵情境會重設假狀態，不改已儲存規則；沒有技能可先載入假資料示範。')
            source.set('已儲存設定快照：'+'／'.join(identity)+'（條件仍全部是手動假資料）')
            note.set('修改條件設定後，請按「重新讀取已儲存設定」。預設未知會阻擋；這不是實機測試。')
            update()
        except Exception as e:rules=None;invalidate(str(e))
    def load_demo():
        nonlocal rules,identity,mode,interactive
        try:
            current,_=rule_module.load(app.app_config_path)
            if current[1:]!=origin or (getattr(app,'selected_class',None),getattr(app,'selected_spec',None))!=origin:raise ValueError('角色已切換，請重新開啟')
            if current[0]!=getattr(app,'active_profile_name',current[0]):raise ValueError('設定檔切換中，請重新開啟')
            identity=current;rules=demo_rules(character);mode='demo';interactive=True;reset_signals(True);value.set('50')
            scenario_note.set('假資料示範已載入；以下情境不會儲存或按鍵。')
            source.set('示範假資料：五種分類，目標／戰鬥／技能狀態預設全部「符合」')
            note.set('0–39與40–100只是教學假區間，不是真實技能花費！改成20看產資源；80看消資源。防禦／位移／中斷不會自動觸發。')
            update()
        except Exception as e:rules=None;invalidate(str(e))
    def all_unknown():
        nonlocal interactive
        interactive=True;reset_signals(None);scenario_note.set('全部假狀態已設為未知；不代表遊戲現在狀態。');update()
    def apply_scenario(name):
        nonlocal interactive
        interactive=True
        try:
            if rules is None or not same_context():raise ValueError('請在目前角色重新載入設定或示範資料')
            from skill_scenarios import scenario
            selected_node=selected() or 'Skill_1'
            fixture=scenario(name,selected_node)
            for node,evidence in fixture['signals'].items():signals[node]=evidence
            for gate,state in fixture['gates'].items():gates[gate].set({None:'未知',True:'符合',False:'不符合'}[state])
            value.set(str(fixture['value']))
            scenario_note.set('假情境：'+name+'（按鍵'+selected_node[6:]+'）；除指定阻擋外，其餘假證據設為符合（全部未知情境除外），不讀取遊戲。')
            update()
            if tree.exists(selected_node):tree.selection_set(selected_node);selection_changed()
        except Exception as e:invalidate(str(e))
    from skill_scenarios import SCENARIOS
    for scenario_name in SCENARIOS:
        ttk.Button(scenario_bar,text=scenario_name,command=lambda name=scenario_name:apply_scenario(name)).pack(side='left',padx=(0,5))
    ttk.Button(tools,text='重新讀取已儲存設定',command=load_saved).pack(side='left')
    ttk.Button(tools,text='載入假資料示範',command=load_demo).pack(side='left',padx=8)
    ttk.Button(tools,text='全部假狀態設為未知',command=all_unknown).pack(side='left')
    def request_update():
        nonlocal interactive
        interactive=True;update()
    ttk.Button(footer,text='更新預覽（不按鍵）',command=request_update).pack(side='left')
    ttk.Button(footer,text='關閉',command=w.destroy).pack(side='right')
    tree.bind('<<TreeviewSelect>>',selection_changed);entry.bind('<Return>',lambda event:request_update())
    for widget in controls.winfo_children():
        if isinstance(widget,ttk.Combobox):widget.bind('<<ComboboxSelected>>',lambda event:request_update())
    def watch():
        nonlocal timer
        timer=None
        if not w.winfo_exists():return
        try:
            if not same_context():invalidate('角色或設定檔已切換，請關閉後重新開啟預覽')
        except Exception:invalidate('無法確認目前設定，請重新讀取')
        timer=w.after(750,watch)
    def destroyed(event):
        nonlocal timer
        if event.widget==w and timer is not None:w.after_cancel(timer);timer=None
    value.trace_add('write',lambda *args:invalidate('模擬數值已變更，請按更新預覽'))
    w.bind('<Destroy>',destroyed,add='+');load_saved();timer=w.after(750,watch)
    return w
