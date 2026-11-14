import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import json
import sys
import time
import os
import hashlib
import calibration_ui
from calibration_hotkeys import CalibrationHotkeys
import queue
from detector import DetectorWorker
from pathlib import Path

import numpy as np
import pyautogui

# 匯入我們之前寫好的三個核心模組
from vision import GameVision
from decision import DecisionEngine, node_matches
from profile_ui import ProfileMixin
import profile_store
from skill_model import SKILL_PRIORITY, skill_command
from mark_trace import TracedESP32Controller as ESP32Controller
import lcd_settings
import endpoint_settings
from hotkey_capture import F8Capture
from target_diagnostics import TargetDiagnostics

class RedirectText:
    """將 print() 與錯誤訊息寫入 GUI 的文字框。"""

    def __init__(self, text_widget):
        self.text_widget = text_widget
        self.pending = queue.Queue(maxsize=256)

    def write(self, string):
        if string:
            try:self.pending.put_nowait(string)
            except queue.Full:pass
        return len(string)

    def flush(self):
        pass

class MacroDashboard(ProfileMixin):
    """
    這是圖形化介面（GUI）的主程式類別。
    我們用它來取代原本 main.py 裡面的終端機黑畫面。
    """
    def __init__(self, root, config_path=None, output_mode='dry_run'):
        self.root = root
        self.root.title("WoW 硬體巨集戰術面板 — " + ('Dry Run' if output_mode == 'dry_run' else 'UDP 測試'))
        self.root.geometry("1100x900")
        self.root.minsize(1020, 720)
        
        # 實例化三個核心模組
        self.detector = None
        self.detector_after_id = None
        self.vision = GameVision()
        self.brain = DecisionEngine()
        # Mode changes replace the process; this guard is NEVER removed in-place.
        from output_guard import install_process_output_guard
        self.output_guard=install_process_output_guard() if output_mode=='dry_run' else None
        self.controller = ESP32Controller(output_mode=output_mode)
        self.dry_start_after_id=None;self.dry_stop_after_id=None;self.dry_start_deadline=None
        self.last_udp_ack_at = None
        self._tx_display_records = {}
        self.request_close = None
        
        # 標控變數：用來紀錄「視覺監控」是否正在執行中
        self.is_running = False
        self.is_tracking = False
        self.tracking_after_id = None
        self.udp_poll_after_id = None
        self.lcd_test_counter = 0
        self.app_config_path = Path(config_path) if config_path else Path(__file__).with_name("config.json")
        from dry_monitor import DryDiagnostics
        self.dry_diagnostics=DryDiagnostics(self.app_config_path.parent/'diagnostics/dry_monitor_runtime.jsonl',guard=self.output_guard)
        self.controller.dry_diagnostics=self.dry_diagnostics
        self.controller.evidence_path = self.app_config_path.resolve().parent / "diagnostics" / "udp_tx_runtime.jsonl"
        self.controller.mark_trace.path = self.app_config_path.resolve().parent / "logs" / "mark_trace.log"
        self.profile_data = profile_store.read(self.app_config_path)
        if json.loads(self.app_config_path.read_text(encoding="utf-8")) != profile_store.disk_document(self.profile_data):
            profile_store.write(self.app_config_path, self.profile_data)
        self.active_profile_name = self.profile_data["last_used"]
        self.capture_generation = 0
        self.vision_after_id = None
        self.dispatch_after_id = None
        self.current_conditions = {}
        self.runtime_nodes = {}
        self.target_diag = TargetDiagnostics(sink=self.log_msg, path=self.app_config_path.parent / "diagnostics" / "node_target_runtime.jsonl")
        self.calibration_jobs = []
        self.node_editor = None
        self.hotkey_capture = F8Capture()
        self._hotkey_epoch = 0
        self.capture_target_var = tk.StringVar(value="Node_Target")
        self.capture_hint_var = tk.StringVar(value="選取節點後啟用採集；切到目標畫面按 F8，自動填入 X / Y / RGB。")
        self.capture_samples = {}
        self.capture_target_var.trace_add("write", self.on_capture_target_change)
        self.lcd_display = lcd_settings.load(self.app_config_path)
        self.lcd_editor = None
        lcd_power = self.load_lcd_power_config()
        self.screensaver_enabled_var = tk.BooleanVar(value=lcd_power["screensaver_enabled"])
        self.screensaver_seconds_var = tk.IntVar(value=lcd_power["screensaver_seconds"])
        self.lcd_sleep_enabled_var = tk.BooleanVar(value=lcd_power["sleep_enabled"])
        self.lcd_sleep_seconds_var = tk.IntVar(value=lcd_power["sleep_seconds"])
        
        # 建立畫面上的所有元件 (UI佈局)
        self.create_widgets()
        self.load_config_into_entries(show_log=False)
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        self.redirect_text = RedirectText(self.txt_log)
        sys.stdout = self.redirect_text
        sys.stderr = self.redirect_text
        self.udp_poll_after_id = self.root.after(250, self.poll_udp)
        self.report_runtime_source()
        self.calibration_hotkeys = CalibrationHotkeys(self)
        self.calibration_hotkeys.start()

    def report_runtime_source(self):
        nodes = self.runtime_nodes
        self.controller.evidence_context = {"gui_file":str(Path(__file__).resolve()),
            "config_path":str(self.app_config_path.resolve()), "profile":self.active_profile_name}
        record = {"event":"GUI_RUNTIME_SOURCE", "pid":os.getpid(), "sys.executable":sys.executable,
            "__file__":__file__, "gui_absolute_path":str(Path(__file__).resolve()),
            "gui_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "transport_absolute_path":str(Path(sys.modules[ESP32Controller.__module__].__file__).resolve()),
            "config_path":str(self.app_config_path.resolve()), "profile":self.active_profile_name,
            "combat_mode":self.runtime_combat_mode,
            "selected_class":self.selected_class,"selected_spec":self.selected_spec,
            **self.runtime_mark_settings,
            "nodes":{name:{"enabled":n["enabled"],"command":n["command"]} for name,n in nodes.items()},
            "skill_priority":list(SKILL_PRIORITY)}
        self.target_diag.emit("GUI_RUNTIME_SOURCE", **{k:v for k,v in record.items() if k!="event"})
        # Also save alongside bytes-level TX evidence, with the same process id.
        if self.controller.output_mode=='dry_run':self.dry_diagnostics.runtime_source(record)
        else:self.controller._append_evidence(record)

    def create_widgets(self):
        """
        建立介面上的按鈕、輸入框與日誌顯示區。
        """
        self.create_profile_bar()
        mode_row = ttk.LabelFrame(self.root, text='輸出模式（本次視窗，不儲存）', padding=8)
        mode_row.pack(fill='x', padx=10, pady=5)
        self.output_mode_var = tk.StringVar(value='Dry Run' if self.controller.output_mode=='dry_run' else 'UDP 測試')
        self.output_mode_choice = ttk.Combobox(mode_row, textvariable=self.output_mode_var,
            values=('Dry Run', 'UDP 測試'), state='readonly', width=15)
        self.output_mode_choice.pack(side='left')
        self.output_mode_choice.bind('<<ComboboxSelected>>', self.change_output_mode)
        ttk.Label(mode_row, text='切換前先停止；確認後更換程序，不自動連線。').pack(side='left', padx=10)
        tk.Button(mode_row, text='停止監控與 UDP', command=self.stop_all,
            bg='#a51d27', fg='white', padx=12, pady=4).pack(side='right')
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(canvas)
        body_item = canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(body_item, width=e.width))
        def scroll(event):
            canvas.yview_scroll(int(-event.delta / 120), "units")
        self.root.bind("<MouseWheel>", scroll, add="+")
        self.body_canvas = canvas
        # --- 區塊 1：硬體連線控制 ---
        frame_hw = ttk.LabelFrame(self.body, text="硬體連線 (手)", padding=10)
        frame_hw.pack(fill="x", padx=10, pady=5)
        self.last_tx_var = tk.StringVar(value='最近實際發送：尚無（送交作業系統不代表裝置執行）')
        self.last_reply_var = tk.StringVar(value='最近裝置回覆：尚無')
        ttk.Label(frame_hw, textvariable=self.last_tx_var, wraplength=900).pack(fill='x', pady=2)
        ttk.Label(frame_hw, textvariable=self.last_reply_var, wraplength=900).pack(fill='x', pady=2)
        ttk.Label(frame_hw, text='停止將嘗試 release_all；不保證送達或裝置確實解除按鍵。',
                  foreground='#9b1c1c').pack(fill='x', pady=2)
        
        endpoint_row = ttk.Frame(frame_hw)
        endpoint_row.pack(fill="x", pady=(0, 6))
        ttk.Label(endpoint_row, text="目標 IP").pack(side="left", padx=(0, 6))
        saved_host, saved_port = endpoint_settings.load(self.app_config_path)
        self.target_ip_var = tk.StringVar(value=saved_host)
        self.target_port_var = tk.StringVar(value=str(saved_port))
        self.ip_entry = ttk.Entry(endpoint_row, textvariable=self.target_ip_var, width=24)
        self.ip_entry.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ttk.Label(endpoint_row, text="Port").pack(side="left", padx=(0, 6))
        self.port_entry = ttk.Entry(endpoint_row, textvariable=self.target_port_var, width=7)
        self.port_entry.pack(side="left")
        self.lbl_udp = ttk.Label(frame_hw, text="UDP 未初始化；請填寫 ESP32 LCD 顯示的 IPv4")
        self.lbl_udp.pack(fill="x", pady=(0, 6))

        control_row = ttk.Frame(frame_hw)
        control_row.pack(fill="x")
        self.btn_connect = ttk.Button(control_row, text='UDP BLOCKED' if self.controller.output_mode=='dry_run' else '初始化 UDP 通訊', command=self.connect_hw,state='disabled' if self.controller.output_mode=='dry_run' else 'normal')
        self.btn_connect.pack(side="left", padx=5)
        
        self.btn_disconnect = ttk.Button(control_row, text="停止 UDP", command=self.disconnect_hw, state="disabled")
        self.btn_disconnect.pack(side="left", padx=5)

        self.btn_test_jump = ttk.Button(control_row, text="手動測試: 獵人跳射", command=self.test_jump_shot, state="disabled")
        self.btn_test_jump.pack(side="right", padx=5)
        self.btn_lcd_test = ttk.Button(control_row, text="測試 LCD", command=self.test_lcd, state="disabled")
        self.btn_lcd_test.pack(side="right", padx=5)

        # --- 區塊 2：視覺監控控制 ---
        frame_vision = ttk.LabelFrame(self.body, text="視覺大腦 (眼與腦)", padding=10)
        frame_vision.pack(fill="x", padx=10, pady=5)
        self.output_banner=ttk.Label(frame_vision,text='DRY RUN / OUTPUT BLOCKED — UDP 禁止傳送' if self.controller.output_mode=='dry_run' else 'UDP 測試 — 可能透過 ESP32 發送 HID 鍵盤指令',foreground='#9b1c1c',font=('TkDefaultFont',11,'bold'))
        self.output_banner.pack(fill='x',pady=(0,6))
        frame_vision_controls = ttk.Frame(frame_vision)
        frame_vision_controls.pack(fill="x")
        
        self.btn_start = ttk.Button(frame_vision_controls, text='啟動 Dry Monitor（25 秒）' if self.controller.output_mode=='dry_run' else '啟動視覺監控', command=self.start_loop)
        self.btn_start.pack(side="left", padx=5)
        
        self.btn_stop = ttk.Button(frame_vision_controls, text="⏹ 停止監控與輸出", command=self.stop_all, state="disabled")
        self.btn_stop.pack(side="left", padx=5)
        
        self.lbl_status = ttk.Label(frame_vision_controls, text="狀態: 待命中", foreground="gray")
        self.lbl_status.pack(side="right", padx=5)

        self.btn_track = ttk.Button(
            frame_vision, text="切換座標採集模式（F8）", command=self.toggle_tracking
        )
        self.btn_track.pack(fill="x", padx=5, pady=(8, 0))
        ttk.Label(frame_vision, textvariable=self.capture_hint_var, wraplength=960).pack(fill="x", padx=5, pady=(6, 0))

        # --- 區塊 3：視覺偵測參數設定 ---
        frame_config = ttk.LabelFrame(self.body, text="戰術參數設定 (Config)", padding=10)
        frame_config.pack(fill="x", padx=10, pady=5)
        self.create_node_table(frame_config)

        # --- 區塊 4：LCD 螢幕保護與睡眠設定 ---
        frame_lcd = ttk.LabelFrame(self.body, text="LCD 螢幕保護與睡眠", padding=10)
        frame_lcd.pack(fill="x", padx=10, pady=5)
        saver_row = ttk.Frame(frame_lcd)
        saver_row.pack(fill="x", pady=2)
        ttk.Checkbutton(saver_row, text="啟用螢幕保護", variable=self.screensaver_enabled_var).pack(side="left")
        ttk.Label(saver_row, text="閒置").pack(side="left", padx=(10, 4))
        ttk.Spinbox(saver_row, from_=5, to=86400, width=7, textvariable=self.screensaver_seconds_var).pack(side="left")
        ttk.Label(saver_row, text="秒後啟動").pack(side="left", padx=(4, 0))

        sleep_row = ttk.Frame(frame_lcd)
        sleep_row.pack(fill="x", pady=2)
        ttk.Checkbutton(sleep_row, text="啟用 LCD 睡眠", variable=self.lcd_sleep_enabled_var).pack(side="left")
        ttk.Label(sleep_row, text="閒置").pack(side="left", padx=(10, 4))
        ttk.Spinbox(sleep_row, from_=5, to=86400, width=7, textvariable=self.lcd_sleep_seconds_var).pack(side="left")
        ttk.Label(sleep_row, text="秒後關閉背光／面板").pack(side="left", padx=(4, 0))
        self.btn_lcd_apply = ttk.Button(frame_lcd, text="套用並儲存 LCD 設定", command=self.apply_lcd_power_settings)
        self.btn_lcd_apply.pack(anchor="e", pady=(6, 0))
        ttk.Button(frame_lcd, text="LCD 文字／字級／中文設定…", command=self.open_lcd_editor).pack(anchor="e", pady=(6, 0))

        # --- 區塊 5：系統日誌顯示區 ---
        frame_log = ttk.LabelFrame(self.body, text="系統日誌", padding=10)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        
        # 建立一個可以捲動的文字框來顯示 Print 訊息
        self.txt_log = scrolledtext.ScrolledText(frame_log, wrap=tk.WORD, height=15)
        self.txt_log.pack(fill="both", expand=True)
        self.log_msg("系統初始化完成。請先連線硬體。")

    def log_msg(self, msg):
        """
        將文字印到介面的日誌框中，取代原本終端機的 print()。
        """
        timestamp = time.strftime("%H:%M:%S")
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        if int(self.txt_log.index('end-1c').split('.')[0]) > 1200:self.txt_log.delete('1.0','400.0')
        self.txt_log.see(tk.END) # 自動捲動到最底端

    def load_lcd_power_config(self):
        """從既有 config.json 讀取 LCD 電源設定；保留其他視覺設定不動。"""
        defaults = {
            "screensaver_enabled": True,
            "screensaver_seconds": 60,
            "sleep_enabled": True,
            "sleep_seconds": 300,
        }
        try:
            data = profile_store.active(self.app_config_path)
            saved = data.get("lcd_power", {}) if isinstance(data, dict) else {}
            if isinstance(saved, dict):
                defaults.update(saved)
        except (OSError, json.JSONDecodeError):
            pass
        for key in ("screensaver_seconds", "sleep_seconds"):
            try:
                defaults[key] = max(5, min(86400, int(defaults[key])))
            except (TypeError, ValueError):
                defaults[key] = 60 if key == "screensaver_seconds" else 300
        defaults["screensaver_enabled"] = bool(defaults["screensaver_enabled"])
        defaults["sleep_enabled"] = bool(defaults["sleep_enabled"])
        return defaults

    def apply_lcd_power_settings(self):
        """驗證並保存設定；連線時立即同步至 ESP32。"""
        try:
            saver_seconds = int(self.screensaver_seconds_var.get())
            sleep_seconds = int(self.lcd_sleep_seconds_var.get())
        except (tk.TclError, ValueError):
            self.log_msg("⚠️ LCD 閒置時間需輸入 5 到 86400 秒的整數。")
            return
        if not 5 <= saver_seconds <= 86400 or not 5 <= sleep_seconds <= 86400:
            self.log_msg("⚠️ LCD 閒置時間範圍為 5 到 86400 秒。")
            return
        if (self.screensaver_enabled_var.get() and self.lcd_sleep_enabled_var.get()
                and sleep_seconds <= saver_seconds):
            self.log_msg("⚠️ 睡眠時間需大於螢幕保護時間，否則螢幕保護階段不會顯示。")
            return

        power_config = {
            "screensaver_enabled": self.screensaver_enabled_var.get(),
            "screensaver_seconds": saver_seconds,
            "sleep_enabled": self.lcd_sleep_enabled_var.get(),
            "sleep_seconds": sleep_seconds,
        }
        try:
            profile_store.update_active(self.app_config_path, {"lcd_power": power_config})
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.log_msg(f"❌ 無法儲存 LCD 設定：{exc}")
            return

        self.log_msg("💾 LCD 螢幕保護與睡眠設定已儲存。")
        if self.controller.is_open:
            self.send_lcd_power_config(power_config)
        else:
            self.log_msg("ℹ️ 尚未連線；設定會在下次連線時同步到 ESP32。")

    def send_lcd_power_config(self, power_config=None):
        """把目前設定透過 JSON 傳給韌體。"""
        if power_config is None:
            try:
                saver_seconds = int(self.screensaver_seconds_var.get())
                sleep_seconds = int(self.lcd_sleep_seconds_var.get())
            except (tk.TclError, ValueError):
                self.log_msg("⚠️ LCD 閒置時間需輸入 5 到 86400 秒的整數；尚未同步。")
                return
            power_config = {
                "screensaver_enabled": self.screensaver_enabled_var.get(),
                "screensaver_seconds": saver_seconds,
                "sleep_enabled": self.lcd_sleep_enabled_var.get(),
                "sleep_seconds": sleep_seconds,
            }
        command = {"action": "lcd_config", **power_config}
        written = self.controller.send_command(command, source_node="GUI.lcd_config")
        if written:
            self.log_msg("📟 LCD 電源設定已排入 UDP 佇列，等待 ESP32 確認。")
        else:
            self.log_msg("❌ LCD 電源設定未送出，請確認 ESP32 連線。")

    def change_output_mode(self, event=None):
        current = self.controller.output_mode
        selected = self.output_mode_var.get()
        desired = 'normal' if selected == 'UDP 測試' else 'dry_run'
        self.output_mode_var.set('Dry Run' if current == 'dry_run' else 'UDP 測試')
        if desired == current:
            return
        worker = self.controller._thread
        if (self.is_running or self.dry_start_after_id is not None or self.is_tracking
                or self.controller.is_open or (worker and worker.is_alive())
                or calibration_ui.busy(self)):
            messagebox.showwarning('請先停止', '請先按「停止監控與 UDP」，並停止座標採集／校正，再切換模式。', parent=self.root)
            return
        if not self.request_close or not self.profile_guard():
            return
        if desired == 'normal' and not messagebox.askyesno('確認 UDP 測試',
                'UDP 測試可透過 ESP32 發送 HID 鍵盤指令，可能操作遊戲或其他視窗。\n'
                '將以獨立程序開啟；仍須手動初始化 UDP 及啟動監控。\n'
                '停止時的 release_all 不保證裝置已解除按鍵。\n\n是否開啟 UDP 測試？',
                parent=self.root, default='no'):
            return
        from output_mode_session import launch_session
        try:
            launch_session(desired)
        except Exception as exc:
            messagebox.showerror('無法切換模式', str(exc), parent=self.root)
            return
        self.request_close()

    def stop_all(self):
        self.stop_loop('user_stop_all')
        self.disconnect_hw()

    def connect_hw(self):
        """Initialize a local UDP socket; receipt of an ACK proves peer response."""
        if self.controller.output_mode=='dry_run':
            self.log_msg('DRY RUN / OUTPUT BLOCKED：禁止初始化 UDP。');return
        self.controller.host = self.target_ip_var.get().strip()
        self.controller.port = self.target_port_var.get().strip()
        if self.controller.connect():
            try:
                endpoint_settings.save(self.app_config_path, self.controller.host, self.controller.port)
                self.log_msg("IP 與 Port 已儲存，下次啟動將自動帶入（不自動連線）。")
            except (OSError, ValueError, TypeError) as exc:
                self.log_msg(f"UDP 已初始化，但無法儲存網路位置：{exc}")
            self.last_udp_ack_at = None
            self.lbl_udp.config(text=f"UDP 已初始化 → {self.controller.host}:{self.controller.port}；等待回覆")
            self.log_msg("UDP 已初始化；尚未確認 ESP32 在線。")
            self.btn_connect.config(state="disabled")
            self.btn_disconnect.config(state="normal")
            self.btn_test_jump.config(state="normal")
            self.btn_lcd_test.config(state="normal")
            self.ip_entry.config(state="disabled")
            self.port_entry.config(state="disabled")
            self.send_lcd_power_config()
            self.send_lcd_display_config()
        else:
            self.log_msg(f"UDP 初始化失敗：{self.controller.last_error}")
            self.lbl_udp.config(text="初始化失敗；請檢查 IP/Port，必要時稍後重試")

    def disconnect_hw(self):
        if self.is_running:
            self.stop_loop()
        self.controller.disconnect()
        self.log_msg("UDP 停止中；背景嘗試送出 release_all，UDP 不保證送達。")
        self.lbl_udp.config(text="UDP 已停止（不代表遠端按鍵已確認釋放）")
        self.btn_connect.config(state="disabled" if self.controller.output_mode=='dry_run' else 'normal')
        self.btn_disconnect.config(state="disabled")
        self.btn_test_jump.config(state="disabled")
        self.btn_lcd_test.config(state="disabled")
        self.ip_entry.config(state="normal")
        self.port_entry.config(state="normal")

    def test_jump_shot(self):
        """舊按鈕沿用入口，改送純 LCD 測試，避免意外送出 HID 按鍵。"""
        self.test_lcd()

    def open_lcd_editor(self):
        if self.lcd_editor and self.lcd_editor.window.winfo_exists():
            self.lcd_editor.window.lift()
            return
        self.lcd_editor = lcd_settings.LcdEditor(self)

    def send_lcd_display_config(self):
        if not self.controller.is_open:
            return False
        all_queued = True
        for command in lcd_settings.commands(self.lcd_display):
            all_queued = bool(self.controller.send_command(command, source_node="GUI." + command["action"])) and all_queued
        self.log_msg("LCD 文字設定已排入 UDP；請確認 lcd_style／lcd_labels 回覆。" if all_queued else "LCD 文字設定未全部排入；請稍後重新套用。")
        return all_queued

    def test_lcd(self):
        """送出不會操作 HID 的 LCD 測試命令。"""
        self.lcd_test_counter += 1
        message = self.lcd_display["labels"]["test_message"]
        if self.controller.send_command({"action": "lcd_test", "message": message}, source_node="GUI.test_lcd"):
            self.log_msg(f"LCD 測試已排入 UDP 佇列：{message}（不觸發 HID）")
        else:
            self.log_msg(f"LCD 測試未排入：{self.controller.last_error}")

    def poll_udp(self):
        """Only the Tk thread renders events; network worker never calls widgets."""
        for _ in range(16):
            try:self.txt_log.insert(tk.END,self.redirect_text.pending.get_nowait())
            except queue.Empty:break
        for event in self.controller.poll_events(limit=16):
            if event["kind"] == "ack":
                self.last_udp_ack_at = event["received_at"]
                reply = event["reply"]
                from datetime import datetime
                self.last_reply_var.set('最近裝置回覆：' + datetime.now().astimezone().isoformat(timespec='seconds') + '  ' + json.dumps(reply, ensure_ascii=False))
                self.lbl_udp.config(text=f"已收到 ESP32 回覆：{reply.get('status')} / {reply.get('action', reply.get('msg', ''))}")
                self.log_msg("ESP32 回覆: " + json.dumps(reply, ensure_ascii=False))
                if reply.get("action") in ("lcd_style", "lcd_labels") and reply.get("status")=="ok" and reply.get("lcd_version")!=2:
                    self.log_msg("LCD 設定未驗證：ESP32 仍可能是舊韌體，請燒入中文字級新版。")
            elif event["kind"] == "tx_evidence":
                record = event['record']
                tx_id = record.get('tx_id')
                if record.get('event') == 'UDP_TX':
                    self._tx_display_records[tx_id] = record
                    if len(self._tx_display_records) > 64:
                        self._tx_display_records.pop(next(iter(self._tx_display_records)))
                elif record.get('event') == 'UDP_TX_RESULT':
                    source = self._tx_display_records.pop(tx_id, {})
                    self.last_tx_var.set('最近發送結果：' + record.get('timestamp', '') + '  ' +
                        json.dumps(source.get('command'), ensure_ascii=False) + '  ' + record.get('outcome', 'unknown') +
                        '（不代表裝置或遊戲已執行）')
                self.log_msg("[" + event["record"]["event"] + "] " + json.dumps(event["record"], ensure_ascii=False))
            elif event["kind"] == "error":
                self.log_msg("UDP: " + event["message"])
            elif event["kind"] == "closed" and not self.controller.is_open:
                if self.is_running:
                    self.stop_loop()
                self.lbl_udp.config(text="UDP 已停止；重新初始化可再次測試")
                self.btn_connect.config(state='disabled' if self.controller.output_mode=='dry_run' else 'normal')
                self.btn_disconnect.config(state="disabled")
                self.btn_test_jump.config(state="disabled")
                self.btn_lcd_test.config(state="disabled")
                self.ip_entry.config(state="normal")
                self.port_entry.config(state="normal")
        if self.controller.is_open and self.last_udp_ack_at is not None and time.monotonic() - self.last_udp_ack_at > 30:
            self.lbl_udp.config(text="超過 30 秒未收到回覆（未必離線；請送 LCD 測試確認）")
        self.udp_poll_after_id = self.root.after(250, self.poll_udp)

    def start_loop(self):
        if calibration_ui.busy(self):
            self.log_msg('亮度校正仍在取樣／結束中，請稍後再啟動 Monitor。')
            return
        if self.is_running:
            return
        dry=self.controller.output_mode=='dry_run'
        if dry:
            from dry_monitor import wow_foreground_ready
            try:ready=wow_foreground_ready()
            except Exception as exc:
                self.dry_diagnostics.record('START_REJECTED',decision='stop',reason=getattr(exc,'code',type(exc).__name__),error=str(exc));return
            if not ready:
                if self.dry_start_deadline is None:self.dry_start_deadline=time.monotonic()+30
                if time.monotonic()>self.dry_start_deadline:
                    self.stop_loop('foreground_wait_timeout');return
                self.lbl_status.config(text='等待 WoW 前景｜OUTPUT BLOCKED',foreground='#9b1c1c')
                self.btn_start.config(state='disabled')
                self.btn_stop.config(state='normal')
                self.dry_start_after_id=self.root.after(150,self.start_loop)
                return
            self.dry_start_deadline=None
            if self.dry_start_after_id is not None:
                self.root.after_cancel(self.dry_start_after_id);self.dry_start_after_id=None
        if not dry and not self.controller.is_open:
            self.log_msg("請先初始化 UDP。")
            return
        if dry:
            # Formal config only. No save/migration or edited-node substitution.
            if not self.load_config_into_entries(show_log=False):return
            self.output_guard.check()
            self.dry_diagnostics.context={'profile':self.active_profile_name,'class':self.selected_class,'spec':self.selected_spec}
            self.dry_diagnostics.current=None
        elif not self.save_config_from_entries():return
        if self.is_tracking:
            self.toggle_tracking()
        self.capture_generation += 1
        self.brain.reset()
        self.target_diag.reset()
        self.report_runtime_source()
        self.target_diag.emit("ACTIVE_SPEC", **{"class":self.selected_class,"spec":self.selected_spec})
        self.target_diag.emit("MONITOR_START", profile=self.active_profile_name, combat_mode=self.runtime_combat_mode, **self.runtime_mark_settings, target_gate_skills=SKILL_PRIORITY)
        self.current_conditions = {}
        self.is_running = True
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.lbl_status.config(text='Monitor: ON | DRY RUN / BLOCKED' if dry else '狀態：監控中',foreground='#9b1c1c' if dry else 'green')
        self.log_msg("監控已啟動；最高優先技能每次發送後重新等待 Min/Max Delay，發送前重查條件。")
        self.controller.mark_trace.gui_context = {"config_path":str(self.app_config_path.resolve()),"profile":self.active_profile_name,"selected_class":self.selected_class,"selected_spec":self.selected_spec}
        self.detector = DetectorWorker(self.runtime_nodes, self.controller.send_command, GameVision, combat_mode=self.runtime_combat_mode, mark_trace=self.controller.mark_trace, output_observer=self.dry_diagnostics if dry else None, **self.runtime_mark_settings)
        self.detector.start()
        self.detector_after_id = self.root.after(250, self.detector_ui_tick)
        if dry:
            self.dry_diagnostics.record('MONITOR_START',reason='25_second_output_blocked_observation')
            self.dry_stop_after_id=self.root.after(25000,lambda:self.stop_loop('duration_elapsed'))

    def stop_loop(self,reason='user_stop'):
        was_running=self.is_running
        for attr in ('dry_start_after_id','dry_stop_after_id'):
            ident=getattr(self,attr,None)
            if ident is not None:self.root.after_cancel(ident);setattr(self,attr,None)
        self.dry_start_deadline=None
        self.is_running = False
        if self.detector is not None:
            self.detector.stop()
        if self.detector_after_id is not None:
            self.root.after_cancel(self.detector_after_id)
            self.detector_after_id = None
        for attr in ("vision_after_id", "dispatch_after_id"):
            timer = getattr(self, attr, None)
            if timer is not None:
                self.root.after_cancel(timer)
                setattr(self, attr, None)
        self.brain.reset()
        self.current_conditions = {}
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_status.config(text="狀態：待命", foreground="gray")
        if was_running and self.controller.output_mode=='dry_run':
            self.dry_diagnostics.current=None
            self.dry_diagnostics.record('MONITOR_STOP',decision='stop',reason=reason,
                would_send_count=self.dry_diagnostics.would_send_count,guard_attempts=len(self.output_guard.attempts))
        self.log_msg("監控已停止，所有尚未排入 UDP 的待送事件已取消。")

    def capture_context(self):
        node=getattr(self,'editing_nodes',{}).get(self.capture_target_var.get(),{})
        return (self._hotkey_epoch, self.active_profile_name, self.capture_target_var.get(), self.selected_class, self.selected_spec,node.get('coordinate_mode','desktop_absolute'))

    def on_capture_target_change(self, *_):
        if self.is_tracking:
            self.hotkey_capture.set_context(self.capture_context())
        name = self.capture_target_var.get()
        sample = self.capture_samples.get(name)
        suffix = "F8 採集已啟用" if self.is_tracking else "請啟用座標採集模式"
        if sample:
            suffix += f"｜X={sample['x']} Y={sample['y']} RGB={sample['rgb']}（尚需儲存）"
        mode=getattr(self,'editing_nodes',{}).get(name,{}).get('coordinate_mode','desktop_absolute')
        label='WoW Client' if mode=='wow_client' else 'Desktop'
        self.capture_hint_var.set(f"採集對象：{name}｜座標：{label}｜{suffix}")

    def toggle_tracking(self):
        if self.is_tracking:
            self.stop_tracking()
            return
        if self.is_running:
            self.stop_loop()
        self.capture_generation += 1
        self._hotkey_epoch += 1
        if not self.hotkey_capture.start(self.capture_context()):
            self.log_msg("無法開始 F8 採集：舊監聽正在結束，請稍後重試，或檢查 Windows 支援。")
            for event in self.hotkey_capture.poll():
                if event.get("message"):
                    self.log_msg(event["message"])
            return
        self.is_tracking = True
        self.btn_track.config(text="停止座標採集（F8）")
        self.lbl_status.config(text="狀態：正在註冊全域 F8…", foreground="blue")
        self.on_capture_target_change()
        self.tracking_loop_tick()

    def stop_tracking(self):
        self.is_tracking = False
        self._hotkey_epoch += 1
        self.hotkey_capture.stop()
        if self.tracking_after_id is not None:
            self.root.after_cancel(self.tracking_after_id)
            self.tracking_after_id = None
        self.btn_track.config(text="切換座標採集模式（F8）")
        self.lbl_status.config(text="狀態：待命", foreground="gray")
        self.on_capture_target_change()
        self.log_msg("F8 採集已停止，舊事件已失效；背景解除系統熱鍵。")

    def apply_capture_event(self, event):
        # Runs exclusively on Tk's thread. Reject events from old target/profile/session.
        if not self.is_tracking or event.get("context") != self.capture_context():
            return False
        name = self.capture_target_var.get()
        if name not in self.config_entries:
            return False
        mode=self.editing_nodes[name].get('coordinate_mode','desktop_absolute')
        if event.get('coordinate_mode','desktop_absolute')!=mode:
            self.log_msg('拒絕座標模式不符的 F8 採集結果。')
            return False
        x, y = event["x"], event["y"]
        rgb = tuple(event["rgb"])
        if type(x) is not int or type(y) is not int or len(rgb) != 3 or any(type(c) is not int or not 0 <= c <= 255 for c in rgb):
            self.log_msg("忽略無效的採集數值。")
            return False
        for key, value in (("x", x), ("y", y)):
            entry = self.config_entries[name][key]
            entry.delete(0, tk.END)
            entry.insert(0, str(value))
        for key, value in zip(("r", "g", "b"), rgb):
            self.editing_nodes[name][key] = value
            if (self.node_editor is not None and self.node_editor.winfo_exists()
                    and getattr(self, "node_editor_name", None) == name):
                self.node_editor_vars[key].set(str(value))
        self.capture_samples[name] = {"x": x, "y": y, "rgb": rgb}
        self.on_capture_target_change()
        self.log_msg(f"F8 → {name}：X={x}, Y={y}, RGB={rgb}；已填入，請按儲存設定。")
        return True

    def tracking_loop_tick(self):
        self.tracking_after_id = None
        if not self.is_tracking:
            return
        for event in self.hotkey_capture.poll():
            kind = event.get("kind")
            if kind == "ready":
                self.lbl_status.config(text="狀態：F8 全域採集已就緒", foreground="blue")
                self.log_msg("F8 已註冊；切到遊戲按 F8，僅採集一次，不發送 HID。")
            elif kind == "capture":
                self.apply_capture_event(event)
            elif kind == "capture_error":
                if event.get("context") == self.capture_context():
                    self.log_msg("F8 像素擷取失敗：" + event["message"])
            elif kind in ("error", "stopped"):
                if kind == "error":
                    self.log_msg("F8 註冊／監聽失敗：" + event.get("message", "未知錯誤"))
                if self.is_tracking:
                    self.stop_tracking()
                break
        if self.is_tracking:
            self.tracking_after_id = self.root.after(25, self.tracking_loop_tick)

    def restore_output(self):
        """關閉視窗前恢復原本的標準輸出與錯誤輸出。"""
        if getattr(self,'calibration_hotkeys',None):self.calibration_hotkeys.stop()
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr

    def detector_ui_tick(self):
        # Main thread only; bounded work and low-frequency rendering.
        self.detector_after_id = None
        worker=self.detector
        if worker is None:return
        for _ in range(32):
            try:record=worker.events.get_nowait()
            except queue.Empty:break
            event=record.pop('event')
            self.target_diag.emit(event, **record)
            if event=='DETECTOR_ERROR':
                self.stop_loop();return
        if self.is_running:self.detector_after_id=self.root.after(250,self.detector_ui_tick)

    def vision_loop_tick(self):
        # Compatibility entry point; never runs detection on Tk.
        return

    def dispatch_loop_tick(self):
        # Dispatch is exclusively owned by DetectorWorker.
        return


# --- 程式進入點 ---
if __name__ == "__main__":
    # 建立主視窗
    root = tk.Tk()
    
    # 確保關閉視窗時，會安全斷開硬體連線
    from output_mode_session import startup_mode
    app = MacroDashboard(root,output_mode=startup_mode())
    
    # 攔截視窗右上角的「X」關閉按鈕，停止 UDP 工作執行緒
    def on_closing():
        if not app.profile_guard():
            return
        app.calibration_hotkeys.stop()
        calibration_ui.cancel_all(app)
        app.capture_generation += 1
        app.stop_tracking()
        app.disconnect_hw()
        deadline = time.monotonic() + 0.3
        def finish_close():
            worker = app.controller._thread
            if ((worker is not None and worker.is_alive()) or app.hotkey_capture.alive or calibration_ui.busy(app) or app.calibration_hotkeys.alive):
                root.after(10, finish_close)
                return
            app.vision.close()
            app.controller.mark_trace.close()
            app.restore_output()
            root.destroy()
        finish_close()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    app.request_close = on_closing
    
    # 啟動圖形化介面
    root.mainloop()
