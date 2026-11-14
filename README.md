# ESP32 Python Controller

ESP32-S3 韌體與 Windows Python 控制台：以區域網路 UDP JSON 傳送命令，由 ESP32 透過原生 USB 提供鍵盤／滑鼠 HID，並在 ST7789 LCD 顯示連線、按鍵與診斷狀態。Python 端包含 Tkinter GUI、畫面取樣、設定檔、校準及 WoW 視窗診斷模組。

> 此儲存庫是現有專案的整理副本。未包含 Wi-Fi 密碼、個人 config、備份、日誌或編譯產物；原本機專案不受影響。

## 目錄

```text
esp32/
  platformio.ini          PlatformIO / Arduino 設定
  src/main.cpp           Wi-Fi、UDP、USB HID、LCD 主程式
  src/wifi_secrets.example.h  Wi-Fi 設定範例
  src/lcd_diagnostic*    LCD 診斷工具與測試
  src/unifont_subset.h   產生的中文字型
  fonts/                 GNU Unifont 來源與授權
  tools/                 字型產生與 UDP 工具
python/
  gui.py                 Tkinter 圖形控制台
  START_GUI.pyw          無主控台視窗啟動器
  main.py                視覺／決策 CLI
  transport.py           非阻塞 UDP 傳輸
  detector.py            偵測工作執行緒
  config.example.json    設定範例
  tests_udp/             傳輸與功能單元測試
```

## 硬體與環境

- ESP32-S3（原生 USB HID），2.4 GHz Wi-Fi；PC 與裝置必須在可互通的可信 LAN。
- ST7789 135 × 240 面板；程式使用橫向 240 × 135 顯示。
- 接腳：MOSI 11、SCLK 12、CS 10、DC 8、RST 9、背光 7。不同板型請先核對接線。
- PlatformIO Core / IDE，Arduino framework；環境名稱 `esp32-s3-devkitc-1`。
- Windows 桌面環境、Python（來源專案使用 Python 3.14）、Tkinter；套件見 `python/requirements.txt`。

## 1. 設定及編譯 ESP32

在儲存庫根目錄執行 PowerShell：

```powershell
Copy-Item esp32/src/wifi_secrets.example.h esp32/src/wifi_secrets.h
```

編輯 `esp32/src/wifi_secrets.h` 的 SSID 與密碼。此檔已被 `.gitignore` 排除，請勿強制提交；編譯後的韌體同樣含密碼，不應公開分享。

```powershell
pio run -d esp32 -e esp32-s3-devkitc-1
pio run -d esp32 -e esp32-s3-devkitc-1 -t upload --upload-port COMx
```

將 `COMx` 換成實際下載埠。必要時按住 BOOT、按一下 RESET、放開 BOOT，進入下載模式再燒錄。正常運行時應用程式禁用 USB CDC、MSC、DFU，使用原生 USB HID；ROM 下載模式或外接 USB-UART 仍可能出現 COM。

LCD 顯示 DHCP 取得的 IP；Python 連線時只填 IPv4，不包含 `:8888`。不要將舊 IP 視為固定值。

## 2. 安裝及啟動 Python GUI

```powershell
cd python
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
.venv/Scripts/python.exe gui.py
```

`config.json` 是本機設定，已排除提交。請依自己的解析度、UI 比例與節點位置重新校準，勿沿用其他電腦座標。也可用相同虛擬環境的 `pythonw.exe START_GUI.pyw` 無主控台啟動；啟動器錯誤寫入本機 `gui-startup.log`。

第一次連線：

1. 先不要啟動視覺監控或輸出功能。
2. 在 GUI 輸入 LCD 顯示的 IPv4，目的 Port 為 `8888`。
3. 初始化 UDP，再執行 LCD 測試；socket 初始化成功不代表裝置在線，應確認回覆與實際 LCD。
4. 確認連線後，僅在安全的文字編輯器測試 HID，並備妥拔除 USB 的方式。

CLI 會直接啟動視覺／決策迴圈，不建議當作第一次連線測試：

```powershell
python main.py --host 192.168.1.50 --port 8888
```

## UDP 協定

每個 datagram 是一個 UTF-8 JSON object，命令上限 1024 bytes，目的埠預設 8888。不是序列埠換行協定。

```json
{"action":"lcd_test","message":"UDP OK"}
{"action":"tap","key":"1"}
{"action":"release_all"}
```

支援鍵盤 tap / press / release、滑鼠 click / press / release / move / scroll，以及 LCD 設定與診斷；實際欄位以 `src/main.cpp` 為準。`tap` 與 `click` 按住時間為 25–60 ms。Python 使用有界佇列與背景 socket worker，排入佇列不等於遠端執行完成。

## 測試

在 `python/` 執行：

```powershell
python -B -m unittest discover -s tests_udp -p "test_*.py" -v
python -B -m unittest discover -s . -p "test_*.py" -v
```

測試包含 PC 本機 UDP 與合成資料；不等同 ESP32 真機驗證。部分原有測試依賴來源目錄或歷史備份，整理副本缺少這些資料時可能失敗；本次實際執行結果另見 `VALIDATION.md`。

## 安全及限制

- UDP 沒有身分驗證或應用層加密，請只用於可信 LAN，不轉發到公網。
- UDP 會丟包、重複與亂序；ACK 無逐筆 request ID，不要自動重送 HID 命令。
- `release_all` 與關閉時釋放是 best effort；斷網可能留下按住狀態。
- 畫面診斷不會讀取遊戲記憶體；桌面遮擋、DPI、視窗移動與 UI 比例仍會影響取樣。
- 使用遊戲相關功能前請自行確認平台規則；本專案不保證符合遊戲服務條款。
- 本次整理不執行燒錄、連線實機或發送 HID。

## 字型授權

`esp32/src/unifont_subset.h` 由 GNU Unifont 16.0.04 產生，來源與授權保留在 `esp32/fonts/`。字型的授權與例外以該目錄原文為準。本次未擅自為使用者程式碼新增開源授權。
