"""Editable LCD wording, per-row size and Unicode settings. No HID commands."""
import copy
import json
import profile_store
import tkinter as tk
from tkinter import ttk

ROW_NAMES = {"title":"標題", "status":"待命狀態", "network":"IP／網路", "action":"動作名稱", "detail":"內容／按鍵", "saver":"螢幕保護"}
DIAGNOSTIC_SIZES = (16,20,24,28,32)
DIAGNOSTIC_ITEMS = ("KEY","CNT","RATE","HID","UDP","IP")
DEFAULT_ITEMS = ["KEY","CNT","RATE"]
DEFAULT_ROWS = {
    "title":{"text":"控制面板","size":16},
    "status":{"text":"狀態：待命","size":16},
    "network":{"text":"{ip}:{port}","size":16},
    "action":{"text":"{action}","size":16},
    "detail":{"text":"{detail}","size":32},
    "saver":{"text":"休息中","size":32},
}
DEFAULT_LABELS = {
    "tap":"點按", "press":"按住", "release":"放開", "click":"點擊",
    "move":"移動", "scroll":"捲動", "release_all":"全部放開", "lcd_test":"顯示測試",
    "lcd_config":"電源設定", "lcd_style":"文字設定", "lcd_labels":"字面設定",
    "key":"按鍵：", "mouse":"滑鼠：", "hold":"（按住）", "released":"（放開）",
    "move_detail":"移動：", "scroll_detail":"捲動：", "all_released":"全部放開",
    "settings_saved":"設定已套用", "test_message":"中文測試成功",
    "connecting":"Wi-Fi 連線中", "binding":"UDP 啟動中", "network_error":"UDP 任務未啟動",
}

def defaults():
    return {"rows":copy.deepcopy(DEFAULT_ROWS), "labels":copy.deepcopy(DEFAULT_LABELS), "diagnostic_size":24, "diagnostic_items":DEFAULT_ITEMS.copy()}

def validate(settings):
    size=settings.get("diagnostic_size",24)
    if type(size) is not int or size not in DIAGNOSTIC_SIZES:raise ValueError("診斷字級只能選 16、20、24、28、32 px")
    items=settings.get("diagnostic_items",DEFAULT_ITEMS)
    if not isinstance(items,list) or not items or any(not isinstance(k,str) or k not in DIAGNOSTIC_ITEMS for k in items) or len(items)!=len(set(items)):raise ValueError("至少勾選一項診斷資訊，且不可重複")
    rows=settings["rows"]; labels=settings["labels"]
    if set(rows)!=set(DEFAULT_ROWS): raise ValueError("LCD 欄位不完整")
    for key,row in rows.items():
        if type(row["size"]) is not int or row["size"] not in (16,32,48):raise ValueError("字級只能選 16、32、48 px")
        text=row["text"]
        if not isinstance(text,str) or len(text.encode("utf-8"))>96 or any(ord(c)<32 for c in text):raise ValueError("每欄最多 96 UTF-8 bytes；不能換行")
    total=sum(rows[k]["size"] for k in rows if k!="saver")
    if total>115:raise ValueError(f"主畫面五列字高合計 {total}px，超過 115px；請縮小其他列（文字留空仍保留高度）")
    if set(labels)!=set(DEFAULT_LABELS):raise ValueError("狀態文字欄位不完整")
    for text in labels.values():
        if not isinstance(text,str) or len(text.encode('utf-8'))>96 or any(ord(c)<32 for c in text):raise ValueError("狀態文字最多 96 bytes，不能換行")
    for command in commands(settings):
        if len(json.dumps(command,ensure_ascii=False,separators=(',',':')).encode())>1024:raise ValueError("文字總量超過 UDP 1024 bytes；請縮短狀態文字")
    return settings

def commands(settings):
    return [{"action":"lcd_style","rows":settings["rows"],"diagnostic_size":settings.get("diagnostic_size",24),"diagnostic_items":settings.get("diagnostic_items",DEFAULT_ITEMS)}, {"action":"lcd_labels","labels":settings["labels"]}]

