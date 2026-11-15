# ESP32-S3 + Python GUI：Wi-Fi UDP 雙向控制

## 已交付內容
- `esp32/`：PlatformIO 完整韌體，HID 鍵盤＋滑鼠、Wi-Fi STA、UDP 8888、JSON 指令與 LCD。
- `python/`：現有 GUI、UDP transport、CLI、視覺與決策模組、config、依賴清單、通訊與 GUI 測試。
- `evidence/`：本次編譯、測試、GUI 畫面。GUI 畫面來自 PC loopback，不是真機連線畫面。
- `backup/`：本次修改前的來源、SHA256、差異與恢復程式。

**私密資料警告：韌體已按要求直接寫入指定 SSID 和密碼。原始碼與編譯後的 firmware 都包含 Wi-Fi 設定，請勿公開上傳本 ZIP、source 或 binary。**

## 1. 韌體設定
Wi-Fi SSID 已設定為 `[REDACTED_WIFI]`，密碼已按要求寫入 `src/main.cpp`，此處不重複列印。請確保路由器開啟 ESP32-S3 支援的 2.4 GHz 網路。PC 可用同一可互通 LAN 的 Wi-Fi 或有線網路，不必用同一種連線介面。

`platformio.ini` 核心設定：
```ini
build_unflags =
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
    -DARDUINO_USB_MSC_ON_BOOT=1
    -DARDUINO_USB_DFU_ON_BOOT=1
build_flags =
    -D ARDUINO_USB_MODE=0
    -D ARDUINO_USB_CDC_ON_BOOT=0
    -D ARDUINO_USB_MSC_ON_BOOT=0
    -D ARDUINO_USB_DFU_ON_BOOT=0
```
這是節錄，不要覆蓋掉完整檔案內原本 TFT／FS／Network 的旗標。鍵盤、滑鼠與 USB 的三個 begin 呼叫保留。

正常應用程式不註冊 CDC，只使用 HID 鍵盤／滑鼠。但是「任何階段絕對不出現 COM」無法靠韌體保證：ROM 下載模式或獨立 USB-UART bridge 仍可出現 COM。這次沒有修改 bootloader/eFuse，也不建議為隱藏 COM 燒寫不可逆 eFuse。正常使用接原生 USB OTG/HID 插口，而不是 UART bridge 插口。

## 2. VS Code / PlatformIO 編譯與燒錄
1. 解壓縮到你自己的本機資料夾；在 VS Code 安裝 PlatformIO IDE，開啟 **`esp32/`**，不要開 `python/`。
2. 等 PlatformIO 依 `platformio.ini` 準備 toolchain 與 library。按下方 **Build（勾號）**，或 PlatformIO 終端機執行：
   ```powershell
   pio run -e esp32-s3-devkitc-1
   ```
3. 使用支援資料傳輸的 USB 線。若板子有 USB-UART 與原生 USB 兩個插口，可先透過既有 UART 下載方式燒錄；此時出現的 COM 是下載工具，不是應用程式 CDC。
4. 在 PlatformIO Project Tasks → `esp32-s3-devkitc-1` → General → **Upload**，或：
   ```powershell
   pio run -e esp32-s3-devkitc-1 -t upload --upload-port COMx
   ```
   `COMx` 是下載模式實際顯示的埠，不要直接照打字母 x。也可省略 `--upload-port` 讓 PlatformIO 自動偵測，但多裝置時應明確選擇。
5. HID-only 執行中原生 USB 可能沒有 serial 埠可自動重置：必要時**按住 BOOT，按一下 EN/RESET，再放開 BOOT**，確認進入 ROM 下載模式後再 Upload。上傳成功後依工具提示或按 RESET 進入應用程式；不要一直按著 BOOT。
6. 正常使用改接／保留原生 USB HID 連線。獨立 UART 插口若仍連 PC，該 bridge 的 COM 不會因本次旗標消失。
7. LCD 等待 Wi-Fi 後顯示 `實際IP:8888`。這裡的 IP 是 DHCP 配發值，不是固定範例值；若路由器重開導致 IP 改變，GUI 也要更新。可由路由器設定 DHCP reservation 固定租約。

本次僅 Build，**沒有執行 Upload 或接觸實機**。目前未交付可保證所有板版適用的單一合併燒錄檔；請以完整專案的 PlatformIO Upload 使用正確 bootloader、partition 與 application。

## 3. Python 安裝與第一次測試
在 `python/` 開終端機：
```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe gui.py
```
GUI 使用 Tkinter；一般 Windows 官方 Python 安裝可選裝 Tcl/Tk。依賴只有 numpy、mss、pyautogui，**沒有 pyserial**；socket、threading、queue、json 是標準函式庫。GUI 原有視覺/決策功能仍保留，運行環境需要桌面 session。

第一次測試：
1. 不啟動視覺監控，先在「目標 IP」填 LCD 顯示的 **IPv4（不要包含 :8888）**。
2. Port 填 **8888**，按 **初始化 UDP 通訊**。
3. GUI 先顯示「已初始化／等待回覆」；本機 socket 成功不等於 ESP32 在線。初始化會排入 `lcd_config`，收到 ACK 後才顯示「已收到 ESP32 回覆」。
4. 按 **測試 LCD**。收到 `status:ok, action:lcd_test` 只表示韌體處理並回覆；也應在實體 LCD 確認測試文字。
5. 確認上述通道後才測試 HID；在安全的文字編輯器測試，避免焦點落在會執行危險動作的應用程式。
6. 停止 UDP／關閉 GUI 時，背景嘗試一次 `release_all`，但 UDP 丟包時不能保證釋放；測試前備妥直接拔開 HID 的方法。

