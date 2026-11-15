# 本次快照驗證（2026-11-15）

- 139個來源檔同步；只有整理副本做秘密移除、路徑／端點去識別化、便攜式入口及schema4範例遷移。原專案未改。
- Python／PYw AST解析通過；Wi-Fi精確值與常見token格式掃描通過。config.json忽略且不提交。
- 選定測試指令：`cd python; Copy-Item config.example.json config.json; python -B -m unittest test_wow_diagnostic test_coordinate_mode test_skill_cooldown_phase3 test_skill_cooldown_phase4 test_skill_cooldown_phase5 -v`。
- 最終98項通過，6.303秒，exit 0。首次缺config出現49 errors；使用舊schema3範例剩1 failure；本次升schema4後重跑通過。不隱藏這兩次失敗。
- 本次沒有重跑全部tests_udp。2026-11-14該套175項曾5 failures／9 errors；不能由本次98項推論全部修好。
- 沒有重新編譯／燒錄ESP32，也沒有在本次上傳過程送任何HID或UDP命令。
- 最新123試驗在啟動即退出後做了前景等待與錯誤記錄修正；修正後live驗證仍待完成。
- 原始本機測試記錄保留於工作區progress-publish-20261115；不把個人路徑及原圖一起上傳。
