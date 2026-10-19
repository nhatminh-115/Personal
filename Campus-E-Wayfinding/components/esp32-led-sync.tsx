import { useEffect, useRef, useState } from 'react';

type Config = { url: string; topic: string; username: string; password: string };
type Mode = { kind: 'ambient' } | { kind: 'floor'; floor: number };
const encoder = new TextEncoder();
const decoder = new TextDecoder();

function bytes(s: string): number[] { return [...encoder.encode(s)]; }
function mqttText(s: string): number[] {
  const b = bytes(s);
  if (b.length > 65535) throw new Error('MQTT string too long');
  return [b.length >> 8, b.length & 255, ...b];
}
function packet(header: number, body: number[]): Uint8Array {
  const length: number[] = [];
  let n = body.length;
  do { let b = n % 128; n = Math.floor(n / 128); if (n) b |= 128; length.push(b); } while (n);
  return Uint8Array.from([header, ...length, ...body]);
}
function connectPacket(c: Config) {
  // MQTT 3.1.1 clean session, 30 second keepalive.
  const flags = 2 | (c.username ? 128 : 0) | (c.password ? 64 : 0);
  const clientId = 'campuse-web-' + Math.random().toString(16).slice(2, 11);
  return packet(0x10, [...mqttText('MQTT'), 4, flags, 0, 30,
    ...mqttText(clientId), ...(c.username ? mqttText(c.username) : []),
    ...(c.password ? mqttText(c.password) : [])]);
}
function subscribePacket(topic: string) {
  return packet(0x82, [0, 1, ...mqttText(topic), 0]); // packet id=1, QoS0
}
function publishPacket(topic: string, message: string) {
  return packet(0x30, [...mqttText(topic), ...bytes(message)]); // QoS0
}
function readFrames(raw: ArrayBuffer): { type: number; payload: Uint8Array }[] {
  const data = new Uint8Array(raw), frames = [];
  let pos = 0;
  while (pos < data.length) {
    const type = data[pos++] >> 4;
    let len = 0, shift = 0, encoded: number;
    do {
      if (pos >= data.length || shift > 21) throw Error('Malformed MQTT frame');
      encoded = data[pos++];
      len += (encoded & 127) * (2 ** shift);
      shift += 7;
    } while (encoded & 128);
    if (pos + len > data.length) throw Error('Truncated MQTT frame');
    frames.push({type, payload: data.slice(pos, pos + len)});
    pos += len;
  }
  return frames;
}
const inputStyle = { display: 'block', width: '100%', padding: '8px', margin: '4px 0 10px', border: '1px solid #b9c6cf', borderRadius: 6 } as const;
const initial: Config = { url: '', topic: 'campus-e/led-01', username: '', password: '' };
function savedConfig(): Config {
  try {
    const saved = JSON.parse(localStorage.getItem('campuse-led-connection') || '{}');
    return { ...initial, url: saved.url || '', topic: saved.topic || initial.topic, username: saved.username || '' };
  } catch { return initial; }
}
/** Browser sends MQTT via WSS; ESP32 subscribes via TLS. No HTTP to a local IP. */
export function useCampusLed() {
  const [config, setConfig] = useState<Config>(savedConfig);
  const [editor, setEditor] = useState(false);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState('Chưa kết nối LED');
  const socket = useRef<WebSocket | null>(null);
  const tick = useRef<ReturnType<typeof setInterval> | null>(null);
  const current = useRef<Mode>({ kind: 'ambient' });
  const waitingFor = useRef('');
  const sequence = useRef(0);

  function publishMode(mode: Mode) {
    current.current = mode;
    const ws = socket.current;
    if (!ws || ws.readyState !== WebSocket.OPEN || !connected) {
      setStatus('Đã chọn ' + (mode.kind === 'ambient' ? 'Ambient' : mode.floor === 0 ? 'GF' : 'F' + mode.floor) + ' · LED chưa kết nối');
      return;
    }
    const command = (mode.kind === 'ambient' ? 'A' : 'F' + mode.floor) + ':' + (++sequence.current);
    waitingFor.current = command;
    ws.send(publishPacket(config.topic + '/cmd', command));
    setStatus('Đã gửi ' + command.split(':')[0] + ' · chờ ESP32 xác nhận');
  }
  function disconnect() {
    if (tick.current) clearInterval(tick.current);
    tick.current = null;
    const ws = socket.current;
    socket.current = null;
    if (ws) { ws.onclose = null; ws.close(); }
    setConnected(false);
    setStatus('Đã ngắt kết nối LED');
  }
  function openConnection() {
    disconnect();
    if (!/^wss:\/\/[^/]+/i.test(config.url)) {
      setStatus('Broker phải dùng wss:// (TLS)');
      return;
    }
    if (!/^[a-zA-Z0-9/_-]{3,100}$/.test(config.topic)) {
      setStatus('Topic chỉ dùng chữ, số, /, _ hoặc - (3–100 ký tự)');
      return;
    }
    localStorage.setItem('campuse-led-connection', JSON.stringify({
      url: config.url, topic: config.topic, username: config.username,
      // Deliberately NEVER persist password into localStorage or source code.
    }));
    setStatus('Đang kết nối MQTT qua WSS...');
    try {
      const ws = new WebSocket(config.url, ['mqtt']);
      socket.current = ws;
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => ws.send(connectPacket(config));
      ws.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        try {
          for (const frame of readFrames(event.data)) {
            if (frame.type === 2) { // CONNACK
              if (frame.payload.length !== 2 || frame.payload[1] !== 0) {
                setStatus('Broker từ chối kết nối MQTT'); disconnect(); return;
              }
              setConnected(true);
              ws.send(subscribePacket(config.topic + '/ack'));
              tick.current = setInterval(() => {
                if (ws.readyState === WebSocket.OPEN) ws.send(Uint8Array.from([0xc0, 0]));
              }, 15000);
              // Synchronize current 3D selection after successful connection.
              const mode = current.current;
              const command = (mode.kind === 'ambient' ? 'A' : 'F' + mode.floor) + ':' + (++sequence.current);
              waitingFor.current = command;
              ws.send(publishPacket(config.topic + '/cmd', command));
              setStatus('Đã kết nối broker · chờ ESP32 xác nhận');
            }
            if (frame.type === 3 && frame.payload.length > 2) { // PUBLISH (QoS0)
              const tlen = (frame.payload[0] << 8) | frame.payload[1];
              if (2 + tlen > frame.payload.length) continue;
              const topic = decoder.decode(frame.payload.slice(2, 2 + tlen));
              const message = decoder.decode(frame.payload.slice(2 + tlen));
              if (topic === config.topic + '/ack' && message === waitingFor.current) {
                setStatus('ESP32 đã xác nhận: ' + message.split(':')[0]);
                waitingFor.current = '';
              }
            }
          }
        } catch { setStatus('Phản hồi MQTT không hợp lệ'); }
      };
      ws.onerror = () => setStatus('Lỗi kết nối WSS / broker');
      ws.onclose = () => { if (tick.current) clearInterval(tick.current); tick.current = null; setConnected(false); setStatus('MQTT đã ngắt · LED chưa được đồng bộ'); };
      setEditor(false);
    } catch (error) { setStatus('Không mở được WSS: ' + String(error)); }
  }
  useEffect(() => () => {
    if (tick.current) clearInterval(tick.current);
    socket.current?.close();
  }, []);

  const panel = <section style={{position: 'absolute', zIndex: 6, top: 76, right: 12, width: 'min(340px, calc(100% - 90px))', maxHeight: '75%', overflowY: 'auto', padding: '9px 12px', background: '#172932f2', color: '#f1f5f5', border: '1px solid #45606a', borderRadius: 10}}>
    <div style={{display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 8, justifyContent: 'space-between'}}>
      <span style={{fontSize: 12}}><strong>LED mô hình:</strong> {status}</span>
      <button type="button" onClick={() => setEditor(v => !v)} style={{padding: '5px 10px', fontSize: 12}}>⚙ {editor ? 'Đóng' : 'Thiết lập LED'}</button>
    </div>
    {editor && <div style={{marginTop: 9, maxWidth: 480}}>
      <small>GitHub Pages chỉ kết nối qua MQTT WebSocket bảo mật (WSS). ESP32 phải cùng đăng nhập một broker. Không lưu mật khẩu vào website hoặc GitHub.</small>
      <label style={{display: 'block', marginTop: 8}}>Broker WSS URL
        <input style={inputStyle} placeholder="wss://your-broker.example:8884/mqtt" value={config.url} onChange={e => setConfig(v => ({ ...v, url: e.target.value.trim() }))}/></label>
      <label style={{display: 'block'}}>Device topic
        <input style={inputStyle} value={config.topic} onChange={e => setConfig(v => ({ ...v, topic: e.target.value.trim() }))}/></label>
      <label style={{display: 'block'}}>MQTT username
        <input style={inputStyle} value={config.username} onChange={e => setConfig(v => ({ ...v, username: e.target.value }))}/></label>
      <label style={{display: 'block'}}>MQTT password (chỉ trong phiên hiện tại)
        <input type="password" style={inputStyle} value={config.password} onChange={e => setConfig(v => ({ ...v, password: e.target.value }))}/></label>
      <button type="button" onClick={openConnection} style={{padding: '8px 12px', marginRight: 8}}>Kết nối LED</button>
      <button type="button" onClick={disconnect} style={{padding: '8px 12px'}}>Ngắt kết nối</button>
      <p style={{marginTop: 7, fontSize: 12}}>Topic lệnh: <code>{config.topic}/cmd</code>. Xác nhận: <code>{config.topic}/ack</code>. GF=0, F1–F7=1–7.</p>
    </div>}
  </section>;
  return { panel, sendAmbient: () => publishMode({ kind: 'ambient' }), sendFloor: (floor: number) => publishMode({ kind: 'floor', floor }), connected };
}
