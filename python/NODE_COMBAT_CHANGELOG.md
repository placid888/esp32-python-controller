# Node_Combat 最小增量修改 — 2026-11-01

## 修改檔案
- skill_model.py：僅增加 GATE_NAMES / NODE_NAMES 中的 Node_Combat；SKILL_PRIORITY、SKILL_KEYS、skill_command AST 與原版一致。
- profile_store.py：新增預設 Combat、補缺 migration、combat_mode 驗證；保留原 Profile 結構/schema_version=3；Target/Combat command 強制 null。
- profile_ui.py：Profile 下新增「開戰方式」下拉選單，節點表新增 Node_Combat，沿用原進階設定/F8；表尾行號依節點數調整避免重疊。保存、重載、切換與未儲存提示包含 combat_mode。
- gui.py：將目前 Profile mode 傳入 worker，啟動診斷記錄 mode。
- main.py：CLI 傳入同一 Profile mode。
- detector.py：Auto 不取 Combat；Manual 先 Target、再 Combat、通過才取原有 Enabled Skills。仍在背景 worker、原 deadline、重新取樣及仲裁流程。
- decision.py：observe 增加 optional combat_mode='auto'；Target 原始狀態不混用 Combat，Skill_Gate 表示有效 gate；poll/complete_dispatch 使用有效 gate。priority、延遲、repeat 不改。

## 預設
Node_Combat：enabled=true、x=0、y=0、mode=color、RGB=(255,0,0)、tolerance=20、threshold=200、sample_mode=single_pixel、match_ratio=0.30、command=null。
座標0,0只是尚未採集的預設，不代表實際紅色方塊位置。沿用 gate 共用欄位 min_delay=25/max_delay=60，但 Combat 本身不建立任何送鍵事件。

GUI：最上方 Profile 區塊下方「開戰方式」→「自動開戰」/「手動第一下」。變更後按「儲存設定」，再手動重新啟動監控。Node_Combat 在原節點表最後一列，可以單選 F8 採集，右側「設定」使用原 RGB/tolerance/sample/ratio editor。

## Gate 與安全
Auto：Enabled Target match=True。Combat 完全不取樣、不阻擋，維持原取樣路徑。
Manual：Enabled Target match=True AND Enabled Combat match=True；Combat disabled 時 fail closed，不以 disabled 當作通過。
每輪重讀，Combat false / Target false / 優先權或技能失效時 observe 清除 pending；到期仍使用該輪新取樣重新驗證。沒有戰鬥 latch。再次進戰會重新等待完整 Min/Max Delay，不沿用上一場 pending。
持續成立仍 repeat；每輪最多一鍵，固定4>5>6>7>8>9>0，只有七個 Skill 能進 skill_command。Combat/Target 永不進 HID mapping。
「立刻停止」是下一次背景取樣偵測到 False 即取消尚未送入 UDP queue 的 pending；不可撤回已送出的封包，也不宣稱硬即時。

## Migration
舊 Profile 缺 Combat 時補上述預設，缺 combat_mode 時補 auto；原 Target/Skill 的座標、顏色、取樣、delay、IP/Port 等保持。已存在自訂 Node_Combat 或 mode 保留，不重置。
現有 config 不由修補腳本覆蓋。工作期間觀察到現用 config 經 GUI 更新並新增 Profile／完成 migration，故它不再與工作開始備份 byte-identical；已保留現況，沒有以備份覆寫。

## Diagnostics
VISION_SNAPSHOT 包含 Node_Target、Node_Combat、combat_mode、Gate、reason、priority_selected 與原 conditions/details/arbitration。
Manual 等待 reason=waiting_for_combat；Target 無效 reason=target_false；有效 reason=gate_open。
Auto Node_Combat=null 表示未取樣，不是偵測為 false。Target false 而跳過 Combat 時也用 null，避免偽造讀值。
GATE_DISPATCH 記錄 mode 與兩個 gate 讀值；PENDING_CANCEL 原機制保留；PERFORMANCE 原欄位保留並增加 combat_mode。沒有把畫面取樣移回 Tk，也沒有新增高頻同步寫檔。

## 實際測試
- tests_udp/test_node_combat.py：14/14 通過；涵蓋要求10項，再加 Combat disabled、跨戰鬥完整新延遲、保留自訂Combat，以及真Tk GUI保存/重載/F8事件填入。
- tests_udp/test_detector_worker.py：原有16/16通過，含取樣比例、持續repeat、到期recheck、GUI停頓隔離。
- tests_udp/test_transport.py：7/7通過；在額外暫存副本執行，只用localhost。
共37項通過。未連線ESP32，未對實機送鍵。
- Auto 真MSS＋假sender，所有Skills enabled、鄰近ROI，短測試：修改前24.74Hz、修改後27.02Hz。此為OS/桌面負載影響的短測試，不宣稱新功能提高速度；Auto確定沒有新增Combat截圖，未見退化。Manual多一次Combat screenshot，可能較Auto慢，未承諾同樣30Hz。
- source compilation通過；GUI render已檢查（畫面受當時其他視窗覆蓋，不能當完整無遮擋版面證明）；檔案差異及額外副本恢復校驗通過。

## 未改與恢復
transport.py、vision.py、hotkey_capture.py、ESP32 src/main.cpp SHA256均與工作前一致。UDP JSON/IP/Port/ACK程式完全未改；不恢復q/e，不恢復rising-edge。
備份：backups/node-combat-20261101，含原檔、SHA256-before.json、七份diff、三組測試log、auto-perf-comparison.json、safety-verification.json。
若需恢復：先關閉GUI/CLI，將備份的七個修改檔複製回專案；保留目前config，不要覆蓋使用者後續調整。已在restore-check額外副本驗證恢復SHA256；現行修改保留。

## 使用
關閉舊GUI/CLI後重開原捷徑，不用刷ESP32。
預設自動開戰，舊設定可直接沿用。要使用手動第一下：F8採集紅色方塊至Node_Combat，核對RGB/tolerance/sample/ratio，選手動第一下、儲存，再啟動監控。
先在安全測試情境確認 waiting_for_combat → gate_open → 戰鬥結束取消pending，不需修改任何數字鍵mapping。
