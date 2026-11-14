#include "wifi_secrets.h"
#include <Arduino.h>
#include <FS.h>
#include <USB.h>
#include <USBHIDKeyboard.h>
#include <USBHIDMouse.h>
#include <ArduinoJson.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <atomic>
#include <Preferences.h>
#include "unifont_subset.h"
#include "lcd_diagnostic_counters.h"
#include "lcd_diagnostic_layout.h"

// Fill these locally. Empty SSID leaves HID/LCD active without networking.


static constexpr uint16_t UDP_PORT = 8888;
static constexpr size_t MAX_COMMAND_BYTES = 1024;
static constexpr size_t MAX_RESPONSE_BYTES = 256;
static constexpr UBaseType_t COMMAND_QUEUE_DEPTH = 8;

#if ARDUINO_USB_MODE != 0 || ARDUINO_USB_CDC_ON_BOOT
#error "Use TinyUSB device mode with CDC disabled"
#endif
#if ARDUINO_USB_MSC_ON_BOOT || ARDUINO_USB_DFU_ON_BOOT
#error "MSC/DFU must be disabled for HID-only application mode"
#endif

struct CommandPacket {
  uint32_t address;
  uint16_t port;
  char json[MAX_COMMAND_BYTES + 1];
};
struct ReplyPacket {
  uint32_t address;
  uint16_t port;
  char json[MAX_RESPONSE_BYTES];
};
static QueueHandle_t commandQueue = nullptr;
static QueueHandle_t replyQueue = nullptr;
static std::atomic<bool> udpListening{false};
static bool networkTaskStarted = false;
static String displayedNetworkStatus;
static String processCommand(String jsonStr);
static void drawNetworkStatus();

// Random hold duration, not electrical switch debouncing or packet deduplication.
static void randomHoldDelay() {
  delay(25U + (esp_random() % 36U));  // Inclusive 25..60 ms, yields the CPU.
}

#define LCD_BL_PIN 7

USBHIDKeyboard Keyboard;
USBHIDMouse Mouse;
TFT_eSPI tft = TFT_eSPI();
static LcdDiagnostic::Counters diagnosticKeys;  // Accessed only from loop().
static std::atomic<uint32_t> diagnosticUdpRx{0}; // udpTask writes; loop reads.
static TFT_eSprite diagnosticSprite(&tft);
static bool diagnosticSpriteReady=false;
static bool diagnosticForceDraw=true;
static uint8_t diagnosticSize=24;
static uint8_t diagnosticMask=7; // KEY, CNT, RATE; display selection only
static constexpr int DIAGNOSTIC_HEIGHT=135;
static const char *diagnosticNames[]={"KEY","CNT","RATE","HID","UDP","IP"};
static int diagnosticY() { return 0; }

bool screensaverEnabled = true;
uint32_t screensaverSeconds = 60;
bool lcdSleepEnabled = true;
uint32_t lcdSleepSeconds = 300;
uint32_t lastActivityMs = 0;
uint32_t lastSaverFrameMs = 0;
bool screensaverActive = false;
bool lcdSleeping = false;
int saverX = 8;
int saverDirection = 1;


