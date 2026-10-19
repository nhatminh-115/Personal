#pragma once
#include <Arduino.h>
struct PowerPlan {
  uint16_t litCount = 0;
  uint16_t estimatedLedMa = ALL_PIXELS_IDLE_MA;
  uint8_t r = 0, g = 0, b = 0;
  uint8_t scalePercent = 100;
  bool limited = false;
};
