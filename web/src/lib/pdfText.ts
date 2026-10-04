import { createLocalOcrWorker, MAX_OCR_PAGES } from './localOcr';

export const MAX_LOCAL_PDF_BYTES = 10 * 1024 * 1024;
export const MAX_LOCAL_PDF_PAGES = 100;
export const MAX_CONTEXT_FILE_CHARS = 20_000;

export async function extractPdfText(blob: Blob): Promise<string> {
  if (blob.size === 0) throw new Error('The selected PDF is empty.');
  if (blob.size > MAX_LOCAL_PDF_BYTES) {
    throw new Error('The selected PDF exceeds the 10 MB browser parsing limit.');
  }

  const pdfjs = await import('pdfjs-dist/webpack.mjs');
  const loadingTask = pdfjs.getDocument({
    data: new Uint8Array(await blob.arrayBuffer()),
    useWorkerFetch: false,
    disableAutoFetch: true,
    disableStream: true,
    stopAtErrors: true,
  });
  let ocrWorker: Awaited<ReturnType<typeof createLocalOcrWorker>> | null = null;

  try {
    const document = await loadingTask.promise;
    if (document.numPages > MAX_LOCAL_PDF_PAGES) {
      throw new Error(`The selected PDF has more than ${MAX_LOCAL_PDF_PAGES} pages.`);
    }

    const pages: string[] = [];
    let characterCount = 0;
    let ocrPages = 0;
    let ocrLimitReached = false;
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const content = await page.getTextContent();
      let previousItemEndedLine = false;
      const pageText = content.items.reduce((rendered, item) => {
        if (!('str' in item)) return rendered;
        const text = item.str.trim();
        const separator = rendered ? (previousItemEndedLine ? '\n' : ' ') : '';
        previousItemEndedLine = item.hasEOL === true;
        return text ? `${rendered}${separator}${text}` : rendered;
      }, '');
      let extractedPageText = pageText;
      if (!pageText) {
        if (ocrPages >= MAX_OCR_PAGES) {
          ocrLimitReached = true;
          continue;
        }
        ocrPages += 1;
        if (!ocrWorker) ocrWorker = await createLocalOcrWorker();
        const viewport = page.getViewport({ scale: 1 });
        const scale = Math.min(1.5, 1800 / viewport.height, 1400 / viewport.width);
        const renderViewport = page.getViewport({ scale });
        const canvas = window.document.createElement('canvas');
        canvas.width = Math.ceil(renderViewport.width);
        canvas.height = Math.ceil(renderViewport.height);
        const canvasContext = canvas.getContext('2d');
        if (!canvasContext) throw new Error('AURA could not prepare this PDF page for local OCR.');
        await page.render({ canvas, canvasContext, viewport: renderViewport }).promise;
        let recognizedText = '';
        try {
          const result = await ocrWorker.recognize(canvas);
          recognizedText = result.data.text.trim();
        } finally {
          canvas.width = 0;
          canvas.height = 0;
        }
        if (recognizedText) extractedPageText = `[OCR page ${pageNumber}]\n${recognizedText}`;
      }
      if (extractedPageText) {
        characterCount += Array.from(extractedPageText).length;
        if (characterCount > MAX_CONTEXT_FILE_CHARS) {
          throw new Error(`The selected PDF exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
        }
        pages.push(extractedPageText);
      }
    }

    if (ocrLimitReached) pages.push(`[Local OCR limited to the first ${MAX_OCR_PAGES} scanned pages.]`);
    const text = pages.join('\n\n').trim();
    if (!text) {
      throw new Error('This PDF has no extractable text, including after local OCR.');
    }
    return text;
  } catch (error) {
    if (error instanceof Error && (
      error.message.startsWith('The selected PDF') || error.message.startsWith('This PDF')
    )) {
      throw error;
    }
    throw new Error('AURA could not extract text from this PDF in the browser.');
  } finally {
    await ocrWorker?.terminate().catch(() => undefined);
    await loadingTask.destroy();
  }
}
