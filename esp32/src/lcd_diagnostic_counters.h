#pragma once
#include <stdint.h>
namespace LcdDiagnostic {
// Loop-owned keyboard activation counters. tap=one, press=one; no HID calls here.
struct Counters {
  uint32_t hidCount = 0;
  uint32_t keyCount[256] = {};
  uint8_t lastKey = 0;
  bool hasLastKey = false;
  uint32_t buckets[10] = {};
  uint32_t bucketStartMs = 0;
  uint8_t bucketIndex = 0;
  static constexpr void bump(uint32_t &value) { if(value != UINT32_MAX) ++value; }
  constexpr void advance(uint32_t now) {
    const uint32_t steps = (now - bucketStartMs) / 100U;
    if(steps >= 10U) {
      for(unsigned i=0;i<10;i++) buckets[i]=0;
      bucketIndex=0;
    } else {
      for(uint32_t i=0;i<steps;i++) { bucketIndex=(bucketIndex+1U)%10U; buckets[bucketIndex]=0; }
    }
    bucketStartMs += steps * 100U;  // Unsigned arithmetic also handles millis wrap.
  }
  constexpr void onKey(uint8_t key, uint32_t now) {
    advance(now); bump(hidCount); bump(keyCount[key]); bump(buckets[bucketIndex]);
    lastKey=key; hasLastKey=true;
  }
  constexpr uint32_t rate(uint32_t now) {
    advance(now); uint32_t sum=0;
    for(unsigned i=0;i<10;i++) {
      if(UINT32_MAX-sum < buckets[i]) return UINT32_MAX;
      sum += buckets[i];
    }
    return sum;  // Number of activations in approximately the last 0.9..1.0 s.
  }
};
}
