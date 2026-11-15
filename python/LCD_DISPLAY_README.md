# LCD 可調字級與中英文字版 — 2026-10-31

## 已完成與未完成
- 更新 Python GUI 與 ESP32 LCD 渲染；USB HID、25–60ms 隨機按住及 UDP 工作執行緒維持原邏輯。
- 主畫面標題、待命、網路、動作、內容與螢幕保護各自可設內容及 16/32/48px 字高。
- 動作名稱、按鍵/滑鼠前綴、按住/放開後綴、測試訊息、設定成功與網路狀態可修改。
- 預設內容 32px、其餘主畫面 16px；較原本 8px 狀態字與 16px 內容更大。
- 字庫 28,560 個字形：ASCII、CJK 統一漢字/擴充 A、相容漢字及所列標點。繁簡中文可顯示；不是全部 Unicode，不含 Emoji 與擴充 B 以上罕字；缺字顯示替代符號。
- 不會把字偷偷縮小；每列單行，超出 228px 可用寬度右裁切。不支援自動換行。32px 約 7 個中文字。
- 主畫面五列字高總和最多 115px；不足空間會拒絕套用。留空只隱藏文字、不回收該列高度。螢幕保護獨立計算。
- 中文與字級新版已編譯，尚未燒錄與實機驗證。之前實機 UDP OK 是舊韌體，不當成本版字庫驗證。

## 使用
1. 關閉先前 Python GUI，避免仍執行舊程式。
2. VS Code / PlatformIO 開啟 esp32 資料夾，執行 Build；需要更新板上韌體才支援本功能。
   `pio run`，再進下載模式並執行 `pio run -t upload --upload-port COMx`。
   COMx 必須重新偵測，不固定 COM7；正常純 HID 程式不提供 CDC，可按住 BOOT、按放 RESET 再放 BOOT 進 ROM 下載模式。燒錄後放開 BOOT、重新插拔/RESET。
   使用正確原生 USB 連接埠；ROM/獨立 UART COM 不等於程式啟用 CDC。
   不要把 binaries/firmware.bin 當成完整 merged image 從位址 0 燒入；建議 PlatformIO 處理 bootloader/partition/application。
3. 在 python 資料夾：`python -m pip install -r requirements.txt`，`python gui.py`。
4. IP 填 LCD 的實際 IP（之前 192.0.2.1，DHCP 可能改變），Port 8888，初始化 UDP。
5. 在 LCD 區塊按「LCD 文字／字級／中文設定…」。內容與字級頁編輯六區，動作與狀態字面頁修改各狀態文案。
6. 按「儲存並套用」。PC 保存 config.json；ESP32 分別回覆 lcd_style/lcd_labels，必須有 status=ok、lcd_version=2、persisted=true 才確認新版接受並保存。
7. 按「中文顯示測試」；預設「中文測試成功」。請核對 LCD 實際顯示，測試不操作 HID。
8. 未連線時可先存 PC，下次初始化同步。ESP32 NVS 保存成功後，重新上電會讀取；相同設定不重複寫 Flash。

## 模板與通訊
- network 列支援 {ip}、{port}；其他主畫面列支援 {action}、{detail}。
- 自訂固定文字會取代該列動態內容；例如內容填固定「歡迎」後，就不再顯示按鍵/測試訊息；需保留 {detail} 才隨指令更新。
- saver 為固定文字，不展開模板。網路未就緒時使用 connecting/binding/network_error 字面。
- lcd_style 傳 rows（六列 text/size），完整驗證後套用；lcd_labels 傳 labels（狀態對照）。每個封包 <=1024 UTF-8 bytes、每文字 <=96 bytes。
- 兩筆設定各自驗證與 ACK，不是跨封包原子交易；UDP 可能掉包。少了某筆 ACK 可重新套用設定（不含 HID）；不要因此自動重送按鍵。
- 設定 UI 不保證 ESP32 真正顯示；以版本 ACK、實際 LCD 及重啟後保留為準。
- 大量 HID 指令時中文字形繪製可能增加處理時間；本次未做實機高頻壓力測試。UDP 未加認證，限可信 LAN。

## 驗證
- PlatformIO 最終編譯成功；靜態 RAM 79,368 bytes、Flash 2,125,781 / 3,342,336 bytes（63.6%）。現有 containsKey/TFT 警告仍在，不是無警告編譯。
- 6 項 LCD 設定/字庫/原 HID 呼叫序列回歸、7 項 UDP 回歸通過。
- Tk 設定視窗：保存、中文測試、非法字高拒絕與兩頁截圖通過，使用假傳送器，非實機。
- 原 GUI localhost UDP 測試通過，命令 lcd_config/lcd_style/lcd_labels/lcd_test/release_all。
- 字庫可用 `python tools/generate_unifont.py` 從隨附原始 hex 重建；已驗證重建 header SHA256 一致。
- 尚未驗證：本版實機中文字形、字級可讀性、NVS 重啟保留、高頻 HID、正常開機 USB 枚舉。

## 備份與恢復
backup 保存修改前 main.cpp/platformio.ini/gui.py/config.json、SHA256、差異與恢復腳本。
`python backup/restore_previous.py --python-root <Python目錄> --esp32-root <韌體目錄>`
已在額外副本恢復並核對 SHA256；不移除新 helper/font 檔，不會操作實機或清 NVS，舊版韌體如需回復仍須重新編譯燒錄。

## 字庫來源與授權
GNU Unifont 16.0.04：
https://unifoundry.com/pub/unifont/unifont-16.0.04/
https://unifoundry.com/pub/unifont/unifont-16.0.04/font-builds/unifont-16.0.04.hex.gz
來源摘要與選字範圍在 esp32/fonts/SOURCE.json；隨附官方 README/COPYING（包含 SIL OFL 1.1 與 GPL/font exception）。字形子集命名為 LCD subset，未冒用商業字型。原始來源不需於編譯時重新下載。

**私人包：ESP32 main.cpp 含你指定的 Wi-Fi 密碼，不要公開分享。未刷機、未 commit/push。**
