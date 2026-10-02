import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';

function jsonResponse(body: unknown, nextCursor?: string): Response {
  const headers = new Headers();
  if (nextCursor) headers.set('X-Next-Cursor', nextCursor);
  return { ok: true, headers, json: async () => body } as Response;
}

describe('workspace collection pagination', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('collects every notes page using the response cursor header', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse([{ id: 'note-1' }, { id: 'note-2' }], 'next-notes'))
      .mockResolvedValueOnce(jsonResponse([{ id: 'note-3' }]));
    vi.stubGlobal('fetch', fetch);

    const notes = await api.fetchWorkspaceNotes();

    expect(notes.map((note) => note.id)).toEqual(['note-1', 'note-2', 'note-3']);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(new URL(fetch.mock.calls[0][0] as string, 'http://aura.test').searchParams.get('page_size')).toBeNull();
    const secondUrl = new URL(fetch.mock.calls[1][0] as string, 'http://aura.test');
    expect(secondUrl.searchParams.get('page_size')).toBe('100');
    expect(secondUrl.searchParams.get('cursor')).toBe('next-notes');
  });
});
