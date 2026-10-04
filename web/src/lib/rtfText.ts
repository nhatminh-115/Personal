import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_RTF_BYTES = 80_000;

type RtfGroupState = { skip: boolean; unicodeFallback: number; fallbackToSkip: number };

const NON_TEXT_DESTINATIONS = new Set([
  'fonttbl', 'colortbl', 'stylesheet', 'info', 'pict', 'object', 'objdata',
  'filetbl', 'listtable', 'listoverridetable', 'revtbl', 'generator',
  'xmlnstbl', 'datastore', 'themedata', 'colorschememapping', 'htmltag', 'mhtmltag',
]);

function decodeRtfSource(bytes: Uint8Array): string {
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return new TextDecoder('utf-8').decode(bytes.subarray(3));
  }
  // RTF control syntax is ASCII; escaped non-ASCII bytes use the document's
  // ANSI code page, with Windows-1252 as the interoperable browser default.
  return new TextDecoder('windows-1252').decode(bytes);
}

function readBlobAsBytes(blob: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the selected RTF file.'));
    reader.onload = () => {
      if (!(reader.result instanceof ArrayBuffer)) {
        reject(new Error('Could not read the selected RTF file.'));
        return;
      }
      resolve(new Uint8Array(reader.result));
    };
    reader.readAsArrayBuffer(blob);
  });
}

function controlWord(source: string, start: number): { word: string; number: number | null; end: number } {
  let cursor = start;
  while (cursor < source.length && /[a-z]/i.test(source[cursor])) cursor += 1;
  const word = source.slice(start, cursor).toLowerCase();
  let sign = 1;
  if (source[cursor] === '-') { sign = -1; cursor += 1; }
  const numberStart = cursor;
  while (cursor < source.length && /\d/.test(source[cursor])) cursor += 1;
  const number = cursor > numberStart ? sign * Number(source.slice(numberStart, cursor)) : null;
  if (source[cursor] === ' ') cursor += 1;
  return { word, number, end: cursor };
}

function parseRtfText(source: string): string {
  if (!/^\s*\{\\rtf\d?/i.test(source)) throw new Error('The selected file is not a readable RTF document.');
  const output: string[] = [];
  const groups: RtfGroupState[] = [{ skip: false, unicodeFallback: 1, fallbackToSkip: 0 }];
  let cursor = 0;
  let groupDepth = 0;

  while (cursor < source.length) {
    const char = source[cursor];
    const current = groups[groups.length - 1];
    if (char === '{') {
      groupDepth += 1;
      groups.push({ ...current, fallbackToSkip: 0 });
      cursor += 1;
      continue;
    }
    if (char === '}') {
      if (groupDepth === 0) throw new Error('The selected RTF document has invalid group structure.');
      const closesRoot = groupDepth === 1;
      groupDepth -= 1;
      groups.pop();
      cursor += 1;
      if (closesRoot) {
        if (source.slice(cursor).trim()) throw new Error('The selected RTF document has trailing data.');
        break;
      }
      continue;
    }
    if (char !== '\\') {
      if (current.fallbackToSkip > 0 && !/\s/.test(char)) current.fallbackToSkip -= 1;
      else if (!current.skip) output.push(char);
      cursor += 1;
      continue;
    }

    cursor += 1;
    if (cursor >= source.length) break;
    const symbol = source[cursor];
    if (symbol === '*') {
      groups[groups.length - 1] = { ...current, skip: true };
      cursor += 1;
      continue;
    }
    if (symbol === "'") {
      const hex = source.slice(cursor + 1, cursor + 3);
      if (/^[0-9a-f]{2}$/i.test(hex)) {
        if (current.fallbackToSkip > 0) current.fallbackToSkip -= 1;
        else if (!current.skip) output.push(new TextDecoder('windows-1252').decode(new Uint8Array([Number.parseInt(hex, 16)])));
        cursor += 3;
      } else cursor += 1;
      continue;
    }
    if (!/[a-z]/i.test(symbol)) {
      cursor += 1;
      if (current.fallbackToSkip > 0) current.fallbackToSkip -= 1;
      else if (!current.skip && (symbol === '\\' || symbol === '{' || symbol === '}')) output.push(symbol);
      else if (!current.skip && symbol === '~') output.push('\u00a0');
      else if (!current.skip && symbol === '_') output.push('\u2011');
      else if (!current.skip && symbol === '-') output.push('\u00ad');
      continue;
    }

    const token = controlWord(source, cursor);
    cursor = token.end;
    if (token.word === 'bin') {
      const binaryLength = token.number ?? -1;
      if (binaryLength < 0 || binaryLength > source.length - cursor) {
        throw new Error('The selected RTF document has invalid binary data.');
      }
      cursor += binaryLength;
      continue;
    }
    if (token.word === '*') {
      groups[groups.length - 1] = { ...current, skip: true };
      continue;
    }
    if (NON_TEXT_DESTINATIONS.has(token.word)) {
      groups[groups.length - 1] = { ...current, skip: true };
      continue;
    }
    if (token.word === 'uc' && token.number !== null) {
      groups[groups.length - 1] = { ...current, unicodeFallback: Math.max(0, Math.min(16, token.number)) };
      continue;
    }
    if (current.fallbackToSkip > 0) {
      groups[groups.length - 1] = { ...current, fallbackToSkip: current.fallbackToSkip - 1 };
      continue;
    }
    if (current.skip) continue;
    if (token.word === 'u' && token.number !== null) {
      if (token.number < -32_768 || token.number > 65_535) {
        throw new Error('The selected RTF document contains an invalid Unicode escape.');
      }
      const codeUnit = token.number < 0 ? token.number + 65_536 : token.number;
      output.push(String.fromCharCode(codeUnit));
      groups[groups.length - 1] = { ...current, fallbackToSkip: current.unicodeFallback };
    } else if (['par', 'line', 'row', 'page', 'sect'].includes(token.word)) output.push('\n');
    else if (token.word === 'cell') output.push('\t');
    else if (token.word === 'tab') output.push('\t');
    else if (token.word === 'emdash') output.push('\u2014');
    else if (token.word === 'endash') output.push('\u2013');
    else if (token.word === 'emspace' || token.word === 'enspace') output.push(' ');
  }

  if (groupDepth !== 0) throw new Error('The selected RTF document is incomplete.');
  return output.join('').replace(/[\t ]+\n/g, '\n').trim();
}

/** Extract bounded plain text from a local RTF file; no source bytes leave the browser. */
export async function extractRtfText(blob: Blob): Promise<string> {
  if (blob.size > MAX_LOCAL_RTF_BYTES) {
    throw new Error('The selected RTF file exceeds the 80,000-byte browser parsing limit.');
  }
  const source = decodeRtfSource(await readBlobAsBytes(blob));
  const text = parseRtfText(source);
  if (Array.from(text).length > MAX_CONTEXT_FILE_CHARS) {
    throw new Error(`The selected RTF file exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
  }
  return text;
}
