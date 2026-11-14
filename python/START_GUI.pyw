"""Windowless entry point. Startup errors go to log and a dialog."""
from pathlib import Path
import os,sys,runpy,traceback
P=Path(__file__).resolve().parent
os.chdir(P)
sys.path.insert(0,str(P))
with (P/'gui-startup.log').open('a',encoding='utf-8',buffering=1) as log:
    sys.stdout=sys.stderr=log
    try:
        if '--check' in sys.argv:
            import tkinter,numpy,mss,pyautogui,lcd_settings,endpoint_settings,profile_store,profile_ui,decision,hotkey_capture
            import ast
            ast.parse((P/'gui.py').read_text(encoding='utf-8'))
            print('PASS: windowless launcher dependencies and syntax')
        else:
            runpy.run_path(str(P/'gui.py'),run_name='__main__')
    except Exception:
        traceback.print_exc()
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk();root.withdraw()
        messagebox.showerror('啟動失敗','請查看錯誤記錄：\n'+str(P/'gui-startup.log'))
        root.destroy()
        raise SystemExit(1)