若無回覆：確認 PC 與 ESP32 路由互通、路由器 AP/client isolation 沒有阻擋、IP 正確，以及 Windows 防火牆允許該 Python 的必要私人網路通訊。**PC 發送端綁定的是本機臨時埠，8888 是 ESP32 目的埠；不要誤認 GUI 在 PC 固定監聽 8888。**不要為了排錯關閉整個防火牆或轉發公網埠。

CLI 保留，但改用：
```powershell
python main.py --host 192.0.2.1 --port 8888
```
IP 為示例。CLI 會啟動原有視覺／決策迴圈，不應作為第一次安全 LCD 測試；優先使用 GUI 的 LCD 按鈕。

## 4. 協定與非阻塞實作
每個 UDP datagram 是一個 UTF-8 JSON object，最多 1024 bytes，不使用 serial 換行切包。例：
```json
{"action":"lcd_test","message":"UDP OK"}
{"action":"tap","key":"1"}
{"action":"release_all"}
```
原有 tap、press/release（key 或 btn）、click、move、scroll、release_all、lcd_test、lcd_config 保留。`1` 或 `jump` 這類裸字串不是原 JSON action 協定，不自動猜測對應鍵。

Python `send_command()` 只做 JSON 編碼與有界佇列 `put_nowait()`；背景 worker 使用 `SOCK_DGRAM`、`setblocking(False)`、`sendto()` 與 `recvfrom()`。回覆透過事件佇列交給 Tk `after()` 處理，不從 worker 操作 Tk，也不在 GUI 等 ACK、DNS 或 sleep/join。回傳 byte count 代表**排入佇列**，不是對端已執行。佇列滿直接失敗回報，不無限堆積記憶體。視覺擷取／決策本身原有的執行耗時沒有在本次重寫；非阻塞保證針對網路 I/O，不是宣稱所有 GUI 工作零延遲。

ESP32 的背景 task 單獨擁有 UDP socket；8-slot queue 將 JSON 交給原 loop 做 HID/LCD，回覆送回來源 IP/port。超長、NUL、佇列滿會回錯誤；Wi-Fi 重連後重綁 UDP。

`esp_random()` 產生 25..60ms 的隨機按住時間，tap/click 在按下與放開之間等待；獨立 press 保持按住直到後續 release/release_all。這不是機械開關去抖、UDP 去重或可靠傳輸；排程及 USB 傳輸還可能增加實際時間。未增加其他連發規則。

## 5. 限制與安全
- UDP 可能丟包、重複、亂序；ACK 遺失不代表未執行，不自動重送 tap/click，避免重複動作。ACK 無 request ID，不能把同 action 的回覆當作逐筆可靠交易。
- release 丟失可能留下按住狀態；沒有擅自加入逾時自動放開，以保留原有 hold 語意。關閉是 best effort，不是遠端釋放確認。
- 此版本沒有網路身分驗證／應用層加密，只適用可信、受控 LAN，不應暴露到公網。
- 改 Wi-Fi 命令通道不等於電氣隔離：USB HID 線仍然存在，地線／供電路徑未改。
- 未完成真機 Wi-Fi 連線、LCD、HID timing、USB 枚舉或斷網恢復測試，不把 PC loopback 當作實機通過。

## 6. 本次驗證
- PlatformIO Build exit 0：Espressif32 8.0.0、Arduino-ESP32 3.3.12、ArduinoJson 7.4.3、TFT_eSPI 2.5.43。
- 新版靜態 RAM 79,112 bytes，Flash 1,073,881 bytes；不含執行中動態 Wi-Fi／task／queue 用量。
- Python 7 項測試通過：真實 PC loopback UTF-8 JSON/ACK、斷開時 release_all、payload/endpoint 驗證、背景 worker 隔離與佇列滿載非阻塞、移除 serial、保留 vision/decision/tracker/config。
- 韌體 7 項 source regression 通過；不是 MCU runtime 測試。
- 真實 Tk GUI localhost smoke 通過：IP/Port 欄位、初始化、lcd_config/lcd_test、ACK 顯示、停止與輸入欄位狀態。首次測試曾因 Tcl state 物件與字串比對失敗，修正測試後通過；首次畫面被背景視窗遮擋，已改用單一視窗擷取並檢查。
- 恢復腳本在額外副本驗證 SHA256 通過，未覆蓋最終修改版。
- 舊 ArduinoJson containsKey 與 TFT_eSPI warning 保留，未修改第三方函式庫。

## 7. 備份／恢復
本機 Python 原始目錄：`C:/Users/USER/Desktop/a`；韌體：`C:/Users/USER/OneDrive/Desktop/A`。這次修改前備份在 Python 目錄的 `backups/udp-system-20261031/`，ZIP 內對應 `backup/`。

需要恢復時，先另存想保留的新版，再執行：
```powershell
python backup/restore_previous.py --python-root "你的Python目錄" --firmware-root "你的韌體目錄"
```
會驗證備份 SHA256，再覆寫備份中列出的原始檔；不移除新增工具／說明。本次修改前韌體已是上一輪 UDP、SSID 留空版本，而 Python 尚是 serial；此備份精確還原該時間點，**不是宣稱還原成可互通的 CDC 系統**。若需更早原 CDC 韌體，本機 A/backups/before-udp-20261031/ 仍保留上一輪備份。

## 官方參考
- PlatformIO board / upload：https://docs.platformio.org/en/latest/boards/espressif32/esp32-s3-devkitc-1.html
- Espressif 下載按鍵與兩個 USB 插口：https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.0.html
- USB CDC 設定：https://docs.espressif.com/projects/arduino-esp32/en/latest/api/usb_cdc.html
- Python 非阻塞 socket：https://docs.python.org/3/library/socket.html
