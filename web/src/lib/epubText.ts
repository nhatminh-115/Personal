import { Unzip, UnzipInflate, UnzipPassThrough } from 'fflate';
import { MAX_CONTEXT_FILE_CHARS } from './pdfText';

export const MAX_LOCAL_EPUB_BYTES = 10 * 1024 * 1024;
export const MAX_LOCAL_EPUB_CHAPTERS = 100;
export const MAX_LOCAL_EPUB_ENTRY_BYTES = 1024 * 1024;
export const MAX_LOCAL_EPUB_EXPANDED_BYTES = 20 * 1024 * 1024;
const MAX_ARCHIVE_ENTRIES = 4096;
const CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container';
const OPF_NS = 'http://www.idpf.org/2007/opf';
const BLOCK_TEXT_SELECTOR = 'h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,td,th,dt,dd';

interface ZipEntryText {
  name: string;
  text: string;
}

async function readZipTextEntries(
  data: Uint8Array,
  includedPaths: Set<string>,
  maxMatchingEntries: number,
  expandedBudget: { bytes: number },
): Promise<ZipEntryText[]> {
  const archive = new Unzip();
  archive.register(UnzipInflate);
  archive.register(UnzipPassThrough);
  const pendingEntries: Promise<ZipEntryText>[] = [];
  let archiveEntryCount = 0;

  archive.onfile = (file) => {
    archiveEntryCount += 1;
    if (archiveEntryCount > MAX_ARCHIVE_ENTRIES) {
      throw new Error('The selected e-book contains too many archive entries.');
    }
    if (!includedPaths.has(file.name)) return;
    if (pendingEntries.length >= maxMatchingEntries) {
      throw new Error(`The selected e-book exceeds the ${MAX_LOCAL_EPUB_CHAPTERS}-chapter limit.`);
    }
    if (file.originalSize != null && file.originalSize > MAX_LOCAL_EPUB_ENTRY_BYTES) {
      throw new Error('The selected e-book has an XHTML/XML entry larger than the 1 MB limit.');
    }

    const pending = new Promise<ZipEntryText>((resolve, reject) => {
      const decoder = new TextDecoder();
      const chunks: string[] = [];
      let entryBytes = 0;
      file.ondata = (error, chunk, final) => {
        if (error) {
          reject(error);
          return;
        }
        entryBytes += chunk.byteLength;
        expandedBudget.bytes += chunk.byteLength;
        if (entryBytes > MAX_LOCAL_EPUB_ENTRY_BYTES || expandedBudget.bytes > MAX_LOCAL_EPUB_EXPANDED_BYTES) {
          void file.terminate();
          reject(new Error('The selected e-book exceeds the browser decompression limit.'));
          return;
        }
        chunks.push(decoder.decode(chunk, { stream: !final }));
        if (final) resolve({ name: file.name, text: chunks.join('') });
      };
      try {
        file.start();
      } catch (error) {
        reject(error);
      }
    });
    pendingEntries.push(pending);
  };

  archive.push(data, true);
  return Promise.all(pendingEntries);
}

function parseXml(xml: string): Document {
  const parsed = new DOMParser().parseFromString(xml, 'application/xml');
  if (parsed.getElementsByTagName('parsererror').length) {
    throw new Error('This e-book has an invalid EPUB navigation file.');
  }
  return parsed;
}

function localElement(document: Document, namespace: string, name: string): Element[] {
  const namespaced = Array.from(document.getElementsByTagNameNS(namespace, name));
  return namespaced.length ? namespaced : Array.from(document.getElementsByTagName(name));
}

