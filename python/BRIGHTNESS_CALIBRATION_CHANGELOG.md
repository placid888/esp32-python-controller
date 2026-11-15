# Skill Brightness 自動校正 — 2026-11-01

## 修改檔案與範圍
新增 brightness_calibration.py（純分析＋只讀取樣worker）、calibration_ui.py（Tk校正區與事件交接）。
只修改 profile_ui.py 的Skill進階設定擴充，以及 gui.py 的校正工作清單、啟動Monitor互斥和關閉取消/等待。
正式detector.py、decision.py、vision.py、mark_opener.py、skill_model.py、profile_store.py、transport.py、hotkey_capture.py、main.py與ESP32 source均SHA256一致。
Target/Combat/Mark、印記A/B、Opener、priority、normal key mapping、deadline/revalidation、sampling/protocol沒有修改。未變更原config，沒有替任何現用Skill自動套Threshold。

## 取樣與數學定義
每次擷取暗或亮各15個有效frame樣本，目標每25ms取一組，14個間隔約350ms加截圖成本；不是在Tk逐格截圖。
背景CalibrationJob自己建立/使用/關閉GameVision/MSS；透過queue把結果交回主執行緒，沒有sender/UDP dependency。底層截圖慢時可能超過500ms，記錄真實duration，不偽稱固定硬期限。任何截圖失敗會使本次擷取失敗，不以不完整樣本建立建議。
沿用Skill現有X/Y（F8同一欄位）、進階視窗當下Sample Mode / Match Ratio。MSS BGRA→RGB與ROI邊界處理均由原GameVision.get_region_rgb，不改原引擎。
每個pixel亮度完全相同：brightness=(int(R)+int(G)+int(B))/3。
正式region判斷是 count(pixel_brightness > Threshold)/N >= Match Ratio，不是區域平均亮度。
因此校正每一frame用「第k亮pixel」作等價亮度，k為最小滿足k/N>=ratio的整數。例如3x3/0.30取第3亮；5x5/0.30取第8亮。這個值>Threshold與正式match完全等價。single_pixel就是唯一pixel的RGB平均。
統計min/max/mean/median是15個frame等價亮度的統計，不是把所有區域pixel任意平均。測試遍歷三種大小、多種ratio及0..255所有整數Threshold，確認等價。

## 建議與品質
suggested_threshold=floor((dark_median+bright_median)/2)，向下取整數；30與110→70。
bright_median<=dark_median：顯示無法安全建立Threshold，無建議值，套用禁用；不自動切模式。
separation=bright_median-dark_median；>=40良好，>=20可用但建議實測，<20警告可能不穩。這只影響GUI說明，不改正式detector。
overlap=(dark_max>=bright_min)。沒有重疊顯示樣本分離良好；有重疊顯示可能不穩，但median仍有效時允許使用者選擇套用。
很小差距、非整數亮度的整數化亦可能降低可分性；建議值不是保證準確，請依顯示品質實測。沒有在失敗時偷偷改color/red。

## GUI操作
1. 停止Monitor。確認所需Skill的X/Y已用F8設定，技能畫面可見且不被校正視窗遮住。
2. 使用者自行將該Skill Comparison Mode改為brightness。
3. Skill_4～Skill_0右側「設定」進階視窗下方有「亮度校正」。color/red時按鈕灰色，完全不自動切換。
4. 將圖示維持不可用/暗→「擷取暗值」；再維持可用/亮→「擷取亮值」。可重新擷取單組，或「重新校正」清除兩組。
5. 查看暗/亮各自min/max/mean/median、亮度差、建議Threshold、品質及overlap提示。
6. 「套用建議Threshold」只改主畫面該Skill的Threshold輸入框，不改RGB/tolerance/X/Y/sample/ratio/Delay/Enabled/command/其他Skill。
7. 最後按主畫面的「儲存設定」，使用原Profile保存流程。若另有手動改動進階設定，要另按原「填入」；那是使用者本來的編輯動作，不是校正自動改設定。
8. 校正結果為本次進階視窗的暫存資料，關閉後不保存summary；Threshold由原Profile保存。開啟新視窗可重新校正。

## 安全與一致性
Monitor運行中拒絕開始校正，顯示請先停止Monitor；校正worker仍在取樣/關閉時拒絕啟動Monitor。
座標、取樣模式、ratio、comparison mode或Profile在取樣前後變動時，結果失效，不能把舊樣本用到新設定。
所有Tk更新在main thread；worker無Tk/widget/UDP呼叫。關閉進階視窗取消取樣；關閉GUI會取消並以after等待工作結束，不以主執行緒join阻塞正常操作。
校正擷取本身不觸發HID。關閉GUI原有UDP release_all行為未更動。

## Diagnostics
CALIBRATION：skill/state、samples/min/max/mean/median、實際duration_ms、sample_mode、match_ratio。
CALIBRATION_RESULT：dark/bright統計、dark_median/bright_median、separation、suggested_threshold、valid、overlap、quality/warning。
CALIBRATION_APPLY：skill、old_threshold、new_threshold。
僅兩次擷取結束/分析/套用時由主執行緒記錄，沒有每frame洗log，不進正常dispatch loop。Monitor運行中不做校正diagnostic寫入。

## Profile相容
沒有新增必填config欄位或schema，profile_store.py完全未改；舊Profile不需calibration資料。每個Skill沿用自己的threshold，絕無全域threshold。
實際production config本次SHA256相同，測試套用/保存只在暫存Profile。

## 測試結果
新增tests_udp/test_brightness_calibration.py：27/27，exit0。
涵蓋median非最後樣本、反向/相等禁止、overlap兩種、Skill4/0隔離、只改threshold、color/red不切換、Monitor取樣互斥（模擬UDP已開亦不啟動Monitor）、舊Profile/保存重載、gate資料不變、印記/priority/transport/ESP檔案hash、region等價性、worker thread/count/錯誤/取消、GUI事件迴圈不中斷、座標變動作廢、gate editor沒有校正區與反向GUI禁用。
既有Hunter Mark：31/31；Combat：14/14；detector：16/16；transport：7/7（額外暫存副本、僅localhost）。
合計95項通過，未修改既有回歸測試以放寬結果。
真Tk render已檢查，截圖calibration-editor.png使用合成暗30/亮110，只作GUI與公式展示，不假裝實際遊戲已完成校正。
真實MSS smoke於桌面固定座標100,100，不向ESP32發送任何指令。三種模式各15個有效樣本，實際duration如下：
- single_pixel: 15 samples / 374.2 ms。
- 3x3: 15 samples / 365.0 ms。
- 5x5: 15 samples / 381.8 ms。
這只是取樣API驗證，不是遊戲暗/亮辨識的實機成功宣稱。

## 交付與恢復
備份：backups/brightness-calibration-20261101；含SHA256-before、safety-verification、gui/profile_ui差異、測試原始log、real-sampling-smoke.json、GUI截圖。
恢復：先關閉GUI，將備份gui.py與profile_ui.py複製回專案；新增兩個calibration模組舊入口不會引用，可保留。不要用備份config覆蓋後續使用者設定。
額外restore-check副本已驗證恢復後SHA256；現行修改保留。
重新開啟原捷徑即可，不需重燒ESP32。此次不進行其他功能開發，也未對實機送技能。
