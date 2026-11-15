# Class → Specialization → Independent Settings — 2026-11-01

## 1. 修改前檢查
修改程式前完整執行既有116項測試，全部通過，原始baseline-*.log留存。
在Desktop/a執行git rev-parse --show-toplevel、git rev-parse HEAD、git status --short均回報not a git repository；因此沒有HEAD/working tree可記錄。沒有init、commit或push。
原始全部Python檔及config備份於backups/class-spec-20261101，保留Default與獵人兩個Profile，未刪除任何Profile。

## 2. 檔案
新增 class_registry.py、spec_data.py、spec_ui.py。
修改 profile_store.py（canonical persistence＋相容view）、profile_ui.py（角色區與載入刷新）、gui.py（Spec context、ACTIVE_SPEC診斷、canonical初次遷移比較）。
新增 tests_udp/test_class_specs.py。
保留全部既有測試；兩個歷史protected-source測試只更新本次明確授權修改profile_store.py的預期SHA256，不放寬任何核心演算法斷言，也不修改舊備份hash。原檔另存本次backup/tests_udp。

## 3. Registry與未來擴充
class_registry.py集中定義ClassDefinition / SpecDefinition，穩定ID：hunter、beast_mastery、marksmanship、survival；名稱為獵人、獸王、射擊、生存。GUI選項均由registry產生，沒有散落的if hunter分支。
未來增加職業只需註冊新的metadata並提供後續規則，不需重寫選擇UI。測試暫時註冊/移除Priest metadata證明通用性，不在正式registry增加牧師，更未實作牧師戰鬥功能。
ActionDefinition預留kind、target、ability、sequence、metadata；每個spec預留state_inputs、decision_rules、actions、metadata。它們本階段只儲存資料，不被dispatch執行，不實作任何新rotation。
目前真正執行的Skill priority/key mapping仍由原skill_model固定數字函式決定，完全未變。

## 4. 新舊格式
舊：schema_version=3，last_used與profiles；每個Profile為平面nodes / combat_mode / hunter_mark_* / udp_endpoint / lcd_*。
新：保留last_used與所有命名Profile；schema_version=4，每個Profile profile_version=2。
概念例（省略實際nodes欄位）：
```json
{
  "schema_version": 4,
  "last_used": "獵人",
  "profiles": {
    "獵人": {
      "profile_version": 2,
      "selected_class": "hunter",
      "selected_spec": "marksmanship",
      "global": {"udp_endpoint": {"host": "192.0.2.1", "port": 8888}},
      "classes": {
        "hunter": {
          "shared": {"nodes": {}, "combat_mode": "manual_first_hit", "hunter_mark_mode": "pre_combat", "hunter_mark_key": "3", "hunter_mark_retry_ms": 500},
          "specs": {
            "beast_mastery": {"nodes": {}, "state_inputs": {}, "decision_rules": [], "actions": [], "metadata": {}},
            "marksmanship": {"nodes": {}, "state_inputs": {}, "decision_rules": [], "actions": [], "metadata": {}},
            "survival": {"nodes": {}, "state_inputs": {}, "decision_rules": [], "actions": [], "metadata": {}}
          }
        }
      }
    }
  }
}
```
實際shared.nodes含Target/Combat/Mark，spec.nodes各含完整Skill4～0，不是上例空物件。global在每個命名Profile內共用於全部Class/Spec；不是擅自合併不同既有Profile的IP設定，以免改變原Profile語意。

## 5. 儲存分層
Global：ESP32 IP/Port、LCD display/power、既有其他系統/裝置欄位；同一Profile全部Class/Spec共用。不複製到三份spec。
Class Shared：Target、Combat、Mark節點、combat_mode、Hunter Mark mode/key/retry，三個Hunter專精共用。沒有三套opener實作。
Per-Spec：Skill4～0每個完整node（Enabled、X/Y、mode、RGB、Tolerance、Threshold、Sample Mode、Ratio、Min/Max、固定command）及上述未來規則擴充欄位。Priority仍是不可變更的現有runtime常數，本次沒有增加可編輯priority。

## 6. Migration與相容讀取
每個舊Profile的全部原Skill資料只放進hunter/marksmanship；原gate/opener放Hunter Shared；原硬體/App資料進global。
獸王與生存使用獨立safe defaults：技能Enabled=false，原預設node結構/固定數字command，不clone射擊的實際座標或啟用狀態。每個字典都deep copy/fresh factory建立，沒有mutable alias。
profile_store.read/active仍提供舊平面nodes、combat_mode、hunter_mark_*與endpoint/lcd aliases，供現有GUI/CLI/worker使用；這是選中Class/Spec的detached runtime view。disk_document只存canonical tree，不把相容view或_runtime_view_hash重複存進檔案。
原read→修改flat nodes→write也有相容性測試。_runtime_view_hash只在記憶體辨識view是否改動；canonical與view同時衝突修改時拒絕寫入，避免靜默覆蓋。推薦現有update_active保存，它會集中把gate寫shared、skill寫目前spec、硬體資料寫global。
實際舊config兩個Profile每個原欄位逐項與遷移後view比較一致；現用config目前SHA256未變。下一次開啟新版GUI才透過既有atomic write流程保存新格式；開始使用前請先關閉所有舊GUI/CLI，避免舊副本再寫回舊設定。

