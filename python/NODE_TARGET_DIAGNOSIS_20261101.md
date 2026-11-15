# Node_Target 自動觸發診斷 — 2026-11-01

## 結論與範圍
CONFIRMED：目前版本沒有 Node_Target → Action_1/Action_2 的連動邏輯。它們是三個獨立的節點；Node_Target 的 command=null，命中後只監控，不產生按鍵。
本次只為 gui.py 加入診斷 hooks，新增 target_diagnostics.py 與測試；decision.py、vision.py、transport.py、config.json 與修改前逐 byte 相同。未修改 ESP32/UDP protocol/Action_1=q、Action_2=e，也沒有發送實機動作。
你提供的手動 Action→UDP→HID E 正常屬使用者觀察；本次未重複向機台發送按鍵。

## 1. 實際像素
目前桌面唯讀採樣 8 次（約 0.75 秒一次），Node_Target X=90 Y=342：
- actual_rgb=(240, 240, 240)
- 原始 raw_bgra=(240, 240, 240, 255)
- 同一個 MSS frame 的 pixel(0,0)=(240, 240, 240)，與 RGB 重排一致。
- target_rgb=(0, 0, 255)
- diff=(240, 240, 15)
- tolerance=20
- 8 次 match 全部 False。
**這是執行診斷當時的桌面，不是已確認顯示藍色目標的遊戲場景。不能由此斷言遊戲中永遠不命中。**
原始記錄 diagnostics/target-20261101/readonly-samples.json。

## 2. RGB / BGR
CONFIRMED：vision.GameVision.get_pixel_color 將 MSS frame 轉 np.array，依 b,g,r,a 解包，再回傳 r,g,b；decision.node_matches 將三個值先轉 Python int，再依 r,g,b 設定比較。
目前活躍的這段流程沒有 OpenCV cv2/cvtColor 中介。GUI F8 來源 hotkey_capture 使用 MSS.pixel(0,0) 的 RGB tuple，依 r/g/b 寫入設定。
測試以純藍 BGRA=(255,0,0,255) 通過原 get_pixel_color，得到 RGB=(0,0,255) 並 match=True；純紅 BGRA=(0,0,255,255) 轉成 RGB=(255,0,0) 並 match=False。不是只憑變數名稱推斷。

## 3. tolerance
color 公式是 all(abs(actual[i]-target[i]) <= tolerance)。目前 tolerance=20，Threshold=200 在 color 模式不參與判斷。
藍色 (0,0,255) 的允許範圍：R≤20、G≤20、B≥235。
示例 (10,15,230) 的 diff=(10,15,25)，在 tolerance=20 不命中；在 tolerance=30 命中。邊界採 <=，不是 <。

## 4. match 曾否為 True
實際桌面採樣：未見 True（0/8）。
合成藍色的原程式比對與 Tk 整合測試：True；這是明確標示的測試輸入，非遊戲實機成功證據。
遊戲顯示目標期間的完整 runtime 日誌：尚待你重新啟動新版診斷 GUI 並測試後取得。

## 5. match=True 為什麼沒有 Action
CONFIRMED source 與合成測試：
- DecisionEngine.observe 分別遍歷節點，只看該節點自己的 enabled/conditions[name]。
- Target True 上升沿只建立 Node_Target 自己的 pending。
- 到期後事件 command=None，GUI dispatch 走純監控分支，不呼叫 send_command。
- Action_1/Action_2 不受 Target 控制，它們必須各自在 (585,883)/(661,874) 通過 brightness：RGB 平均>200，才各自抽 25–60ms 延遲後送 q/e。
- 勾選 enabled 並不表示它們的視覺條件已成立；其儲存 RGB 在 brightness 模式不使用。
- 已送過的 True 狀態會 latch，直到先 False 再 True 才再次送；等待途中 False 會取消。沒有獨立 cooldown/debounce。
合成整合驗證：Target=藍色 True、Action_1/2=黑色 False → Target 到期 monitor_only、Action 自己條件不成立，假傳送器收到 0 筆。記錄 synthetic-blue-gui.jsonl / integration-test.json。
因此，這不是已證實的「Target 命中後被某個隱藏 cooldown 阻擋」；根本沒有 Target 驅動 Action 的那條連線。

