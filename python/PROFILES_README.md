# IoT UDP Profiles / 8 Nodes / Randomized Trigger Delay

## 啟動
先關閉舊 GUI，再用原桌面「ESP32 UDP 控制台」捷徑啟動；現有捷徑仍指向更新後專案。不需要重新燒錄 ESP32。
完整可攜原始碼解壓後：`python -m pip install -r requirements.txt`，再雙擊 `START_GUI.pyw` 或 `python gui.py`。
Python 需包含 Tk；原桌面捷徑是本機絕對路徑，不是可攜 ZIP 內容。無 CMD 啟動仍使用 pythonw，錯誤記錄 gui-startup.log。
本次未刷機、未 commit/push，未傳送任何實機 HID 動作。

## Profiles
config.json 已從原平面結構遷移成 schema_version / last_used / profiles。
- 舊座標、threshold、Q/E 的 RGB/tolerance、LCD 自訂文案/字級、休眠設定、IP/Port 全部保留在 Default。
- 原 hp_bar→Node_HP、target→Node_Target、skill_q→Action_1、skill_e→Action_2。
- last_used 在每次切換時立即持久保存，正常關閉後與下次啟動會一致。關閉不會偷偷保存未確認的節點輸入，會詢問儲存/放棄/取消。
- 新增複製目前已儲存 Profile；重新命名不改參數；不能刪除最後一個；名稱需唯一，1–64 字。
- 下拉切換同步八節點全部輸入、進階 RGB/JSON、IP/Port、LCD 電源及文字設定。網路不自動初始化，監控不自動啟動。
- 節點按「儲存設定（目前 Profile）」只更新目前 nodes；LCD 與 IP 各自保存時也只更新目前 Profile，不覆寫其他 Profile。
- 變更前停止掃描、取消待送事件、停止舊 UDP session、關閉進階/LCD 編輯視窗。未保存修改會提示。舊 session 結束前立刻初始化可能顯示 busy，稍後再按。
- 一次只開一個 GUI/CLI。原子寫入防半截檔，不是多程序並行編輯鎖；不要同時執行舊版工具寫設定。

## 八節點
Node_HP、Node_Target、Action_1–Action_6，每列有 enabled、X、Y、Threshold、Min/Max Delay、mode、座標採集、進階設定。
座標可為負數（多螢幕）。在節點右側 F8 選取單選按鈕選定目標，再啟用座標採集模式；切到遊戲按 F8，自動填入 X/Y/RGB。停止、切換 Profile 會解除熱鍵並丟棄舊事件。請選真實桌面範圍內的座標。
- brightness：RGB 算術平均 > Threshold（相等不觸發）。不是加權感知亮度。
- red：R > Threshold，遷移 HP/Target 沿用舊 red 判定。
- color：每個 RGB 分量與目標差距 ≤ tolerance；此模式不使用 Threshold。遷移 Q/E 沿用此模式。
- Min / Max：整數毫秒，0 ≤ Min ≤ Max ≤ 60000；錯誤輸入不寫檔。
- 進階 JSON 為 null 時僅記錄監控事件；可改成 {"action":"tap","key":"1"} 或 lcd_test/click/move/scroll/release_all 等單次 JSON。
- HP/Target 預設只監控，不是自動 Target gate。Action_1/2 保留 q/e 動作，Action_3–6 預設停用。新的通用系統不再使用舊遊戲專用優先級、低血量自動 9 或持續填充 1。
- 為避免 UDP 遺失 release 導致持續按住，本 UI 不允許持續 press/release 設定；不影響 transport 本身既有 API。

## 非阻塞隨機延遲
核心在 decision.py，GUI 的 vision_loop_tick / dispatch_loop_tick 接線：
1. 偵測 false→true（開始監控第一張為 true 也算上升沿）。random.randint(min_delay,max_delay) **只抽一次**。
2. due = time.monotonic() + delay_ms / 1000；每節點最多一筆 pending，不建立 Timer 執行緒，不 sleep。
3. 每約 50ms 掃描；每約 10ms 用 Tk after 比對到期，再呼叫原 controller.send_command(dict)，由原 UDP worker 非阻塞 sendto。
4. 持續 true 不重複送；需先變 false 才重新武裝。等待中變 false 或停用會取消。
5. 停止、儲存新節點、切換 Profile、斷線、採集異常會清 pending；儲存/重新開始後若條件仍成立，將當成新週期重新抽延遲。
6. send_command 失敗不自動重送，以免重複動作。節點 null 不發 UDP，但仍依延遲記錄事件。
7. 已排入 transport 或已送出的封包無法靠清 pending 撤回；UDP 非可靠協定。切換會結束舊 session 並嘗試 release_all，不代表遠端已確認釋放。
8. 延遲是最早到期時間，不是精準硬即時；Tk 排程、同步畫面讀取、OS、Wi-Fi 與 ESP32 的 25–60ms hold 都會增加實際時間。只根據最近一次取樣取消，無法得知兩次掃描間短暫變化。
9. 隨機延遲可能仍同時到期，不是全域限速器，也不保證封包均勻分布。

## 檔案
- gui.py：完整現有 GUI、UDP/LCD 連線、Tk 掃描與延遲 dispatch。
- profile_ui.py：Profile 下拉/CRUD、8 節點表格、進階編輯與採集。
- profile_store.py：驗證、平面遷移、原子寫檔、選取/增刪改。
- decision.py：純條件比對與可注入時鐘/亂數的時間戳狀態機。
- endpoint_settings.py / lcd_settings.py：改為目前 Profile 的保存。
- config.json：你目前已遷移設定；config.example.json：兩組範例，所有節點停用，避免無意動作；不要用範例覆寫真實設定而遺失自訂值。
- transport.py：完全未修改，SHA256 82514c662f22ae3a3f1da0b83e4c37dbed9761a98f188f5a10f6ae391db126b0。
- main.py：可選 CLI，同樣使用 Profile 與新狀態機；不是預設啟動入口。執行即開始監控，不用於首次連線測試。

## 驗證
`python tests_udp/test_profiles.py`：10 項 migration/CRUD/隔離/驗證/時序/抑制重複/取消/邊界測試。
`python tests_udp/test_transport.py`：7 項原 UDP 回歸，含真實 localhost UDP 來回、佇列回壓；非實機。
`python tests_udp/profiles_gui_smoke.py`：真實 Tk + 暫存設定 + 假像素/傳送器，測增刪改/切換/重開記憶/所有欄位/非法延遲拒絕/非阻塞發送/停止取消；未觸發實機。
畫面在 1100×900 與 1020×720 檢查，主頁可捲動，較小高度的後幾列/LCD/日誌需向下捲動。
字型/LCD 舊版本歷史測試已備份至 backups/profiles-20261031/historical-tests，不當成本次新架構回歸結果。
未驗證：實機畫面條件、實際 Wi-Fi 延遲、高負載流量均勻度與 ESP32 執行效果。本次不宣稱這些已通過。

## 恢復
backup/ 含本次修改前原檔、SHA256、diff 與 restore_previous.py。
先關閉 GUI，再執行 `python backup/restore_previous.py --target <Python專案目錄>`。
已在額外副本驗證 SHA256；會回復舊平面 config 與對應程式，不刪新 helper，不操作 ESP32。新 helper 閒置不影響舊版啟動。
