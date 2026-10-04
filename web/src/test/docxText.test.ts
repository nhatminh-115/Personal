import { beforeEach, describe, expect, it, vi } from 'vitest';
import mammoth from 'mammoth';
import { extractDocxText, MAX_LOCAL_DOCX_BYTES } from '../lib/docxText';
import { MAX_CONTEXT_FILE_CHARS } from '../lib/pdfText';

vi.mock('mammoth', () => ({ default: { extractRawText: vi.fn() } }));

describe('browser-local Word document text extraction', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    if (!Blob.prototype.arrayBuffer) {
      Object.defineProperty(Blob.prototype, 'arrayBuffer', {
        configurable: true,
        value: async () => new ArrayBuffer(8),
      });
    }
  });

  it('extracts raw text locally and trims document padding', async () => {
    vi.mocked(mammoth.extractRawText).mockResolvedValue({ value: '\n Local paragraph one.\n\nParagraph two. \n', messages: [] });

    await expect(extractDocxText(new Blob(['docx fixture']))).resolves.toBe('Local paragraph one.\n\nParagraph two.');
    expect(mammoth.extractRawText).toHaveBeenCalledWith({ arrayBuffer: expect.any(ArrayBuffer) });
  });

  it('rejects empty or oversized files before invoking the parser', async () => {
    await expect(extractDocxText(new Blob([]))).rejects.toThrow('Word document is empty');
    await expect(extractDocxText(new Blob([new Uint8Array(MAX_LOCAL_DOCX_BYTES + 1)]))).rejects.toThrow('10 MB browser parsing limit');
    expect(mammoth.extractRawText).not.toHaveBeenCalled();
  });

  it('rejects empty and over-limit extracted text with safe messages', async () => {
    vi.mocked(mammoth.extractRawText).mockResolvedValueOnce({ value: '  ', messages: [] });
    await expect(extractDocxText(new Blob(['docx fixture']))).rejects.toThrow('no extractable text');

    vi.mocked(mammoth.extractRawText).mockResolvedValueOnce({ value: `a${'b'.repeat(MAX_CONTEXT_FILE_CHARS)}`, messages: [] });
    await expect(extractDocxText(new Blob(['docx fixture']))).rejects.toThrow('20,000-character text limit');
  });

  it('hides parser internals when a document is malformed', async () => {
    vi.mocked(mammoth.extractRawText).mockRejectedValue(new Error('private ZIP parser detail'));

    await expect(extractDocxText(new Blob(['not a docx']))).rejects.toThrow('AURA could not extract text from this Word document in the browser.');
  });
});