struct DisplayRow { String text; uint8_t size; };
static DisplayRow displayRows[6] = {
  {"控制面板",16}, {"狀態：待命",16}, {"{ip}:{port}",16},
  {"{action}",16}, {"{detail}",32}, {"休息中",32}
};
static const char *rowKeys[] = {"title","status","network","action","detail","saver"};
static JsonDocument displayLabels;
static String lastAction, lastDetail;
static Preferences lcdPrefs;
static bool lcdPrefsReady = false;
static String label(const char *key, const char *fallback) {
  return displayLabels[key].is<const char *>() ? displayLabels[key].as<String>() : String(fallback);
}
static String errorReply(const char *msg) {
  JsonDocument r; r["status"]="error"; r["msg"]=msg; String out; serializeJson(r,out); return out;
}
static const LcdGlyph *glyphFor(uint32_t cp) {
  int lo=0, hi=sizeof(lcdGlyphs)/sizeof(lcdGlyphs[0])-1;
  while(lo<=hi) { int mid=(lo+hi)/2; uint16_t c=lcdGlyphs[mid].code;
    if(c==cp) return &lcdGlyphs[mid]; if(c<cp) lo=mid+1; else hi=mid-1; }
  if(cp!=0xfffd) return glyphFor(0xfffd); return nullptr;
}
static uint32_t nextCodepoint(const char *&p) {
  uint8_t c=static_cast<uint8_t>(*p++); if(c<128) return c;
  int n; uint32_t value;
  if(c>=0xc2 && c<=0xdf) { n=1;value=c&31; }
  else if(c>=0xe0 && c<=0xef) { n=2;value=c&15; }
  else if(c>=0xf0 && c<=0xf4) { n=3;value=c&7; }
  else return 0xfffd;
  for(int i=0;i<n;i++) { uint8_t b=static_cast<uint8_t>(*p); if((b&0xc0)!=0x80) return 0xfffd; ++p; value=(value<<6)|(b&63); }
  if((n==1 && value<128)||(n==2 && value<2048)||(n==3 && value<65536)||value>0x10ffff||(value>=0xd800 && value<=0xdfff)) return 0xfffd;
  return value;
}
static void drawUnicode(const String &text,int y,int pixels,uint16_t color) {
  const int scale=pixels/16, limit=234; int x=6; const char *p=text.c_str();
  while(*p) {
    auto g=glyphFor(nextCodepoint(p)); if(!g) continue;
    const int advance=g->width*scale;
    if(x+advance>limit) break; // Never shrink behind the user's back; right clipping.
    for(int row=0;row<16;row++) for(int col=0;col<g->width;col++) {
      if(g->rows[row*2+col/8] & (0x80>>(col%8))) tft.fillRect(x+col*scale,y+row*scale,scale,scale,color);
    }
    x+=advance;
  }
}
static String networkText() {
  if(!networkTaskStarted) return label("network_error","UDP 任務未啟動");
  if(WiFi.status()!=WL_CONNECTED) return label("connecting","Wi-Fi 連線中");
  if(!udpListening.load()) return label("binding","UDP 啟動中");
  String text=displayRows[2].text;
  text.replace("{ip}",WiFi.localIP().toString());text.replace("{port}",String(UDP_PORT));return text;
}
static String expandRow(String text) {
  text.replace("{action}",lastAction);text.replace("{detail}",lastDetail);return text;
}
// Home is now the selected diagnostic view; ordinary rows must not overlay it.
static void renderRow(int) { diagnosticForceDraw=true; }
static bool parseDiagnosticItems(JsonVariantConst value,uint8_t &mask) {
  mask=7;if(value.isNull())return true; // Existing clients/configs.
  if(!value.is<JsonArrayConst>())return false;
  mask=0;
  for(JsonVariantConst item:value.as<JsonArrayConst>()) {
    if(!item.is<const char*>())return false;
    bool found=false;
    for(int i=0;i<6;i++)if(strcmp(item.as<const char*>(),diagnosticNames[i])==0) {
      if(mask & (1U<<i))return false;
      mask|=1U<<i;found=true;break;
    }
    if(!found)return false;
  }
  return mask!=0;
}
static bool validRows(JsonVariantConst rows) {
  if(!rows.is<JsonObjectConst>())return false;
  int total=0;
  for(int i=0;i<6;i++) {
    JsonVariantConst r=rows[rowKeys[i]];
    if(!r.is<JsonObjectConst>() || !r["text"].is<const char *>() || !r["size"].is<int>())return false;
    int size=r["size"].as<int>(); if(size!=16 && size!=32 && size!=48)return false;
    if(strlen(r["text"].as<const char *>())>96)return false;
    if(i<5)total+=size;
  }
  return total<=115;
}
static void applyRows(JsonVariantConst rows) {
  for(int i=0;i<6;i++){displayRows[i].text=rows[rowKeys[i]]["text"].as<String>();displayRows[i].size=rows[rowKeys[i]]["size"].as<int>();}
}
static void loadLcdStyle() {
  lcdPrefsReady=lcdPrefs.begin("lcd-style",false);
  if(!lcdPrefsReady)return;
  JsonDocument d;
  if(!deserializeJson(d,lcdPrefs.getString("rows","")) && validRows(d.as<JsonVariantConst>()))applyRows(d.as<JsonVariantConst>());
  deserializeJson(displayLabels,lcdPrefs.getString("labels","{}"));
  const uint8_t savedSize=lcdPrefs.getUChar("diag-size",24);
  diagnosticSize=LcdDiagnosticLayout::valid(savedSize)?savedSize:(savedSize>32?32:24);
  const uint8_t savedMask=lcdPrefs.getUChar("diag-mask",7);
  diagnosticMask=(savedMask>0 && savedMask<64)?savedMask:7;
}
void drawHomeScreen() {
  diagnosticForceDraw=true;
  tft.fillScreen(TFT_BLACK);
  for(int i=0;i<5;i++)renderRow(i);
}

