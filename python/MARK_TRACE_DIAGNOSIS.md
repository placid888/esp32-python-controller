# Hunter's Mark / 按鍵3 — 純診斷部署

## 本階段完成與界線
沒有修復／改變 Hunter's Mark A/B、500ms Retry、sampling、Target/Combat/Mark、技能優先級、Delay、HID、UDP wire JSON、WeakAuras、ESP32。
只在既有分支加入不可影響正式流程的診斷observer。
尚未執行使用者的A→技能4→B實機重現，因此不宣稱已確診實際30次的原因。

## 修改檔案
- detector.py：既有scan結果／opener嘗試／pending取消與結果的旁路trace呼叫。取樣及gate演算法不改。
- gui.py：採用既有ESP32Controller的observer子類、傳遞trace與profile/session context。沒有新增或改動GUI互動、熱鍵或技能行為。
- 新增mark_trace.py：bounded非阻塞queue、背景JSONL writer、node狀態變化與sendto旁路證據。
- 新增tests_udp/test_mark_trace.py：18項診斷／隔離／等價／localhost測試。
- logs/mark_trace.log：獨立append log，預先建立；真正Monitor重現資料尚待收集。
transport.py、mark_opener.py、decision.py、vision.py、config.json及ESP32 source逐byte未變。

## Log位置與操作
`C:\Users\USER\Desktop\a\logs\mark_trace.log`
請先停止並關閉舊GUI，重新開啟同一專案，才能載入新診斷。沒有替你重啟或啟動實機監控。
每次Monitor start產生新的session UUID、SESSION START；stop/error產生SESSION END。
SESSION包含pid、sys.executable、config絕對路徑、Profile、class/spec、mode/retry。

正常trace預設開啟，verbose預設關閉。需要逐tick時，用PowerShell啟動：
```powershell
$env:DEBUG_VERBOSE_MARK='1'
& 'C:\Users\USER\AppData\Local\Programs\Python\Python314\pythonw.exe' 'C:\Users\USER\Desktop\a\START_GUI.pyw'
```
停用逐tick：將值設'0'，以同方式重新開啟GUI；新程序未設定此變數也預設關閉。
不修改Profile格式。Verbose會大量輸出，僅短時間重現時開啟。

## 每筆意義
- TARGET_STATE / COMBAT_STATE / MARK_STATE：只在該節點本輪真的取樣且首次觀察／boolean變化時記錄；previous=null代表初始觀察，不冒稱false→true。
- MARK_STATE／MARK_TRACE包含Node_Mark座標、mode、expected RGB、中心actual RGB、tolerance、threshold、sample_mode、設定match_ratio、matching/total pixels、實際比例及final_match。
  區域模式的actual_rgb是中心像素，不冒稱整個區域每個pixel。
- MARK_TRACE：opener真正走進發送分支前的證據，包含monotonic/decision時間、target/combat/mark、mode、retry、elapsed、pending deadline、fresh scan revalidation、selected skill、normal pending與前次pending。
  action=SEND_3_PREPARE只代表準備／佇列嘗試，不等於已送出。
- reason=mark_missing_first_attempt：本session第一次嘗試。
- reason=mark_missing_retry：既有pending截止時間到期，Mark仍缺失。
- reason=mark_missing_rearmed_after_cancel：先前pending取消／Mark成功後，再次缺失而重新進入既有observe()即時排程。
- MARK_RETRY：真正retry分支。
- MARK_PENDING_CANCEL：診斷reason分清target_false、mark_detected_success、combat_false等；保留original_gate_reason。沒有修改舊cancel邏輯。
- NORMAL_PENDING_CANCEL：取消的技能／前次pending／具體gate原因。
- MARK_QUEUE_RESULT：queue accepted/rejected，拒絕後原程式同樣仍等待Retry，不忙重試。
- MARK_UDP_BEFORE_SENDTO：原sendto bytes與tx_id、source、destination。可能包含would_block重試，不能當作已送次數。
- MARK_SEND：僅在原transport已成功sent_to_os後增加MARK_SEND_SEQ，每session從1開始。含原因、狀態、raw bytes、tx_id與monotonic時間。
- MARK_UDP_RESULT：would_block/socket_error，不增加成功sequence。
- 已排進UDP佇列的封包不能由Stop回收（原行為）；若SESSION END後才真正送出，仍歸屬原session，並標after_session_end=true。
- GUI／其他來源手動送3亦會捕捉，reason標non_opener_or_missing_trace_context及source；其latest scan context非fresh revalidation，不偽裝成opener。

