# 本次整理驗證（2026-11-14）

- 上傳副本的 66 個 Python / PYw 檔案：AST 語法解析通過；config.example.json 解析通過。
- Wi-Fi：從 main.cpp 移除兩個硬編碼常數，改用 wifi_secrets.h；範例檔與 .gitignore 已建立。以原始 SSID、密碼精確比對副本：未找到洩漏。
- START_GUI.cmd：僅在副本把固定使用者 Python 路徑改為優先使用 python/.venv，找不到時使用 PATH 的 python。
- Python 視窗診斷：`python -B -m unittest test_wow_diagnostic -v`，8 / 8 通過，exit 0。
- tests_udp 全套：`python -B -m unittest discover -s tests_udp -p "test_*.py" -v`，175 項，5 failures、9 errors，未全數通過。
  - 首次沙箱執行有暫存目錄權限問題；沙箱外重跑仍有上述失敗。
  - 多項歷史雜湊與效能證據測試依賴未上傳的 backups；部分舊測試預期舊版 transport 原始碼／雜湊。
  - 另有本機 UDP timeout、佇列延遲／工作執行緒未及時停止、GUI dry-run guard 與記錄斷言失敗，未在本次上傳整理中修改原邏輯。測試報告產生後程序未自然結束，已中止。
- esp32/tools/test_udp_source.py 依賴歷史備份，未執行。
- 未重新編譯韌體，未燒錄、未連接 ESP32、未測試實體 LCD／HID。不能將語法或合成測試視為硬體驗證。

完整本機測試輸出放在本機上傳工作目錄的上一層，未上傳含絕對路徑的原始紀錄。原始專案未改動；本次為來源快照，並非宣稱修復所有既有問題。
