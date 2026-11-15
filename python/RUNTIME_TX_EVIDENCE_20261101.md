# GUI / 真實 sendto bytes 執行時證據 — 2026-11-01

## 本次修改界線
只更新 gui.py（來源身分輸出、傳送來源標籤、顯示 TX 記錄）與 transport.py（sendto 前後證據）。
沒有更改決策／Target gate、Action mapping、延遲、ESP32、JSON wire protocol；來源 metadata 只保留在本地 bytes 子類屬性，不序列化到 UDP。
沒有替你修改任何 Profile/enabled flag，也沒有向 ESP32 發送實驗按鍵。

## 實際捷徑
Shortcut: C:\Users\USER\OneDrive\Desktop\ESP32 UDP 控制台.lnk
Target: C:\Users\USER\AppData\Local\Programs\Python\Python314\pythonw.exe
Arguments: "C:\Users\USER\Desktop\a\START_GUI.pyw"
Start in: C:\Users\USER\Desktop\a
START_GUI.pyw 使用它自己的 __file__ 所在目錄，runpy.run_path 同目錄 gui.py。
已觀察到現存 PID 36628 的 CommandLine 與此相符；這是舊行程，不會因修改磁碟檔案自動載入新診斷，必須關閉再重開。
C:\Users\USER\OneDrive\Desktop\A 是 ESP32 PlatformIO 韌體來源，不是此捷徑指向的 Python GUI。

已針對 Desktop、OneDrive Desktop、Documents/ChatGPT、Documents/Codex 搜尋 gui.py/START_GUI.pyw 並比對本專案識別內容，排除 backups/.pio/node_modules/.venv/vendor 等歷史/依賴目錄；只找到 Desktop/a 的這組活動來源。搜尋結果在 backup 的 copy-search.json。這不是全磁碟無其他程式的保證，未刪除或改動其他副本／捷徑。

## 啟動與監控開始時的來源輸出
GUI_RUNTIME_SOURCE 同時寫 GUI 日誌、diagnostics/node_target_runtime.jsonl 與 diagnostics/udp_tx_runtime.jsonl。
包含 PID、sys.executable、__file__、完整 gui 路徑與 SHA256、實際 import 的 transport 路徑、config 完整路徑、Profile、Action_1/2 command 與 enabled。
監控開始會再取一次當時 runtime_nodes，避免只看到開機時而非儲存後的設定。

## 最靠近 sendto 的 TX 證據
transport._worker 在 `session.sock.sendto(pending, session.endpoint)` 前，直接讀取同一 pending bytes 物件。
UDP_TX：timestamp、pid、tx_id、source_node、caller_file/function/line、GUI/config/Profile context、由實際 bytes 解析的 command、payload_raw（bytes repr）、payload_hex、destination。
UDP_TX_RESULT：同 tx_id，sent_to_os / would_block / socket_error，以及 OS 接受的 byte count。傳送前記錄不是成功證明；請同時核對 RESULT。
背景 worker 只寫檔／放事件佇列，不碰 Tk；GUI 自己從事件佇列顯示。檔案 I/O 在 worker（啟動身分寫檔除外），不在影像掃描/按鍵 callback 等待網路。
停止通訊時原有 release_all 也記錄，source_node=transport.disconnect.release_all；所以不能把最後一筆 release_all 誤當 Action_1，要按 source_node 與 timestamp/tx_id/PID 找到相符的 Action 記錄。

## 測試
1. 真實 Tk + 暫存 Profile，只啟用 Node_Target/Action_1，合成畫面、實際 localhost UDP socket：一次 Action_1；socket receiver bytes 與 UDP_TX payload_raw/payload_hex 完全一致，Action_2 disabled。
2. 最終 caller metadata 版本以 localhost 逐筆傳 q/e，記錄 Action_1/Action_2 來源、真實 bytes 與 sendto RESULT 一致。
測試證據：backups/runtime-tx-20261101/localhost-test.json、localhost-tx-evidence.jsonl、final-loopback-evidence.jsonl。
測試目的地是 127.0.0.1，不是 ESP32。未注入 HID，不把此結果當成你本次 LCD=e 的實機證據。
備份含修改前 SHA256、gui.py.diff、transport.py.diff；在額外副本驗證恢復 SHA256，最終診斷版仍保留。

## 請進行的一次實機測試
1. 先停止監控，關閉舊 GUI；保留未保存參數後，再用原桌面捷徑開啟。
2. 確認 GUI_RUNTIME_SOURCE 的 gui/config/Profile 路徑。
3. 只啟用 Node_Target、Action_1；停用 Node_HP、Action_2–6，按儲存設定。不要修改 command。
   本次診斷讀取磁碟時 Node_HP=True、Action_1=False、Action_2=False；不代表稍後或未保存的 GUI 狀態。我沒有更改這些值。
4. 初始化 UDP、啟動監控，確認第二筆 GUI_RUNTIME_SOURCE 的 enabled 符合測試條件。
5. 讓 Target 與 Action_1 都命中一次後停止監控（不要停止 UDP，避免最後一筆變 release_all）。
6. 記下 LCD 顯示與時間／拍照，再讀 diagnostics/udp_tx_runtime.jsonl 的 Action_1 UDP_TX 及同 tx_id RESULT。
7. 若該 Action_1 TX 的 key 已是 e，依記錄中的 command/caller/Profile 回查上游；若 TX=q 但 LCD=e，再追查 ESP32 收包、其他來源封包及 parser。不能僅靠本機送出證據排除其他發送者。

## 目前可證明鏈路
localhost：C:\Users\USER\Desktop\a\gui.py → Action_1 → b'{"action":"tap","key":"q"}' → localhost receiver 同 bytes。
實機：上述 GUI → 本次 source_node（待觸發）→ 真正 sendto bytes（待觸發）→ ESP32 LCD（待同時間照片／觀察）。
**目前尚無你 LCD=e 那次對應的新 UDP_TX；不能宣稱已找到 e 來源，也不能直接怪罪 ESP32。**

## 取消本次診斷
關閉 GUI 後，將 backups/runtime-tx-20261101 中的 gui.py、transport.py 覆蓋活動專案原檔即可。不要覆蓋 config.json（避免覆蓋後來自行調整的 enabled）。
