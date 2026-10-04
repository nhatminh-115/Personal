import { describe, expect, it, vi } from 'vitest';
import { extractHtmlText, MAX_HTML_INPUT_BYTES, MAX_HTML_TEXT_CHARS } from '../lib/htmlText';

const htmlBlob = (text: string) => new Blob([text], { type: 'text/html' });

describe('local HTML text extraction', () => {
  it('keeps body text and block boundaries, strips executable and hidden content', async () => {
    const parser = vi.spyOn(DOMParser.prototype, 'parseFromString');
    const extracted = await extractHtmlText(htmlBlob(`<!doctype html><html><head><title>Not body text</title></head><body>
      <h1>Résumé 世界</h1><p>Hello <strong>there</strong>.</p><p hidden>secret</p>
      <div aria-hidden="true">screen reader hidden</div><span style="display:none">invisible</span>
      <span style="visibility: hidden">also invisible</span><span style="content-visibility:hidden">hidden</span>
      <script>window.__executed = true</script><style>.x { display:none }</style><noscript>fallback</noscript>
      <template>template secret</template><svg><text>svg secret</text></svg><iframe>frame secret</iframe>
      <object>object secret</object><embed><img src="https://example.test/pixel" onerror="window.__executed = true">
      <style>@import url("https://example.test/unclosed.css");`));

    expect(extracted).toBe('Résumé 世界\nHello there.');
    const parsedSource = String(parser.mock.calls[0]?.[0]);
    expect(parsedSource).not.toMatch(/<img\b|<iframe\b|<style\b|https:\/\/example\.test|onerror/i);
    expect(window).not.toHaveProperty('__executed');
    expect(extracted).not.toContain('<');
    parser.mockRestore();
  });

  it('handles malformed markup, Unicode, and empty documents', async () => {
    await expect(extractHtmlText(htmlBlob('<p>Héllo 🌍<p>Unclosed'))).resolves.toBe('Héllo 🌍\nUnclosed');
    await expect(extractHtmlText(htmlBlob('<script>private()</script><p hidden>secret</p>'))).resolves.toBe('');
  });

  it('enforces byte and extracted character limits', async () => {
    await expect(extractHtmlText(new Blob(['x'.repeat(MAX_HTML_INPUT_BYTES + 1)]))).rejects.toThrow('80,000-byte');
    await expect(extractHtmlText(htmlBlob(`<p>${'文'.repeat(MAX_HTML_TEXT_CHARS + 1)}</p>`))).rejects.toThrow('20,000-character');
    await expect(extractHtmlText(htmlBlob(`<p>${'文'.repeat(MAX_HTML_TEXT_CHARS)}</p>`))).resolves.toHaveLength(MAX_HTML_TEXT_CHARS);
  });
});
