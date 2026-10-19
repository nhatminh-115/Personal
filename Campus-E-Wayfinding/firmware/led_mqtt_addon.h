#pragma once
// GitHub Pages (WSS MQTT) -> test.mosquitto.org -> ESP32 (MQTT TLS) -> WS2812.
// Include this header near the bottom of the base .ino, immediately ABOVE setup().
// Required symbols already declared in the base sketch:
// mode, MODE_AMBIENT, MODE_SPOTLIGHT, activeFloor, previewActive, needsPaint, paint().
// "GF" uses internal floor 8; F1..F7 retain their original indices.

#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <mbedtls/md.h>
#include <sys/time.h>
#include <time.h>
#include "led_private.h"
#include "led_mqtt_ca.h"

static WiFiClientSecure ledTls;
static PubSubClient ledMqtt(ledTls);
static uint64_t ledLastAcceptedMillis = 0;
static uint32_t ledLastAttempt = 0;
static String ledTopicRoot;

static bool ledIsDigits(const String &text) {
  if (text.isEmpty() || text.length() > 16) return false;
  for (unsigned i = 0; i < text.length(); ++i)
    if (text[i] < '0' || text[i] > '9') return false;
  return true;
}

static String ledHmacHex(const String &message) {
  byte digest[32] = {};
  const mbedtls_md_info_t *md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!md || mbedtls_md_hmac(md,
       (const unsigned char *)LED_PAIRING_KEY, strlen(LED_PAIRING_KEY),
       (const unsigned char *)message.c_str(), message.length(), digest) != 0) return "";
  const char *digits = "0123456789abcdef";
  char hex[65];
  for (int i = 0; i < 32; ++i) {
    hex[2*i] = digits[digest[i] >> 4];
    hex[2*i+1] = digits[digest[i] & 15];
  }
  hex[64] = 0;
  return String(hex);
}

static bool ledEqualHex(const String &expected, const String &got) {
  if (expected.length() != 64 || got.length() != 64) return false;
  unsigned char mismatch = 0;
  for (int i = 0; i < 64; ++i) mismatch |= expected[i] ^ got[i];
  return mismatch == 0;
}

static void ledOnMessage(char *topic, byte *bytes, unsigned int length) {
  if (length == 0 || length > 220 || String(topic) != ledTopicRoot + "/cmd") return;
  String message;
  message.reserve(length);
  for (unsigned int i = 0; i < length; ++i) message += (char)bytes[i];
  String parts[6];
  int start = 0;
  for (int i = 0; i < 5; ++i) {
    int cut = message.indexOf('|', start);
    if (cut < 0) return;
    parts[i] = message.substring(start, cut);
    start = cut + 1;
  }
  parts[5] = message.substring(start);
  if (parts[5].indexOf('|') >= 0) return;
  if (parts[0] != "v1" || parts[1] != LED_DEVICE_ID || !ledIsDigits(parts[2])) return;
  const bool isAmbient = parts[3] == "ambient";
  const bool isFloor = parts[3] == "spotlight";
  if (!isAmbient && !isFloor) return;
  if (!ledIsDigits(parts[4])) return;
  const int f = parts[4].toInt();
  if ((isAmbient && f != 0) || (isFloor && (f < 1 || f > NUM_FLOORS))) return;

  // Time-bound HMAC and strictly increasing timestamps reject old/replayed commands.
  struct timeval now;
  if (gettimeofday(&now, nullptr) != 0) return;
  const uint64_t nowMillis = uint64_t(now.tv_sec) * 1000ull + now.tv_usec / 1000;
  if (nowMillis < 1700000000000ull) return; // NTP not ready
  const uint64_t sentMillis = strtoull(parts[2].c_str(), nullptr, 10);
  if (sentMillis <= ledLastAcceptedMillis ||
      sentMillis + 30000ull < nowMillis || sentMillis > nowMillis + 30000ull) return;
  const String signedBody = message.substring(0, message.lastIndexOf('|'));
  if (!ledEqualHex(ledHmacHex(signedBody), parts[5])) return;

  ledLastAcceptedMillis = sentMillis;
  mode = isAmbient ? MODE_AMBIENT : MODE_SPOTLIGHT;
  if (isFloor) activeFloor = (uint8_t)f;
  previewActive = false;
  needsPaint = true;
  if (isAmbient) lastAmbientStep = millis();
  paint();

  const String ackBody = String("ack|") + LED_DEVICE_ID + "|" +
    parts[2] + "|" + parts[3] + "|" + parts[4];
  const String ack = ackBody + "|" + ledHmacHex(ackBody);
  ledMqtt.publish((ledTopicRoot + "/ack").c_str(), ack.c_str(), false);
  Serial.printf("LED remote: %s %d\n", isAmbient ? "ambient" : "floor", f);
}

static void ledRemoteSetup() {
  if (strlen(LED_PAIRING_KEY) < 16) {
    Serial.println("Remote disabled: use a private pairing key of at least 16 characters");
    return;
  }
  ledTopicRoot = String("campus-e-led/v1/") + LED_DEVICE_ID;
  WiFi.begin(LED_STA_SSID, LED_STA_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  ledTls.setCACert(MOSQUITTO_ROOT_CA);
  ledMqtt.setServer("test.mosquitto.org", 8886); // valid Let's Encrypt certificate
  ledMqtt.setCallback(ledOnMessage);
  ledMqtt.setBufferSize(384);
  Serial.println("Remote MQTT configured; waiting for STA Wi-Fi and NTP");
}

static void ledRemoteLoop() {
  if (WiFi.status() != WL_CONNECTED || strlen(LED_PAIRING_KEY) < 16) return;
  if (ledMqtt.connected()) {
    ledMqtt.loop();
    return;
  }
  const uint32_t t = millis();
  if (uint32_t(t - ledLastAttempt) < 5000) return;
  ledLastAttempt = t;
  if (time(nullptr) < 1700000000) return;
  String clientId = String("campus-esp-") + String((uint32_t)ESP.getEfuseMac(), HEX);
  if (ledMqtt.connect(clientId.c_str())) {
    ledMqtt.subscribe((ledTopicRoot + "/cmd").c_str(), 0);
    Serial.println("Remote MQTT connected");
  } else {
    Serial.printf("Remote MQTT connect failed, state=%d\n", ledMqtt.state());
  }
}
