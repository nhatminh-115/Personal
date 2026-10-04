export const MAX_HTML_INPUT_BYTES = 80_000;
export const MAX_HTML_TEXT_CHARS = 20_000;

const REMOVED_TAGS = new Set([
  'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'IFRAME', 'OBJECT', 'EMBED',
  'CANVAS', 'VIDEO', 'AUDIO', 'SOURCE', 'TRACK', 'INPUT', 'TEXTAREA', 'SELECT',
]);

function readBlobAsText(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('Could not read the selected HTML file.'));
    reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
    reader.readAsText(blob);
  });
}

function neutralizeHtmlResources(source: string): string {
  return source
    // DOMParser documents are inert but can still fetch iframe and image URLs.
    .replace(/<(script|style|svg|iframe|img|picture|object|embed|video|audio|source|track|link|base|frame|frameset)\b[^>]*>(?:[\s\S]*?<\/\1\s*>)?/gi, ' ')
    .replace(/\sstyle\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, (attribute) => {
      const style = attribute.slice(attribute.indexOf('=') + 1).trim().replace(/^(?:"([\s\S]*)"|'([\s\S]*)')$/, '$1$2');
      return /(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden|content-visibility\s*:\s*hidden)(?:\s*!important)?\s*(?:;|$)/i.test(style)
        ? ' data-aura-extractor-hidden="true"'
        : ' ';
    })
    .replace(/\s(?:src|srcset|srcdoc|data|poster|background|xlink:href|href|action|formaction|ping|on[a-z]+)(?=\s|=)\s*(?:=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?/gi, ' ');
}
const BLOCK_TAGS = new Set([
  'ADDRESS', 'ARTICLE', 'ASIDE', 'BLOCKQUOTE', 'BR', 'DD', 'DIV', 'DL', 'DT',
  'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM', 'H1', 'H2', 'H3',
  'H4', 'H5', 'H6', 'HEADER', 'HR', 'LI', 'MAIN', 'NAV', 'OL', 'P', 'PRE',
  'SECTION', 'TABLE', 'TBODY', 'TD', 'TFOOT', 'TH', 'THEAD', 'TR', 'UL',
]);

/** Extract bounded, visible-ish text locally. DOMParser parses inert markup and never executes its scripts. */
export async function extractHtmlText(blob: Blob): Promise<string> {
  if (blob.size > MAX_HTML_INPUT_BYTES) {
    throw new Error('HTML file exceeds the 80,000-byte browser parsing limit.');
  }
  const source = neutralizeHtmlResources(await readBlobAsText(blob));
  const document = new DOMParser().parseFromString(source, 'text/html');
  const parts: string[] = [];

  const visit = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      parts.push(node.textContent ?? '');
      return;
    }
    if (!(node instanceof Element)) return;

    const element = node as HTMLElement;
    const tagName = element.tagName.toUpperCase();
    const hidden = REMOVED_TAGS.has(tagName)
      || element.hasAttribute('hidden')
      || element.hasAttribute('data-aura-extractor-hidden')
      || element.getAttribute('aria-hidden')?.toLowerCase() === 'true'
      || element.getAttribute('type')?.toLowerCase() === 'hidden';
    if (hidden) {
      return;
    }

    if (tagName === 'BR' || tagName === 'HR') {
      parts.push('\n');
      return;
    }
    const block = BLOCK_TAGS.has(tagName);
    if (block) parts.push('\n');
    for (const child of element.childNodes) visit(child);
    if (block) parts.push('\n');
  };

  if (document.body) visit(document.body);
  const text = parts
    .join('')
    .split(/\r?\n/)
    .map((line) => line.replace(/[\t\f\v ]+/g, ' ').trim())
    .filter(Boolean)
    .join('\n');
  if (Array.from(text).length > MAX_HTML_TEXT_CHARS) {
    throw new Error(`HTML text exceeds the ${MAX_HTML_TEXT_CHARS.toLocaleString('en-US')}-character limit.`);
  }
  return text;
}
