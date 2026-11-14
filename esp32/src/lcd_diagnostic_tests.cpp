// Compile-time tests execute the production counter methods, no runtime test HID.
#include "lcd_diagnostic_counters.h"
using LcdDiagnostic::Counters;
constexpr bool zeroState() { Counters c; return c.hidCount==0 && !c.hasLastKey && c.rate(0)==0; }
constexpr bool perKeyAndTotal() {
  Counters c; for(int i=0;i<19;i++)c.onKey('3',10);
  for(int i=0;i<8;i++)c.onKey('4',20);
  if(c.hidCount!=27 || c.keyCount['3']!=19 || c.keyCount['4']!=8 || c.lastKey!='4')return false;
  c.onKey('3',30);return c.keyCount['3']==20 && c.keyCount['4']==8 && c.lastKey=='3';
}
constexpr bool rateExpires() {
  Counters c;c.onKey('3',0);
  return c.rate(0)==1 && c.rate(950)==1 && c.rate(1000)==0 && c.hidCount==1 && c.keyCount['3']==1;
}
constexpr bool stormRate() {
  Counters c;for(int i=0;i<100;i++)c.onKey('3',0);
  return c.rate(100)==100 && c.rate(1000)==0 && c.keyCount['3']==100;
}
constexpr bool wrapSafe() {
  Counters c;c.onKey('3',UINT32_MAX-10U);
  return c.rate(20U)==1 && c.rate(1200U)==0 && c.hidCount==1;
}
constexpr bool allDigitKeys() {
  Counters c;const char keys[]="34567890";
  for(unsigned i=0;i<8;i++){c.onKey(keys[i],1);c.onKey(keys[i],2);}
  for(unsigned i=0;i<8;i++)if(c.keyCount[static_cast<uint8_t>(keys[i])]!=2)return false;
  return c.hidCount==16;
}
constexpr bool saturation() {
  Counters c;c.hidCount=UINT32_MAX;c.keyCount['3']=UINT32_MAX;c.onKey('3',1);
  return c.hidCount==UINT32_MAX && c.keyCount['3']==UINT32_MAX;
}
static_assert(zeroState(),"diagnostics zero state");
static_assert(perKeyAndTotal(),"diagnostics counts survive key changes");
static_assert(rateExpires(),"diagnostics rate expires without new commands");
static_assert(stormRate(),"diagnostics distinguishes 100/s storm");
static_assert(wrapSafe(),"diagnostics millis wrap safety");
static_assert(allDigitKeys(),"diagnostics all required keys supported");
static_assert(saturation(),"diagnostics totals saturate instead of wrapping");