void wakeLcdIfNeeded() {
  const bool needsRedraw = lcdSleeping || screensaverActive;
  if (lcdSleeping) {
    tft.writecommand(TFT_SLPOUT);
    delay(120);
    tft.writecommand(TFT_DISPON);
    lcdSleeping = false;
  }
  screensaverActive = false;
  if (needsRedraw) drawHomeScreen();
  digitalWrite(LCD_BL_PIN, HIGH);
}

void updateLcdIdleMode() {
  const uint32_t now = millis();
  const uint32_t idleMs = now - lastActivityMs;
  if (lcdSleepEnabled && lcdSleepSeconds > 0 && idleMs >= lcdSleepSeconds * 1000UL) {
    if (!lcdSleeping) {
      tft.writecommand(TFT_DISPOFF);
      delay(20);
      tft.writecommand(TFT_SLPIN);
      digitalWrite(LCD_BL_PIN, LOW);
      lcdSleeping = true;
      screensaverActive = false;
    }
    return;
  }
  if (!screensaverEnabled || screensaverSeconds == 0 || idleMs < screensaverSeconds * 1000UL) return;
  if (!screensaverActive) {
    tft.fillScreen(TFT_BLACK);
    drawUnicode(displayRows[5].text, 20, displayRows[5].size, TFT_CYAN);
    screensaverActive = true;
    saverX = 8;
    saverDirection = 1;
    lastSaverFrameMs = 0;
  }
  if (now - lastSaverFrameMs >= 100) {
    tft.fillRect(saverX, 90, 8, 8, TFT_BLACK);
    saverX += saverDirection * 5;
    if (saverX >= 224 || saverX <= 8) saverDirection = -saverDirection;
    tft.fillRect(saverX, 90, 8, 8, TFT_YELLOW);
    lastSaverFrameMs = now;
  }
}

static void drawNetworkStatus() {
  String status=networkText();
  if(displayedNetworkStatus==status)return;
  displayedNetworkStatus=status;
  renderRow(2);
}

