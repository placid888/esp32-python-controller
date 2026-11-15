# Node_Target gate 最小修改 — 2026-11-01

## 已修改
1. decision.py / DecisionEngine.observe：只對 Action_1、Action_2 套用 Target enabled AND Target match AND Action enabled AND Action 自己 match；其餘節點不變。
2. gui.py / dispatch_loop_tick：送出前依目前最近一張掃描結果再次檢查 Target/Action enabled 與條件，不通過就不進 UDP queue。
3. target_diagnostics.py / scan：只更新 gate 診斷理由；原 actual/target RGB、diff、tolerance、限速與 edge/dispatch 日誌保留。MONITOR_START 標記亦更新為 gate 模式。

## 行為
- Node_Target 只作門檻，command 仍 null，不直接發送 E。
- 原 Action_1=q、Action_2=e、Min/Max、random.randint、時間戳、UDP worker、ESP32 都不變。
- edge 現在套用於有效 AND 條件：Target 持續 True 時，Action False→True 正常觸發；兩者持續 True 只送一次。
- 等待途中 Target False 會取消 pending 並重新武裝；Target 再 True 且 Action 還 True 時，視為有效條件的新上升沿，重新抽原範圍延遲。
- Target 缺失／停用視為 gate=False。Action_3–6 不加 gate，維持原行為。
- dispatch 再檢查依最近的 50ms 掃描快照，並非在 sendto 瞬間重擷取。已排入 UDP／已送出的封包無法撤回。

## 診斷
原路徑 diagnostics/node_target_runtime.jsonl 與 GUI 系統日誌。
TRIGGER_TRACE 顯示 target_match、action_match、Gate、target_dependency、reason；blocked_by_Node_Target 表示 Target gate 不通過。
GATE_DISPATCH 在送出時顯示 Node_Target=True、Action=True、Gate=True、message=Dispatch Action_1/2；被攔截時顯示 Gate=False 與 Blocked by Node_Target／Action disabled or own condition False。
queued 僅表示本機 UDP queue 接受，不表示遠端 HID 執行已確認。

## 測試
新增 test_target_gate.py 11 項通過：
- Target=False / Action=True：不送
- Target=True / Action=False：不送
- Target=True / Action=True：原延遲到期才送
- Target 持續 True、Action False→True：正常送
- 100 次穩定 True 掃描：只送一次
- 延遲中 Target 失效取消；Target 恢復可重新抽延遲
- Action False 後重新武裝
- Target 停用／缺失 fail closed
- Action_3 不受 gate 影響，Target 本身仍 command=null
- Action_1/2 可各自觸發
- 真實 Tk dispatch 防線對兩個 Action 的三種條件組合均正確，送出的 JSON command 不變。
原 Profile/時間戳 10 項、診斷 5 項、UDP 7 項亦通過（舊測試 fixture 更新為明確供應 Target=True；未放寬測試斷言）。共 33 項單元／回歸，加上原 Tk Profile smoke 通過。
測試使用假時鐘／假 UDP sender／localhost，沒有發送實機 HID，也沒有修改或燒錄 ESP32。現有 MSS deprecation warning 未在本次順便處理。

## 啟用與恢復
目前原專案已更新。關閉舊 GUI，從原桌面捷徑重新開啟；不需重燒 ESP32。不自動啟動真實監控。
ZIP 是小型 patch，需搭配目前完整專案，不是獨立可執行程式。
backup 有修改前檔案、SHA256；diff 有逐行差異。要恢復只需關閉 GUI，將 backup 的 gui.py、decision.py、target_diagnostics.py 覆蓋原檔。已在額外副本驗證原 SHA256，最終修改版保留。
config.json 與 transport.py 已核對逐 byte 不變。

## Source 位置
{
  "gui.py": [
    [
      543,
      "def dispatch_loop_tick(self):"
    ]
  ],
  "decision.py": [
    [
      11,
      "def observe(self,conditions,nodes):"
    ],
    [
      13,
      "target_gate=bool(nodes.get('Node_Target',{}).get('enabled',False) and conditions.get('Node_Target',False))"
    ]
  ],
  "target_diagnostics.py": [
    [
      31,
      "def scan(self,nodes,pixels,conditions,brain,before_states,before_pending):"
    ]
  ]
}