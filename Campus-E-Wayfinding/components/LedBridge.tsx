import { useEffect, useRef, useState } from 'react';

type Selection = { mode: 'ambient' | 'spotlight'; floor: number };
type LedBridgeProps = { selection: Selection };
const BROKER = 'wss://test.mosquitto.org:8081/mqtt';

const enc = new TextEncoder();
const utf = (s: string) => Array.from(enc.encode(s));
const word = (n: number) => [(n >>> 8) & 255, n & 255];
const field = (s: string) => [...word(utf(s).length), ...utf(s)];
const remain = (n: number) => {
  const result: number[] = [];
  do { let digit = n % 128; n = Math.floor(n / 128); if (n) digit |= 128; result.push(digit); } while (n);
  return result;
};
const mqttPacket = (header: number, data: number[]) =>
  Uint8Array.from([header, ...remain(data.length), ...data]);
const hex = (buf: ArrayBuffer) =>
  Array.from(new Uint8Array(buf), b => b.toString(16).padStart(2, '0')).join('');
const unhex = (str: string) =>
  Uint8Array.from(str.match(/.{2}/g)?.map(v => parseInt(v, 16)) ?? []);

class SimpleMqtt {
  socket: WebSocket;
  ready = false;
  received = new Uint8Array(0);
  packetId = 0;
  ping: ReturnType<typeof setInterval> | null = null;
  constructor(
    readonly topic: string,
    readonly onReady: () => void,
    readonly onMessage: (message: string) => void,
    readonly onClosed: (message: string) => void,
  ) {
    this.socket = new WebSocket(BROKER, ['mqtt']);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onopen = () => {
      const id = 'campus-web-' + crypto.randomUUID().replaceAll('-', '').slice(0, 20);
      const connect = [...field('MQTT'), 4, 2, 0, 30, ...field(id)];
      this.socket.send(mqttPacket(0x10, connect));
    };
    this.socket.onmessage = event => this.consume(new Uint8Array(event.data as ArrayBuffer));
    this.socket.onerror = () => this.onClosed('Không mở được kết nối MQTT');
    this.socket.onclose = () => {
      this.ready = false;
      if (this.ping) clearInterval(this.ping);
      this.onClosed('Mất kết nối MQTT');
    };
  }
  private send(packet: Uint8Array) {
    if (this.socket.readyState === WebSocket.OPEN) this.socket.send(packet);
  }
  private subscribe() {
    const id = ++this.packetId;
    this.send(mqttPacket(0x82, [...word(id), ...field(this.topic + '/ack'), 0]));
  }
  publish(message: string) {
    if (!this.ready) return false;
    this.send(mqttPacket(0x30, [...field(this.topic + '/cmd'), ...utf(message)]));
    return true;
  }
  private consume(chunk: Uint8Array) {
    const joined = new Uint8Array(this.received.length + chunk.length);
    joined.set(this.received); joined.set(chunk, this.received.length);
    let cursor = 0;
    while (cursor + 2 <= joined.length) {
      let n = 0, factor = 1, digits = 0, octet = 0;
      do {
        if (cursor + 1 + digits >= joined.length) {
          this.received = joined.slice(cursor); return;
        }
        octet = joined[cursor + 1 + digits++];
        n += (octet & 127) * factor;
        factor *= 128;
      } while ((octet & 128) && digits < 4);
      if (digits === 4 && (octet & 128)) { this.socket.close(); return; }
      const start = cursor + 1 + digits;
      const end = start + n;
      if (end > joined.length) break;
      const type = joined[cursor] >> 4;
      if (type === 2) {
        if (n >= 2 && joined[start + 1] === 0) {
          this.subscribe();
        } else this.onClosed('Broker từ chối MQTT CONNECT');
      } else if (type === 9 && n >= 3) {
        // Only publish after subscription is confirmed, so the first ACK is not lost.
        this.ready = true;
        this.ping = setInterval(() => this.send(Uint8Array.from([0xc0, 0])), 15000);
        this.onReady();
      } else if (type === 3 && n >= 2) {
        const size = (joined[start] << 8) | joined[start + 1];
        if (start + 2 + size <= end) {
          const name = new TextDecoder().decode(joined.slice(start + 2, start + 2 + size));
          if (name === this.topic + '/ack') {
            const skip = (joined[cursor] & 0x06) ? 2 : 0;
            if (start + 2 + size + skip <= end) {
              this.onMessage(new TextDecoder().decode(joined.slice(start + 2 + size + skip, end)));
            }
          }
        }
      }
      cursor = end;
    }
    this.received = joined.slice(cursor);
  }
  close() {
    if (this.ping) clearInterval(this.ping);
    this.socket.close();
  }
}