## 6. 已加入的限速診斷
重新開啟 GUI、初始化 UDP、啟動監控後：
- diagnostics/node_target_runtime.jsonl：主程式實際執行的樣本與 trigger/dispatch 日誌；同時顯示於 GUI 日誌，不依賴 CMD。
- Target 約每 0.75 秒一筆，False↔True 立即輸出。
- Action 狀態/阻擋理由改變或 Target 邊沿時立即輸出一次，不在每次掃描重複洗版；dispatch 立即記錄。
- 記錄 actual/target RGB、diff、mode/tolerance、match、enabled、選中延遲/剩餘時間、latch、command、local queued 或 blocked 原因。
- trigger_requested_wait_random_delay：上升沿已排時間；waiting_random_delay：尚未到期；blocked_own_condition_false：自己不匹配；blocked_disabled：停用；blocked_rising_edge_latched_requires_false_then_true：持續 True 已鎖存；command_null_monitor_only：僅監控。
- queued 只代表原 UDP 佇列接受，不代表遠端 HID 已執行。
- 診斷寫檔/顯示失敗不會改變決策，但 diagnostic.last_error 可檢查；本次沒有重構決策或變更傳送行為。
注意 GUI 一旦真正在原機台場景啟動，原本獨立 Action 仍可能照既有設定發送。加入診斷不會禁用或額外觸發它們；本次我只使用暫存設定與假傳送器測試。

## 7. 問題位置（本機 source 行號）
- `gui.py def vision_loop_tick`：[517]
- `gui.py def dispatch_loop_tick`：[543]
- `decision.py def node_matches`：[29]
- `decision.py def observe`：[11]
- `decision.py def poll(`：[22]
- `vision.py def get_pixel_color`：[15]
- `vision.py b, g, r, a =`：[33]
- `vision.py return (r, g, b)`：[36]
- `config.json "Node_Target":`：[84]
- `config.json "Action_1":`：[98]
- `config.json "Action_2":`：[115]
- `target_diagnostics.py def scan(`：[31]
- `target_diagnostics.py def dispatch(`：[59]

## 8. 建議最小方案（未套用）
1. 先取得真正藍色目標顯示時的 runtime actual_rgb。若仍為灰/黑或座標偏移，優先確認螢幕座標、視窗位置、DPI、截圖是否可讀；目前無證據可直接指定其中哪一項為根因。不要盲目擴大 tolerance 讓灰色也通過。
2. 若需求是「Target 當 Action 的啟用門檻」，可在 GUI 計算完所有條件後、brain.observe 前，對指定 Action 的 conditions 做 AND Target 條件；保留其原 q/e mapping。這只是局部候選 patch，尚未套用，且 Action 自己條件仍需成立。
3. 若需求是「只要藍色 Target 出現就執行某一個 Action」，需明確指定 Action_1/2 的選擇規則與是否仍檢查它自己的條件；這與門檻不同，不能自行把 Target command 改成 E，否則可能與原 Action_2 重複送出。
4. 若希望持續命中就連續執行，需另行決定 repeat/cooldown，因現行上升沿設計不連發。本次不擅自改動。

## 測試與恢復
5 項新增診斷測試、原 10 項 Profile／時間戳測試及 7 項 UDP 測試通過。Tk 合成藍色/黑色整合通過，無實機網路指令。
備份位於 backups/target-diagnostic-20261101，含原始 SHA256、gui.py.diff。
如要移除診斷：關閉 GUI，用該備份 gui.py 覆蓋專案 gui.py；新增 target_diagnostics.py 可保留閒置。已在額外副本驗證恢復 SHA256，最終診斷版仍保留。
