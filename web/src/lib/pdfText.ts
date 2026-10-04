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

  try {
    const document = await loadingTask.promise;
    if (document.numPages > MAX_LOCAL_PDF_PAGES) {
      throw new Error(`The selected PDF has more than ${MAX_LOCAL_PDF_PAGES} pages.`);
    }

    const pages: string[] = [];
    let characterCount = 0;
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
      if (pageText) {
        characterCount += Array.from(pageText).length;
        if (characterCount > MAX_CONTEXT_FILE_CHARS) {
          throw new Error(`The selected PDF exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
        }
        pages.push(pageText);
      }
    }

    const text = pages.join('\n\n').trim();
    if (!text) {
      throw new Error('This PDF has no selectable text. Scanned PDFs need OCR before they can be sent.');
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
    await loadingTask.destroy();
  }
}
