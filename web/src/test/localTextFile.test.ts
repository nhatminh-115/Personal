import { describe, expect, it } from 'vitest';
import { extractLocalTextFile, MAX_LOCAL_TEXT_FILE_BYTES } from '../lib/localTextFile';

function utf16(value: string, endian: 'le' | 'be'): ArrayBuffer {
  const bytes = new Uint8Array(new ArrayBuffer(2 + value.length * 2));
  bytes.set(endian === 'le' ? [0xff, 0xfe] : [0xfe, 0xff]);
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    bytes[2 + index * 2] = endian === 'le' ? code & 0xff : code >> 8;
    bytes[3 + index * 2] = endian === 'le' ? code >> 8 : code & 0xff;
  }
  return bytes.buffer as ArrayBuffer;
}

describe('browser-local text file decoding', () => {
  it('decodes UTF-8 and strips its BOM', async () => {
    await expect(extractLocalTextFile(new Blob([new Uint8Array([0xef, 0xbb, 0xbf]), 'Résumé 🌍'])))
      .resolves.toBe('Résumé 🌍');
    await expect(extractLocalTextFile(new Blob(['plain UTF-8 text'])))
      .resolves.toBe('plain UTF-8 text');
  });

  it('decodes UTF-16 little- and big-endian BOM text', async () => {
    await expect(extractLocalTextFile(new Blob([utf16('Résumé 🌍', 'le')]))).resolves.toBe('Résumé 🌍');
    await expect(extractLocalTextFile(new Blob([utf16('Résumé 🌍', 'be')]))).resolves.toBe('Résumé 🌍');
  });

  it('enforces byte and Unicode character limits', async () => {
    await expect(extractLocalTextFile(new Blob(['x'.repeat(MAX_LOCAL_TEXT_FILE_BYTES + 1)])))
      .rejects.toThrow('80,000-byte');
    await expect(extractLocalTextFile(new Blob(['文'.repeat(20_001)])))
      .rejects.toThrow('20,000-character');
    await expect(extractLocalTextFile(new Blob(['文'.repeat(20_000)])))
      .resolves.toHaveLength(20_000);
  });
});
