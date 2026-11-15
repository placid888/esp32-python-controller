"""Opt-in async synthetic check and read-only local guide. Never starts transport."""
import json,os,sys,time,tempfile,subprocess
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,scrolledtext

def show_document(app,title,text):
    w=tk.Toplevel(app.root);w.title(title);w.geometry('760x640');w.minsize(600,420)
    footer=ttk.Frame(w,padding=10);footer.pack(side='bottom',fill='x')
    ttk.Button(footer,text='關閉',command=w.destroy).pack(side='right')
    area=scrolledtext.ScrolledText(w,wrap='word',font=('Microsoft JhengHei UI',11),padx=14,pady=14)
    area.pack(fill='both',expand=True,padx=8,pady=8);area.insert('1.0',text);area.configure(state='disabled')
    return w

def save_report(path,result):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='selfcheck-',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(result,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def validate_result(result):
    if result.get('format')!='resource-selfcheck-v1' or result.get('mode')!='offline_synthetic' or result.get('live_calibration') is not False or result.get('output_allowed') is not False:raise ValueError('不是有效的離線檢查結果')
    for key in ('total','passed','failed'):
        if type(result.get(key)) is not int or result[key]<0:raise ValueError('測試數量無效')
    if result['total']==0 or result['passed']+result['failed']!=result['total']:raise ValueError('測試總數不符')
    if not isinstance(result.get('failures'),list):raise ValueError('缺少錯誤清單')
    return result

def add_tools(app):
    frame=ttk.LabelFrame(app.advanced_parent,text='離線自我檢查',padding=10);frame.pack(fill='x',padx=10,pady=8)
    toolbar=ttk.Frame(frame);toolbar.pack(fill='x')
    status=tk.StringVar(value='尚未執行。只檢查模擬邏輯，不代表實機校準完成。')
    label=ttk.Label(frame,textvariable=status,wraplength=800,justify='left');label.pack(anchor='w',fill='x',pady=(8,0))
    frame.bind('<Configure>',lambda event:label.configure(wraplength=max(260,event.width-30)))
    proc=None;output=None;after=None;began=0.;latest=None;report_path=None
    def cleanup():
        nonlocal proc,output,after
        if after is not None:
            frame.after_cancel(after);after=None
        if proc is not None:
            if proc.poll() is None:proc.kill()
            proc.wait();proc=None
        if output is not None:output.close();output=None
    def details():
        if latest is None:return
        lines=['本次離線檢查報告','時間：'+str(latest.get('timestamp','')),
               f"通過 {latest['passed']}／失敗 {latest['failed']}／共 {latest['total']} 項",'',
               '範圍：兩職業0–100資源、1至0優先組合、缺少證據、讀值過期、中文原因與獵人校準阻擋。',
               '全部使用合成規則，不是目前技能實戰測試；未擷取畫面、不連ESP32、不送按鍵。',
               '實機校準未執行；冷卻、距離及技能可用性仍須另行整合與驗證。','']
        lines.extend('失敗：'+str(item.get('case',''))+'／'+str(item.get('error','')) for item in latest['failures'][:50])
        if len(latest['failures'])>50:lines.append('此處只列前50項，完整資料請看JSON紀錄。')
        if report_path:lines.extend(['','紀錄檔：'+str(report_path)])
        show_document(app,'離線自我檢查報告', '\n'.join(lines))
    def tick():
        nonlocal after,latest,report_path
        after=None
        if proc is None:return
        if proc.poll() is None:
            if time.monotonic()-began>15:
                cleanup();status.set('檢查逾時，未取得有效結果；不算通過。');run_button.configure(state='normal')
            else:after=frame.after(100,tick)
            return
        try:
            code=proc.returncode;output.seek(0);raw=output.read(4*1024*1024)
            if len(raw)>=4*1024*1024:raise ValueError('檢查結果過大')
            result=validate_result(json.loads(raw.decode('utf-8')))
            if code not in (0,1) or (code==0)!=(result['failed']==0):raise ValueError('程序退出狀態與測試結果不符')
            latest=result;report_path=None
            suffix=''
            try:
                destination=Path(app.app_config_path).parent/'diagnostics'/'resource_selfcheck_latest.json'
                save_report(destination,result);report_path=destination
            except Exception:suffix='\n測試結果已取得，但無法儲存紀錄；可查看本次報告。'
            status.set(f"離線檢查{'通過' if result['failed']==0 else '有失敗'}：{result['passed']} 通過／{result['failed']} 失敗。\n僅為模擬邏輯，不代表實機校準完成。"+suffix)
            detail_button.configure(state='normal')
        except Exception as e:status.set('檢查未完成，不算通過：'+str(e)[:180])
        finally:cleanup();run_button.configure(state='normal')
    def start():
        nonlocal proc,output,began,after,latest,report_path
        if proc is not None:return
        latest=None;report_path=None;detail_button.configure(state='disabled')
        try:
            output=tempfile.TemporaryFile(mode='w+b')
            proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).with_name('resource_selfcheck.py'))],stdout=output,stderr=output,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            began=time.monotonic();status.set('離線檢查執行中…不需要開魔獸，請稍候。');run_button.configure(state='disabled');after=frame.after(100,tick)
        except Exception as e:cleanup();status.set('無法啟動檢查：'+str(e)[:180]);run_button.configure(state='normal')
    run_button=ttk.Button(toolbar,text='一鍵離線自我檢查',command=start);run_button.pack(side='left')
    detail_button=ttk.Button(toolbar,text='查看本次報告…',command=details,state='disabled');detail_button.pack(side='left',padx=8)
    frame.bind('<Destroy>',lambda event:cleanup() if event.widget==frame else None,add='+')
    return frame