// A separate diagnostic parse classifies received control datagrams; it never
// rejects/changes the original packet, response, queue or command execution.
static bool isDiagnosticControlPacket(const char *json) {
  JsonDocument d;
  if(deserializeJson(d,json) || !d.is<JsonObject>())return false;
  const String action=d["action"] | "";
  if(action=="tap")return d["key"].is<const char*>() && strlen(d["key"].as<const char*>())>0;
  if(action=="press" || action=="release") {
    if(d.containsKey("key"))return d["key"].is<const char*>() && strlen(d["key"].as<const char*>())>0;
    if(!d.containsKey("btn"))return false;
    const String btn=d["btn"] | "left";return btn=="left" || btn=="right" || btn=="middle";
  }
  if(action=="click") {const String btn=d["btn"] | "left";return btn=="left" || btn=="right" || btn=="middle";}
  if(action=="release_all" || action=="move" || action=="scroll" || action=="lcd_test" || action=="lcd_config")return true;
  if(action=="lcd_style")return validRows(d["rows"].as<JsonVariantConst>());
  if(action=="lcd_labels") {
    if(!d["labels"].is<JsonObject>())return false;
    for(JsonPair pair:d["labels"].as<JsonObject>())if(!pair.value().is<const char*>() || strlen(pair.value().as<const char*>())>96)return false;
    return true;
  }
  return false;
}
static void noteDiagnosticUdp(const char *json) {
  if(!isDiagnosticControlPacket(json))return;
  const uint32_t count=diagnosticUdpRx.load(std::memory_order_relaxed);
  if(count!=UINT32_MAX)diagnosticUdpRx.store(count+1U,std::memory_order_relaxed);
}
// Exact-height nearest-neighbour resampling of original Unifont 8x16 cells.
// Destination-driven mapping supports true 20/24/28px, not pixels/16 rounding.
static void diagnosticText(const char *text,int y,int pixels) {
  int x=0;
  for(const char *p=text;*p;++p) {
    const auto g=glyphFor(static_cast<uint8_t>(*p));if(!g)continue;
    const int width=g->width*pixels/16;
    if(x+width>240)break;
    for(int dy=0;dy<pixels;++dy) {
      const int r=LcdDiagnosticLayout::sourceRow(dy,pixels);
      int run=-1;
      for(int dx=0;dx<=width;++dx) {
        const int c=LcdDiagnosticLayout::sourceColumn(dx,pixels);
        const bool on=dx<width && (g->rows[r*2+c/8] & (0x80>>(c%8)));
        if(on && run<0)run=dx;
        if(!on && run>=0) {
          if(diagnosticSpriteReady)diagnosticSprite.drawFastHLine(x+run,y+dy,dx-run,TFT_WHITE);
          else tft.drawFastHLine(x+run,diagnosticY()+y+dy,dx-run,TFT_WHITE);
          run=-1;
        }
      }
    }
    x+=width;
  }
}
static void updateDiagnosticLcd() {
  const uint32_t now=millis(),rate=diagnosticKeys.rate(now);
  static uint32_t lastDrawMs=0;
  if(lcdSleeping || screensaverActive || now-lastDrawMs<200U)return;
  lastDrawMs=now;
  const uint32_t udp=diagnosticUdpRx.load(std::memory_order_relaxed);
  char key[12]="-";
  if(diagnosticKeys.hasLastKey) {
    if(diagnosticKeys.lastKey>=33 && diagnosticKeys.lastKey<=126)snprintf(key,sizeof(key),"%c",diagnosticKeys.lastKey);
    else snprintf(key,sizeof(key),"0x%02X",diagnosticKeys.lastKey);
  }
  const uint32_t count=diagnosticKeys.hasLastKey?diagnosticKeys.keyCount[diagnosticKeys.lastKey]:0;
  char values[6][48];
  snprintf(values[0],48,"KEY %s",key);
  snprintf(values[1],48,"CNT %lu",static_cast<unsigned long>(count));
  snprintf(values[2],48,"RATE %lu/s",static_cast<unsigned long>(rate));
  snprintf(values[3],48,"HID %lu",static_cast<unsigned long>(diagnosticKeys.hidCount));
  snprintf(values[4],48,"UDP %lu",static_cast<unsigned long>(udp));
  snprintf(values[5],48,"IP %s:%u",WiFi.localIP().toString().c_str(),UDP_PORT);
  const int columns=LcdDiagnosticLayout::columns(diagnosticSize);
  char lines[18][31];int lineCount=0;
  for(int i=0;i<6;i++)if(diagnosticMask & (1U<<i)) {
    const int length=strlen(values[i]);
    for(int offset=0;offset<length && lineCount<18;offset+=columns) {
      const int n=min(columns,length-offset);memcpy(lines[lineCount],values[i]+offset,n);
      lines[lineCount][n]='\0';++lineCount;
    }
  }
  const int capacity=LcdDiagnosticLayout::capacity(diagnosticSize);
  const int pages=LcdDiagnosticLayout::pageCount(lineCount,diagnosticSize);
  const int page=pages>1?(now/1500U)%pages:0;
  static uint32_t shownH=UINT32_MAX,shownU=UINT32_MAX,shownR=UINT32_MAX;
  static int shownPage=-1;
  if(!diagnosticForceDraw && shownH==diagnosticKeys.hidCount && shownU==udp && shownR==rate && shownPage==page)return;
  const int first=page*capacity,visible=min(capacity,lineCount-first);
  const int y=LcdDiagnosticLayout::centeredY(visible,diagnosticSize);
  if(diagnosticSpriteReady)diagnosticSprite.fillSprite(TFT_BLACK);
  else tft.fillRect(0,0,240,135,TFT_BLACK);
  for(int i=0;i<visible;i++)diagnosticText(lines[first+i],y+i*diagnosticSize,diagnosticSize);
  if(diagnosticSpriteReady)diagnosticSprite.pushSprite(0,0);
  shownH=diagnosticKeys.hidCount;shownU=udp;shownR=rate;shownPage=page;diagnosticForceDraw=false;
}

// Only this task touches the UDP socket. HID/LCD remain in Arduino loop().
static void sendUdpReply(WiFiUDP &udp, uint32_t address, uint16_t port, const char *json) {
  if (!udp.beginPacket(IPAddress(address), port)) return;
  udp.write(reinterpret_cast<const uint8_t *>(json), strlen(json));
  udp.endPacket();
}

