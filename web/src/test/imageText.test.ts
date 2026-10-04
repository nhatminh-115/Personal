import { beforeEach, describe, expect, it, vi } from 'vitest';
import { extractImageText, MAX_LOCAL_IMAGE_BYTES } from '../lib/imageText';
import { createLocalOcrWorker } from '../lib/localOcr';

const ocr = vi.hoisted(() => ({ createLocalOcrWorker: vi.fn() }));
vi.mock('../lib/localOcr', () => ocr);

describe('browser-local image OCR', () => {
  const drawImage = vi.fn();
  const recognize = vi.fn();
  const terminate = vi.fn().mockResolvedValue(undefined);
  const close = vi.fn();
  let dimensions = { width: 1200, height: 800 };

  beforeEach(() => {
    vi.clearAllMocks();
    dimensions = { width: 1200, height: 800 };
    vi.mocked(createLocalOcrWorker).mockResolvedValue({ recognize, terminate } as any);
    recognize.mockResolvedValue({ data: { text: '  Invoice total: $42  ' } });
    close.mockClear();
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ ...dimensions, close })));
    vi.spyOn(document, 'createElement').mockImplementation(((tagName: string) => {
      if (tagName !== 'canvas') return document.createElementNS('http://www.w3.org/1999/xhtml', tagName) as any;
      const canvas = document.createElementNS('http://www.w3.org/1999/xhtml', 'canvas') as HTMLCanvasElement;
      vi.spyOn(canvas, 'getContext').mockReturnValue({ drawImage } as any);
      return canvas;
    }) as typeof document.createElement);
  });

  it('extracts text in the browser using the shared local OCR worker', async () => {
    await expect(extractImageText(new Blob(['image']))).resolves.toBe('[Image OCR]\nInvoice total: $42');
    expect(createImageBitmap).toHaveBeenCalledOnce();
    expect(createLocalOcrWorker).toHaveBeenCalledOnce();
    expect(drawImage).toHaveBeenCalledOnce();
    expect(recognize).toHaveBeenCalledOnce();
    expect(close).toHaveBeenCalledOnce();
    expect(terminate).toHaveBeenCalledOnce();
  });

  it('rejects oversized images before decoding', async () => {
    await expect(extractImageText(new Blob([new Uint8Array(MAX_LOCAL_IMAGE_BYTES + 1)]))).rejects.toThrow('10 MB');
    expect(createImageBitmap).not.toHaveBeenCalled();
  });

  it('rejects images over the pixel limit and releases the bitmap', async () => {
    dimensions = { width: 5000, height: 5000 };
    await expect(extractImageText(new Blob(['image']))).rejects.toThrow('20-megapixel');
    expect(close).toHaveBeenCalledOnce();
    expect(createLocalOcrWorker).not.toHaveBeenCalled();
  });

  it('rejects images without text and terminates the worker', async () => {
    recognize.mockResolvedValueOnce({ data: { text: '   ' } });
    await expect(extractImageText(new Blob(['image']))).rejects.toThrow('no extractable text');
    expect(terminate).toHaveBeenCalledOnce();
  });

  it('enforces the extracted text limit', async () => {
    recognize.mockResolvedValueOnce({ data: { text: 'x'.repeat(20_001) } });
    await expect(extractImageText(new Blob(['image']))).rejects.toThrow('20,000-character');
  });
});
