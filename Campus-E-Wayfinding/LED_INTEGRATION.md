# Campus E Wayfinding × ESP32 Building LEDs

> Integration branch belonging to \`nhatminh-115\`, staged under \`Campus-E-Wayfinding/\` inside the \`Personal\` repository. It does **not** alter the upstream \`taitv-png/Campus-E-Wayfinding\` repository or the user's default branch.

## Behaviour

- In the wayfinding 3D map, click **GF / F1 / ... / F7** on the floor rail: send MQTT command \`F0\` / \`F1\` / ... / \`F7\` respectively. ESP32 switches to Spotlight and lights **only saved pixels mapped to that floor**.
- Click **Toàn bộ tòa nhà**: send \`A\`, ESP32 switches to **Sparse Ambient** (default 30 spaced pixels across five strips, moving every 180 ms).
- **Đặt lại** and **Tầng của tuyến** also send Ambient, since they show no unique selected floor.
- All map navigation features work with no LED attached. The little **Thiết lập LED** panel shows whether an ESP32 acknowledgment has been received.
- MQTT command publishes are **QoS 0** (low overhead). The ESP32 sends a matching per-command acknowledgment so the website does not mistake broker connectivity for successful LED control.

## Physical LED model

| Strip | Orientation | GPIO | WS2812 LEDs |
| --- | --- | --- | --- |
| 1 | Length | 13 | 79 |
| 2 | Length | 14 | 79 |
| 3 | Length | 16 | 79 |
| 4 | Width | 17 | 83 |
| 5 | Width | 18 | 81 |

Total **401 LEDs**. Supply **5 V / 2 A** is an upper bound, not an instruction to switch on all pixels. The current estimator assumes 1.5 mA static per powered LED and 20 mA per full-brightness color channel and targets an LED budget of 1000 mA. Another 500 mA is reserved for the ESP32 / radio, plus a 500 mA contingency. Estimates are **not** substitutes for an inline ammeter, low-voltage checks, adequate wiring, fuse, ground sharing and suitable 3.3 V→5 V logic level shifting where needed.

## Communication topology

\`\`\`text
GitHub Pages / any HTTPS browser site
    │  MQTT 3.1.1 over WSS (TLS)
    │  publish: <root>/cmd   e.g. F4:129 or A:130
    │  subscribe: <root>/ack
    ▼
Private, authenticated MQTT broker with WSS and TLS listeners
    ▲                 │
    │ TLS TCP:8883    │
    └─────────────────┘
ESP32 (outbound Wi-Fi station, ESP32 AP still enabled for mapping)
    │
    ├── subscribe: <root>/cmd
    └── publish:   <root>/ack   (echoes accepted command+sequence)
    ▼
Physical WS2812 strips
\`\`\`

There is **no \`fetch('http://192.168.4.1')\` from GitHub Pages**. Doing so from an HTTPS site can be blocked as mixed content; the AP is only for local mapping/configuration. **Both ESP32 and the user-facing browser need Internet connectivity to the broker**, which can come from the same shared Wi-Fi or different networks.

No broker is provisioned in the code. Use a broker that offers:
- TLS MQTT on port 8883 for ESP32 and WSS MQTT 3.1.1 for browsers.
- Authentication and topic ACLs. Give website operators **publish-only** permission for \`<root>/cmd\` and **subscribe-only** for \`<root>/ack\`, where supported. Give ESP32 the opposite. Use distinct broker accounts for browser and board.
- The root topic on the website and the ESP32 must match exactly. Use a device-specific root; avoid sharing commands with unrelated devices.
- Use a broker CA PEM file on the ESP32. **Do not** disable TLS certificate verification; do not put permanent admin passwords in a public GitHub repo or public kiosk HTML.

## Configure the board

1. Open \`esp32/CampusELedController.ino\` in Arduino IDE with ESP32 board package, **Adafruit NeoPixel**, and **PubSubClient** installed.
2. Before compiling, fill in the \`WIFI_STA_SSID\` / password, \`MQTT_HOST\`, \`MQTT_USERNAME\`, \`MQTT_PASSWORD\`, \`MQTT_TOPIC_ROOT\`, and \`MQTT_ROOT_CA\`. Note \`MQTT_HOST\` is a hostname, and \`MQTT_ROOT_CA\` is the PEM CA provided by your broker. Real values must never be committed to the repository. Set the secure AP password to something other than \`12345678\`.
3. Upload to ESP32. Connect locally to AP \`ESP32_Building1\`; open \`http://192.168.4.1\`. Mapping UI supports all 8 labels (GF, F1–F7), all 5 strips, comma-separated LED numbers, and ranges such as \`1,3,77-79\`.
4. Save mappings to NVS; local mapping stays available if Internet is lost. **Existing version-1 seven-floor NVS mappings are migrated in RAM into F1–F7; GF starts unmapped.** Press Save once to persist version 2.
5. Verify current consumption and LED voltage **under worst intended animations** and on your actual battery, then raise any brightness or dot-count settings cautiously.
6. On the website, open \`Thiết lập LED\`, enter broker **WSS URL** (usually \`wss://host:port/mqtt\`), device topic root, and browser-side MQTT credentials. Press \`Kết nối LED\`. Password is only kept in the page's memory for the current session. Observe \`ESP32 đã xác nhận\` before treating a floor change as successful.

For browsers operating publicly over GitHub Pages, ESP32 **cannot stay isolated on its own AP** and receive MQTT remotely. It must join an upstream Wi-Fi with outbound Internet access. The firmware runs **AP+STA** for both requirements.

## Test matrix

| Action | MQTT payload | Physical result |
|---|---|---|
| Select GF | \`F0:<sequence>\` | GF saved mapping, empty before configured |
| Select F1 | \`F1:<sequence>\` | Only F1 mapping |
| Select F7 | \`F7:<sequence>\` | Only F7 mapping |
| Select all-building | \`A:<sequence>\` | Sparse Ambient |
| Reset route | \`A:<sequence>\` | Sparse Ambient |
| Disconnect broker | none | 3D website remains usable; LED stays in last commanded mode |
| Reconnect browser | sync latest choice | ESP32 reenters currently selected floor or Ambient |

\`<sequence>\` is a decimal command identifier. Browser uses an in-memory counter (starting at 1 on each page session); ESP32 acknowledges only syntactically valid commands it applies. The ESP32 currently **does not authenticate the user itself**: broker access controls must do this. MQTT command/ack traffic must be ACL-restricted. The broker's availability and Wi-Fi credentials are deployment requirements, not supplied by this repository.

## Transferring back to the original website

The code is in the user's staging branch:
\`https://github.com/nhatminh-115/Personal/tree/feature/campus-e-led-sync/Campus-E-Wayfinding\`

A collaborator can **download this branch's code, copy the \`Campus-E-Wayfinding/\` contents into their own working tree, review the diffs**, then rebuild/redeploy the upstream site. Integration changes are primarily:

- \`components/esp32-led-sync.tsx\` — new MQTT/WSS browser adapter + UI.
- \`components/CampusEMap.tsx\` — floor selection & all-building actions wired to LED.
- \`esp32/CampusELedController.ino\` — independent ESP32 firmware with 8-floor mapping and TLS MQTT.
- This integration document.

For the original repository, retain its own \`vite.pages.config.ts\` base \`/Campus-E-Wayfinding/\` and existing GitHub Pages deployment workflow. The subfolder \`.github/workflows/deploy-pages.yml\` was copied for reference only; GitHub runs workflows from the repository's **root** \`.github/workflows/\`, so copying the site here does **not** automatically publish a new live Pages URL.

## Deployment status

**Committed to the user's GitHub feature branch; NOT a publicly deployed website, NOT hardware tested.** GitHub Pages is not switched on for this staging branch and no MQTT broker credentials or certificates have been supplied. Site source, commands, and firmware are staged for a later redeploy. Running a production installation requires the broker, Wi-Fi, TLS CA and at least one real ESP32 test.

Original website source: https://github.com/taitv-png/Campus-E-Wayfinding . Check the upstream project's reuse/redistribution rights with its maintainers before publishing a modified public mirror.
