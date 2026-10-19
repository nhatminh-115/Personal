/*
 * Campus E Building LEDs — ESP32 + WS2812 + MQTT/TLS
 * Wiring: GPIO 13/14/16/17/18; LED counts 79/79/79/83/81 (401).
 * Mapping: GF=0, F1..F7=1..7. One arbitrary bitmask per floor/strip.
 * Arduino libraries: Adafruit NeoPixel, PubSubClient (Nick O'Leary).
 *
 * Fill WIFI_STA_SSID/PASS, MQTT_HOST/USERNAME/PASSWORD, MQTT_ROOT_CA.
 * Do NOT commit real credentials or broker private information.
 * No MQTT connection is attempted until all settings are provided.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <Adafruit_NeoPixel.h>
#include <PubSubClient.h>
#include <time.h>
#include <string.h>

// ============== PRIVATE DEPLOYMENT CONFIG (change locally) ============
const char* AP_SSID = "ESP32_Building1";
const char* AP_PASSWORD = "12345678";  // CHANGE THIS PASSWORD
const char* WIFI_STA_SSID = "";        // WiFi with Internet access
const char* WIFI_STA_PASSWORD = "";
const char* MQTT_HOST = "";            // hostname only, without scheme
constexpr uint16_t MQTT_TLS_PORT = 8883;
const char* MQTT_USERNAME = "";
const char* MQTT_PASSWORD = "";
const char* MQTT_TOPIC_ROOT = "campus-e/led-01";
// PEM root CA / issuing CA supplied by your TLS MQTT broker.
// Example: R"CA(-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----)CA"
const char* MQTT_ROOT_CA = "";
// ======================================================================

constexpr uint8_t STRIPS = 5, FLOORS = 8, MAP_BYTES = 11, MAP_VERSION = 2;
constexpr uint16_t LENS[STRIPS] = {79,79,79,83,81};
constexpr uint8_t PINS[STRIPS] = {13,14,16,17,18};
constexpr uint16_t LEDS = 401, LED_BUDGET_MA = 1000;
constexpr uint16_t IDLE_EST_MA = (LEDS * 15 + 9) / 10; // assumes 1.5mA unlit LED
constexpr uint8_t CHANNEL_EST_MA = 20;               // per full 8-bit RGB channel
static_assert(IDLE_EST_MA < LED_BUDGET_MA, "Insufficient budget");
static_assert(LED_BUDGET_MA + 500 + 500 <= 2000, "Exceeded 2A supply budget");
const bool REVERSED[STRIPS] = {false,false,false,false,false};

Adafruit_NeoPixel d1(79,13,NEO_GRB+NEO_KHZ800), d2(79,14,NEO_GRB+NEO_KHZ800),
d3(79,16,NEO_GRB+NEO_KHZ800), d4(83,17,NEO_GRB+NEO_KHZ800), d5(81,18,NEO_GRB+NEO_KHZ800);
Adafruit_NeoPixel* strip[STRIPS] = {&d1,&d2,&d3,&d4,&d5};
uint8_t saved[FLOORS][STRIPS][MAP_BYTES] = {};
uint8_t preview[FLOORS][STRIPS][MAP_BYTES] = {};
bool previewing = false, stored = false, dirty = true;
enum Mode : uint8_t { OFF, AMBIENT, SPOTLIGHT };
Mode mode = AMBIENT;
uint8_t floorNumber = 1; // GF=0
uint8_t brightness = 12, red = 255, green = 228, blue = 168, ambientDots = 30;
uint16_t stepMs = 180, phase = 0;
uint32_t lastStep = 0, lastMqttTry = 0, lastWifiTry = 0;

WebServer server(80);
DNSServer dns;
Preferences preferences;
WiFiClientSecure tls;
PubSubClient mqtt(tls);
String cmdTopic, ackTopic;

bool pixel(uint8_t arr[FLOORS][STRIPS][MAP_BYTES], uint8_t f, uint8_t s, uint16_t index) {
  return (arr[f][s][index / 8] & (1u << (index % 8))) != 0;
}
int nibble(char c) {
  if(c >= '0' && c <= '9') return c-'0';
  if(c >= 'a' && c <= 'f') return c-'a'+10;
  if(c >= 'A' && c <= 'F') return c-'A'+10;
  return -1;
}
bool parseHex(const String& input, uint8_t arr[FLOORS][STRIPS][MAP_BYTES]) {
  if(input.length() != sizeof(saved)*2) return false;
  memset(arr, 0, sizeof(saved));
  uint8_t* out = &arr[0][0][0];
  for(size_t i=0; i<sizeof(saved); i++) {
    int h=nibble(input[i*2]),l=nibble(input[i*2+1]);
    if(h<0 || l<0) return false;
    out[i]=uint8_t(h*16+l);
  }
  for(uint8_t f=0; f<FLOORS; f++) for(uint8_t s=0; s<STRIPS; s++)
    for(uint16_t n=LENS[s]; n<MAP_BYTES*8; n++) if(pixel(arr,f,s,n)) return false;
  return true;
}
String mappingHex() {
  String out; out.reserve(sizeof(saved)*2);
  const char* HEX="0123456789abcdef";
  const uint8_t* b=&saved[0][0][0];
  for(size_t i=0;i<sizeof(saved);i++) {out += HEX[b[i]>>4];out += HEX[b[i]&15];}
  return out;
}
void loadMapping() {
  memset(saved,0,sizeof(saved));
  if(!preferences.begin("buildingled",true)) return;
  const uint8_t version=preferences.getUChar("version",0);
  const size_t length=preferences.getBytesLength("mask");
  if(version==MAP_VERSION && length==sizeof(saved)) {
    stored=(preferences.getBytes("mask",saved,sizeof(saved))==sizeof(saved));
  } else if(version==1 && length==(size_t)7*STRIPS*MAP_BYTES) {
    // Preserve all previous F1..F7 mappings by shifting old floor 0..6 to 1..7.
    const size_t oldSize=7*STRIPS*MAP_BYTES;
    stored=(preferences.getBytes("mask",&saved[1][0][0],oldSize)==oldSize);
    Serial.println("Legacy 7-floor mapping loaded; GF remains blank until mapped.");
  }
  preferences.end();
  if(!stored) memset(saved,0,sizeof(saved));
}
bool persist(uint8_t arr[FLOORS][STRIPS][MAP_BYTES]) {
  if(!preferences.begin("buildingled",false)) return false;
  const size_t n=preferences.putBytes("mask",arr,sizeof(saved));
  const size_t v=(n==sizeof(saved))?preferences.putUChar("version",MAP_VERSION):0;
  preferences.end();
  if(n!=sizeof(saved) || v!=1) return false;
  memcpy(saved,arr,sizeof(saved)); stored=true; previewing=false; dirty=true;
  return true;
}
bool parseUInt(const String& s, uint16_t min, uint16_t max, uint16_t& out) {
  if(!s.length()) return false;
  unsigned long x=0;
  for(size_t i=0;i<s.length();i++) {
    if(s[i]<'0'||s[i]>'9') return false;
    x=x*10+(s[i]-'0');
    if(x>max) return false;
  }
  if(x<min) return false;
  out=uint16_t(x); return true;
}
struct Power {
  uint16_t lit=0, est=IDLE_EST_MA;
  uint8_t r=0,g=0,b=0;
  bool capped=false;
};
Power budget() {
  Power p;
  if(mode==OFF) return p;
  p.r=uint16_t(red)*brightness/100;
  p.g=uint16_t(green)*brightness/100;
  p.b=uint16_t(blue)*brightness/100;
  const uint16_t weight=uint16_t(p.r)+p.g+p.b;
  const uint32_t maxWeight=uint32_t(LED_BUDGET_MA-IDLE_EST_MA)*255/CHANNEL_EST_MA;
  if(mode==AMBIENT) {
    p.lit=weight ? uint16_t(min(uint32_t(ambientDots),maxWeight/weight)) : ambientDots;
    p.capped=p.lit<ambientDots;
  } else {
    uint8_t (*arr)[STRIPS][MAP_BYTES]=previewing?preview:saved;
    for(uint8_t s=0;s<STRIPS;s++) for(uint16_t n=0;n<LENS[s];n++) if(pixel(arr,floorNumber,s,n)) p.lit++;
    if(uint32_t(p.lit)*weight>maxWeight) {
      p.capped=true;
      uint32_t factor=(uint64_t(maxWeight)*65536)/(uint32_t(p.lit)*weight);
      p.r=uint32_t(p.r)*factor/65536;
      p.g=uint32_t(p.g)*factor/65536;
      p.b=uint32_t(p.b)*factor/65536;
    }
  }
  p.est=IDLE_EST_MA+(uint32_t(p.lit)*(uint16_t(p.r)+p.g+p.b)*CHANNEL_EST_MA+254)/255;
  return p;
}
void paint() {
  if(!dirty) return;
  dirty=false;
  const Power p=budget();
  uint8_t (*arr)[STRIPS][MAP_BYTES]=previewing?preview:saved;
  for(uint8_t s=0;s<STRIPS;s++) {
    strip[s]->clear();
    if(mode==SPOTLIGHT) {
      for(uint16_t n=0;n<LENS[s];n++) if(pixel(arr,floorNumber,s,n)) strip[s]->setPixelColor(n,p.r,p.g,p.b);
    } else if(mode==AMBIENT) {
      uint8_t count=p.lit/STRIPS+(s<p.lit%STRIPS?1:0);
      for(uint8_t j=0;j<count;j++) {
        uint16_t n=((uint32_t(phase)+s*7)%LENS[s]+uint32_t(j)*LENS[s]/count)%LENS[s];
        if(REVERSED[s]) n=LENS[s]-1-n;
        strip[s]->setPixelColor(n,p.r,p.g,p.b);
      }
    }
    strip[s]->show();
  }
}
void setAmbient() {mode=AMBIENT;previewing=false;dirty=true;lastStep=millis();}
void setFloor(uint8_t f) {floorNumber=f;mode=SPOTLIGHT;previewing=false;dirty=true;}
void jsonError(int status,const char* msg) {
  server.send(status,"application/json","{\"ok\":false,\"error\":\""+String(msg)+"\"}");
}
void ok() {server.send(200,"application/json","{\"ok\":true}");}
void routeState() {
  const Power p=budget();
  String result="{\"ok\":true,\"mode\":\""+String(mode==OFF?"off":mode==AMBIENT?"ambient":"spotlight")+
    "\",\"floor\":"+String(floorNumber)+",\"activeLeds\":"+String(p.lit)+
    ",\"estimatedLedMa\":"+String(p.est)+",\"ledBudgetMa\":"+String(LED_BUDGET_MA)+
    ",\"powerCapped\":"+String(p.capped?"true":"false")+
    ",\"saved\":"+String(stored?"true":"false")+
    ",\"mqttConnected\":"+String(mqtt.connected()?"true":"false")+"}";
  server.send(200,"application/json",result);
}
void routeControl() {
  if(server.hasArg("mode")) {
    String m=server.arg("mode");
    if(m=="ambient") setAmbient();
    else if(m=="off") {mode=OFF;previewing=false;dirty=true;}
    else if(m=="spotlight") {mode=SPOTLIGHT;previewing=false;dirty=true;}
    else {jsonError(400,"Unknown mode");return;}
  }
  if(server.hasArg("floor")) {
    uint16_t f=0;
    if(!parseUInt(server.arg("floor"),0,7,f)){jsonError(400,"Invalid floor");return;}
    setFloor(uint8_t(f));
  }
  if(server.hasArg("brightness")) {
    uint16_t b=0;
    if(!parseUInt(server.arg("brightness"),1,100,b)){jsonError(400,"Invalid brightness");return;}
    brightness=b;dirty=true;
  }
  ok();
}
void routeMapGet() {
  server.send(200,"application/json",
    "{\"ok\":true,\"version\":2,\"sizes\":[79,79,79,83,81],\"floors\":[\"GF\",\"F1\",\"F2\",\"F3\",\"F4\",\"F5\",\"F6\",\"F7\"],\"masks\":\""+mappingHex()+"\"}");
}
void routeMapPost(bool temporary) {
  static uint8_t candidate[FLOORS][STRIPS][MAP_BYTES];
  if(!server.hasArg("masks")||!parseHex(server.arg("masks"),candidate)) {
    jsonError(400,"Invalid 8-floor mapping");return;
  }
  if(temporary) {
    uint16_t f=0;
    if(!server.hasArg("floor")||!parseUInt(server.arg("floor"),0,7,f)) {
      jsonError(400,"Invalid preview floor");return;
    }
    memcpy(preview,candidate,sizeof(saved));previewing=true;floorNumber=f;mode=SPOTLIGHT;dirty=true;
  } else if(!persist(candidate)) {
    jsonError(500,"NVS save failed");return;
  }
  ok();
}

// Lightweight mapping UI served by ESP32 AP even when Internet is unavailable.
const char HTML[] PROGMEM=R"UI(
<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Campus E · LED</title>
<style>body{background:#0d1927;color:#eff6ff;font:15px system-ui;max-width:760px;margin:auto;padding:20px}
section{background:#1c3041;border-radius:14px;margin:12px 0;padding:16px}button,input,select{font:inherit;padding:9px;margin:3px;border-radius:8px}
button{background:#1d7b7b;color:white;border:0;cursor:pointer}input{max-width:97%}#ranges{width:96%}
small{color:#aac2cc}#floors button{min-width:52px}.active{background:#bd722f}</style>
<h2>Campus E · Building LEDs</h2><section><div id="status">Đang tải...</div>
<button onclick="control({mode:'ambient'})">Toàn bộ nhà · Ambient</button>
<button onclick="control({mode:'off'})">Tắt LED</button><div id="floors"></div></section>
<section><h3>Pixel Mapping · GF và 7 tầng</h3><small>Nhập LED 1-based; ví dụ 1,3,77-79</small>
<p>Tầng <select id="floor"></select> Dây <select id="strip"></select></p>
<input id="ranges" placeholder="1,3,77-79"><br>
<button onclick="apply()">Áp dụng vào mapping</button>
<button onclick="preview()">Xem thử</button>
<button onclick="save()">Lưu NVS</button><p id="editor"></p></section>
<script>
const sizes=[79,79,79,83,81],floors=['GF','F1','F2','F3','F4','F5','F6','F7'],bytes=11;
let map=new Uint8Array(8*5*bytes);
const $=id=>document.getElementById(id);
function offset(f,s,n){return(f*5+s)*bytes+(n>>3)}
function on(f,s,n){return Boolean(map[offset(f,s,n)]&(1<<(n&7)))}
function bit(f,s,n,v){const p=offset(f,s,n),b=1<<(n&7);map[p]=v?map[p]|b:map[p]&~b}
function hex(){return Array.from(map,v=>v.toString(16).padStart(2,'0')).join('')}
async function request(path,data){
 const cfg=data?{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(data)}:{};
 const r=await fetch(path,cfg);const j=await r.json();if(!r.ok||!j.ok)throw Error(j.error||r.status);return j;
}
function selected(){return[Number($('floor').value),Number($('strip').value)]}
function renderRange(){
 const [f,s]=selected(),nums=[];for(let n=0;n<sizes[s];n++)if(on(f,s,n))nums.push(n+1);
 $('ranges').value=nums.join(',');$('editor').textContent=nums.length+' LED đang chọn; nhớ Lưu NVS nếu muốn giữ sau khi tắt nguồn';
}
function apply(){
 try{
 const[f,s]=selected(),v=$('ranges').value,nums=new Set();
 if(v.trim())for(const token of v.split(',')){
 const m=/^\s*(\d+)(?:\s*-\s*(\d+))?\s*$/.exec(token);if(!m)throw Error('Cú pháp sai: '+token);
 const a=+m[1],b=m[2]?+m[2]:a;if(a<1||b>sizes[s]||b<a)throw Error('LED ngoài khoảng');for(let i=a;i<=b;i++)nums.add(i-1);
 }
 for(let n=0;n<sizes[s];n++)bit(f,s,n,nums.has(n));renderRange();
 }catch(e){alert(e.message)}
}
async function control(v){try{await request('/api/control',v);await state()}catch(e){alert(e.message)}}
async function preview(){apply();try{await request('/api/preview',{floor:$('floor').value,masks:hex()});await state()}catch(e){alert(e.message)}}
async function save(){apply();try{await request('/api/mapping',{masks:hex()});alert('Đã lưu NVS')}catch(e){alert(e.message)}}
async function state(){const v=await request('/api/state');$('status').textContent='Mode '+v.mode+' · '+(v.floor?('F'+v.floor):'GF')+' · '+v.activeLeds+' LED · '+v.estimatedLedMa+'mA (ước tính) · MQTT '+(v.mqttConnected?'online':'offline');}
async function boot(){
 $('floor').innerHTML=floors.map((f,i)=>'<option value="'+i+'">'+f+'</option>').join('');
 $('strip').innerHTML=sizes.map((n,i)=>'<option value="'+i+'">Dây '+(i+1)+' ('+n+' LED)</option>').join('');
 $('floors').innerHTML=floors.map((f,i)=>'<button onclick="control({floor:'+i+'})">'+f+'</button>').join('');
 $('floor').onchange=renderRange;$('strip').onchange=renderRange;
 try{const v=await request('/api/mapping');map=new Uint8Array(v.masks.match(/../g).map(h=>parseInt(h,16)));renderRange();await state()}
 catch(e){$('status').textContent='Error: '+e.message}
 setInterval(()=>state().catch(()=>{}),4000);
}boot();
</script></html>
)UI";

void onMqtt(char* topic, byte* payload, unsigned int length) {
  if(String(topic)!=cmdTopic || length<3 || length>24) return;
  char input[25]={0};
  for(unsigned i=0;i<length;i++) input[i]=char(payload[i]);
  if(!strchr(input,':')) return;
  const char* colon=strchr(input,':');
  // Require nonce/sequence consisting only of 1-12 digits, no retained command.
  const char* n=colon+1;
  size_t digits=strlen(n);
  if(digits<1 || digits>12) return;
  for(size_t i=0;i<digits;i++) if(n[i]<'0'||n[i]>'9') return;
  if(colon==input+1 && input[0]=='A') setAmbient();
  else if(colon==input+2 && input[0]=='F' && input[1]>='0' && input[1]<='7') setFloor(uint8_t(input[1]-'0'));
  else return;
  paint();
  mqtt.publish(ackTopic.c_str(),input,false);
}
void ensureMqtt() {
  if(!strlen(WIFI_STA_SSID)||!strlen(MQTT_HOST)||!strlen(MQTT_ROOT_CA)) return;
  if(WiFi.status()!=WL_CONNECTED || mqtt.connected()) return;
  if(time(nullptr)<1700000000) return; // NTP required for certificate verification
  if(millis()-lastMqttTry<12000) return;
  lastMqttTry=millis();
  String id="campus-e-esp32-"+String((uint32_t)ESP.getEfuseMac(),HEX);
  if(mqtt.connect(id.c_str(),MQTT_USERNAME,MQTT_PASSWORD)) {
    mqtt.subscribe(cmdTopic.c_str(),0);
    Serial.println("MQTT connected, subscribed to "+cmdTopic);
  } else Serial.println("MQTT connect failed: "+String(mqtt.state()));
}
void ensureWiFi() {
  if(!strlen(WIFI_STA_SSID)||WiFi.status()==WL_CONNECTED) return;
  if(millis()-lastWifiTry<30000) return;
  lastWifiTry=millis();WiFi.begin(WIFI_STA_SSID,WIFI_STA_PASSWORD);
}
void setup() {
  Serial.begin(115200);
  for(uint8_t i=0;i<STRIPS;i++){strip[i]->begin();strip[i]->clear();strip[i]->show();}
  loadMapping();
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID,AP_PASSWORD);
  if(strlen(WIFI_STA_SSID)) {WiFi.begin(WIFI_STA_SSID,WIFI_STA_PASSWORD);lastWifiTry=millis();}
  dns.start(53,"*",WiFi.softAPIP());
  server.on("/",HTTP_GET,[](){server.send_P(200,"text/html; charset=utf-8",HTML);});
  server.on("/api/state",HTTP_GET,routeState);
  server.on("/api/control",HTTP_POST,routeControl);
  server.on("/api/mapping",HTTP_GET,routeMapGet);
  server.on("/api/mapping",HTTP_POST,[](){routeMapPost(false);});
  server.on("/api/preview",HTTP_POST,[](){routeMapPost(true);});
  server.begin();
  cmdTopic=String(MQTT_TOPIC_ROOT)+"/cmd";
  ackTopic=String(MQTT_TOPIC_ROOT)+"/ack";
  tls.setCACert(MQTT_ROOT_CA); // Strict CA validation, no setInsecure()
  mqtt.setServer(MQTT_HOST,MQTT_TLS_PORT);
  mqtt.setCallback(onMqtt);
  mqtt.setKeepAlive(30);
  configTime(0,0,"pool.ntp.org","time.google.com");
  Serial.println("ESP32 AP http://"+WiFi.softAPIP().toString());
  paint();
}
void loop() {
  dns.processNextRequest();server.handleClient();
  ensureWiFi();ensureMqtt();
  if(mqtt.connected()) mqtt.loop();
  if(mode==AMBIENT && millis()-lastStep>=stepMs) {
    uint32_t jumps=(millis()-lastStep)/stepMs;lastStep+=jumps*stepMs;phase+=jumps;dirty=true;
  }
  paint();delay(1);
}
