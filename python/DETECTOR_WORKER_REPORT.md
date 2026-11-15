# 高速視覺 detector 修正 — 2026-11-01

## 根因與證據範圍
舊 gui.py 的 vision_loop_tick / dispatch_loop_tick 在 Tk 主執行緒逐點截圖，並同步呼叫 TargetDiagnostics.scan 寫 JSON / Text。after(10) 是最早回呼時間，不是硬期限；忙碌時回呼只能排隊。transport.py 原本在 sendto 前同步開檔寫證據，亦會延誤真正送出。
這是 source 確認的阻塞架構；未取得原先 1.7 秒情境的逐段 profiler，不能將該次全部時間歸因於單一函式。

## 實作
- detector.py：獨立非 daemon worker，建立自己的 MSS instance。DecisionEngine 只由 worker 擁有。monotonic deadline 與 Event.wait 取較近的 scan/deadline，與 Tk 排程無關。
- 每輪先 Target；False 不取技能。True 只取 Enabled Skills，合併其 ROIs 成一次截圖，再依固定 priority 仲裁。八節點不是八次 screenshot。分散座標的 bounding rectangle 可能較大，實測取決於桌面／解析度／節點位置。
- 到期仍重新取樣 Target 和所有 Enabled Skills，observe 重新仲裁再 poll；條件消失取消；優先權換人會重新等待該技能延遲。
- 持續 True 無 latch。每次送入本機 queue 後 complete_dispatch 重新抽 Min/Max，再下一輪重掃，最多一個 key。Min>=1、Max>=Min；零延遲仍 fail closed。
- gui.py：不再使用 Tk callback 做視覺 decision / dispatch。250ms bounded event drain；500ms snapshot；1秒 PERFORMANCE。disabled 沒有逐節點 scan DIAG。stdout redirect 也改為 queue，背景警告不得直接碰 Tk。
- vision.py：RGB region／batch API，BGRA 明確轉成 RGB。單點介面/F8 保留。
- profile_ui.py / profile_store.py：只增加 sample_mode / match_ratio，舊 profile default single_pixel / 0.30；schema_version、其他設定不變。儲存／載入前安全停止 worker，使用者需重新按啟動，避免半更新快照。
- main.py：CLI 同樣採用 worker，避免另一入口沿用慢掃描。
- transport.py：僅本地診斷改成獨立 bounded queue + writer，不在 sendto hot path 寫磁碟；新增本地 schedule metadata，絕不寫進 UDP JSON。sender 不等 Tk / ACK。
- decision.py 此次未更動；固定 Skill mapping、config.json、F8 source byte-identical。ESP32 未修改、未刷機、未測試實機按鍵。

## 診斷語意
PERFORMANCE：scan_count、scan_hz（session 累計）、avg_scan_ms/max_scan_ms（最近統計窗）、enabled_skill_count、pending_skill、pending_remaining_ms、dispatch_count、cancel_count。
GATE_DISPATCH：first_detected_time（本次 pending 建立時間）、chosen_delay_ms、deadline、actual_dispatch_time（呼叫 queue 的 monotonic 時間）、scheduling_error_ms。持續重複時 first_detected_time 為該輪新 pending 的起點，不是第一次看到技能亮起的永久時間。
UDP_TX：實際 bytes、deadline metadata、sendto_check_monotonic、真正送到 socket 前的 scheduling_error_ms。queue 接受不是 ACK 或 HID 完成；UDP_TX_RESULT 仍記錄 OS 結果。無法撤回已排入／已送出的封包。
檔案在 diagnostics/node_target_runtime.jsonl、diagnostics/udp_tx_runtime.jsonl。detector 的 event queue 滿時丟診斷而不阻塞偵測；sender 的證據 queue 滿時記 evidence_error，不阻塞送出。GUI 長時間無回應可能丟失部分顯示紀錄，不應拖慢 detector。
Stop 同步停止 detector 並取消 pending；關閉視窗等待 UDP/evidence writer 和 F8 結束。若底層截圖／檔案 API 本身卡死，仍需等待底層返回，無法宣稱硬即時或強制安全中斷。

## 取樣設定
技能右側「設定」→「Sample Mode」single_pixel / 3x3 / 5x5 → Match ratio (0 < ratio <= 1) →「填入（尚需儲存設定）」→「儲存設定」→重新啟動監控。
F8 X/Y 是中心；桌面邊界時 ROI 向內夾到有效範圍。3x3 預設0.30需至少3/9符合；5x5需至少8/25。每個 pixel 用既有 RGB tolerance / brightness > threshold / red > threshold，再算符合比例，不是全區平均亮度。single_pixel 沿用原行為。

## 測試（無 ESP32）
- tests_udp/test_detector_worker.py：16項通過，包含需求15項及 GUI 區域參數儲存重載。GUI stall test 建立真 Tk，但刻意1.4秒不處理主執行緒事件。
- 既有 transport regression：7項通過，在暫存專案執行，僅 localhost。golden transport SHA 因診斷解耦而更新；舊測試原檔在 backup。
- tests_udp/detector_localhost.py：24筆真 localhost UDP 通過；證據 writer 每筆額外 sleep30ms，仍不阻塞 sender。只收到固定數字4，沒有 q/e。
- 固定 mapping／F8／現有 config SHA256 不變，production AST 無 literal key=q/e dispatch，source compilation、GUI 實際 render、額外副本恢復校驗通過。
- 舊 Tk timer 專用 repeat tests 移至 backup/historical-tests；不將舊測試偽稱仍適用本 worker。

### 50ms Min=Max 的量測
|條件|dispatch 數|scan Hz|平均誤差 ms|最大誤差 ms|
|---|---:|---:|---:|---:|
|模擬像素＋假sender；Tk停頓|22|64.74|12.22|14.61|
|真MSS八節點，假sender|44|27.95|16.64|18.95|
|模擬像素＋真localhost sendto|24|不另計|26.34|28.89|

以上誤差是在設定50ms之外多出的時間，例如16.6ms誤差約等於66.6ms派送，而非16.6ms總延遲。不是實際遊戲／ESP32鍵盤完成時間。
本機 MSS 未達10–20ms目標；合併截圖由約6Hz提高到約28Hz（約36ms/輪）。可合理消除 GUI/log 秒級排隊，但更短的亮起脈衝仍可能漏判。不同坐標分布、GPU負載、視窗模式、Windows scheduler 都會改變結果；需看實機 PERFORMANCE，不保證相同 Hz。

## 啟動與實機前準備
1. 關閉所有舊 GUI/CLI，再開原桌面捷徑（仍指向本專案），不用重燒ESP32。
2. 檢查 Profile、Target、Enabled技能、F8座標、delay>0；新取樣預設單點，先不要大幅調整全部參數。
3. 先在不會造成危險操作的測試視窗短時間測試，核對 UDP_TX key 及 ACK，再測目標軟體。不要直接開始無人值守連發。
4. 保存／切換設定會停止監控，確認後手動再啟動。
5. 本次未連線ESP32，未對實機大量送鍵。

## 交付與恢復
backup：backups/detector-worker-20261101；SHA256-before.json、diff、tests.log、timing-result.json、real-mss-timing.json、localhost-result.json、localhost-tx.jsonl、editor.png。
恢復：先關閉程式，將 backup 的 gui.py/vision.py/main.py/profile_ui.py/profile_store.py/transport.py 複製回專案；detector.py 是新增檔，舊入口不會引用它。保留現用 config，不要覆蓋後續調整。恢復已在額外副本驗證，現行修改保留。
