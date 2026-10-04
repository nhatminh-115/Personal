import { zipSync, strToU8 } from 'fflate';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  extractEpubText,
  MAX_LOCAL_EPUB_BYTES,
  MAX_LOCAL_EPUB_CHAPTERS,
  MAX_LOCAL_EPUB_ENTRY_BYTES,
  MAX_LOCAL_EPUB_EXPANDED_BYTES,
} from '../lib/epubText';

const containerXml = (packagePath = 'OPS/package.opf') => strToU8(
  `<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="${packagePath}" media-type="application/oebps-package+xml"/></rootfiles></container>`,
);
const xhtml = (text: string) => strToU8(
  `<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Not chapter content</title></head><body><p>${text}</p></body></html>`,
);
function epub(chapters: string[], paths = chapters.map((_, index) => `OPS/Text/ch${index + 1}.xhtml`), extras: Record<string, Uint8Array> = {}) {
  const manifest = paths.map((path, index) => `<item id="chapter-${index + 1}" href="Text/${path.split('/').pop()}" media-type="application/xhtml+xml"/>`).join('');
  const spine = chapters.map((_, index) => `<itemref idref="chapter-${index + 1}"/>`).join('');
  return new Blob([zipSync({
    'META-INF/container.xml': containerXml(),
    'OPS/package.opf': strToU8(`<package xmlns="http://www.idpf.org/2007/opf"><manifest>${manifest}</manifest><spine>${spine}</spine></package>`),
    ...Object.fromEntries(paths.map((path, index) => [path, xhtml(chapters[index])])),
    ...extras,
  })]);
}

describe('browser-local EPUB chapter extraction', () => {
  beforeEach(() => {
    if (!Blob.prototype.arrayBuffer) {
      Object.defineProperty(Blob.prototype, 'arrayBuffer', {
        configurable: true,
        value: function arrayBuffer(this: Blob) {
          return new Promise<ArrayBuffer>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as ArrayBuffer);
            reader.onerror = () => reject(reader.error);
            reader.readAsArrayBuffer(this);
          });
        },
      });
    }
  });

  it('follows the package spine reading order and ignores unreferenced markup', async () => {
    const blob = epub(
      ['The second section.', 'The first section.'],
      ['OPS/Text/ch2.xhtml', 'OPS/Text/ch1.xhtml'],
      { 'OPS/Text/unlisted.xhtml': xhtml('Do not include this file.') },
    );
    await expect(extractEpubText(blob)).resolves.toBe('[EPUB]\nChapter 1\nThe second section.\n\nChapter 2\nThe first section.');
  });

  it('rejects oversized input before reading the archive', async () => {
    await expect(extractEpubText(new Blob([new Uint8Array(MAX_LOCAL_EPUB_BYTES + 1)]))).rejects.toThrow('10 MB');
  });

  it('rejects malformed archives and empty chapter text clearly', async () => {
    await expect(extractEpubText(new Blob(['not a zip archive']))).rejects.toThrow('not a readable EPUB');
    await expect(extractEpubText(epub(['   ']))).rejects.toThrow('no extractable chapter text');
  });

  it('rejects unsafe chapter paths that escape the archive root', async () => {
    const packageXml = `<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="chapter" href="../../outside.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>`;
    const blob = new Blob([zipSync({
      'META-INF/container.xml': containerXml(),
      'OPS/package.opf': strToU8(packageXml),
      'outside.xhtml': xhtml('Unsafe chapter'),
    })]);
    await expect(extractEpubText(blob)).rejects.toThrow('chapter path outside its archive');
  });

  it('enforces chapter count and per-entry expansion ceilings', async () => {
    await expect(extractEpubText(epub(Array.from({ length: MAX_LOCAL_EPUB_CHAPTERS + 1 }, () => 'small'))))
      .rejects.toThrow('100-chapter limit');
    await expect(extractEpubText(epub(['x'.repeat(MAX_LOCAL_EPUB_ENTRY_BYTES)])))
      .rejects.toThrow('larger than the 1 MB limit');
  });

  it('caps aggregate expansion of highly compressed chapter content', async () => {
    const chapterText = 'x'.repeat(Math.floor(MAX_LOCAL_EPUB_ENTRY_BYTES - 300));
    const count = Math.floor(MAX_LOCAL_EPUB_EXPANDED_BYTES / (MAX_LOCAL_EPUB_ENTRY_BYTES - 190)) + 1;
    await expect(extractEpubText(epub(Array.from({ length: count }, () => chapterText))))
      .rejects.toThrow('decompression limit');
  });
});
