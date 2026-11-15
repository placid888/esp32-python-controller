# Skill repeat after Min/Max Delay — 2026-11-01

## 修改範圍
僅 decision.py、gui.py、main.py。其餘 config/Profile 格式、Target gate 公式、固定數字 mapping、brightness/color、F8、UDP transport/protocol、DIAG、ESP32 均不變，已核對檔案／韌體來源 SHA256。

## decision.py 仲裁的具體差異
- observe：候選直接取 Target 與自身條件有效的技能，不再用 consumed latch 排除；固定優先順序不變，因此 4/6 同時 True 永遠優先 4。
- poll：只有到期且仍為目前最高優先候選才交出一次，使用 _inflight 防止同個 dispatch 週期或尚未回報完成時重複交出。
- 新 complete_dispatch：GUI/CLI 完成本機 queue 操作後，再抽 random.randint(min_delay,max_delay)，從完成時的 monotonic 時間重新排下一次，不沿用舊 scan 或舊 deadline。
- 每次重複都必須完整等新的延遲。失敗的 queue 嘗試也等下一個完整間隔，不 busy retry。
- 延遲中 Target/Skill False 或優先權變動：取消原 pending。若換成另一個候選，該候選從當下重新等待自己的延遲，不挪用前一個技能等待的時間。
- 保留空 latched 屬性供現有診斷讀取，不再參與選擇／阻擋；沒有新的 rising-edge 條件。

## gui.py / main.py
- dispatch_loop_tick 只有 pending 到期時，才額外重新擷取所有啟用節點的像素，使用原 node_matches，再呼叫 observe 仲裁，然後 poll。
- 因此不是只相信 50ms 前的 cached True；當時 Target/Skill 消失即不送，若更高優先亮起會改選並重新等延遲。
- 完成 send_command（本機 queue 接受或拒絕）後呼叫 complete_dispatch，保持每個 dispatch 週期最多一筆。
- CLI 使用同樣的到期重讀與完成回報，避免兩種入口行為不一致。
- 「成功」以現有本機 UDP queue 接受為界，不是新增 ESP32 ACK 後才重複。UDP/HID 實際送達無法由此保證，也無法撤回已送出的封包。

## 零延遲安全
Profile 格式未變，但重複模式的有效技能要求 Min Delay >=1 且 Max>=Min。
若目前選中技能 Min=0（包括 0/0），明確停止並顯示錯誤，不自動夾值、不以零延遲連發；請設定正數範圍。原本 25–60ms 等正數設定不受影響。
這是防零間隔 spam 的執行時安全檢查，沒有改寫使用者儲存設定。

## 測試
15 項 repeat 回歸通過：涵蓋你要求的十項，另含從 queue 完成時計時、優先權在等待中改變、重抽亂數範圍、零延遲 fail closed，以及真實 Tk 發送前新像素攔截/改選驗證。
額外真實 Tk + localhost UDP smoke 實際收到兩筆 {"action":"tap","key":"4"}，但未達測試要求的三筆，故此項 smoke 不計通過；原始失敗 log 已保留。不據此聲稱實際吞吐量或 ESP32 實機通過。
所有測試使用暫存設定，不修改現有 config，不發送實機 HID。
現有 MSS deprecated warning 未順便修改。

## 使用與恢復
先停止並關閉舊 GUI/CLI，再用原桌面捷徑啟動。無需刷 ESP32。
本修補包需搭配目前完整專案；目前專案使用 python gui.py 或 START_GUI.pyw。新操作語意以本文件為準，前版 rising-edge 說明屬歷史。
舊 latch 專用測試存入 backup historical-tests；本版執行 tests_udp/test_skill_repeat.py、tests_udp/repeat_udp_smoke.py。
backup 含修改前檔案、SHA256、三份 diff。若明確要回復單次 latch，關閉 GUI 後將 backup 的 decision.py/gui.py/main.py 複製回專案即可；不要覆蓋後來自行調整的 config。
恢復已在額外副本驗證 SHA256；最終 repeat 版本保留。
