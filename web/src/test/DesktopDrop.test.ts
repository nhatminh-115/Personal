import { describe, expect, it } from 'vitest';
import { toDesktopDroppedFile } from '../lib/desktopDrop';

describe('native desktop file drop adapter', () => {
  it('creates an in-memory File from the Rust sidecar payload', async () => {
    const file = toDesktopDroppedFile({
      name: 'plan.txt',
      mimeType: 'text/plain',
      bytesBase64: 'c2VjcmV0',
    });
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file);
    });

    expect(file.name).toBe('plan.txt');
    expect(file.type).toBe('text/plain');
    expect(content).toBe('secret');
  });
});
