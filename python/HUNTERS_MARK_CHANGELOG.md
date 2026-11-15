# Hunter's Mark 開場技能 — 2026-11-01

## 修改範圍
修改 skill_model.py、profile_store.py、profile_ui.py、detector.py、gui.py、main.py；新增 mark_opener.py。
新增 tests_udp/test_hunters_mark.py、tests_udp/mark_perf_smoke.py。未新增 Skill_3。
Opener_Mark 是 mark_opener.OpenerMark 的獨立 retry deadline，不在正常 Skill priority，也不是視覺節點。沒有 mark_pressed／成功 latch；唯有這一輪 Node_Mark 讀到 True 才算完成。

## 預設與設定
Node_Mark：Enabled=true、X=0/Y=0（未採集）、color、RGB=(0,255,0)、Tolerance=20、Threshold=200、single_pixel、Match Ratio=0.30、command=null。
沿用狀態節點資料結構的 Min/Max 欄位，但它們不控制 opener。Node_Mark 本身永不送 HID。
Hunter's Mark Key：預設3，GUI可改；本版驗證一個可列印ASCII字元，不宣稱支援 F1 等多字元名稱。它只改獨立 opener，不改正常數字映射。
Retry Delay：預設500ms，接受1..60000ms正整數；拒絕零間隔。使用者若自行設極短間隔仍會增加送鍵頻率，正常使用請保留合理重試間隔。
Hunter Mark mode：off（關閉）/ pre_combat（A－開戰前印記）/ post_combat（B－開戰後印記）。
Spell ID 257284 是使用者提供的已驗證資訊，僅文件/diagnostic；不存取WoW API。

GUI Profile下方新增「獵人印記模式」「Hunter's Mark Key」「Retry Delay (ms)」。Node_Mark 在節點表最後一列，可選F8、設定RGB/Tolerance/Threshold及region/ratio。按填入後仍需儲存設定；保存/重載沿用既有停止監控機制，需手動再次啟動。

## 開戰流程
|印記模式|開戰方式|正常技能必要條件|Opener 條件|
|---|---|---|---|
|OFF|Auto|Target|不使用、不取樣Mark|
|OFF|Manual|Target AND Combat|不使用、不取樣Mark|
|A|Auto|Target AND Mark|Target AND NOT Mark|
|A|Manual|Target AND Mark AND Combat|Target AND NOT Mark，可在Combat之前|
|B|Auto或Manual|Target AND Combat AND Mark|Target AND Combat AND NOT Mark|

A：先Target→Mark。缺印記時只做Opener，不掃正常Skills。真正讀到Mark=True後才往下依原combat mode判斷；A+Manual會等玩家第一下。
B：先Target→Combat；Combat=False時不取樣Mark/Skills。Combat=True再讀Mark，缺Mark時只有Opener能送；確認Mark=True才讀正常Skills。
B本身要求Combat，即使正常combat mode選Auto也不會在Combat前印記/攻擊，需其他操作先進戰；這是B模式的指定條件。

每個step先用本輪新取樣呼叫原brain.observe。印記未滿足時無任何正常Skill match，故取消既有normal pending；Opener處理在normal poll之前，且同step禁止同時走Opener和正常dispatch。正常數字鍵仍4>5>6>7>8>9>0，原Min/Max及連續成立重複觸發不改。

## Deadline / retry / cancellation
首次符合Opener條件，完成本輪Target/Mark（B另有Combat）新取樣後立即嘗試一次，仍走既有send_command。
每次本機queue嘗試之後（接受或拒絕皆同）重新設定 now+Retry Delay，期間持續讀取狀態但不重送。到期這一輪一定再次新取樣、驗證模式/Gate/Mark才可重試。
Mark=True會取消多餘retry，並放行必要的combat gate及正常arbitration。UDP ACK不被當作Mark成功。
Target=False取消opener retry及normal pending；B的Combat=False亦取消retry。再次有Target/Combat時重讀Mark，不保留上一個目標的成功記憶。Mark True→False會中止正常pending並回到opener requirement，不會同step先送Skill。
Node_Mark disabled而模式開啟：fail closed，既不盲目按印記也不放行正常技能，diagnostic reason=mark_node_disabled。OFF不受它影響。
Stop Monitor停止worker並清理兩種pending。只能取消尚未排入UDP queue的事件，不能撤回已排入/已交OS/已執行的按鍵。下一次取樣發現失效即取消，不宣稱硬即時。

