const MAX_OCR_PAGES = 5;

export { MAX_OCR_PAGES };

function assetUrl(path: string): string {
  const baseUrl = new URL('/', window.location.href);
  return new URL(`ocr/${path}`, baseUrl).toString();
}

export async function createLocalOcrWorker() {
  const { createWorker } = await import('tesseract.js');
  return createWorker('eng+vie', 1, {
    workerPath: assetUrl('worker.min.js'),
    corePath: assetUrl('core/tesseract-core-lstm.wasm.js'),
    langPath: assetUrl('lang'),
    gzip: true,
    workerBlobURL: false,
  });
}