## 7. GUI與安全切換
Profile下新增「角色/專精」區：職業下拉第一版只有獵人；三個Radiobutton獸王/射擊/生存，選中狀態清楚；右側固定顯示「目前：獵人 / 射擊」等。
同一GUI內切換，不需重開。未保存變更沿用原profile_guard提示，可儲存/捨棄/取消。
Monitor running時任何Class/Spec request被拒絕，提示「請先停止 Monitor 再切換職業或專精」，不熱換worker快照。
切換時停止F8、增加context epoch、關閉舊進階/LCD視窗、取消舊calibration，選擇新spec再載入完整view。UDP連線不因切spec而斷開，IP/Port輸入不被換成另一套。
Monitor啟動一次記錄ACTIVE_SPEC class/spec，runtime source亦記selected_class/spec；不每frame新增log。

## 8. F8/F9/F10與校正隔離
F8事件context新增selected_class/spec，切換也停監聽並增加epoch，舊事件不能寫入新spec。
F9/F10原hotkey infrastructure完全未改；切換會銷毀舊panel/deactivate token，新panel重新activate serial。因此舊排隊事件被拒絕，新capture仍走原CalibrationPanel.capture。
Calibration演算法與fingerprint本身未改；切spec前銷毀panel，所以不能把上一專精的樣本帶入下一個。Threshold套用只填目前node欄位，update_active將其保存到目前spec。

## 9. 測試結果
修改前116/116，修改後同樣116/116，全部exit0。
新增test_class_specs.py 25/25；合計141/141。
新增測試涵蓋registry/穩定ID、舊Profile→MM、所有原gate/opener/未知欄位保留、多Profile不刪、BM/MM/SV各參數隔離、deep copy、global共用且disk不重複aliases、shared gate跨spec、重啟選擇、未來metadata、擴充資料保存、MM遷移前後決策一致、三spec GUI刷新/返回、Monitor禁止切職業/專精、F8新spec寫入與舊事件拒絕、F9/F10/套用Threshold只寫SV、進階視窗使用當前資料、hotkey舊token拒絕、取消切換、flat/canonical兩種write相容，以及ACTIVE_SPEC只記一次。
所有GUI測試只用暫存Profile。F9/F10測試是真background calibration＋合成像素；native F8/F9/F10既有測試只PostThreadMessage到測試執行緒，不向遊戲注入鍵。
既有transport/Opener回歸只localhost，不連ESP32。沒有啟動實機Monitor或向ESP32大量送鍵。
既有mss.mss deprecation warning保留，未順便改依賴。

## 10. 實際GUI smoke
真實Tk、目前Profile的暫存副本，依序BM→MM→SV→MM，設定三組Skill4 X/Y/Threshold再切回，確認獨立保存；沒有初始化UDP。
第一次切換含首次全畫面繪製約577ms；後三次約99/98/81ms（本機短測，不是硬即時保證）。class-spec-gui.png已目視檢查，保留既有Tk風格、沒有大幅redesign。
gui-smoke.json、class-spec-tests.log與baseline/post原始log可重查。

## 11. 未改與恢復
safety-verification.json確認detector.py、decision.py、vision.py、mark_opener.py、skill_model.py、brightness_calibration.py、calibration_ui.py、hotkey_capture.py、calibration_hotkeys.py、transport.py、ESP32 src/main.cpp等保護檔byte-identical。因此Hunter Mark A/B、Target/Combat/Mark、Retry、numeric priority/mapping、正式判定/時序、UDP protocol未改，ESP32不需重燒。
備份含全部原Python檔、原config、SHA256-before、三份source diff、兩份舊測試、baseline/post/new測試log及GUI截圖。
已在額外暫存副本還原舊source/config、驗證SHA並用舊reader讀回原兩個Profile。現行修改保留。
目前config仍為原檔，現在回退只需關閉GUI並還原三份修改source（及舊測試）。若日後新版GUI已保存分層config，回退前必須先另存新版config，再用備份舊config配舊source；三spec新增資料保留在另存的新版檔，不可假稱舊版能直接讀完整新樹。不要直接覆蓋後續設定。

## 建議人工驗證
1. 開啟舊Profile。
2. 確認自動進入獵人/射擊。
3. 記錄射擊Skill_4 X/Y/Threshold。
4. 切換生存。
5. 修改生存Skill_4 X/Y/Threshold並儲存。
6. 切回射擊。
7. 確認原數值完全沒有改變。
8. 切換獸王，再設定另一組數值並儲存。
9. 三個專精來回切換確認完全獨立。
10. 射擊專精執行一次原本的短時間、安全實機Monitor測試。

未加入獸王/生存/射擊rotation、Focus、pet、healing、新職業行為、新WA訊號或新ESP32命令。完成後停止。
