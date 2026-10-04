import { Unzip, UnzipInflate, UnzipPassThrough } from 'fflate';
import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_PPTX_BYTES = 10 * 1024 * 1024;
export const MAX_LOCAL_PPTX_SLIDES = 100;
export const MAX_LOCAL_PPTX_SLIDE_XML_BYTES = 1024 * 1024;
export const MAX_LOCAL_PPTX_EXPANDED_BYTES = 20 * 1024 * 1024;
const MAX_ARCHIVE_ENTRIES = 4096;
const DRAWING_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main';

interface ExtractedSlide {
  number: number;
  xml: string;
}

function slideText(xml: string): string {
  const document = new DOMParser().parseFromString(xml, 'application/xml');
  if (document.getElementsByTagName('parsererror').length) {
    throw new Error('This presentation contains an invalid slide.');
  }
  const paragraphs = Array.from(document.getElementsByTagNameNS(DRAWING_NS, 'p'));
  return paragraphs.map((paragraph) => Array.from(paragraph.getElementsByTagNameNS(DRAWING_NS, 't'))
    .map((run) => run.textContent ?? '').join('')).filter(Boolean).join('\n');
}

export async function extractPptxText(blob: Blob): Promise<string> {
  if (!blob.size) throw new Error('The selected presentation is empty.');
  if (blob.size > MAX_LOCAL_PPTX_BYTES) {
    throw new Error('The selected presentation exceeds the 10 MB browser parsing limit.');
  }

  try {
    const archive = new Unzip();
    archive.register(UnzipInflate);
    archive.register(UnzipPassThrough);

    const slides: Promise<ExtractedSlide>[] = [];
    let entryCount = 0;
    let expandedBytes = 0;
    archive.onfile = (file) => {
      entryCount += 1;
      if (entryCount > MAX_ARCHIVE_ENTRIES) {
        throw new Error('The selected presentation contains too many archive entries.');
      }
      const match = /^ppt\/slides\/slide(\d+)\.xml$/i.exec(file.name);
      if (!match) return;
      if (slides.length >= MAX_LOCAL_PPTX_SLIDES) {
        throw new Error(`The selected presentation exceeds the ${MAX_LOCAL_PPTX_SLIDES}-slide limit.`);
      }
      if (file.originalSize != null && file.originalSize > MAX_LOCAL_PPTX_SLIDE_XML_BYTES) {
        throw new Error('The selected presentation has a slide XML file larger than the 1 MB limit.');
      }

      const number = Number(match[1]);
      const pending = new Promise<ExtractedSlide>((resolve, reject) => {
        const decoder = new TextDecoder();
        const chunks: string[] = [];
        let slideBytes = 0;
        file.ondata = (error, chunk, final) => {
          if (error) {
            reject(error);
            return;
          }
          slideBytes += chunk.byteLength;
          expandedBytes += chunk.byteLength;
          if (slideBytes > MAX_LOCAL_PPTX_SLIDE_XML_BYTES || expandedBytes > MAX_LOCAL_PPTX_EXPANDED_BYTES) {
            void file.terminate();
            reject(new Error('The selected presentation exceeds the browser decompression limit.'));
            return;
          }
          chunks.push(decoder.decode(chunk, { stream: !final }));
          if (final) resolve({ number, xml: chunks.join('') });
        };
        try {
          file.start();
        } catch (error) {
          reject(error);
        }
      });
      slides.push(pending);
    };

    archive.push(new Uint8Array(await blob.arrayBuffer()), true);
    if (!slides.length) throw new Error('This presentation is not a valid or readable PowerPoint file.');
    const extracted = (await Promise.all(slides)).sort((a, b) => a.number - b.number);
    const content = extracted.map(({ number, xml }) => {
      const text = slideText(xml);
      return text ? `Slide ${number}\n${text}` : '';
    }).filter(Boolean).join('\n\n');
    if (!content.trim()) throw new Error('This presentation has no extractable slide text.');
    if (Array.from(content).length > MAX_CONTEXT_FILE_CHARS) {
      throw new Error(`The selected presentation exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
    }
    return `[PowerPoint]\n${content}`;
  } catch (error) {
    if (error instanceof Error && (
      error.message.startsWith('The selected presentation') || error.message.startsWith('This presentation')
    )) {
      throw error;
    }
    throw new Error('AURA could not extract slide text from this presentation in the browser.');
  }
}