正式UDP JSON仍是`{"action":"tap","key":"3"}`，sequence只在本機log/context，不進入wire。原ACK不含seq，所以sent_to_os不是HID已執行的證明。
與既有diagnostics/udp_tx_runtime.jsonl可透過tx_id對照。

## 重要限制：Combat可能是null，而非false
現有scan()在A模式先讀Target、Mark；Mark缺失立即return，因此SEND3時不會額外讀Combat。
A+Auto即使Mark成立，正常路徑也不需要Combat sample；A+Manual只有Mark成立後才可能掃Combat。
本次沒有新增額外螢幕擷取。combat=null、combat_observed=false表示本輪未取樣；不能解讀成「不在戰鬥」。
原opener_allowed(A)不要求Combat，所以A模式在戰鬥中仍可因Mark缺失重試；這是已存在的source行為，本次未改。

## Target identity稽核
**確認不支援辨識目標identity改變。**
GameVision只讀設定ROI，Node_Target只有比對後的boolean。source沒有GUID、姓名、target ID或換怪訊號。
A→B若畫面一直維持「有Target」，讀值true→true，不會產生TARGET_STATE transition。
因此現有程式無法把嘗試／成功綁定到A或B，也無法僅以Target重新arm。
但OpenerMark本身不是完成後永久鎖住的target latch：它只有pending deadline。
mark=true使observe(false)取消pending；之後mark=false且opener_allowed成立就立刻重新排程；持續mark=false則每Retry週期嘗試。
所以缺identity是明確的觀測盲點，不能單憑它斷言就是本次30次的根因，也沒有加入target-change workaround。

## 下一次重現建議（不改設定）
1. 記下開始時ESP32的3 CNT，啟動Monitor後辨認最新SESSION START。
2. 按原操作A→印記出現→技能4→選B重現。
3. 停止Monitor，等約1秒讓診斷queue寫完，記下3 CNT終值。
4. 提供mark_trace.log與diagnostics/udp_tx_runtime.jsonl。
5. 比較該session MARK_SEND筆數與ESP32 3 CNT「增量」，不是直接比自開機累積總數；排除手動3及其他來源。
   UDP累積數還包含LCD等有效控制封包，不能把UDP96直接視為96次按鍵3。
6. 日誌可辨別持續mark=false的500ms retry，或mark true/false波動造成cancel/rearm；目前不預判是哪一種。

## 非阻塞與故障隔離
detector/UDP observer只做snapshot與put_nowait；檔案open/write由mark-trace-writer執行。
queue上限8192，滿時丟診斷並累計dropped/error，絕不阻塞正式sender。
observer所有例外隔離；磁碟寫入失敗、queue滿、observer拋錯都不得阻止正式命令。
writer為daemon，退出時最多等1秒；極端磁碟故障／退出可能失去診斷，但不改控制流程。

## 驗證與產物
- 新增18項：原因/retry/elapsed、Mark雙向、Target/Combat transition、sequence、would_block不算成功、sampling/decision等價、writer故障、observer故障、queue滿、session、verbose、target identity盲點、localhost wire JSON、source scope hash等。
- Hunter's Mark既有31項已通過。
- 全套結果另見TEST_RESULTS.md與all-tests-delivery.log；不會因整檔SHA凍結測試或F9環境占用而冒稱全綠。
- verification.json：只有既有gui.py與detector.py改動；sampling/gate五個函式AST完全相同，其他保護source與ESP32 SHA不變。
- 原始函式／line位置：{"detector.py:def scan": [56], "detector.py:opener.observe": [98], "detector.py:opener.attempted": [112], "mark_trace.py:def scan": [59], "mark_trace.py:def attempt": [70], "mark_trace.py:def snapshot": [46], "mark_trace.py:def _record_tx": [105, 121], "mark_trace.py:def _record_tx_result": [121], "mark_trace.py:def begin": [32], "mark_trace.py:def end": [40], "gui.py:mark_trace=self.controller": [448], "mark_opener.py:def attempt": [25], "mark_opener.py:def observe": [20], "mark_opener.py:def attempted": [25]}。
- 備份、SHA、diff、測試紀錄：`C:\Users\USER\Desktop\a\backups\mark-trace-20261101`。
- restore-source.ps1已在額外副本執行並驗證bytes一致；不刪log，不刷機；回退後新增trace module不再被runtime引用。

沒有實機HID測試，只有本機127.0.0.1 UDP測試；沒有刷ESP32、commit或push。本階段停止，等待實機trace。