static void udpTask(void *) {
  WiFiUDP udp;
  IPAddress boundIp;
  bool listening = false;
  uint32_t lastReconnectMs = millis();
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      if (listening) udp.stop();
      listening = false;
      udpListening.store(false);
      // Do not execute stale commands after a lost Wi-Fi association.
      xQueueReset(commandQueue);
      xQueueReset(replyQueue);
      if (WIFI_SSID[0] != '\0' && millis() - lastReconnectMs >= 10000U) {
        lastReconnectMs = millis();
        WiFi.reconnect();
      }
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }
    const IPAddress ip = WiFi.localIP();
    if (listening && ip != boundIp) {
      udp.stop();
      listening = false;
      udpListening.store(false);
    }
    if (!listening) {
      listening = udp.begin(UDP_PORT) != 0;
      udpListening.store(listening);
      boundIp = ip;
      if (!listening) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        continue;
      }
    }
    // Bounded work per iteration; receive bursts cannot starve reply delivery.
    for (unsigned count = 0; count < 4; ++count) {
      const int packetSize = udp.parsePacket();
      if (packetSize <= 0) break;
      CommandPacket packet{};
      packet.address = static_cast<uint32_t>(udp.remoteIP());
      packet.port = udp.remotePort();
      if (packetSize > static_cast<int>(MAX_COMMAND_BYTES)) {
        while (udp.available()) udp.read();
        sendUdpReply(udp, packet.address, packet.port,
                     "{\"status\":\"error\",\"msg\":\"UDP payload too large\"}");
        continue;
      }
      const int n = udp.read(packet.json, packetSize);
      if (n != packetSize || memchr(packet.json, '\0', n > 0 ? n : 0)) {
        sendUdpReply(udp, packet.address, packet.port,
                     "{\"status\":\"error\",\"msg\":\"Invalid UDP payload\"}");
        continue;
      }
      packet.json[n] = '\0';
      noteDiagnosticUdp(packet.json);  // Count valid RX even if the original queue is full.
      if (xQueueSend(commandQueue, &packet, 0) != pdTRUE) {
        sendUdpReply(udp, packet.address, packet.port,
                     "{\"status\":\"error\",\"msg\":\"Command queue full\"}");
      }
    }
    ReplyPacket reply{};
    for (unsigned count = 0; count < COMMAND_QUEUE_DEPTH; ++count) {
      if (xQueueReceive(replyQueue, &reply, 0) != pdTRUE) break;
      sendUdpReply(udp, reply.address, reply.port, reply.json);
    }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

static void fixedKeyTap(uint8_t key) {
  diagnosticKeys.onKey(key,millis());  // One activation, not press + release twice.
  Keyboard.press(key);
  delay(50);  // Hold for at least 50 ms before sending key-up.
  Keyboard.release(key);
}
static void randomMouseClick(uint8_t button) {
  // Match Mouse.click's existing button-mask behavior, adding only a hold delay.
  Mouse.buttons(button);
  randomHoldDelay();
  Mouse.buttons(0);
}

void setup() {
  // 先關背光，待面板初始化及清屏完成後才點亮，避免啟動時顯示雜訊。
  pinMode(LCD_BL_PIN, OUTPUT);
  digitalWrite(LCD_BL_PIN, LOW);
  tft.init();
  tft.setRotation(1);  // 135x240 面板轉為橫向 240x135。
  diagnosticSprite.setColorDepth(1);
  diagnosticSprite.setBitmapColor(TFT_WHITE,TFT_BLACK);
  diagnosticSpriteReady=diagnosticSprite.createSprite(240,DIAGNOSTIC_HEIGHT)!=nullptr;
  // diagnosticText draws scaled glyph pixels directly; no small-font drawString path.
  loadLcdStyle();
  drawHomeScreen();
  digitalWrite(LCD_BL_PIN, HIGH);

  // 初始化 USB 與 HID 複合裝置
  Keyboard.begin();
  Mouse.begin();
  USB.begin();

  commandQueue = xQueueCreate(COMMAND_QUEUE_DEPTH, sizeof(CommandPacket));
  replyQueue = xQueueCreate(COMMAND_QUEUE_DEPTH, sizeof(ReplyPacket));
  if (commandQueue && replyQueue) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    if (WIFI_SSID[0] != '\0') WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    networkTaskStarted = xTaskCreate(udpTask, "udp_rx", 8192, nullptr, 1, nullptr) == pdPASS;
  }
  drawNetworkStatus();
  lastActivityMs = millis();
}