function resolveArchivePath(basePath: string, href: string): string {
  const withoutFragment = href.split(/[?#]/, 1)[0];
  if (!withoutFragment || /^[a-z][a-z\d+.-]*:/i.test(withoutFragment) || withoutFragment.startsWith('/') || withoutFragment.includes('\\')) {
    throw new Error('This e-book contains an unsupported chapter path.');
  }
  let decoded: string;
  try { decoded = decodeURIComponent(withoutFragment); }
  catch { throw new Error('This e-book contains an invalid chapter path.'); }

  const parts = [...basePath.split('/').filter(Boolean)];
  for (const part of decoded.split('/')) {
    if (!part || part === '.') continue;
    if (part === '..') {
      if (!parts.length) throw new Error('This e-book contains a chapter path outside its archive.');
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  return parts.join('/');
}

function chapterText(markup: string, mediaType: string): string {
  const document = new DOMParser().parseFromString(markup, mediaType === 'text/html' ? 'text/html' : 'application/xhtml+xml');
  if (document.getElementsByTagName('parsererror').length) {
    throw new Error('This e-book contains an invalid XHTML chapter.');
  }
  document.querySelectorAll('script,style,noscript,svg').forEach((element) => element.remove());
  const body = document.getElementsByTagName('body')[0] ?? document.body ?? document.documentElement;
  const blocks = Array.from(body.querySelectorAll(BLOCK_TEXT_SELECTOR)).filter((element) =>
    !element.parentElement?.closest(BLOCK_TEXT_SELECTOR),
  );
  const normalize = (value: string | null) => (value ?? '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  const paragraphs = blocks.map((block) => normalize(block.textContent)).filter(Boolean);
  return paragraphs.length ? paragraphs.join('\n') : normalize(body.textContent);
}

export async function extractEpubText(blob: Blob): Promise<string> {
  if (!blob.size) throw new Error('The selected e-book is empty.');
  if (blob.size > MAX_LOCAL_EPUB_BYTES) {
    throw new Error('The selected e-book exceeds the 10 MB browser parsing limit.');
  }

  try {
    const data = new Uint8Array(await blob.arrayBuffer());
    const expandedBudget = { bytes: 0 };
    const packageFiles = await readZipTextEntries(data, new Set(['META-INF/container.xml']), 1, expandedBudget);
    const container = packageFiles[0]?.text;
    if (!container) throw new Error('This file is not a readable EPUB e-book.');
    const containerDoc = parseXml(container);
    const opfPath = localElement(containerDoc, CONTAINER_NS, 'rootfile')[0]?.getAttribute('full-path');
    if (!opfPath || opfPath.startsWith('/') || opfPath.split('/').includes('..')) {
      throw new Error('This e-book does not identify a safe EPUB package file.');
    }

    const opfFiles = await readZipTextEntries(data, new Set([opfPath]), 1, expandedBudget);
    if (!opfFiles[0]) throw new Error('This e-book is missing its EPUB package file.');
    const packageDoc = parseXml(opfFiles[0].text);
    const manifest = new Map(localElement(packageDoc, OPF_NS, 'item').flatMap((item) => {
      const id = item.getAttribute('id');
      const href = item.getAttribute('href');
      if (!id || !href) return [];
      return [[id, { href, mediaType: item.getAttribute('media-type') ?? '' }] as const];
    }));
    const spineItems = localElement(packageDoc, OPF_NS, 'itemref');
    if (spineItems.length > MAX_LOCAL_EPUB_CHAPTERS) {
      throw new Error(`The selected e-book exceeds the ${MAX_LOCAL_EPUB_CHAPTERS}-chapter limit.`);
    }
    const spine = spineItems.flatMap((item) => {
      const resource = manifest.get(item.getAttribute('idref') ?? '');
      if (!resource || !['application/xhtml+xml', 'text/html'].includes(resource.mediaType)) return [];
      const path = resolveArchivePath(opfPath.slice(0, Math.max(0, opfPath.lastIndexOf('/'))), resource.href);
      return [{ path, mediaType: resource.mediaType }];
    });
    if (!spine.length) throw new Error('This e-book has no readable text chapters.');

    const includedPaths = new Set(spine.map((item) => item.path));
    const chapterFiles = await readZipTextEntries(data, includedPaths, MAX_LOCAL_EPUB_CHAPTERS, expandedBudget);
    const chaptersByPath = new Map(chapterFiles.map((file) => [file.name, file.text]));
    const content = spine.map((item, index) => {
      const markup = chaptersByPath.get(item.path);
      if (markup == null) throw new Error('This e-book is missing a chapter listed in its spine.');
      const text = chapterText(markup, item.mediaType);
      return text ? `Chapter ${index + 1}\n${text}` : '';
    }).filter(Boolean).join('\n\n');
    if (!content.trim()) throw new Error('This e-book has no extractable chapter text.');
    if (Array.from(content).length > MAX_CONTEXT_FILE_CHARS) {
      throw new Error(`The selected e-book exceeds the ${MAX_CONTEXT_FILE_CHARS.toLocaleString('en-US')}-character text limit.`);
    }
    return `[EPUB]\n${content}`;
  } catch (error) {
    if (error instanceof Error && (
      error.message.startsWith('The selected e-book') || error.message.startsWith('This e-book') || error.message.startsWith('This file')
    )) {
      throw error;
    }
    throw new Error('AURA could not extract chapter text from this e-book in the browser.');
  }
}
