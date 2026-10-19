/*
 * Building Light — ESP32 / WS2812 (Adafruit_NeoPixel)
 * 5 physical strips: GPIO 13, 14, 16, 17, 18
 * Lengths: 79, 79, 79, 83, 81 = 401 LEDs
 * 7 independently mapped floors, arbitrary pixels per floor / strip.
 *
 * Browser uses 1-based LEDs; NeoPixel library uses 0-based pixels.
 * Ambient: sparse moving dots. Only a configurable subset lights at once.
 * Spotlight turns on only pixels assigned to the selected floor.
 *
 * Requires ESP32 Arduino core and Adafruit NeoPixel library.
 * Access: WiFi "ESP32_Building1" / "12345678" -> http://192.168.4.1
 * IMPORTANT: Change AP_PASSWORD before real deployment.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>
#include "led_power_plan.h"
// Arduino's generated function prototypes appear before later type definitions.
struct PowerPlan;

static const char* AP_SSID = "ESP32_Building1";
static const char* AP_PASSWORD = "12345678";

constexpr uint8_t NUM_STRIPS = 5;
constexpr uint8_t NUM_FLOORS = 8; // F1..F7 and GF (stored last)
constexpr uint8_t MAP_BYTES = 11; // ceil(max(83)/8) = 11
constexpr uint8_t MAP_VERSION = 2; // migrate legacy v1 floor data
constexpr uint8_t STRIP_PINS[NUM_STRIPS] = {13, 14, 16, 17, 18};
constexpr uint16_t STRIP_LENGTHS[NUM_STRIPS] = {79, 79, 79, 83, 81};

// 5 V / 2 A source profile. Editable after you measure actual consumption.
// LED budget 1.0 A + ESP32/Wi-Fi reserve 0.5 A + contingency 0.5 A = 2 A.
// 401 powered pixels always have nonzero quiescent current, even when black.
// We conservatively model 1.5 mA/pixel plus up to 20 mA/channel (RGB).
// No software-only current estimator is a physical overcurrent protector.
constexpr uint16_t TOTAL_LEDS = 401;
constexpr uint16_t LED_BUDGET_MA = 1000;
constexpr uint16_t ESP32_RESERVE_MA = 500;
constexpr uint16_t SYSTEM_CONTINGENCY_MA = 500;
constexpr uint16_t PIXEL_IDLE_TENTHS_MA = 15; // 1.5 mA, model assumption
constexpr uint8_t PIXEL_CHANNEL_MA = 20;       // full R/G/B channel
constexpr uint16_t ALL_PIXELS_IDLE_MA = (TOTAL_LEDS * PIXEL_IDLE_TENTHS_MA + 9) / 10;
static_assert(ALL_PIXELS_IDLE_MA < LED_BUDGET_MA, "LED idle estimate exceeds budget");
static_assert(LED_BUDGET_MA + ESP32_RESERVE_MA + SYSTEM_CONTINGENCY_MA <= 2000, "Exceeds supply rating");

Adafruit_NeoPixel strip1(79, 13, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip2(79, 14, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip3(79, 16, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip4(83, 17, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel strip5(81, 18, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel* strips[NUM_STRIPS] = {&strip1, &strip2, &strip3, &strip4, &strip5};

using FloorMap = uint8_t[NUM_FLOORS][NUM_STRIPS][MAP_BYTES];
FloorMap savedMap = {};
FloorMap previewMap = {};

WebServer server(80);
DNSServer dnsServer;
Preferences preferences;

enum LightMode : uint8_t { MODE_OFF = 0, MODE_AMBIENT = 1, MODE_SPOTLIGHT = 2 };
LightMode mode = MODE_AMBIENT;
uint8_t activeFloor = 1; // 1..7 = F1..F7, 8 = GF
uint8_t brightnessPercent = 12; // requested output; guarded at every paint()
uint8_t ambientCount = 30;       // how many pixels may be lit across ALL 5 strips
uint16_t ambientStepMs = 180;    // advance one pixel every 180 ms
uint16_t ambientPhase = 0;
uint32_t lastAmbientStep = 0;
// Reverse when a physical strip was installed with LED #1 at the opposite end.
constexpr bool STRIP_REVERSED[NUM_STRIPS] = {false, false, false, false, false};
uint8_t red = 255, green = 228, blue = 168;
bool previewActive = false;
bool hasStoredMap = false;
bool needsPaint = true;

// Entire self-contained dashboard embedded in flash; no LittleFS or internet needed.
const char DASHBOARD_HTML[] PROGMEM = R"BLDUI(
<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a1322">
<title>Building Light · ESP32</title>
<style>
:root{color-scheme:dark;--bg:#0a1322;--panel:#101e31;--panel2:#162741;--line:#2b3c52;--ink:#f4f8ff;--sub:#9caec3;--accent:#76d9ba;--accent2:#f6c678;--red:#ff9898;--round:17px}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(ellipse at 5% 0%,#173249 0,transparent 32%),radial-gradient(ellipse at 100% 95%,#142b38 0,transparent 34%),var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
button,input{font:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:not-allowed}
.shell{max-width:1200px;margin:auto;padding:26px 24px 58px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap;margin-bottom:26px}
.kicker,.eyebrow{font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--accent);font-weight:750}
h1{font-size:clamp(26px,4vw,38px);letter-spacing:-.05em;line-height:1.1;margin:7px 0}
.subtitle{color:var(--sub);margin:7px 0 0}
.badge{border:1px solid #376356;background:#153b37;color:var(--accent);border-radius:99px;font-weight:750;font-size:12px;padding:9px 13px;display:flex;align-items:center;gap:9px;white-space:nowrap}
.badge:before{content:'';width:7px;height:7px;border-radius:50%;background:currentColor}
.badge.off{border-color:#6b4343;color:var(--red);background:#37202b}.badge.demo{border-color:#715c38;color:var(--accent2);background:#3a2d1a}
.top{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:19px}
.tabs{display:inline-flex;background:#101e31;border:1px solid var(--line);padding:5px;border-radius:12px;gap:3px}
.tab{border:0;border-radius:8px;color:var(--sub);background:none;padding:10px 18px;font-weight:700}.tab.active{background:#24435a;color:#fff}
.metrics{margin-left:auto;display:flex;gap:12px;flex-wrap:wrap}
.metric{background:#12253a;border:1px solid #254058;padding:7px 12px;border-radius:10px;color:var(--sub);font-size:12px}.metric b{color:var(--ink);font-size:16px;margin-right:4px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(320px,.86fr);gap:18px;align-items:start}
.panel{background:linear-gradient(150deg,#14253a,#0f1d2f);border:1px solid var(--line);border-radius:var(--round);padding:24px;box-shadow:0 12px 35px #020a1742}
.panel+.panel{margin-top:16px}
.panel h2{font-size:19px;letter-spacing:-.025em;margin:7px 0 6px}.desc{color:var(--sub);font-size:13px;margin:0 0 20px}
.label{font-weight:720;margin:0 0 9px}.mode-grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}
.mode{background:#13243a;border:1px solid #33485f;border-radius:12px;text-align:left;color:var(--ink);padding:16px;min-height:105px}
.mode .symbol{display:inline-block;margin-bottom:11px;font-size:19px}.mode b{display:block;font-size:16px}.mode small{display:block;color:var(--sub);margin-top:4px;font-size:12px}
.mode.active{border-color:var(--accent);background:#123c3c;box-shadow:0 0 0 1px #76d9ba33}
.separator{height:1px;background:var(--line);margin:23px 0}
.floor-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:8px}
.floor-button{border:1px solid #3a5167;border-radius:11px;background:#172b43;color:#c9d9e8;height:53px;font-weight:800}.floor-button.active{border-color:var(--accent);background:#1b554f;color:#e8fff7}
.controls{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:end}
.colorpicker{display:flex;align-items:center;gap:12px;border:1px solid var(--line);border-radius:11px;background:#0c1a2b;padding:7px 10px;width:100%}
.colorpicker input{width:42px;height:40px;padding:0;border:0;background:none;cursor:pointer}.colorpicker span{font-weight:750;letter-spacing:.05em}
input[type=range]{width:100%;accent-color:var(--accent);margin:11px 0 4px}
.rangehead{display:flex;justify-content:space-between;font-weight:700}.rangehead span{color:var(--accent)}
.btn{border:1px solid transparent;border-radius:10px;padding:11px 15px;font-weight:780;color:#10251f;background:var(--accent)}
.btn.alt{background:#1b3147;color:var(--ink);border-color:#365269}.btn.danger{background:#352b3b;color:#ffc2c2;border-color:#674553}.btn:active{transform:translateY(1px)}
.btnrow{display:flex;gap:9px;flex-wrap:wrap}.hint{font-size:12px;color:var(--sub);margin:12px 0 0}
.blueprint-title{display:flex;align-items:center;justify-content:space-between;gap:10px}
.mark{color:var(--accent);font-size:11px;letter-spacing:.1em;text-transform:uppercase;font-weight:800}
.matrix-head,.matrix-row{display:grid;grid-template-columns:60px repeat(5,minmax(0,1fr));gap:7px;align-items:center}
.matrix-head{margin-top:16px;margin-bottom:9px;color:var(--sub);font-size:11px;font-weight:750;text-align:center}
.matrix-row{margin:7px 0}
.floorlabel{font-size:13px;font-weight:800;color:#c9d8e8}.floorlabel small{display:block;font-size:10px;font-weight:500;color:#7c95aa}
.matrix-cell{min-width:0;padding:8px 3px;min-height:53px;border:1px solid #334c64;background:#152b41;border-radius:8px;text-align:center;color:var(--ink);font-size:15px;font-weight:800}
.matrix-cell small{display:block;font-size:9px;color:var(--sub);font-weight:550}.matrix-cell.filled{background:#205347;border-color:#3c8571}.matrix-cell.focused{outline:2px solid #f6c678;outline-offset:1px}
.legend{display:flex;gap:12px;flex-wrap:wrap;color:var(--sub);font-size:11px;margin-top:18px}.dot{display:inline-block;background:#205347;border:1px solid #3c8571;border-radius:3px;height:10px;width:10px;margin-right:5px}
.substats{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:23px}.stat{border:1px solid var(--line);border-radius:11px;background:#0e1d2f;padding:12px}.stat b{display:block;font-size:23px;letter-spacing:-.04em}.stat small{color:var(--sub)}
.notice{border:1px solid #67563c;background:#302a25;border-radius:10px;color:#f6d7a2;padding:12px 14px;font-size:12px;margin-top:18px}.notice.limited{border-color:#b47c45;background:#382b24}.notice .hint{font-size:11px}
.ambient-settings{margin-top:19px;border:1px solid #2b6658;background:#112e32;border-radius:12px;padding:15px}
.ambient-settings .desc{margin:9px 0 15px}
#preview-canvas{display:block;width:100%;height:auto;border:1px solid #284457;background:linear-gradient(160deg,#071524,#102b35);border-radius:12px}
.mapping-top{display:flex;align-items:flex-start;justify-content:space-between;gap:15px;flex-wrap:wrap}.mapping-layout{display:grid;grid-template-columns:300px minmax(0,1fr);gap:17px;align-items:start}
.selectline{display:flex;flex-wrap:wrap;gap:7px}.selectchip{background:#172c43;border:1px solid #35516a;border-radius:9px;color:#cfe0ee;padding:9px 12px;font-size:13px;font-weight:750}
.selectchip.active{background:#205446;border-color:var(--accent);color:#ebfff8}
.striplist{display:flex;flex-direction:column;gap:8px}
.stripitem{display:flex;justify-content:space-between;gap:10px;text-align:left;border-radius:10px;border:1px solid #334a61;background:#15283e;color:var(--ink);padding:11px 13px}
.stripitem.active{border-color:var(--accent);background:#1a423e}.stripitem small{display:block;color:var(--sub);font-size:11px}.stripitem strong{color:var(--accent);font-size:14px}
.pixelwrap{border:1px solid var(--line);border-radius:12px;background:#0d1a2a;padding:14px}
.pixel-head{display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:13px}
.pixel-grid{display:grid;grid-template-columns:repeat(10,minmax(0,1fr));gap:6px}
.pixel{min-width:0;aspect-ratio:1/1;background:#192d42;border:1px solid #38516a;color:#aebfd0;border-radius:7px;font-size:11px;font-weight:800;padding:0}
.pixel.on{background:var(--accent);color:#0b2520;border-color:var(--accent);box-shadow:0 0 12px #76d9ba29}
.pixel:focus-visible,button:focus-visible,input:focus-visible{outline:2px solid var(--accent2);outline-offset:2px}
.editor{margin-top:18px}.editor label{display:block;font-size:13px;font-weight:800;margin-bottom:8px}
.editor input[type=text]{width:100%;background:#0b1a2c;border:1px solid #38516a;border-radius:9px;padding:13px 11px;color:var(--ink);font-size:14px}
.editor .btnrow{margin-top:10px}
.savebar{margin-top:18px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-top:1px solid var(--line);padding-top:18px}
.savebar b{font-size:13px}.savebar small{display:block;color:var(--sub);font-size:12px}
#toast{position:fixed;z-index:10;bottom:22px;left:50%;transform:translateX(-50%);background:#235143;color:#eefff8;border:1px solid #63b69c;border-radius:11px;padding:11px 16px;box-shadow:0 12px 30px #0006;font-weight:750;max-width:90vw;display:none}
#toast.bad{background:#4a2930;border-color:#cf7583;color:#fff2f2}
.hidden{display:none!important}
@media(max-width:950px){.layout{grid-template-columns:1fr}.mapping-layout{grid-template-columns:1fr}.striplist{display:grid;grid-template-columns:repeat(5,minmax(0,1fr))}.stripitem{display:block;text-align:center;padding:11px 4px}.stripitem small{font-size:10px}}
@media(max-width:580px){.shell{padding:16px 12px 55px}.panel{padding:18px}.metrics{margin:0;width:100%}.metric{flex:1;text-align:center}.floor-grid{grid-template-columns:repeat(4,1fr)}.mode-grid{gap:7px}.mode{padding:12px}.controls{grid-template-columns:1fr}.matrix-head,.matrix-row{grid-template-columns:46px repeat(5,minmax(0,1fr));gap:4px}.matrix-cell{min-height:48px}.pixel-grid{grid-template-columns:repeat(8,minmax(0,1fr));gap:5px}.striplist{gap:5px}.stripitem{font-size:12px}.stripitem strong{font-size:12px}.badge{margin-top:0}.top{gap:14px}}
</style>
</head>
<body>
<main class="shell">
<header>
  <div><div class="kicker">ESP32 / LIGHT CONTROL SYSTEM</div><h1>Building Light<span style="color:var(--accent)">.</span></h1><p class="subtitle">Ánh sáng kiến trúc · 5 dây · GF + 7 tầng · WS2812</p></div>
  <div id="connection" class="badge off">Đang kết nối</div>
</header>
<div class="top">
  <nav class="tabs" aria-label="Trang"><button id="tab-control" class="tab active" type="button">Điều khiển</button><button id="tab-mapping" class="tab" type="button">Pixel Mapping</button></nav>
  <div class="metrics"><div class="metric"><b>5</b> dây</div><div class="metric"><b>401</b> LED</div><div class="metric"><b>7</b> tầng</div></div>
</div>
<section id="page-control" class="layout">
  <div>
    <section class="panel"><div class="eyebrow">01 — OPERATING MODE</div><h2>Chế độ chiếu sáng</h2><p class="desc">Chọn animation toàn tòa nhà hoặc tập trung vào một tầng.</p>
      <div class="mode-grid"><button class="mode active" id="mode-ambient" type="button"><span class="symbol">✦</span><b>Ambient</b><small>Animation toàn nhà</small></button><button class="mode" id="mode-spotlight" type="button"><span class="symbol">▤</span><b>Spotlight</b><small>Chiếu sáng từng tầng</small></button></div>
      <div class="separator"></div>
      <p class="label">Tầng đang chọn</p><div id="floors-control" class="floor-grid"></div>
      <p class="hint" id="mode-hint">Ambient: các điểm sáng di chuyển cách đều, không bật toàn bộ 401 bóng.</p>
      <div class="separator"></div>
      <div class="controls"><div><p class="label">Màu LED</p><div class="colorpicker"><input id="light-color" type="color" value="#ffe4a8" aria-label="Màu LED"><span id="color-label">#FFE4A8</span></div></div>
      <div><div class="rangehead">Độ sáng <span id="brightness-label">12%</span></div><input id="brightness" type="range" min="1" max="100" value="12"></div></div>
      <div id="ambient-settings" class="ambient-settings">
        <div class="eyebrow">SPARSE AMBIENT · ANIMATION</div>
        <p class="desc">Chỉ bật một số bóng, rải đều trên 5 dây và di chuyển tuần tự. Nếu công suất không đủ, ESP32 giảm <b>số bóng</b>, không giảm độ sáng các điểm.</p>
        <div class="controls">
          <div><div class="rangehead">Số bóng tối đa <span id="ambient-count-label">30 / 401</span></div><input id="ambient-count" type="range" min="5" max="60" step="5" value="30"></div>
          <div><div class="rangehead">Tốc độ di chuyển <span id="ambient-step-label">180 ms/bước</span></div><input id="ambient-step" type="range" min="80" max="500" step="20" value="180"></div>
        </div>
        <p class="hint">Ví dụ: 30 bóng = 6 bóng/dây, khoảng cách trung bình 13 LED. Các dây lệch pha để ánh sáng không chạy thành một hàng ngang.</p>
      </div>
      <div class="notice" id="power-guard" role="status" aria-live="polite"><b>POWER GUARD · NGUỒN 5V/2A</b><div id="power-guard-detail">Đang tính ngân sách điện…</div><div id="power-guard-result" class="hint">Nguồn LED được giới hạn bằng ước tính; chưa phải phép đo thực tế.</div></div>
      <p class="hint">Spotlight luôn giữ đúng pixel mapping; nếu quá tải sẽ giảm RGB. Ambient ưu tiên giữ màu/độ sáng nhưng giảm số điểm đang bật. Các phép tính chỉ là ước lượng.</p>
    </section>
    <section class="panel"><div class="eyebrow">02 — LIVE SIMULATION</div><h2>5 dây LED · mô phỏng</h2>
      <p class="desc">Các chấm sáng biểu diễn bố cục LED (được đơn giản hóa), không phải hình dạng thật của công trình.</p>
      <canvas id="preview-canvas" width="520" height="310" aria-label="Mô phỏng các LED đang sáng trên năm dây"></canvas>
      <p class="hint">Bản xem trước trên trình duyệt có thể lệch pha so với ESP32. Hướng lắp LED #1 sẽ quyết định hướng sáng ngoài thực tế.</p>
    </section>
    <section class="panel"><div class="eyebrow">03 — QUICK ACTIONS</div><h2>Thao tác nhanh</h2><p class="desc">Cấu hình LED theo tầng hoặc tắt sáng tạm thời.</p><div class="btnrow"><button class="btn" id="go-mapping">Cấu hình LED →</button><button class="btn alt" id="turn-off">Tắt tất cả</button></div></section>
  </div>
  <section class="panel"><div class="blueprint-title"><div><div class="eyebrow">FLOOR OVERVIEW</div><h2>Bản đồ tòa nhà</h2></div><span class="mark">7 × 5</span></div>
    <p class="desc">Mỗi ô cho biết số bóng được gán trên một dây ở một tầng. Bấm vào ô để chỉnh sửa.</p>
    <div class="matrix-head"><div>TẦNG</div><div>D1</div><div>D2</div><div>D3</div><div>N4</div><div>N5</div></div><div id="matrix"></div>
    <div class="legend"><span><i class="dot"></i>Có LED</span><span>D1–D3: chiều dài</span><span>N4–N5: chiều ngang</span></div>
    <div class="substats"><div class="stat"><b id="mapped-stat">0/401</b><small>LED đã gán ít nhất một tầng</small></div><div class="stat"><b id="floors-stat">0/7</b><small>Tầng đã cấu hình</small></div></div>
    <div id="conflict-summary" class="notice hidden"></div>
  </section>
</section>
<section id="page-mapping" class="hidden">
  <div class="mapping-top"><div><div class="eyebrow">DEVELOPER CONFIGURATION</div><h2 style="margin:7px 0">Pixel Mapping</h2><p class="desc">Chọn tầng và dây, sau đó đánh dấu bóng tương ứng. Số LED bắt đầu từ <b>1</b> (không phải 0).</p></div><div id="edit-status" class="badge demo">Chưa thay đổi</div></div>
  <div class="mapping-layout">
    <div class="panel"><p class="label">1. Chọn tầng</p><div id="floors-editor" class="selectline"></div><div class="separator"></div><p class="label">2. Chọn dây</p><div id="strip-editor" class="striplist"></div><p class="hint">D1–D3: chiều dài; N4–N5: chiều ngang. Thứ tự theo GPIO 13, 14, 16, 17, 18.</p><div class="separator"></div><div class="btnrow"><button class="btn danger" id="clear-floor">Xóa LED tầng này</button></div></div>
    <div class="panel"><div class="pixel-head"><div><div class="eyebrow" id="editing-label">TẦNG 1 · DÂY 1</div><h2 style="margin:4px 0" id="pixel-heading">Bản đồ LED</h2></div><div class="mark" id="selected-count">0 đã chọn</div></div>
      <div class="pixelwrap"><div id="pixel-grid" class="pixel-grid"></div></div>
      <p class="hint">Nhấn vào một bóng để bật/tắt lựa chọn. Các số ở đây là vị trí LED thực trên dây, không phải số GPIO.</p>
      <div class="editor"><label for="ranges">Hoặc nhập danh sách / khoảng LED</label><input id="ranges" type="text" autocomplete="off" placeholder="Ví dụ: 1,3,77,79 hoặc 1-3,77-79"><p class="hint">Phân cách bằng dấu phẩy. Dấu gạch nối là khoảng bao gồm cả hai đầu. Áp dụng sẽ thay thế lựa chọn của dây này tại tầng đang chọn.</p><div class="btnrow"><button class="btn alt" id="apply-ranges">Áp dụng danh sách</button><button class="btn danger" id="clear-strip">Xóa dây này</button></div></div>
      <div class="savebar"><div><b id="dirty-label">Cấu hình hiện tại</b><small>Lưu xuống ESP32 để tồn tại sau khi khởi động lại.</small></div><div class="btnrow"><button class="btn alt" id="reload-map">Hoàn tác</button><button class="btn alt" id="preview-floor">Xem thử trên LED</button><button class="btn" id="save-map">Lưu cấu hình</button></div></div>
      <div id="editor-warning" class="notice hidden"></div>
    </div>
  </div>
</section>
</main>
<div id="toast" role="status" aria-live="polite"></div>
<script>
'use strict';
const SIZES=[79,79,79,83,81], PINS=[13,14,16,17,18], FLOORS=8, BYTES=11, HEX_LENGTH=FLOORS*5*BYTES*2;
const DEMO=location.protocol==='file:';
const $=id=>document.getElementById(id);
const blank=()=>Array.from({length:FLOORS},()=>Array.from({length:5},()=>new Uint8Array(BYTES)));
let map=blank(), savedHex='0'.repeat(HEX_LENGTH), editFloor=0, editStrip=0, dirty=false, page='control', synced=false;
let state={mode:'ambient',floor:1,color:'#FFE4A8',brightness:12,ambientCount:30,ambientStepMs:180,preview:false,uptime:0,heap:0,activeLeds:30,estimatedLedMa:785,ledBudgetMa:1000,powerCapped:false,powerScalePct:100};
let demoPreviewHex=null;
const DEMO_START=Date.now();
function toHex(m=map){let out='';for(let f=0;f<FLOORS;f++)for(let s=0;s<5;s++)for(const b of m[f][s])out+=b.toString(16).padStart(2,'0');return out;}
function fromHex(h){if(typeof h!=='string'||h.length!==HEX_LENGTH||!/^[a-f0-9]+$/i.test(h))throw Error('Dữ liệu mapping không hợp lệ');const m=blank();let n=0;for(let f=0;f<FLOORS;f++)for(let s=0;s<5;s++)for(let b=0;b<BYTES;b++)m[f][s][b]=parseInt(h.slice(n,n+=2),16);return m;}
function has(m,f,s,i){return Boolean(m[f][s][i>>3]&(1<<(i&7)));}
function set(m,f,s,i,value){const b=i>>3,bit=1<<(i&7);if(value)m[f][s][b]|=bit;else m[f][s][b]&=(~bit)&255;}
function count(f,s){let n=0;for(let i=0;i<SIZES[s];i++)if(has(map,f,s,i))n++;return n;}
function floorCount(f){return SIZES.reduce((sum,_,s)=>sum+count(f,s),0);}
function getStats(){let unique=0,overlap=0;for(let s=0;s<5;s++)for(let i=0;i<SIZES[s];i++){let uses=0;for(let f=0;f<FLOORS;f++)if(has(map,f,s,i))uses++;if(uses)unique++;if(uses>1)overlap++;}return {unique,overlap,floors:Array.from({length:FLOORS},(_,f)=>floorCount(f)).filter(Boolean).length};}
function demoPower(){
  const source=demoPreviewHex?fromHex(demoPreviewHex):map;
  let n=0;if(state.mode==='spotlight')for(let s=0;s<5;s++)for(let i=0;i<SIZES[s];i++)if(has(source,state.floor-1,s,i))n++;
  const ch=[1,3,5].map(pos=>Math.floor(parseInt(state.color.slice(pos,pos+2),16)*state.brightness/100));
  let wanted=n,scale=1;
  const weight=ch.reduce((a,b)=>a+b,0),maxWeight=Math.floor((1000-602)*255/20);
  if(state.mode==='ambient'){
    wanted=state.ambientCount;
    n=weight?Math.min(wanted,Math.floor(maxWeight/weight)):wanted;
  } else if(state.mode==='off'){n=0;wanted=0;}
  else if(n*weight>maxWeight)scale=maxWeight/(n*weight);
  const actual=ch.map(v=>Math.floor(v*scale)),draw=Math.ceil(n*actual.reduce((a,b)=>a+b,0)*20/255);
  return {activeLeds:n,estimatedLedMa:602+draw,ledBudgetMa:1000,powerCapped:state.mode==='ambient'?n<wanted:scale<1,powerScalePct:Math.floor(scale*100)};
}
function demoCall(path,data){if(path==='/api/state')return {...state,...demoPower(),uptime:Math.floor((Date.now()-DEMO_START)/1000),heap:196000,ip:'DEMO',preview:Boolean(state.preview)};
  if(path==='/api/mapping'&&!data)return {ok:true,masks:savedHex,sizes:SIZES,saved:savedHex!=='0'.repeat(HEX_LENGTH)};
  if(path==='/api/control'){if(data.mode){state.mode=data.mode;state.preview=false;demoPreviewHex=null;}if(data.floor){state.floor=Number(data.floor);state.preview=false;demoPreviewHex=null;}if(data.color){state.color=data.color.toUpperCase();}if(data.brightness){state.brightness=Number(data.brightness);}if(data.ambientCount){state.ambientCount=Number(data.ambientCount);}if(data.ambientStepMs){state.ambientStepMs=Number(data.ambientStepMs);}return {ok:true};}
  if(path==='/api/preview'){state.mode='spotlight';state.floor=Number(data.floor);state.preview=true;demoPreviewHex=data.masks;return {ok:true};}
  if(path==='/api/mapping'&&data){savedHex=data.masks;state.preview=false;demoPreviewHex=null;try{localStorage.setItem('building-light-demo-map',savedHex)}catch(_){}return {ok:true};}
  throw Error('Endpoint không xác định');}
async function api(path,data){if(DEMO)return demoCall(path,data);const config={cache:'no-store'};if(data){config.method='POST';config.headers={'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8'};config.body=new URLSearchParams(data).toString();}const r=await fetch(path,config);let payload;try{payload=await r.json();}catch(_){throw Error('Phản hồi ESP32 không phải JSON');}if(!r.ok||payload.ok===false)throw Error(payload.error||'Lệnh bị từ chối');return payload;}
let toastTimer=null;
function toast(msg,bad=false){const el=$('toast');el.textContent=msg;el.classList.toggle('bad',bad);el.style.display='block';clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.style.display='none',3600);}
function connectivity(on){$('connection').textContent=DEMO?'DEMO · BROWSER':on?'ESP32 · ONLINE':'ESP32 · OFFLINE';$('connection').className='badge '+(DEMO?'demo':on?'':'off');}
function showPage(name){page=name;$('page-control').classList.toggle('hidden',name!=='control');$('page-mapping').classList.toggle('hidden',name!=='mapping');$('tab-control').classList.toggle('active',name==='control');$('tab-mapping').classList.toggle('active',name==='mapping');if(name==='mapping')renderEditor();else renderMatrix();}
function renderPower(){
  const lit=Number(state.activeLeds||0),ma=Number(state.estimatedLedMa||602),budget=Number(state.ledBudgetMa||1000);
  const bounded=Boolean(state.powerCapped),factor=Number(state.powerScalePct??100);
  $('power-guard-detail').textContent=lit+' LED được bật · ước tính '+ma+' / '+budget+' mA cho 5 dây (bao gồm dòng nền).';
  $('power-guard-result').textContent=bounded
    ?(state.mode==='ambient'?'Giữ độ sáng điểm LED, giảm từ '+state.ambientCount+' xuống '+lit+' bóng vì giới hạn dòng (ước tính).':'Đã giảm RGB xuống '+factor+'% mức yêu cầu để giữ đúng pixel mapping.')
    :'Không phải giảm độ sáng thêm. Dự phòng ~500 mA cho ESP32 và ~500 mA cho sai số nguồn/mạch.';
  $('power-guard').classList.toggle('limited',bounded);
}
function renderControls(){
  for(const m of ['ambient','spotlight'])$('mode-'+m).classList.toggle('active',state.mode===m);
  $('ambient-settings').classList.toggle('hidden',state.mode!=='ambient');
  $('floors-control').innerHTML=Array.from({length:FLOORS},(_,f)=>`<button type="button" class="floor-button ${state.mode==='spotlight'&&state.floor===f+1?'active':''}" data-floor="${f+1}">${f===7?"GF":f+1}</button>`).join('');
  $('mode-hint').textContent=state.mode==='ambient'?'Ambient: các điểm sáng cách đều, chạy dọc từng dây; không bật cả 401 bóng.':state.mode==='off'?'Đã tắt ánh sáng chủ động. Nhấn Ambient hoặc Spotlight để bật lại.':'Spotlight: chỉ bật bóng thuộc '+(state.floor===8?'GF':'tầng '+state.floor)+'.'+(state.preview?' Đang hiển thị bản xem trước chưa lưu.':'');
  $('light-color').value=state.color.toLowerCase();$('color-label').textContent=state.color.toUpperCase();
  $('brightness').value=state.brightness;$('brightness-label').textContent=state.brightness+'%';
  $('ambient-count').value=state.ambientCount;$('ambient-count-label').textContent=state.ambientCount+' / 401';
  $('ambient-step').value=state.ambientStepMs;$('ambient-step-label').textContent=state.ambientStepMs+' ms/bước';
  renderPower();
}
function renderMatrix(){let html='';for(const f of [6,5,4,3,2,1,0,7]){html+=`<div class="matrix-row"><div class="floorlabel">${f===7?"GF":"F"+(f+1)}<small>${f===7?"Tầng trệt":"Tầng "+(f+1)}</small></div>`;for(let s=0;s<5;s++){const n=count(f,s);html+=`<button type="button" data-f="${f}" data-s="${s}" class="matrix-cell ${n?'filled':''} ${page==='mapping'&&f===editFloor&&s===editStrip?'focused':''}">${n}<small>LED</small></button>`;}html+='</div>';}$('matrix').innerHTML=html;const info=getStats();$('mapped-stat').textContent=info.unique+'/401';$('floors-stat').textContent=info.floors+'/8';$('conflict-summary').classList.toggle('hidden',!info.overlap);$('conflict-summary').textContent=info.overlap+' bóng đang được gán cho nhiều tầng. Có thể cố ý, nhưng nên kiểm tra nếu không muốn tầng sáng chồng nhau.';}
function compactExpr(f,s){const numbers=[];for(let i=0;i<SIZES[s];i++)if(has(map,f,s,i))numbers.push(i+1);const parts=[];for(let i=0;i<numbers.length;){let j=i;while(j+1<numbers.length&&numbers[j+1]===numbers[j]+1)j++;parts.push(j>i?numbers[i]+'-'+numbers[j]:String(numbers[i]));i=j+1;}return parts.join(',');}
function renderEditor(){ $('floors-editor').innerHTML=Array.from({length:FLOORS},(_,f)=>`<button type="button" class="selectchip ${editFloor===f?'active':''}" data-floor="${f}">${f===7?"GF":"F"+(f+1)}</button>`).join('');$('strip-editor').innerHTML=SIZES.map((n,s)=>`<button type="button" class="stripitem ${editStrip===s?'active':''}" data-strip="${s}"><span><b>${s<3?'D':'N'}${s+1}</b><small>GPIO ${PINS[s]} · ${n} LED</small></span><strong>${count(editFloor,s)}</strong></button>`).join('');$('editing-label').textContent=(editFloor===7?'GF':'TẦNG '+(editFloor+1))+' · DÂY '+(editStrip+1);$('pixel-heading').textContent=SIZES[editStrip]+' bóng khả dụng';$('selected-count').textContent=count(editFloor,editStrip)+' đã chọn';$('pixel-grid').innerHTML=Array.from({length:SIZES[editStrip]},(_,i)=>`<button class="pixel ${has(map,editFloor,editStrip,i)?'on':''}" type="button" aria-pressed="${has(map,editFloor,editStrip,i)}" title="LED ${i+1}" data-pixel="${i}">${i+1}</button>`).join('');$('ranges').value=compactExpr(editFloor,editStrip);$('edit-status').textContent=dirty?'● CHƯA LƯU':'✓ ĐÃ ĐỒNG BỘ';$('edit-status').className='badge '+(dirty?'demo':'');$('dirty-label').textContent=dirty?'Có thay đổi chưa lưu':'Cấu hình đã lưu / chưa thay đổi';const info=getStats();$('editor-warning').classList.toggle('hidden',!info.overlap);$('editor-warning').textContent=info.overlap+' bóng được gán cho hơn một tầng. Chỉ lưu nếu đây là chủ ý.';}
function modified(){dirty=toHex()!==savedHex;renderEditor();renderMatrix();}
function parseList(expr,max){if(!expr.trim())return [];const output=new Set();for(const part of expr.split(',')){const chunk=part.trim();const match=/^(\d+)(?:\s*-\s*(\d+))?$/.exec(chunk);if(!match)throw Error('Sai cú pháp tại: "'+chunk+'"');const a=Number(match[1]),b=match[2]?Number(match[2]):a;if(a<1||b<a||b>max)throw Error('Khoảng '+chunk+' phải nằm trong 1–'+max);for(let i=a;i<=b;i++)output.add(i-1);}return [...output];}
async function command(data){try{await api('/api/control',data);await refreshState();}catch(e){connectivity(false);toast('Không gửi được: '+e.message,true);}}
async function refreshState(){try{state=await api('/api/state');renderControls();connectivity(true);}catch(e){connectivity(false);}}
async function saveMapping(){try{const hex=toHex();if(DEMO||confirm('Ghi cấu hình của GF + 7 tầng xuống ESP32?')){await api('/api/mapping',{masks:hex});savedHex=hex;dirty=false;renderEditor();renderMatrix();await refreshState();toast('Đã lưu cấu hình '+(DEMO?'trong bản xem trước.':'vào ESP32.'));}}catch(e){toast('Không lưu được: '+e.message,true);}}
async function previewMapping(){try{await api('/api/preview',{floor:String(editFloor+1),masks:toHex()});await refreshState();toast('Đang xem thử '+(editFloor===7?'GF':'tầng '+(editFloor+1))+(DEMO?' (giả lập).':'. Chưa lưu vào bộ nhớ.'));}catch(e){toast('Lỗi preview: '+e.message,true);}}
async function loadMapping(){const resp=await api('/api/mapping');savedHex=resp.masks;map=fromHex(resp.masks);dirty=false;renderEditor();renderMatrix();}
$('tab-control').onclick=()=>showPage('control');$('tab-mapping').onclick=()=>showPage('mapping');$('go-mapping').onclick=()=>showPage('mapping');$('turn-off').onclick=()=>command({mode:'off'});
$('mode-ambient').onclick=()=>command({mode:'ambient'});$('mode-spotlight').onclick=()=>command({mode:'spotlight'});
$('floors-control').onclick=e=>{const b=e.target.closest('[data-floor]');if(b)command({mode:'spotlight',floor:b.dataset.floor});};
$('light-color').onchange=e=>command({color:e.target.value});$('light-color').oninput=e=>$('color-label').textContent=e.target.value.toUpperCase();
$('brightness').oninput=e=>$('brightness-label').textContent=e.target.value+'%';$('brightness').onchange=e=>command({brightness:e.target.value});
$('ambient-count').oninput=e=>$('ambient-count-label').textContent=e.target.value+' / 401';
$('ambient-count').onchange=e=>command({ambientCount:e.target.value});
$('ambient-step').oninput=e=>$('ambient-step-label').textContent=e.target.value+' ms/bước';
$('ambient-step').onchange=e=>command({ambientStepMs:e.target.value});
$('matrix').onclick=e=>{const b=e.target.closest('[data-f]');if(!b)return;editFloor=Number(b.dataset.f);editStrip=Number(b.dataset.s);showPage('mapping');};
$('floors-editor').onclick=e=>{const b=e.target.closest('[data-floor]');if(!b)return;editFloor=Number(b.dataset.floor);renderEditor();};
$('strip-editor').onclick=e=>{const b=e.target.closest('[data-strip]');if(!b)return;editStrip=Number(b.dataset.strip);renderEditor();};
$('pixel-grid').onclick=e=>{const b=e.target.closest('[data-pixel]');if(!b)return;const i=Number(b.dataset.pixel);set(map,editFloor,editStrip,i,!has(map,editFloor,editStrip,i));modified();};
$('apply-ranges').onclick=()=>{try{const selected=parseList($('ranges').value,SIZES[editStrip]);map[editFloor][editStrip].fill(0);for(const i of selected)set(map,editFloor,editStrip,i,true);modified();toast('Đã áp dụng '+selected.length+' bóng ở dây '+(editStrip+1)+'.');}catch(e){toast(e.message,true);}};
$('clear-strip').onclick=()=>{map[editFloor][editStrip].fill(0);modified();};
$('clear-floor').onclick=()=>{if(!confirm('Xóa toàn bộ LED đã gán cho '+(editFloor===7?'GF':'tầng '+(editFloor+1))+' trên cả 5 dây?'))return;for(let s=0;s<5;s++)map[editFloor][s].fill(0);modified();};
$('reload-map').onclick=()=>{if(dirty&&!confirm('Bỏ tất cả thay đổi chưa lưu?'))return;map=fromHex(savedHex);dirty=false;renderEditor();renderMatrix();toast('Đã hoàn tác về bản lưu.');};
$('preview-floor').onclick=previewMapping;$('save-map').onclick=saveMapping;

function drawPreview(){
  const canvas=$('preview-canvas');if(!canvas)return;
  const ctx=canvas.getContext('2d');if(!ctx)return;
  const W=canvas.width,H=canvas.height,top=30,usable=H-48;
  ctx.clearRect(0,0,W,H);
  ctx.font='600 12px system-ui';ctx.textAlign='center';
  const n=Number(state.activeLeds||0),per=Math.floor(n/5),extra=n%5;
  const phase=Math.floor(Date.now()/Math.max(80,Number(state.ambientStepMs)||180));
  const selected=state.mode==='spotlight'?(demoPreviewHex?fromHex(demoPreviewHex):map):null;
  for(let s=0;s<5;s++){
    const len=SIZES[s],x=65+s*98;
    ctx.fillStyle='#94b2bf';ctx.fillText('D'+(s+1),x,19);
    ctx.strokeStyle='#244e58';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+usable);ctx.stroke();
    const lit=new Set();
    if(state.mode==='ambient'){
      const count=per+(s<extra?1:0);
      for(let j=0;j<count;j++)lit.add(((phase+s*7)%len+Math.floor(j*len/count))%len);
    }else if(state.mode==='spotlight'){
      for(let i=0;i<len;i++)if(has(selected,state.floor-1,s,i))lit.add(i);
    }
    for(let i=0;i<len;i++){
      const y=top+(i/(len-1))*usable;
      ctx.fillStyle=lit.has(i)?state.color:'#305064';
      if(lit.has(i)){ctx.shadowBlur=8;ctx.shadowColor=state.color;}else{ctx.shadowBlur=0;}
      ctx.beginPath();ctx.arc(x,y,lit.has(i)?2.55:1.1,0,Math.PI*2);ctx.fill();
    }
    ctx.shadowBlur=0;
    ctx.fillStyle='#7192a2';ctx.font='10px system-ui';ctx.fillText(len+' LED',x,H-7);
  }
}
setInterval(drawPreview,180);

window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
async function boot(){if(DEMO){try{const h=localStorage.getItem('building-light-demo-map');if(h&&h.length===HEX_LENGTH)savedHex=h;}catch(_){}}try{if(!DEMO)await loadMapping();else{map=fromHex(savedHex);renderEditor();renderMatrix();}await refreshState();synced=true;}catch(e){connectivity(false);toast('Không tải được cấu hình: '+e.message,true);}setInterval(refreshState,4000);drawPreview();}
boot();
</script>
</body>
</html>
)BLDUI";

static bool pixelMapped(const FloorMap &m, uint8_t floor0, uint8_t strip0, uint16_t led0) {
  return (m[floor0][strip0][led0 >> 3] & (1u << (led0 & 7))) != 0;
}

// Enforces a TOTAL pixel power budget, not a separate cap for each strip.
// The UI brightness slider is treated as a request; the RGB values are
// scaled in one step AFTER inspecting the mapped LED count.
// PowerPlan is defined in led_power_plan.h before Arduino prototypes.

static PowerPlan calculatePowerPlan() {
  PowerPlan plan;
  if (mode == MODE_OFF) return plan;
  const uint8_t wantR = uint16_t(red) * brightnessPercent / 100u;
  const uint8_t wantG = uint16_t(green) * brightnessPercent / 100u;
  const uint8_t wantB = uint16_t(blue) * brightnessPercent / 100u;
  plan.r = wantR; plan.g = wantG; plan.b = wantB;
  const uint16_t channelWeight = uint16_t(wantR) + wantG + wantB;
  const uint32_t maxWeight = uint32_t(LED_BUDGET_MA - ALL_PIXELS_IDLE_MA)
    * 255u / PIXEL_CHANNEL_MA;

  if (mode == MODE_AMBIENT) {
    // Prefer SPARSE lighting over dimming the entire strip.
    // Keep requested color/brightness, reduce the number of lit dots if required.
    uint16_t safeCount = ambientCount;
    if (channelWeight > 0) {
      safeCount = static_cast<uint16_t>(maxWeight / channelWeight);
      if (safeCount > ambientCount) safeCount = ambientCount;
    }
    plan.litCount = safeCount;
    plan.limited = safeCount < ambientCount;
  } else { // Spotlight: honor exact floor mapping, then scale RGB when necessary.
    const FloorMap &source = previewActive ? previewMap : savedMap;
    for (uint8_t s = 0; s < NUM_STRIPS; ++s) {
      for (uint16_t i = 0; i < STRIP_LENGTHS[s]; ++i) {
        if (pixelMapped(source, activeFloor - 1, s, i)) ++plan.litCount;
      }
    }
    const uint32_t requestedWeight = uint32_t(plan.litCount) * channelWeight;
    if (requestedWeight > maxWeight) {
      plan.limited = true;
      const uint32_t factor = uint32_t((uint64_t(maxWeight) * 65536u)
        / requestedWeight);
      plan.r = uint8_t((uint32_t(wantR) * factor) >> 16);
      plan.g = uint8_t((uint32_t(wantG) * factor) >> 16);
      plan.b = uint8_t((uint32_t(wantB) * factor) >> 16);
      plan.scalePercent = uint8_t(uint32_t(factor) * 100u / 65536u);
    }
  }
  const uint32_t actualWeight = uint32_t(plan.litCount) *
    (uint16_t(plan.r) + uint16_t(plan.g) + uint16_t(plan.b));
  const uint32_t dynamicMa = (actualWeight * PIXEL_CHANNEL_MA + 254u) / 255u;
  plan.estimatedLedMa = uint16_t(ALL_PIXELS_IDLE_MA + dynamicMa);
  return plan;
}

// Space N dots evenly along a vertical strip; phases differ between strips.
// j*len/N produces unique locations for the supported N <= 12 per strip.
static uint16_t ambientPixelFor(uint8_t s, uint16_t j, uint16_t count) {
  const uint16_t len = STRIP_LENGTHS[s];
  const uint16_t start = (uint32_t(ambientPhase) + uint16_t(s) * 7u) % len;
  uint16_t pixel = (start + uint32_t(j) * len / count) % len;
  if (STRIP_REVERSED[s]) pixel = len - 1u - pixel;
  return pixel;
}

static void paint() {
  if (!needsPaint) return;
  needsPaint = false;
  const PowerPlan plan = calculatePowerPlan();
  const FloorMap &source = previewActive ? previewMap : savedMap;
  for (uint8_t s = 0; s < NUM_STRIPS; ++s) {
    Adafruit_NeoPixel* strip = strips[s];
    strip->clear();
    if (mode == MODE_SPOTLIGHT) {
      for (uint16_t i = 0; i < STRIP_LENGTHS[s]; ++i) {
        if (pixelMapped(source, activeFloor - 1, s, i)) {
          strip->setPixelColor(i, plan.r, plan.g, plan.b);
        }
      }
    } else if (mode == MODE_AMBIENT) {
      // Split the active budget evenly over all 5 strips (remainder to the first).
      const uint16_t n = plan.litCount / NUM_STRIPS + (s < (plan.litCount % NUM_STRIPS) ? 1 : 0);
      for (uint16_t j = 0; j < n; ++j) {
        strip->setPixelColor(ambientPixelFor(s, j, n), plan.r, plan.g, plan.b);
      }
    }
    strip->show();
  }
}

static void loadMapping() {
  memset(savedMap, 0, sizeof(savedMap));
  hasStoredMap = false;
  if (!preferences.begin("buildingled", true)) {
    Serial.println("WARN: NVS read failed; starting with empty mapping");
    return;
  }
  const uint8_t storedVersion = preferences.getUChar("version", 0);
  const size_t storedSize = preferences.getBytesLength("mask");
  const size_t legacyBytes = 7u * NUM_STRIPS * MAP_BYTES;
  if (storedVersion == MAP_VERSION && storedSize == sizeof(savedMap)) {
    hasStoredMap = preferences.getBytes("mask", savedMap, sizeof(savedMap)) == sizeof(savedMap);
  } else if (storedVersion == 1 && storedSize == legacyBytes) {
    // Preserve all seven old floor mappings. GF is an initially empty eighth map.
    hasStoredMap = preferences.getBytes("mask", savedMap, legacyBytes) == legacyBytes;
    if (hasStoredMap) Serial.println("Legacy 7-floor mapping imported; save to migrate to v2");
  }
  preferences.end();
  if (!hasStoredMap) memset(savedMap, 0, sizeof(savedMap));
  Serial.printf("Mapping: %s (%u bytes)\n", hasStoredMap ? "loaded" : "empty", (unsigned)sizeof(savedMap));
}

static bool persistMapping(const FloorMap &candidate) {
  if (!preferences.begin("buildingled", false)) return false;
  size_t written = preferences.putBytes("mask", candidate, sizeof(savedMap));
  size_t versionWritten = 0;
  if (written == sizeof(savedMap)) versionWritten = preferences.putUChar("version", MAP_VERSION);
  preferences.end();
  if (written != sizeof(savedMap) || versionWritten != 1) return false;
  memcpy(savedMap, candidate, sizeof(savedMap));
  hasStoredMap = true;
  previewActive = false;
  needsPaint = true;
  return true;
}

static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static bool parseMappingHex(const String &hex, FloorMap &result) {
  const size_t expected = sizeof(result) * 2;
  if (hex.length() != expected) return false;
  uint8_t *out = reinterpret_cast<uint8_t*>(result);
  for (size_t i = 0; i < sizeof(result); ++i) {
    const int hi = hexNibble(hex[2 * i]);
    const int lo = hexNibble(hex[2 * i + 1]);
    if (hi < 0 || lo < 0) return false;
    out[i] = uint8_t((hi << 4) | lo);
  }
  // Reject bits beyond physical strip lengths (e.g., LED 80 in a 79-LED strip).
  for (uint8_t f = 0; f < NUM_FLOORS; ++f)
    for (uint8_t s = 0; s < NUM_STRIPS; ++s)
      for (uint16_t i = STRIP_LENGTHS[s]; i < MAP_BYTES * 8u; ++i)
        if (pixelMapped(result, f, s, i)) return false;
  return true;
}

static String mappingHex() {
  const char DIGITS[] = "0123456789abcdef";
  const uint8_t* data = reinterpret_cast<const uint8_t*>(savedMap);
  String out;
  out.reserve(sizeof(savedMap) * 2);
  for (size_t i = 0; i < sizeof(savedMap); ++i) {
    uint8_t b = data[i];
    out += DIGITS[b >> 4];
    out += DIGITS[b & 15];
  }
  return out;
}

static void respondError(int status, const String &message) {
  server.send(status, "application/json; charset=utf-8", "{\"ok\":false,\"error\":\"" + message + "\"}");
}

static void respondOK() {
  server.send(200, "application/json; charset=utf-8", "{\"ok\":true}");
}

static bool unsignedNumber(const String& value, uint16_t minValue, uint16_t maxValue, uint16_t &result) {
  if (value.isEmpty()) return false;
  unsigned long out = 0;
  for (size_t i = 0; i < value.length(); ++i) {
    if (value[i] < '0' || value[i] > '9') return false;
    out = out * 10u + (value[i] - '0');
    if (out > maxValue) return false;
  }
  if (out < minValue) return false;
  result = static_cast<uint16_t>(out);
  return true;
}

static bool parseHTMLColor(String text, uint8_t &r, uint8_t &g, uint8_t &b) {
  if (text.length() != 7 || text[0] != '#') return false;
  uint8_t rgb[3] = {};
  for (int i = 0; i < 3; ++i) {
    int a = hexNibble(text[1 + i * 2]);
    int z = hexNibble(text[2 + i * 2]);
    if (a < 0 || z < 0) return false;
    rgb[i] = uint8_t((a << 4) | z);
  }
  r = rgb[0]; g = rgb[1]; b = rgb[2];
  return true;
}

static String colorHex() {
  char str[8];
  snprintf(str, sizeof(str), "#%02X%02X%02X", red, green, blue);
  return String(str);
}

static void stateEndpoint() {
  String out;
  out.reserve(260);
  out += "{\"ok\":true,\"mode\":\"";
  out += mode == MODE_OFF ? "off" : (mode == MODE_AMBIENT ? "ambient" : "spotlight");
  out += "\",\"floor\":";
  out += String(activeFloor);
  out += ",\"color\":\"";
  out += colorHex();
  out += "\",\"brightness\":";
  out += String(brightnessPercent);
  out += ",\"ambientCount\":";
  out += String(ambientCount);
  out += ",\"ambientStepMs\":";
  out += String(ambientStepMs);
  out += ",\"preview\":";
  out += previewActive ? "true" : "false";
  out += ",\"saved\":";
  out += hasStoredMap ? "true" : "false";
  const PowerPlan power = calculatePowerPlan();
  out += ",\"activeLeds\":";
  out += String(power.litCount);
  out += ",\"estimatedLedMa\":";
  out += String(power.estimatedLedMa);
  out += ",\"ledBudgetMa\":";
  out += String(LED_BUDGET_MA);
  out += ",\"powerCapped\":";
  out += power.limited ? "true" : "false";
  out += ",\"powerScalePct\":";
  out += String(power.scalePercent);
  out += ",\"uptime\":";
  out += String(millis() / 1000UL);
  out += ",\"heap\":";
  out += String(ESP.getFreeHeap());
  out += ",\"ip\":\"";
  out += WiFi.softAPIP().toString();
  out += "\"}";
  server.send(200, "application/json; charset=utf-8", out);
}

static void getMappingEndpoint() {
  String output;
  output.reserve(sizeof(savedMap) * 2 + 100);
  output += "{\"ok\":true,\"version\":1,\"sizes\":[79,79,79,83,81],\"saved\":";
  output += hasStoredMap ? "true" : "false";
  output += ",\"masks\":\"";
  output += mappingHex();
  output += "\"}";
  server.send(200, "application/json; charset=utf-8", output);
}

static void controlEndpoint() {
  const bool providedMode = server.hasArg("mode");
  const bool providedFloor = server.hasArg("floor");
  const bool providedBrightness = server.hasArg("brightness");
  const bool providedColor = server.hasArg("color");
  const bool providedAmbientCount = server.hasArg("ambientCount");
  const bool providedAmbientStep = server.hasArg("ambientStepMs");
  if (!providedMode && !providedFloor && !providedBrightness && !providedColor && !providedAmbientCount && !providedAmbientStep) {
    respondError(400, "Missing control parameters"); return;
  }
  LightMode nextMode = mode;
  uint8_t nextFloor = activeFloor;
  uint8_t nextBrightness = brightnessPercent;
  uint8_t nextAmbientCount = ambientCount;
  uint16_t nextAmbientStep = ambientStepMs;
  uint8_t nr = red, ng = green, nb = blue;
  if (providedMode) {
    const String m = server.arg("mode");
    if (m == "off") nextMode = MODE_OFF;
    else if (m == "ambient") nextMode = MODE_AMBIENT;
    else if (m == "spotlight") nextMode = MODE_SPOTLIGHT;
    else { respondError(400, "Unknown mode"); return; }
  }
  if (providedFloor) {
    uint16_t f = 0;
    if (!unsignedNumber(server.arg("floor"), 1, NUM_FLOORS, f)) { respondError(400, "Invalid floor"); return; }
    nextFloor = static_cast<uint8_t>(f);
  }
  if (providedBrightness) {
    uint16_t b = 0;
    if (!unsignedNumber(server.arg("brightness"), 1, 100, b)) { respondError(400, "Invalid brightness"); return; }
    nextBrightness = static_cast<uint8_t>(b);
  }
  if (providedColor && !parseHTMLColor(server.arg("color"), nr, ng, nb)) {
    respondError(400, "Invalid HTML hex color"); return;
  }
  if (providedAmbientCount) {
    uint16_t n = 0;
    if (!unsignedNumber(server.arg("ambientCount"), 5, 60, n) || n % 5 != 0) {
      respondError(400, "Ambient count must be 5..60, step 5"); return;
    }
    nextAmbientCount = static_cast<uint8_t>(n);
  }
  if (providedAmbientStep) {
    uint16_t n = 0;
    if (!unsignedNumber(server.arg("ambientStepMs"), 80, 500, n) || n % 20 != 0) {
      respondError(400, "Ambient speed must be 80..500 ms, step 20"); return;
    }
    nextAmbientStep = n;
  }
  mode = nextMode;
  activeFloor = nextFloor;
  brightnessPercent = nextBrightness;
  ambientCount = nextAmbientCount;
  ambientStepMs = nextAmbientStep;
  if (providedMode && mode == MODE_AMBIENT) lastAmbientStep = millis();
  red = nr; green = ng; blue = nb;
  if (providedMode || providedFloor) previewActive = false;
  needsPaint = true;
  paint();
  respondOK();
}

static void previewEndpoint() {
  uint16_t floor = 0;
  if (!server.hasArg("floor") || !unsignedNumber(server.arg("floor"), 1, NUM_FLOORS, floor)) {
    respondError(400, "Invalid preview floor"); return;
  }
  if (!server.hasArg("masks") || !parseMappingHex(server.arg("masks"), previewMap)) {
    respondError(400, "Invalid mapping bytes or out-of-bounds LED"); return;
  }
  previewActive = true;
  activeFloor = static_cast<uint8_t>(floor);
  mode = MODE_SPOTLIGHT;
  needsPaint = true;
  paint();
  respondOK();
}

static void saveMappingEndpoint() {
  FloorMap candidate = {};
  if (!server.hasArg("masks") || !parseMappingHex(server.arg("masks"), candidate)) {
    respondError(400, "Invalid mapping bytes or out-of-bounds LED"); return;
  }
  if (!persistMapping(candidate)) {
    respondError(500, "Cannot save mapping to NVS"); return;
  }
  paint();
  respondOK();
}

static void setupRoutes() {
  server.on("/", HTTP_GET, []() {
    server.sendHeader("Cache-Control", "no-store, max-age=0");
    server.send_P(200, "text/html; charset=utf-8", DASHBOARD_HTML);
  });
  server.on("/api/state", HTTP_GET, stateEndpoint);
  server.on("/api/mapping", HTTP_GET, getMappingEndpoint);
  server.on("/api/mapping", HTTP_POST, saveMappingEndpoint);
  server.on("/api/control", HTTP_POST, controlEndpoint);
  server.on("/api/preview", HTTP_POST, previewEndpoint);
  server.onNotFound([]() {
    if (server.uri().startsWith("/api/")) {
      respondError(404, "Unknown API endpoint"); return;
    }
    // Captive-portal helpers; manually opening 192.168.4.1 also works.
    server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString(), true);
    server.send(302, "text/plain", "Redirecting to Building Light");
  });
  server.begin();
}

// Remote control addon uses the existing LED modes and mapping.
#include "led_mqtt_addon.h"

void setup() {
  Serial.begin(115200);
  delay(150);
  for (uint8_t s = 0; s < NUM_STRIPS; ++s) {
    strips[s]->begin();
    strips[s]->clear();
    strips[s]->show();
  }
  loadMapping();
  WiFi.mode(WIFI_AP_STA);
  bool apStarted = WiFi.softAP(AP_SSID, AP_PASSWORD);
  Serial.printf("Access point: %s\n", apStarted ? "started" : "ERROR");
  Serial.print("SSID: "); Serial.println(AP_SSID);
  Serial.print("Web UI: http://"); Serial.println(WiFi.softAPIP());
  dnsServer.start(53, "*", WiFi.softAPIP());
  setupRoutes();
  ledRemoteSetup();
  needsPaint = true;
  paint();
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
  ledRemoteLoop();
  if (mode == MODE_AMBIENT) {
    const uint32_t now = millis();
    if (uint32_t(now - lastAmbientStep) >= ambientStepMs) {
      const uint32_t steps = (now - lastAmbientStep) / ambientStepMs;
      lastAmbientStep += steps * ambientStepMs;
      ambientPhase = uint16_t(ambientPhase + steps);
      needsPaint = true;
    }
  }
  paint();
  delay(1);
}