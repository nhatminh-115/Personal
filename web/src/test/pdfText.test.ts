import { beforeEach, describe, expect, it, vi } from 'vitest';
import { extractPdfText, MAX_CONTEXT_FILE_CHARS, MAX_LOCAL_PDF_BYTES, MAX_LOCAL_PDF_PAGES } from '../lib/pdfText';

const pdfjs = vi.hoisted(() => ({ getDocument: vi.fn() }));
vi.mock('pdfjs-dist/webpack.mjs', () => pdfjs);

function mockPdf(pages: string[][]) {
  const getPage = vi.fn(async (pageNumber: number) => ({
    getTextContent: async () => ({ items: pages[pageNumber - 1].map((str) => ({ str })) }),
  }));
  const destroy = vi.fn().mockResolvedValue(undefined);
  pdfjs.getDocument.mockReturnValue({
    promise: Promise.resolve({ numPages: pages.length, getPage }),
    destroy,
  });
  return { getPage, destroy };
}

function mockPdfItems(items: Array<{ str: string; hasEOL?: boolean }>) {
  const getPage = vi.fn(async () => ({ getTextContent: async () => ({ items }) }));
  const destroy = vi.fn().mockResolvedValue(undefined);
  pdfjs.getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 1, getPage }), destroy });
  return { destroy };
}

describe('browser-local PDF text extraction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    if (!Blob.prototype.arrayBuffer) {
      Object.defineProperty(Blob.prototype, 'arrayBuffer', {
        configurable: true,
        value: async () => new ArrayBuffer(8),
      });
    }
  });

  it('extracts selectable text in page order and destroys the local parser', async () => {
    const { getPage, destroy } = mockPdf([['Page one', 'continues'], ['Page two']]);

    await expect(extractPdfText(new Blob(['%PDF fixture']))).resolves.toBe('Page one continues\n\nPage two');
    expect(getPage).toHaveBeenNthCalledWith(1, 1);
    expect(getPage).toHaveBeenNthCalledWith(2, 2);
    expect(pdfjs.getDocument).toHaveBeenCalledWith(expect.objectContaining({ stopAtErrors: true, disableAutoFetch: true }));
    expect(destroy).toHaveBeenCalledOnce();
  });

  it('preserves PDF line breaks from text item boundaries', async () => {
    mockPdfItems([
      { str: 'Heading', hasEOL: true },
      { str: 'First line' },
      { str: 'continues' },
      { str: 'Second line', hasEOL: true },
    ]);

    await expect(extractPdfText(new Blob(['%PDF fixture']))).resolves.toBe('Heading\nFirst line continues Second line');
  });

  it('rejects oversized PDFs before parsing', async () => {
    const oversized = new Blob([new Uint8Array(MAX_LOCAL_PDF_BYTES + 1)]);

    await expect(extractPdfText(oversized)).rejects.toThrow('10 MB browser parsing limit');
    expect(pdfjs.getDocument).not.toHaveBeenCalled();
  });

  it('rejects PDFs above the page limit and releases parser resources', async () => {
    const { destroy } = mockPdf(Array.from({ length: MAX_LOCAL_PDF_PAGES + 1 }, () => []));

    await expect(extractPdfText(new Blob(['%PDF fixture']))).rejects.toThrow(`${MAX_LOCAL_PDF_PAGES} pages`);
    expect(destroy).toHaveBeenCalledOnce();
  });

  it('rejects extracted text above the per-file character limit', async () => {
    const { destroy } = mockPdf([[`a${'b'.repeat(MAX_CONTEXT_FILE_CHARS)}`]]);

    await expect(extractPdfText(new Blob(['%PDF fixture']))).rejects.toThrow('20,000-character text limit');
    expect(destroy).toHaveBeenCalledOnce();
  });

  it('explains that scanned PDFs need OCR when no selectable text exists', async () => {
    const { destroy } = mockPdf([['  '], []]);

    await expect(extractPdfText(new Blob(['%PDF fixture']))).rejects.toThrow('Scanned PDFs need OCR');
    expect(destroy).toHaveBeenCalledOnce();
  });
});