## Diagnostics
沿用bounded queue及低頻snapshot/Performance，不在worker同步寫檔或碰Tk。
VISION_SNAPSHOT 新增 hunter_mark_mode、opener_key、spell_id、Node_Mark、opener_complete；Gate為加入Mark需求後的有效Gate。
reason包括 waiting_for_hunters_mark、waiting_for_post_combat_mark、waiting_for_combat、target_false、mark_node_disabled、gate_open。
OPENER_DISPATCH：node=Opener_Mark、key、hunters_mark_missing、retry_delay_ms、deadline、actual_dispatch_time、queued/queue_rejected。
OPENER_CANCEL記錄retry被取消。GATE_DISPATCH保留原欄位並加Mark讀值/模式。PERFORMANCE保留原欄位並加 hunter_mark_mode / opener_pending_deadline。
未取樣的Mark/Combat顯示null，不偽裝為實測false。真實UDP bytes/ACK evidence仍由完全未變的transport.py記錄。

## Profile migration
缺Node_Mark就補上述預設；hunter_mark_mode預設off，key=3，retry=500。既有自訂值不覆蓋；Target/Combat、正常Skill、IP/Port、LCD、Profile名稱及其他欄位保留。兩個gate與Mark command都強制null，Skill command仍固定數字。
原config.json本次byte-identical；不由修補腳本覆寫。下次GUI正常讀取時會使用既有migration/保存流程補欄位；預設OFF，舊Profile實際行為不變。schema_version沿用3，僅增加向後相容欄位。

## 實際執行測試（均無ESP32實機）
1. python tests_udp/test_hunters_mark.py：31/31，exit0。涵蓋指定23項（其中既有UDP regression另列於第4項），再加disabled fail-closed、queue拒絕限頻、GUI/F8/設定重載、保留自訂、驗證輸入、換目標、可改key/retry，及真localhost Opener按3/ACK驗證。
2. python tests_udp/test_node_combat.py：14/14，exit0。
3. python tests_udp/test_detector_worker.py：16/16，exit0。原取樣比例、deadline、GUI停頓、priority、repeat測試全過。
4. python tests_udp/test_transport.py：7/7，exit0。在額外暫存完整副本執行，只localhost，避免寫入現用diagnostics。
合計68項通過。沒有修改既有測試來放寬結果。未連線ESP32/未對實機送鍵。
source compile、GUI控制列/Mark editor render已檢查；進階文字增加wrap避免截斷。

## 真實MSS效能短測（假sender、鄰近ROI、可控always-match）
|條件|scan Hz|
|---|---:|
|修改前（印記尚不存在，Auto）|28.21|
|修改後OFF，Auto|28.34|
|修改後A，Mark已成立、Auto|18.08|
|修改後B，Combat/Mark已成立|13.30|

OFF沒有顯著下降，確定不額外取樣Mark。啟用A/B的完整有效路徑有明顯下降：依指定短路順序，A多一次Mark截圖，B比原Auto多Combat與Mark截圖；不是GUI排隊造成，沒有隱瞞為30Hz。若Gate不滿足，照要求停止後續採樣，沒有浪費正常Skills截圖。這些不是遊戲實測，各節點分布/OS/GPU負載會改變速率。此次不擴大重構原screen sampling來追求速度。

## 未改證據與恢復
backups/hunters-mark-20261101/SHA256-before.json、safety-verification.json確認decision.py、transport.py、vision.py、hotkey_capture.py、config.json、ESP32 src/main.cpp byte-identical。SKILL_PRIORITY、SKILL_KEYS及skill_command AST一致；無Skill_3，未復活Action_1/Action_2路徑。自訂opener key是明確獨立設定，不是舊q/e mapping。
備份含原六份修改檔與依賴、diff、原始測試log、效能JSON、GUI截圖。restore-check在額外副本驗證原檔SHA256，現行修改保留。
回復：先關閉GUI/CLI，再將備份skill_model.py/profile_store.py/profile_ui.py/detector.py/gui.py/main.py複製回；mark_opener.py是新增檔，舊入口不引用它。不要拿備份config覆蓋使用者後來的設定。

## 使用
先關閉舊GUI/CLI再開原捷徑，不用重燒ESP32。
舊Profile預設OFF。要啟用時，F8取得Node_Mark綠色方塊座標、確認RGB/取樣與ratio、選A/B及key/retry、保存後重新啟動監控。
A+Manual可先印記再等玩家開戰；B必須先進Combat。先做短時間、安全情境測試並查看Node_Mark實讀值，不把ACK當成功。
