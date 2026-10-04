import { MAX_CONTEXT_FILE_CHARS } from './pdfText';
import { createLocalOcrWorker } from './localOcr';

export const MAX_LOCAL_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_IMAGE_PIXELS = 20_000_000;
const MAX_IMAGE_DIMENSION = 1_800;

export async function extractImageText(blob: Blob): Promise<string> {
  if (blob.size === 0) throw new Error('The selected image is empty.');
  if (blob.size > MAX_LOCAL_IMAGE_BYTES) {
    throw new Error('The selected image exceeds the 10 MB browser parsing limit.');
  }

  let bitmap: ImageBitmap | null = null;
  let ocrWorker: Awaited<ReturnType<typeof createLocalOcrWorker>> | null = null;
  let canvas: HTMLCanvasElement | null = null;
  try {
    bitmap = await createImageBitmap(blob);
    if (!bitmap.width || !bitmap.height || bitmap.width * bitmap.height > MAX_IMAGE_PIXELS) {
      throw new Error('The selected image exceeds the 20-megapixel browser OCR limit.');
    }

    const scale = Math.min(1, MAX_IMAGE_DIMENSION / Math.max(bitmap.width, bitmap.height));
    canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('AURA could not prepare this image for local OCR.');
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    ocrWorker = await createLocalOcrWorker();
    const result = await ocrWorker.recognize(canvas);
    const text = result.data.text.trim();
    if (!text) throw new Error('This image has no extractable text.');
    if (Array.from(text).length > MAX_CONTEXT_FILE_CHARS) {
      throw new Error(`The selected image exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
    }
    return `[Image OCR]\n${text}`;
  } catch (error) {
    if (error instanceof Error && (
      error.message.startsWith('The selected image') || error.message.startsWith('This image')
    )) {
      throw error;
    }
    throw new Error('AURA could not extract text from this image in the browser.');
  } finally {
    if (canvas) {
      canvas.width = 0;
      canvas.height = 0;
    }
    bitmap?.close();
    await ocrWorker?.terminate().catch(() => undefined);
  }
}
