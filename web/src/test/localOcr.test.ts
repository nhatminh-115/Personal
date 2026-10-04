import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createWorker } from 'tesseract.js';
import { createLocalOcrWorker } from '../lib/localOcr';

vi.mock('tesseract.js', () => ({ createWorker: vi.fn() }));

describe('local OCR runtime configuration', () => {
  beforeEach(() => vi.clearAllMocks());

  it('uses bundled same-origin worker, WASM core, and English/Vietnamese models', async () => {
    await createLocalOcrWorker();

    expect(createWorker).toHaveBeenCalledWith('eng+vie', 1, {
      workerPath: `${window.location.origin}/ocr/worker.min.js`,
      corePath: `${window.location.origin}/ocr/core/tesseract-core-lstm.wasm.js`,
      langPath: `${window.location.origin}/ocr/lang`,
      gzip: true,
      workerBlobURL: false,
    });
  });
});