def load(path):
    result=defaults()
    try:
        saved=profile_store.active(path).get('lcd_display',{})
        for group in ('rows','labels'):
            if isinstance(saved.get(group),dict):result[group].update(saved[group])
        size=saved.get("diagnostic_size",24)
        result["diagnostic_size"]=32 if type(size) is int and size>32 else size
        result["diagnostic_items"]=saved.get("diagnostic_items",DEFAULT_ITEMS.copy())
        validate(result)
    except (OSError,ValueError,KeyError,TypeError):return defaults()
    return result

class LcdEditor:
    def __init__(self,app):
        self.app=app; self.window=tk.Toplevel(app.root);self.window.title('LCD 文字與字級設定')
        self.window.geometry('780x760');self.window.minsize(740,700)
        frame=ttk.Frame(self.window,padding=12);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='LCD 240×135｜診斷字級 16 / 20 / 24 / 28 / 32 px',font=('',12,'bold')).pack(anchor='w')
        ttk.Label(frame,text='診斷只顯示勾選項目；固定字級放不下時分頁輪播，不會縮小。').pack(anchor='w',pady=(4,8))
        notebook=ttk.Notebook(frame);notebook.pack(fill='both',expand=True)
        main=ttk.Frame(notebook,padding=10);other=ttk.Frame(notebook,padding=10)
        notebook.add(main,text='內容與字級');notebook.add(other,text='動作與狀態字面')
        self.rows={};self.labels={}
        for col,text in enumerate(('顯示區域','顯示文字／模板','字高 px')):ttk.Label(main,text=text).grid(row=0,column=col,sticky='w',pady=(0,8))
        for i,(key,name) in enumerate(ROW_NAMES.items(),1):
            i += (key == 'saver')
            row=app.lcd_display['rows'][key];text=tk.StringVar(value=row['text']);size=tk.StringVar(value=str(row['size']))
            self.rows[key]=(text,size)
            ttk.Label(main,text=name).grid(row=i,column=0,sticky='w',padx=(0,10),pady=6)
            ttk.Entry(main,textvariable=text).grid(row=i,column=1,sticky='ew',pady=6)
            ttk.Combobox(main,textvariable=size,values=(16,32,48),state='readonly',width=5).grid(row=i,column=2,padx=(12,0),pady=6)
        self.diagnostic_size=tk.StringVar(value=str(app.lcd_display.get('diagnostic_size',24)))
        ttk.Label(main,text='診斷資訊').grid(row=6,column=0,sticky='w',pady=6)
        ttk.Label(main,text='依「診斷顯示項目」勾選，最高 32 px').grid(row=6,column=1,sticky='w')
        ttk.Combobox(main,textvariable=self.diagnostic_size,values=DIAGNOSTIC_SIZES,state='readonly',width=5).grid(row=6,column=2,padx=(12,0),pady=6)
        main.columnconfigure(1,weight=1)
        ttk.Label(main,text='模板：{ip}、{port} 僅用於網路列；{action}、{detail} 用於其他列。\n可直接填中文。留空隱藏文字，但仍保留該列高度。\n16px 一行約 14 個中文字；32px 約 7 個；48px 約 4 個。\n字庫不含 Emoji 與 CJK 擴充 B 以上罕字，缺字顯示替代符號。',justify='left').grid(row=8,column=0,columnspan=3,sticky='nw',pady=14)
        diagnostic=ttk.Frame(notebook,padding=10);notebook.add(diagnostic,text='診斷顯示項目')
        ttk.Label(diagnostic,text='至少選一項；未勾選的項目不顯示，也不保留空白列。').pack(anchor='w',pady=(0,10))
        self.diagnostic_items={}
        names={'KEY':'最後實際 HID 按鍵','CNT':'目前 KEY 的累積次數','RATE':'HID 執行速率','HID':'HID 累積次數','UDP':'有效 UDP 控制封包累積數','IP':'IP / Port'}
        for key in DIAGNOSTIC_ITEMS:
            var=tk.BooleanVar(value=key in app.lcd_display.get('diagnostic_items',DEFAULT_ITEMS));self.diagnostic_items[key]=var
            ttk.Checkbutton(diagnostic,text=f'{key} — {names[key]}',variable=var,command=self.update_layout_hint).pack(anchor='w',pady=5)
        presets=ttk.Frame(diagnostic);presets.pack(anchor='w',pady=12)
        for name,items in (('按鍵診斷',['KEY','CNT','RATE']),('通訊診斷',['UDP','HID','RATE']),('極簡診斷',['CNT','RATE'])):
            ttk.Button(presets,text=name,command=lambda items=items:self.set_diagnostic_items(items)).pack(side='left',padx=(0,8))
        self.layout_hint=tk.StringVar();ttk.Label(diagnostic,textvariable=self.layout_hint,wraplength=680).pack(anchor='w',pady=8)
        self.diagnostic_size.trace_add('write',lambda *_:self.update_layout_hint());self.update_layout_hint()
        canvas=tk.Canvas(other,highlightthickness=0);bar=ttk.Scrollbar(other,orient='vertical',command=canvas.yview)
        inner=ttk.Frame(canvas);item=canvas.create_window((0,0),window=inner,anchor='nw')
        canvas.configure(yscrollcommand=bar.set);canvas.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(item,width=e.width))
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        for i,key in enumerate(DEFAULT_LABELS):
            var=tk.StringVar(value=app.lcd_display['labels'][key]);self.labels[key]=var
            ttk.Label(inner,text=key,width=18).grid(row=i,column=0,sticky='w',pady=4)
            ttk.Entry(inner,textvariable=var).grid(row=i,column=1,sticky='ew',pady=4)
        inner.columnconfigure(1,weight=1)
        self.message=tk.StringVar(value='先儲存並套用，再按「中文顯示測試」。ESP32 需更新版韌體。')
        ttk.Label(frame,textvariable=self.message,wraplength=700).pack(fill='x',pady=8)
        buttons=ttk.Frame(frame);buttons.pack(fill='x')
        ttk.Button(buttons,text='恢復預設值',command=self.reset).pack(side='left')
        ttk.Button(buttons,text='中文顯示測試',command=self.test).pack(side='right')
        ttk.Button(buttons,text='儲存並套用',command=self.apply).pack(side='right',padx=8)
    def set_diagnostic_items(self,items):
        for k,v in self.diagnostic_items.items():v.set(k in items)
        self.update_layout_hint()
    def update_layout_hint(self):
        if not hasattr(self,'layout_hint'):return
        items=[k for k,v in self.diagnostic_items.items() if v.get()]
        if not items:self.layout_hint.set('請至少勾選一項；目前不能儲存。');return
        try:size=int(self.diagnostic_size.get())
        except ValueError:return
        columns=240//(size//2);capacity=135//size
        lengths={'KEY':8,'CNT':14,'RATE':17,'HID':14,'UDP':14,'IP':24}
        worst=sum((lengths[k]+columns-1)//columns for k in items)
        pages=(worst+capacity-1)//capacity
        self.layout_hint.set(f'{len(items)} 項，{size}px；每頁最多 {capacity} 列。'+('長數值／IP 最多約 '+str(pages)+' 頁，每 1.5 秒輪播；不縮字。' if pages>1 else '置中顯示，未選項目不占空間。'))
    def reset(self):
        data=defaults()
        for k,(text,size) in self.rows.items():text.set(data['rows'][k]['text']);size.set(str(data['rows'][k]['size']))
        self.diagnostic_size.set(str(data['diagnostic_size']))
        self.set_diagnostic_items(data["diagnostic_items"])
        for k,var in self.labels.items():var.set(data['labels'][k])
        self.message.set('已載入預設；按「儲存並套用」才會生效。')
    def apply(self):
        try:
            data={'rows':{k:{'text':v[0].get(),'size':int(v[1].get())} for k,v in self.rows.items()},'labels':{k:v.get() for k,v in self.labels.items()},'diagnostic_size':int(self.diagnostic_size.get()),'diagnostic_items':[k for k,v in self.diagnostic_items.items() if v.get()]}
            validate(data)
            profile_store.update_active(self.app.app_config_path, {'lcd_display':data})
            self.app.lcd_display=data
            queued=self.app.send_lcd_display_config()
            self.message.set('已儲存；兩筆設定已排入 UDP，請查看主視窗回覆。' if queued else '已儲存到電腦；尚未同步，初始化 UDP 後會再傳送。')
        except (OSError,ValueError,KeyError,TypeError) as exc:self.message.set(str(exc))
    def test(self):
        message=self.labels['test_message'].get()
        ok=self.app.controller.send_command({'action':'lcd_test','message':message})
        self.message.set('顯示測試已排入；請看 ESP32 LCD 與主視窗 ACK。' if ok else '未送出；請先初始化 UDP 通訊。')
