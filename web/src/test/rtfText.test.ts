import { describe, expect, it } from 'vitest';
import { extractRtfText, MAX_LOCAL_RTF_BYTES } from '../lib/rtfText';

describe('browser-local RTF text extraction', () => {
  it('extracts paragraphs, formatting-independent text, Unicode, and Windows-1252 escapes', async () => {
    const rtf = "{\\rtf1\\ansi\\deff0 Hello \\b bold\\b0\\par Caf\\'e9 \\u-10179?\\u-8704?}";
    await expect(extractRtfText(new Blob([rtf]))).resolves.toBe('Hello bold\nCafé 😀');
  });

  it('drops metadata, optional destinations, pictures, and embedded binary data', async () => {
    const rtf = "{\\rtf1 Visible{\\fonttbl{\\f0 Ignore this font;}}{\\*\\private Ignore this too;}{\\pict\\bin5 abc{}} After}";
    await expect(extractRtfText(new Blob([rtf]))).resolves.toBe('Visible After');
  });

  it('rejects malformed or non-RTF input and enforces byte and extracted-text limits', async () => {
    await expect(extractRtfText(new Blob(['not an RTF document']))).rejects.toThrow('not a readable RTF');
    await expect(extractRtfText(new Blob(['{\\rtf1 incomplete']))).rejects.toThrow('incomplete');
    await expect(extractRtfText(new Blob(['{\\rtf1 text}trailing']))).rejects.toThrow('trailing data');
    await expect(extractRtfText(new Blob(['{\\rtf1 \\u70000?}']))).rejects.toThrow('invalid Unicode escape');
    await expect(extractRtfText(new Blob([`{\\rtf1 ${'x'.repeat(MAX_LOCAL_RTF_BYTES)}}`]))).rejects.toThrow('80,000-byte');
    await expect(extractRtfText(new Blob([`{\\rtf1 ${'x'.repeat(20_001)}}`]))).rejects.toThrow('20,000-character');
    await expect(extractRtfText(new Blob([`{\\rtf1 ${'x'.repeat(20_000)}}`]))).resolves.toBe('x'.repeat(20_000));
  });
});