static String processCommand(String jsonStr) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, jsonStr);

  if (error) {
    return "{\"status\":\"error\",\"msg\":\"JSON parse failed\"}";
  }

  const String configAction=doc["action"] | "";
  if(configAction=="lcd_style") {
    if(!validRows(doc["rows"].as<JsonVariantConst>()))return errorReply("Invalid rows or height >115px");
    if(!doc["diagnostic_size"].isNull() && !doc["diagnostic_size"].is<int>())return errorReply("Invalid diagnostic size type");
    uint8_t mask;
    if(!parseDiagnosticItems(doc["diagnostic_items"].as<JsonVariantConst>(),mask))return errorReply("Select at least one valid diagnostic item");
    const int size=doc["diagnostic_size"] | 24;
    if(!LcdDiagnosticLayout::valid(size))return errorReply("Invalid diagnostic size");
    String saved;serializeJson(doc["rows"],saved);
    if(!lcdPrefsReady)return errorReply("NVS unavailable");
    if(lcdPrefs.getString("rows","")!=saved && lcdPrefs.putString("rows",saved)!=saved.length())return errorReply("NVS write failed");
    if(lcdPrefs.getUChar("diag-size",24)!=size && lcdPrefs.putUChar("diag-size",size)!=1)return errorReply("NVS write failed");
    if(lcdPrefs.getUChar("diag-size",24)!=size)return errorReply("NVS diagnostic size verify failed");
    if(lcdPrefs.getUChar("diag-mask",7)!=mask && lcdPrefs.putUChar("diag-mask",mask)!=1)return errorReply("NVS write failed");
    if(lcdPrefs.getUChar("diag-mask",7)!=mask)return errorReply("NVS diagnostic items verify failed");
    diagnosticMask=mask;
    diagnosticSize=size;
    diagnosticForceDraw=true;
    applyRows(doc["rows"].as<JsonVariantConst>());
  } else if(configAction=="lcd_labels") {
    if(!doc["labels"].is<JsonObject>())return errorReply("labels must be an object");
    for(JsonPair pair:doc["labels"].as<JsonObject>()) {
      if(!pair.value().is<const char *>() || strlen(pair.value().as<const char *>())>96)return errorReply("Invalid label");
    }
    String saved;serializeJson(doc["labels"],saved);
    if(!lcdPrefsReady)return errorReply("NVS unavailable");
    if(lcdPrefs.getString("labels","")!=saved && lcdPrefs.putString("labels",saved)!=saved.length())return errorReply("NVS write failed");
    displayLabels.set(doc["labels"]);
  }
  wakeLcdIfNeeded();
  lastActivityMs = millis();
  String action = doc["action"] | "";
  String targetKey = "";
  
  if (action == "tap") {
    String key = doc["key"] | "";
    targetKey = label("key","按鍵：") + key;
    if (key.length() > 0) fixedKeyTap(key.charAt(0));
  } 
  else if (action == "press" && doc.containsKey("key")) {
    String key = doc["key"] | "";
    targetKey = label("key","按鍵：") + key + label("hold","（按住）");
    if (key.length() > 0) {
      diagnosticKeys.onKey(static_cast<uint8_t>(key.charAt(0)),millis());
      Keyboard.press(key.charAt(0));
      delay(50);  // Remains held until a later release/release_all command.
    }
  } 
  else if (action == "release" && doc.containsKey("key")) {
    String key = doc["key"] | "";
    targetKey = label("key","按鍵：") + key + label("released","（放開）");
    if (key.length() > 0) Keyboard.release(key.charAt(0));
  } 
  else if (action == "click") {
    String btn = doc["btn"] | "left";
    targetKey = label("mouse","滑鼠：") + btn;
    if (btn == "left") randomMouseClick(MOUSE_LEFT);
    else if (btn == "right") randomMouseClick(MOUSE_RIGHT);
    else if (btn == "middle") randomMouseClick(MOUSE_MIDDLE);
  } 
  else if (action == "press" && doc.containsKey("btn")) {
    String btn = doc["btn"] | "left";
    targetKey = label("mouse","滑鼠：") + btn + label("hold","（按住）");
    if (btn == "left") { Mouse.press(MOUSE_LEFT); randomHoldDelay(); }
    else if (btn == "right") { Mouse.press(MOUSE_RIGHT); randomHoldDelay(); }
    else if (btn == "middle") { Mouse.press(MOUSE_MIDDLE); randomHoldDelay(); }
  } 
  else if (action == "release" && doc.containsKey("btn")) {
    String btn = doc["btn"] | "left";
    targetKey = label("mouse","滑鼠：") + btn + label("released","（放開）");
    if (btn == "left") Mouse.release(MOUSE_LEFT);
    else if (btn == "right") Mouse.release(MOUSE_RIGHT);
    else if (btn == "middle") Mouse.release(MOUSE_MIDDLE);
  } 
  else if (action == "move") {
    int x = doc["x"] | 0;
    int y = doc["y"] | 0;
    targetKey = label("move_detail","移動：") + String(x) + ", " + String(y);
    Mouse.move(x, y);
  } 
  else if (action == "scroll") {
    int y = doc["y"] | 0;
    targetKey = label("scroll_detail","捲動：") + String(y);
    Mouse.move(0, 0, y);
  } 
  else if (action == "release_all") {
    targetKey = label("all_released","全部放開");
    Keyboard.releaseAll();
    Mouse.release(MOUSE_ALL);
  } else if (action == "lcd_test") {
    // 純 LCD 測試命令；不觸發鍵盤或滑鼠 HID。
    targetKey = doc["message"].is<const char *>() ? doc["message"].as<String>() : label("test_message","中文測試成功");
  } else if (action == "lcd_config") {
    if (doc["screensaver_enabled"].is<bool>()) screensaverEnabled = doc["screensaver_enabled"].as<bool>();
    if (doc["sleep_enabled"].is<bool>()) lcdSleepEnabled = doc["sleep_enabled"].as<bool>();
    uint32_t saver = doc["screensaver_seconds"] | screensaverSeconds;
    uint32_t sleep = doc["sleep_seconds"] | lcdSleepSeconds;
    screensaverSeconds = constrain(saver, 5UL, 86400UL);
    lcdSleepSeconds = constrain(sleep, 5UL, 86400UL);
    targetKey = label("settings_saved","設定已套用");
  }

  if(action=="lcd_style" || action=="lcd_labels")targetKey=label("settings_saved","設定已套用");
  lastAction=label(action.c_str(),action.c_str());
  lastDetail=targetKey;
  if(action=="lcd_style" || action=="lcd_labels")drawHomeScreen();
  else { renderRow(3); renderRow(4); }

  // Return the existing JSON acknowledgement to the originating UDP endpoint.
  JsonDocument response;
  response["status"] = "ok";
  response["action"] = action;
  if(action=="lcd_style" || action=="lcd_labels") { response["lcd_version"]=2; response["persisted"]=true; response["diagnostic_renderer"]=3; response["diagnostic_size"]=diagnosticSize; JsonArray items=response["diagnostic_items"].to<JsonArray>(); for(int i=0;i<6;i++)if(diagnosticMask & (1U<<i))items.add(diagnosticNames[i]); }
  String result;
  serializeJson(response, result);
  return result;
}

void loop() {
  CommandPacket packet{};
  if (commandQueue && xQueueReceive(commandQueue, &packet, 0) == pdTRUE) {
    const String result = processCommand(String(packet.json));
    ReplyPacket reply{};
    reply.address = packet.address;
    reply.port = packet.port;
    if (result.length() < sizeof(reply.json)) result.toCharArray(reply.json, sizeof(reply.json));
    else strlcpy(reply.json, "{\"status\":\"error\",\"msg\":\"Response too large\"}", sizeof(reply.json));
    // Replies may be dropped under overload; UDP is not a reliable transport.
    xQueueSend(replyQueue, &reply, 0);
  }
  static uint32_t lastNetworkDrawMs = 0;
  if (!lcdSleeping && !screensaverActive && millis() - lastNetworkDrawMs >= 1000U) {
    lastNetworkDrawMs = millis();
    drawNetworkStatus();
  }
  updateLcdIdleMode();
  updateDiagnosticLcd();  // No new delay; bounded diagnostic region, at most 5 Hz.
  delay(1);
}
