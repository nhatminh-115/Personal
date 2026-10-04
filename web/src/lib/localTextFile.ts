import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_TEXT_FILE_BYTES = 80_000;

function readBlobAsBytes(blob: Blob): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the selected text file.'));
    reader.onload = () => {
      if (!(reader.result instanceof ArrayBuffer)) {
        reject(new Error('Could not read the selected text file.'));
        return;
      }
      resolve(new Uint8Array(reader.result));
    };
    reader.readAsArrayBuffer(blob);
  });
}

function decodeLocalText(bytes: Uint8Array): string {
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    return new TextDecoder('utf-8').decode(bytes.subarray(3));
  }
  if (bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xfe) {
    return new TextDecoder('utf-16le').decode(bytes.subarray(2));
  }
  if (bytes.length >= 2 && bytes[0] === 0xfe && bytes[1] === 0xff) {
    const bigEndianText = bytes.subarray(2);
    const littleEndianText = new Uint8Array(bigEndianText.length - (bigEndianText.length % 2));
    for (let index = 0; index + 1 < bigEndianText.length; index += 2) {
      littleEndianText[index] = bigEndianText[index + 1];
      littleEndianText[index + 1] = bigEndianText[index];
    }
    return new TextDecoder('utf-16le').decode(littleEndianText) + (bigEndianText.length % 2 ? '\ufffd' : '');
  }
  return new TextDecoder('utf-8').decode(bytes);
}

/** Decode local TXT/Markdown/CSV/JSON with BOM-aware Unicode decoding, without uploading the source blob. */
export async function extractLocalTextFile(blob: Blob): Promise<string> {
  if (blob.size > MAX_LOCAL_TEXT_FILE_BYTES) {
    throw new Error('The selected text file exceeds the 80,000-byte browser parsing limit.');
  }
  const text = decodeLocalText(await readBlobAsBytes(blob));
  if (Array.from(text).length > MAX_CONTEXT_FILE_CHARS) {
    throw new Error(`The selected text file exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
  }
  return text;
}
