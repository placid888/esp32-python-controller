"""Explicit local backup/restore UI. Restore requires idle app and confirmation."""
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from pathlib import Path
import settings_backup as backup

def blocked(app):
    controller=getattr(app,'controller',None);worker=getattr(controller,'_thread',None)
    if (getattr(app,'is_running',False) or getattr(app,'is_tracking',False)
        or getattr(app,'dry_start_after_id',None) is not None
        or getattr(controller,'is_open',False) or (worker and worker.is_alive())):
        return '請先停止監控、UDP、座標採集及待啟動的測試。'
    if any(job.alive for job in getattr(app,'calibration_jobs',[])):return '請先停止校準工作。'
    if any(isinstance(w,tk.Toplevel) and w.winfo_exists() for w in app.root.winfo_children()):
        return '請先關閉監控小窗、設定編輯器與模擬視窗，避免還原後舊視窗覆寫設定。'
    return None

def add_controls(app):
    frame=ttk.LabelFrame(app.advanced_parent,text='設定備份與還原',padding=10);frame.pack(fill='x',padx=10,pady=8)
    status=tk.StringVar(value='備份範圍：全部 Profile、戰士／獵人專精、採色與資源條件；不包含魔獸插件、程式碼或韌體。')
    line=ttk.Frame(frame);line.pack(fill='x')
    folder=Path(app.app_config_path).parent/'settings-backups'
    def create():
        try:
            path=backup.create_backup(app.app_config_path,folder)
            status.set('備份已完成：'+str(path)+'\n只備份已儲存的設定，不包含編輯器尚未儲存內容。')
        except Exception as e:messagebox.showerror('備份失敗',str(e),parent=app.root)
    def restore():
        reason=blocked(app)
        if reason:messagebox.showwarning('暫時不能還原',reason,parent=app.root);return
        selected=filedialog.askopenfilename(parent=app.root,title='選擇控制台設定備份',initialdir=str(folder if folder.exists() else folder.parent),filetypes=[('控制台備份','*.wowbackup.json')])
        if not selected:return
        safety=None;restored_hash=None
        try:
            raw=backup.read_backup(selected)
            if not messagebox.askyesno('確認還原全部設定','這會取代全部 Profile、職業與專精設定。\n目前設定會先自動備份；不會啟動監控或連線。\n\n是否繼續？',parent=app.root,default='no'):return
            if blocked(app):raise ValueError('目前不是停止狀態，請關閉小窗後重試')
            if not app.profile_guard():return
            if blocked(app):raise ValueError('目前不是停止狀態')
            expected=backup.digest(Path(app.app_config_path).read_bytes())
            safety=backup.restore(app.app_config_path,selected,folder,expected,backup.digest(raw))
            restored_hash=backup.digest(raw)
            app.refresh_profile()
            if not app.load_config_into_entries(show_log=False):raise ValueError('還原設定載入失敗')
            status.set('還原已完成；監控與UDP維持停止。\n還原前的安全備份：'+str(safety))
        except Exception as e:
            extra=''
            if safety is not None and restored_hash is not None:
                try:
                    backup.replace_config(app.app_config_path,backup.read_backup(safety),restored_hash)
                    app.refresh_profile();extra='\n已回復還原前的設定。'
                except Exception as rollback:extra='\n自動回復未完成：'+str(rollback)+'\n安全備份：'+str(safety)
            messagebox.showerror('還原未完成',str(e)+extra,parent=app.root)
    ttk.Button(line,text='備份已儲存設定',command=create).pack(side='left')
    ttk.Button(line,text='選擇備份並還原…',command=restore).pack(side='left',padx=8)
    ttk.Label(frame,textvariable=status,wraplength=800).pack(anchor='w',pady=(8,0))
    return frame
