# 全域 F8 座標與 RGB 採集

## 使用
1. 關閉舊 GUI，再用原桌面「ESP32 UDP 控制台」捷徑啟動。本次不需要更新 ESP32 韌體。
2. 在八個節點表格右側「F8 選取」單選按鈕，選定例如 Action_1。此按鈕與「啟用」偵測的勾選框不同。
3. 按「切換座標採集模式（F8）」，確認狀態顯示「F8 全域採集已就緒」。此步不需要 UDP 連線，會先停止視覺自動監控。
4. 切到遊戲／目標視窗，將游標指向取樣點，按裸 F8（不加 Ctrl/Shift）。不需要把視窗焦點切回本 GUI。
5. 該節點 X/Y 自動填入；RGB 自動寫入該節點編輯資料，提示列顯示 RGB。按該節點「設定」可看到 r/g/b；若進階視窗已開啟，也會即時更新。
6. 不會自行變更 Threshold、mode、Tolerance、延遲或指令。要用新採樣 RGB 判斷時，選 color 模式；brightness/red 模式仍依 Threshold。
7. 按「儲存設定（目前 Profile）」才持久保存。F8 不會自動寫 config，不會發送 UDP 或 HID 動作。
8. 可在採集模式中改選其他節點；舊節點已排隊的事件會丟棄，避免誤填。
9. 按「停止座標採集（F8）」會停止並解除熱鍵；切換／改名／刪除 Profile、開始監控、關閉程式時也會停止。解除在背景處理，快速連按停止/開始若舊執行緒尚未結束，稍後重試即可。

## 實作與完整程式碼
- gui.py 為完整 GUI，不是片段；同時依賴本包的 profile_ui.py 與新增 hotkey_capture.py，不可只複製 gui.py 回舊目錄。
- profile_ui.py：8 個單選按鈕、採集對象、進階 RGB 同步。
- hotkey_capture.py：使用 Windows 原生 RegisterHotKey / MOD_NOREPEAT / GetMessage，不新增 keyboard/pynput 依賴。
- MSS 物件在採集執行緒建立並關閉，沒有跨執行緒重用 GameVision 的 thread-local MSS。
- 原生訊息執行緒收到 F8 後，讀取當時游標與 1×1 畫面像素，將快照放入容量 32 的 queue；Tk 主執行緒每約 25ms 消化事件並修改欄位。背景執行緒完全不讀寫 Tk，也不呼叫 Tk after。
- 事件附採集 session、Profile、節點快照；停止／切換後不接受舊結果。
- MOD_NOREPEAT 防鍵盤長按自動重複；每次鬆開再按 F8 才採一次。
- F8 在採集啟用期間由本程式保留，可能不再傳給原遊戲。若被其他軟體占用，會顯示註冊失敗並退出採集，不會假裝成功。
- 正常情況不需系統管理員權限；沒有自動提權、驅動、注入遊戲、外掛繞過或記錄其他按鍵。

## 限制
- 原生實作僅支援 Windows。其他系統啟動採集會顯示不支援；其餘 GUI/UDP 不依賴 Windows API 初始化。
- 擷取為收到 OS 熱鍵訊息後的游標／畫面快照，不是硬即時的硬體按下瞬間。MSS 或 OS 忙碌會增加延遲。
- 遊戲獨占全螢幕、受保護內容、反作弊或安全桌面可能使擷取黑屏／失敗或熱鍵不可用；沒有宣稱已在特定遊戲測通，也不嘗試繞過限制。可先在一般桌面或視窗化畫面驗證。
- 多螢幕可有負座標；混合 DPI 環境仍須核對實際座標是否一致。
- 採集目標選擇為本次編輯狀態；切換 Profile 預設回 Node_HP，既有 Profiles 與儲存內容不受影響。

## 啟動與測試
完整資料夾：`python -m pip install -r requirements.txt`，`python gui.py`，或雙擊 START_GUI.pyw（無 CMD）。原有桌面捷徑仍指向已更新目錄。
- test_hotkey_capture.py：5 項原生註冊/衝突/解除/重啟、MSS 真實像素、佇列上限測試。
- f8_gui_smoke.py：真實 Tk、暫存 Profile，測單選、自動 XY/RGB 填入、進階視窗同步、保存、舊 session/選取拒絕、原生 WM_HOTKEY→MSS→Tk 流程、停止及 Profile 清理。
- test_profiles.py 10 項、test_transport.py 7 項、profiles_gui_smoke.py 回歸亦通過。
- 原生測試向本程式 worker 發送 WM_HOTKEY 訊息，沒有注入鍵盤或滑鼠輸入；未真的在遊戲畫面按 F8。本機像素讀取與 GUI 流程通過，不等於遊戲內驗證。
- transport.py、decision.py、config.json 本次 SHA256 與備份相同；ESP32 韌體未修改／燒錄，未傳送實機 HID 指令。
- evidence/ 含實際測試日誌與 Tk 截圖（截圖中的範例數值來自暫存測試設定，不是替換你實際 Profile）。

## 恢復
backup/ 含修改前檔案與 SHA256、差異、restore_previous.py。
關閉 GUI 後執行 `python backup/restore_previous.py --target <專案目錄>`。
已在額外副本核對全部 SHA256；會回復前版來源與備份當時的 config（請自行留意後續新增設定），保留新版供檢查，不操作 ESP32。

## Win32 原廠 API 來源
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-unregisterhotkey
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getmessage
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-postthreadmessagew
