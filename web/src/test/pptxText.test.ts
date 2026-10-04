import { zipSync, strToU8 } from 'fflate';
import { beforeEach, describe, expect, it } from 'vitest';
import {
  extractPptxText,
  MAX_LOCAL_PPTX_BYTES,
  MAX_LOCAL_PPTX_EXPANDED_BYTES,
  MAX_LOCAL_PPTX_SLIDE_XML_BYTES,
  MAX_LOCAL_PPTX_SLIDES,
} from '../lib/pptxText';

const drawingNs = 'http://schemas.openxmlformats.org/drawingml/2006/main';
const slide = (text: string) => strToU8(`<?xml version="1.0"?><p:sld xmlns:p="urn:p" xmlns:a="${drawingNs}"><a:p><a:r><a:t>${text}</a:t></a:r></a:p></p:sld>`);
const presentation = (files: Record<string, Uint8Array>) => new Blob([zipSync(files)]);

describe('browser-local PowerPoint text extraction', () => {
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

  it('extracts slide text in numeric order without sending or persisting the presentation', async () => {
    const blob = presentation({
      'ppt/slides/slide10.xml': slide('Last slide'),
      'ppt/slides/slide2.xml': slide('Second slide'),
      'ppt/slides/slide1.xml': slide('First slide'),
      'ppt/notesSlides/notesSlide1.xml': slide('Speaker note'),
    });
    await expect(extractPptxText(blob)).resolves.toBe('[PowerPoint]\nSlide 1\nFirst slide\n\nSlide 2\nSecond slide\n\nSlide 10\nLast slide');
  });

  it('rejects oversized files before reading the archive', async () => {
    await expect(extractPptxText(new Blob([new Uint8Array(MAX_LOCAL_PPTX_BYTES + 1)]))).rejects.toThrow('10 MB');
  });

  it('rejects malformed archives with a safe browser-local error', async () => {
    await expect(extractPptxText(new Blob(['not a zip archive']))).rejects.toThrow('not a valid or readable PowerPoint');
  });

  it('rejects presentations without slide text', async () => {
    await expect(extractPptxText(presentation({ 'ppt/slides/slide1.xml': slide('') }))).rejects.toThrow('no extractable slide text');
  });

  it('enforces slide count and per-slide decompression limits', async () => {
    const tooManySlides = Object.fromEntries(Array.from({ length: MAX_LOCAL_PPTX_SLIDES + 1 }, (_, index) => [
      `ppt/slides/slide${index + 1}.xml`, slide('small'),
    ]));
    await expect(extractPptxText(presentation(tooManySlides))).rejects.toThrow('100-slide limit');

    await expect(extractPptxText(presentation({
      'ppt/slides/slide1.xml': slide('x'.repeat(MAX_LOCAL_PPTX_SLIDE_XML_BYTES)),
    }))).rejects.toThrow('larger than the 1 MB limit');
  });

  it('caps total expanded slide XML for highly compressed presentations', async () => {
    const perSlideText = Math.floor(MAX_LOCAL_PPTX_SLIDE_XML_BYTES - 200);
    const files = Object.fromEntries(Array.from({ length: Math.floor(MAX_LOCAL_PPTX_EXPANDED_BYTES / perSlideText) + 1 }, (_, index) => [
      `ppt/slides/slide${index + 1}.xml`, slide('x'.repeat(perSlideText)),
    ]));
    await expect(extractPptxText(presentation(files))).rejects.toThrow('decompression limit');
  });
});
