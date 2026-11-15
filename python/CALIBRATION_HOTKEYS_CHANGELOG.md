# F9/F10 亮度校正快捷鍵 — 2026-11-01

## 修改檔案
- hotkey_capture.py：將既有 F8Capture 的 Win32 RegisterHotKey/GetMessage worker 增加可選hotkeys參數。預設仍只註冊原F8、原HOTKEY_ID/VK_F8，原座標取樣流程保留。
- 新增 calibration_hotkeys.py：沿用同一F8Capture class / Windows message-loop infrastructure，獨立instance同時註冊F9/F10；不新增keyboard/pynput套件。此instance只產生queue事件，不建立MSS、不抓像素。
- calibration_ui.py：加提示文字、通知active panel啟用/關閉、完成時清除延遲鍵事件。沒有修改capture()/統計/Threshold算法。
- gui.py：建立/輪詢/停止快捷鍵service，關閉GUI等待它結束。
- 新增tests_udp/test_calibration_hotkeys.py；既有test_brightness_calibration.py僅更新本次授權修改hotkey_capture.py的預期SHA256，其他受保護檔案預期hash及演算法斷言全部保留，沒有改舊備份。

## 操作
停止Monitor；打開想校正的Skill_4～Skill_0進階設定；自己選brightness；確保既有X/Y、Sample Mode、Match Ratio正確。
停留遊戲畫面：F9擷取暗值、F10擷取亮值。F8沿用原座標採集模式與其選取節點規則，不改為自動選擇。
F9/F10的目標只由目前開啟的Skill進階視窗決定，不由F8單選按鈕決定，不需要額外選一次校正Skill。
切回GUI查看原有min/max/mean/median、separation、overlap、品質與建議Threshold。按套用後，仍需主畫面儲存設定。原四個滑鼠按鈕全部保留。
F9/F10在GUI存續時為全域保留鍵；關閉GUI會解除。如果被其他程式/另一份GUI占用，diagnostics會顯示registration_error，鼠標校正仍可使用；請關閉舊副本後重開。

## 共用capture path
GUI按鈕 lambda: panel.capture('dark'/'bright')。
Windows F9/F10 → F8Capture事件queue → root.after(50ms)在Tk main thread處理 → CalibrationHotkeys.handle → 同一panel.capture('dark'/'bright')。
沒有第二套sampling/statistics/median/threshold程式。brightness_calibration.py byte-identical，仍15 samples、約350–500ms背景MSS、同X/Y、per-pixel(R+G+B)/3、原ratio等價亮度與原floor midpoint。
完成統計仍由原CalibrationPanel.tick/root.after(100ms)回到Tk更新；native listener及校正worker均不操作Tk。

## active與防誤觸
每個Skill panel啟用時產生(Profile,Skill,遞增序號)token，透過原lock/set_context讓native事件帶上當下context。handler檢查目前window仍存在、確實是app.node_editor、Skill有效、Profile/token一致。
關閉/切到gate editor/切Profile即解除active，舊事件不能誤操作新Skill。
Monitor running、mode為color/red、worker busy/panel.job尚未收尾或沒有active panel：拒絕、不建立worker、不換comparison mode。
MOD_NOREPEAT防按住鍵自動重複；既有capture忙碌保護防同時兩個worker。GUI結束處理取樣時設定ignore_before，會丟棄取樣期間排隊、延遲到完成後才送達的事件，避免busy的按鍵又變成下一次擷取。
校正期間啟動Monitor的既有保護保留。快捷鍵無send_command/sendto/HID呼叫，不能把F9/F10送到ESP32。

## Diagnostics
CALIBRATION_HOTKEY包含skill/key/type=dark或bright/outcome及簡短reason。
拒絕原因：no_active_calibration_skill、monitor_running、mode_not_brightness、calibration_busy、stale_calibration_context、stale_or_busy_key_event、capture_rejected。
無active時skill=null。ignored依key/skill/reason限頻0.75秒，避免按住/連按洗log；正常CALIBRATION/CALIBRATION_RESULT/CALIBRATION_APPLY沿用原流程。

## 測試與限制
實際執行、exit0：
- 新test_calibration_hotkeys.py：16/16。F9/F10暗亮、共用button capture、color/red拒絕、Monitor拒絕、無panel、busy不開第二worker、切Skill舊token拒絕、排隊busy事件丟棄、F8填座標、ignored限頻、main-thread routing、gate editor不啟動、保護hash、Profile失效，以及原Win32 worker註冊F9/F10與預設F8參數。
- 原校正：27/27。
- Hunter Mark：31/31。
- Combat：14/14。
- detector：16/16。
- transport：7/7，在額外暫存副本、僅localhost。
上述既有95項全部通過；另跑F8既有native/queue regression 5/5。
合計116項通過（95+新增16+額外既有F8的5）。全部測試原始log在此backup。
Native測試只PostThreadMessage到測試自己的Win32 message loop，不是SendInput/真實鍵盤注入；驗證註冊、事件、capture context及解除。沒有宣稱已在遊戲中實際按F9/F10驗證。新測試以Mock sender確認未呼叫UDP，既有UDP/Mark測試只用localhost，不連ESP32。
新測試teardown取消測試root的after callbacks，最後重跑無Tcl invalid-command訊息；未因此重構production GUI其他清理流程。
GUI render已檢查，hotkey-hint.png可見提示及原有按鈕，無新增遊戲邏輯。

## 未改證據
safety-verification.json / SHA256-before.json確認以下byte-identical：brightness_calibration.py、profile_ui.py、detector.py、decision.py、vision.py、mark_opener.py、skill_model.py、profile_store.py、transport.py、config.json、ESP32 src/main.cpp。
因此Target/Combat/Mark、印記A/B、Opener/Retry、正式取樣、normal key mapping、priority、Profile格式、UDP JSON protocol及ESP32 firmware皆未變更。
F8 shared infrastructure有授權擴充，所以不是宣稱整個hotkey_capture.py未變；它的預設F8行為由5項native/queue測試＋座標填入測試確認。

## 備份與恢復
backups/calibration-hotkeys-20261101 含修改前原檔、hash、diff、回歸log、GUI截圖及restore-check。
恢復：關閉所有GUI/CLI，複製備份hotkey_capture.py/calibration_ui.py/gui.py回原專案；若恢復舊測試也複製backup/tests_udp/test_brightness_calibration.py回tests_udp。新增calibration_hotkeys.py舊入口不引用，可以保留。不要覆蓋config。
已在額外副本恢復並驗證SHA256，現行修改保留。
重新開原桌面捷徑即可；ESP32不需重燒。本次只完成F9/F10快捷鍵，不繼續加入功能。
