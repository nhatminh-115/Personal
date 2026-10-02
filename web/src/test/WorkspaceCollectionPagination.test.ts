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

  it('uses the same paged loader for Study cards', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse([{ id: 'card-1' }], 'next-cards'))
      .mockResolvedValueOnce(jsonResponse([{ id: 'card-2' }]));
    vi.stubGlobal('fetch', fetch);

    const cards = await api.fetchStudyCards();

    expect(cards.map((card) => card.id)).toEqual(['card-1', 'card-2']);
    expect(new URL(fetch.mock.calls[1][0] as string, 'http://aura.test').searchParams.get('cursor')).toBe('next-cards');
  });

  it('uses the same paged loader for automations', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse([{ id: 'automation-1' }], 'next-automations'))
      .mockResolvedValueOnce(jsonResponse([{ id: 'automation-2' }]));
    vi.stubGlobal('fetch', fetch);

    const automations = await api.fetchAutomations();

    expect(automations.map((automation) => automation.id)).toEqual(['automation-1', 'automation-2']);
    expect(new URL(fetch.mock.calls[1][0] as string, 'http://aura.test').searchParams.get('cursor')).toBe('next-automations');
  });

  it('returns one automation run-history page and its next cursor', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([
      { event_id: 'event-1', run_id: 'run-1', queued_at: '2026-10-02T09:00:00Z', status: 'completed', retry_count: 0 },
    ], 'next-runs'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchAutomationRuns('automation/one', 10, 'prior-cursor');

    expect(page.runs.map((run) => run.event_id)).toEqual(['event-1']);
    expect(page.nextCursor).toBe('next-runs');
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/automations/automation%2Fone/runs');
    expect(url.searchParams.get('page_size')).toBe('10');
    expect(url.searchParams.get('cursor')).toBe('prior-cursor');
  });
});
