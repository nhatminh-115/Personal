# Campus E Wayfinding × ESP32 Building LEDs

**Staging branch:** `nhatminh-115/Personal`, branch `feature/campus-e-led-sync`, directory `Campus-E-Wayfinding/`. The original `taitv-png/Campus-E-Wayfinding` is unchanged. Neither `Personal/main` nor upstream has been deployed/overwritten.

## User-visible behavior

- Select **F1...F7** on the right-hand 3D floor rail: ESP32 Spotlight for existing saved floor mapping 1–7.
- Select **GF**: internal LED floor 8 (a new, independently configurable ground-floor map; empty until set up).
- Select **Toàn bộ tòa nhà** or **Đặt lại**: return to moving, sparse Ambient, default 30 of 401 LEDs.
- **Tầng của tuyến** changes only 3D display, does not force another lighting mode.
- Original wayfinding and 3D navigation continue to work while ESP32 is offline. Browser LED panel reports broker status and waits for an authenticated ESP32 acknowledgement.

## Connectivity

`HTTPS GitHub Pages -> WSS MQTT test.mosquitto.org:8081 -> MQTT TLS test.mosquitto.org:8886 -> ESP32 STA Wi-Fi -> WS2812 strips`.

The browser does **not** send HTTP requests directly to `192.168.4.1` (blocked as mixed content on HTTPS sites). ESP32 retains its own Access Point and local dashboard for editing Pixel Mapping, but must also join 2.4 GHz Internet-enabled Wi-Fi to receive remote commands.

The demo broker is **public and unauthenticated**; TLS protects the channel and HMAC-SHA256 binds commands to a private device pairing key. ESP checks timestamp ±30 seconds and a monotonically increasing last accepted timestamp. This is appropriate for a proof-of-concept only; use an authenticated broker with topic ACLs for production.

## ESP32 firmware preparation

1. Install ESP32 Arduino board support and libraries **Adafruit NeoPixel**, **PubSubClient**. Open `firmware/BuildingSpotlight_SparseAmbient.ino`.
2. Place `firmware/led_mqtt_addon.h`, `firmware/led_mqtt_ca.h` and your own `firmware/led_private.h` in the **same Arduino sketch folder** as the `.ino`. Rename `.ino` folder to `BuildingSpotlight_SparseAmbient` if prompted.
3. Copy `firmware/led_private.h.example` as `led_private.h`, and set `LED_STA_SSID`, `LED_STA_PASSWORD`, a lowercase `LED_DEVICE_ID` (6–48 characters), and a random 32+ character `LED_PAIRING_KEY`.
4. **Never commit `led_private.h`.** Change firmware AP password from `12345678`; your pairing key and STA password are separate.
5. Upload firmware and monitor Serial at 115200. Confirm Wi-Fi STA, NTP time and MQTT connection. WSS port 8081 and MQTT TLS port 8886 must be reachable.
6. Edit the pixel mapping using ESP32 AP `ESP32_Building1` and browser `http://192.168.4.1`. Original F1–F7 saved mapping is read from NVS version 1; new GF mapping is slot 8, initialized empty. Saving writes NVS version 2.
7. On the Campus E website, enter Device ID and the same private pairing key in the new **Đồng bộ LED mô hình** panel, then click **Kết nối ESP32**. Key is kept in runtime memory only, never localStorage. Choose floors or entire building and observe “ESP32 đã áp dụng”.

## MQTT command format

The website publishes (QoS 0): `v1|device-id|unix-milliseconds|ambient|0|hmachex` or `v1|device-id|unix-milliseconds|spotlight|1..8|hmachex` to topic `campus-e-led/v1/{device-id}/cmd`. HMAC is over all preceding fields using SHA-256 and private pairing key. The ESP responds `ack|device-id|unix-milliseconds|mode|floor|hmachex` on `/ack` after applying the LEDs. The browser checks the ACK signature.

**Mappings:** GF = 8, F1 = 1, F2 = 2, ..., F7 = 7. Keep GF empty unless you need ground-floor LEDs. F1–F7 use the previous mapping slots unchanged.

## Hardware / supply

Five WS2812 strips on GPIO 13/14/16/17/18 with 79/79/79/83/81 pixels (401 total). Software keeps the original conservative estimated 1 A LED limit inside a 5 V 2 A total supply profile. Default sparse Ambient lights up to 30 spaced LED points at once. This is **not** a hardware current limit or proof of electrical safety. Use common ground, appropriate power injection, voltage checks, and direct load measurement before operation.

## Pulling into upstream and redeploying

Use this directory as the integration source. The **website code changes** are `components/CampusEMap.tsx` and new `components/LedBridge.tsx`. The **hardware code** is in `firmware/`. Copy web changes into the upstream website working tree, review, run `pnpm install --frozen-lockfile && pnpm pages:build`, and deploy using its original GitHub Pages workflow. The upstream `vite.pages.config.ts` must retain `base: "/Campus-E-Wayfinding/"` for its own published URL. No extra npm dependency is needed.

**Current status:** Published to the user’s GitHub feature branch as source code, **not** a live GitHub Pages URL; no ESP32 hardware has been compiled/flashed/tested in this session. TLS/broker routing and NVS migration must be verified with real board and network before installation. The original upstream repository is not modified.

**Source sites:** https://github.com/taitv-png/Campus-E-Wayfinding , https://test.mosquitto.org/