/** A public GitHub Pages site never stores or publishes the device pairing secret. */
export default function LedBridge({ selection }: LedBridgeProps) {
  const [device, setDevice] = useState(() => typeof window === 'undefined' ? '' : (localStorage.getItem('campus-led-device') ?? ''));
  const [secret, setSecret] = useState('');
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState('Chưa kết nối LED');
  const mqtt = useRef<SimpleMqtt | null>(null);
  const key = useRef<CryptoKey | null>(null);
  const lastStamp = useRef(0);
  const selected = useRef(selection);
  selected.current = selection;
  const deviceRef = useRef(device);
  deviceRef.current = device;

  const sign = async (body: string) =>
    hex(await crypto.subtle.sign('HMAC', key.current!, enc.encode(body)));

  const publish = async (target: Selection) => {
    const transport = mqtt.current;
    if (!transport?.ready || !key.current) return;
    const stamp = Math.max(Date.now(), lastStamp.current + 1);
    lastStamp.current = stamp;
    const floor = target.mode === 'ambient' ? 0 : target.floor;
    const body = ['v1', deviceRef.current, stamp, target.mode, floor].join('|');
    try {
      if (transport.publish(body + '|' + await sign(body))) {
        setStatus('Đã gửi ' + (floor === 0 ? 'Ambient' : floor === 8 ? 'GF' : 'F' + floor) + ' · chờ ESP32 xác nhận');
      }
    } catch {
      setStatus('Không ký được lệnh điều khiển');
    }
  };

  useEffect(() => {
    if (connected) void publish(selection);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection.mode, selection.floor, connected]);

  const connect = async () => {
    if (!/^[a-z0-9-]{6,48}$/.test(device)) {
      setStatus('Device ID: 6–48 ký tự thường, số hoặc dấu -'); return;
    }
    if (secret.length < 16) {
      setStatus('Pairing key phải có ít nhất 16 ký tự'); return;
    }
    mqtt.current?.close();
    setConnected(false);
    try {
      key.current = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
      localStorage.setItem('campus-led-device', device);
      setSecret('');
      setStatus('Đang kết nối broker MQTT…');
      const topic = 'campus-e-led/v1/' + device;
      const client = new SimpleMqtt(
        topic,
        () => { setConnected(true); setStatus('MQTT online · đang gửi trạng thái tầng'); },
        async (ack: string) => {
          const parts = ack.split('|');
          if (parts.length !== 6 || parts[0] !== 'ack' || parts[1] !== deviceRef.current || !/^[0-9a-f]{64}$/.test(parts[5])) return;
          const body = parts.slice(0, 5).join('|');
          if (!key.current || !await crypto.subtle.verify('HMAC', key.current, unhex(parts[5]), enc.encode(body))) return;
          setStatus('ESP32 đã áp dụng: ' + (parts[3] === 'ambient' ? 'Ambient' : parts[4] === '8' ? 'GF' : 'F' + parts[4]));
        },
        message => { setConnected(false); setStatus(message); },
      );
      mqtt.current = client;
    } catch {
      setStatus('Không thể khởi tạo kết nối MQTT');
    }
  };

  useEffect(() => () => mqtt.current?.close(), []);

  return (
    <section id="led-pairing" aria-label="Ghép nối LED với ESP32" style={{ marginTop: 18, scrollMarginTop: 24, padding: 14, border: '1px solid #547f8b', borderRadius: 12, background: '#102731', color: '#eefaff' }}>
      <strong style={{ display: 'block', marginBottom: 6 }}>Ghép nối LED · ESP32</strong>
      <small style={{ display: 'block', opacity: 0.85, marginBottom: 11 }}>
        Chọn F1–F7 hoặc GF sẽ bật Spotlight. “Toàn bộ tòa nhà” sẽ trở lại Sparse Ambient.
      </small>
      <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Device ID</label>
      <input value={device} disabled={connected} onChange={e => setDevice(e.target.value.trim().toLowerCase())}
        placeholder="campus-e-001" autoComplete="off" style={{ width: '100%', padding: 9, marginBottom: 8, borderRadius: 7 }} />
      {!connected && <>
        <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>Pairing key (nhập trên thiết bị đang điều khiển)</label>
        <input value={secret} onChange={e => setSecret(e.target.value)} type="password" autoComplete="off"
          placeholder="Mã bí mật trùng với ESP32" style={{ width: '100%', padding: 9, marginBottom: 8, borderRadius: 7 }} />
      </>}
      <div style={{ display: 'flex', gap: 8 }}>
        <button type="button" onClick={() => connected ? (mqtt.current?.close(), setConnected(false)) : void connect()}
          style={{ border: 0, padding: '9px 13px', borderRadius: 8, background: '#7cdfbc', color: '#092e2a', fontWeight: 700 }}>
          {connected ? 'Ngắt kết nối' : 'Kết nối ESP32'}
        </button>
        {connected && <button type="button" onClick={() => void publish(selected.current)}
          style={{ border: '1px solid #6c909a', borderRadius: 8, padding: '8px 10px', color: '#fff', background: '#1f4954' }}>
          Gửi lại
        </button>}
      </div>
      <small role="status" style={{ display: 'block', marginTop: 8, opacity: 0.92 }}>{status}</small>
      <small style={{ display: 'block', marginTop: 6, opacity: 0.75 }}>
        Broker công cộng chỉ để thử nghiệm. Mã bí mật không được ghi vào GitHub.
      </small>
    </section>
  );
}
