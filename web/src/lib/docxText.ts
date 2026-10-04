import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_DOCX_BYTES = 10 * 1024 * 1024;

export async function extractDocxText(blob: Blob): Promise<string> {
  if (blob.size === 0) throw new Error('The selected Word document is empty.');
  if (blob.size > MAX_LOCAL_DOCX_BYTES) {
    throw new Error('The selected Word document exceeds the 10 MB browser parsing limit.');
  }

  try {
    const { default: mammoth } = await import('mammoth');
    const result = await mammoth.extractRawText({ arrayBuffer: await blob.arrayBuffer() });
    const text = result.value.trim();
    if (!text) throw new Error('This Word document has no extractable text.');
    if (Array.from(text).length > MAX_CONTEXT_FILE_CHARS) {
      throw new Error(`The selected Word document exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
    }
    return text;
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('This Word document')) throw error;
    if (error instanceof Error && error.message.startsWith('The selected Word document')) throw error;
    throw new Error('AURA could not extract text from this Word document in the browser.');
  }
}
