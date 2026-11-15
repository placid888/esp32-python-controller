# Skill 4–0 視覺監控 — 2026-11-01

## 必讀
**先停止並關閉全部舊 GUI/CLI，再從原桌面捷徑重新開啟。舊行程的記憶體不會因磁碟改版而更新。**
新版不需要重燒 ESP32。本次沒有對 ESP32 發送任何按鍵，沒有修改韌體／USB HID／UDP protocol。
原始專案已更新：C:/Users/USER/Desktop/a。桌面 ESP32 UDP 控制台捷徑仍可用。
完整 ZIP 解壓後用 `python -m pip install -r requirements.txt`、`python gui.py`，或 pythonw 執行 START_GUI.pyw。

## 新資料結構
schema_version=3，維持 last_used/profiles；每個 Profile 的 nodes 只有八個：
Node_Target、Skill_4、Skill_5、Skill_6、Skill_7、Skill_8、Skill_9、Skill_0。
每個節點保有 enabled/x/y/mode/threshold/r/g/b/tolerance/min_delay/max_delay/command。
例如 Skill_6：
```json
{"enabled":false,"x":0,"y":0,"mode":"brightness","threshold":200,
 "r":255,"g":255,"b":255,"tolerance":20,"min_delay":25,"max_delay":60,
 "command":{"action":"tap","key":"6"}}
```
Node_Target 的 command 永遠 null，只有 gate，不直接觸發 HID。
Skill command 固定為同名數字（4/5/6/7/8/9/0），進階 GUI command 為唯讀，不能編成字母。
brightness=RGB 算術平均，嚴格 > threshold；color=三個 RGB 差值各 <= tolerance；red 相容模式仍保留。
F8：先在節點右側選取、啟用採集，切至目標視窗按 F8，填入該技能 X/Y/RGB，再儲存；不自動改變比較模式、threshold 或送按鍵。

## 優先仲裁與 latch
集中設定：skill_model.py / SKILL_PRIORITY = 4 > 5 > 6 > 7 > 8 > 9 > 0；按鍵由技能名稱產生，不會因調整優先順序而錯換鍵。
實作：decision.py / DecisionEngine.observe、poll。
- 有效條件：Target enabled AND Target match AND Skill enabled AND Skill 自己 match。
- 任一有效條件 False 會解除該技能 latch；Target False 取消所有待送。
- 在有效且尚未消耗的技能中，選最高優先者。全引擎最多一筆 pending；只有此技能抽 random.randint(min,max)，用 monotonic 時間戳等待。
- 較高優先技能在較低者等待中變亮時，會取消較低者的 pending、先等較高者的新隨機延遲；較低者不被 latch。
- poll 每次最多交出一筆，只有交出者才 latch。未選中的技能保持資格，不會永久鎖死。
- 例：4/6 同時亮，第一輪只送 4；4 已消耗並 latch 後，下一輪仍亮的 6 可以被選中。不是同輪連送，也不是讓已觸發的 4 永遠餓死 6。
- 全部持續亮時最多各消耗一次，不會無限 spam；需有效條件先 False 再 True 才可重新發。
- 保留既有 UDP 失敗不自動重送安全語意：交出到 dispatch 後即消耗該次 edge，即使本地 queue 拒絕也不盲目再發。
- GUI dispatch 再驗技能名稱、固定 command、最近掃描的 gate/own enabled/條件，每次最多處理一個技能。不是硬即時重新截圖，不能撤回已進 UDP 的封包。
- CLI main.py 也使用同一個引擎與固定 command 守門，不存在舊遊戲 rotation/filler 分支。

## Profile migration
profile_store.py / migrate：
- 對全部 Profile 遷移，保留名稱、last_used、Node_Target 完整有效設定、UDP IP/Port、LCD 電源與字型文案等其他資料。
- 舊 Action 節點與 Node_HP 不保留於新監控 nodes；不搬座標/條件/command 到任何 Skill，避免混淆。
- 新 Skill 一律預設停用；需自行 F8 採點並設定條件、啟用、儲存。
- 已存在的 Skill 設定可保留，但 command 一律正規化回固定數字；Target command 強制 null。舊 q/e 不會從 config 復活。
- GUI 啟動會把需要遷移的結構原子保存。config.example.json 為完整雙 Profile 範例，勿用它覆蓋自己的實際設定。

## DIAG 與 sendto 證據
target_diagnostics.py 保留 RGB/brightness/mode/threshold/tolerance/match、Target/Gate、priority_selected、blocked_by_priority、latch、HID key、選定延遲與 blocked/queued 原因，按狀態改變／限速輸出。
原 GUI/transport 啟動來源與真實 sendto bytes 診斷保留；來源節點現在是 Skill_4 等。transport.py 本次逐 byte 未改。
檔案：diagnostics/node_target_runtime.jsonl、diagnostics/udp_tx_runtime.jsonl。
舊日誌可能包含歷史 q/e；請按新版 GUI_RUNTIME_SOURCE/PID/時間分辨，不將歷史行當成新 TX。
queued/sent_to_os 不等於 ESP32 已執行 ACK。

## 驗證與修改檔
- 新增 skill_model.py。
- 修改 profile_store.py、decision.py、gui.py、profile_ui.py、target_diagnostics.py、main.py、config.json、config.example.json。
- transport.py、hotkey_capture.py、LCD helper、ESP32 main.cpp 均未修改。
- test_skills.py：20 項測試，含所要求的 13 種案例，以及 loser 不錯誤 latch、七技能每輪一鍵、等待中優先搶占、Target 停用、全部 Profile 保留與舊 command 正規化。
- skills_gui_udp_smoke.py：真實 Tk、7 個 F8 結果自動填入、Profile 保存、4/6 同亮只排 4、拒絕注入字母 command、真實 localhost UDP bytes/來源證據一致。
- 圖片為真實 Tk 暫存測試 Profile，不是覆蓋你現有參數的證據。檢查 1100x900 與 1020x720，較小高度請向下捲動。
- 搜尋 active root Python AST，沒有 key=q/e 字面 command；GUI/CLI 都只能從固定 Skill 產生視覺指令。transport 本身仍是通用 API；外部另寫腳本或繼續執行舊行程，不屬於已移除的新版視覺路徑。
- 舊版 Action 專用測試移至 backup historical-tests，避免把舊規格測試當新規格；保留原始結果與來源。
- 無實際遊戲/ESP32按鍵測試；不宣稱已驗證遊戲畫面或所有 Wi-Fi 環境。

## 備份與恢復
backup 含原檔、原 SHA256、diff 與 restore_previous.py。已在額外副本核對全部 SHA256，最終版本保留。
恢復：關閉 GUI 後 `python backup/restore_previous.py --target <原專案目錄>`。
**此為完整舊版回滾，會恢復舊 Action/q/e 映射，僅供明確回滾使用；不是正常啟動步驟。**
