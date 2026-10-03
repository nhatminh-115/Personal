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

  it('fetches project-scoped session pages and tolerates responses without headers', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [{ id: 'session-1' }] });
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchSessions('Research Project');

    expect(page).toEqual({ items: [{ id: 'session-1' }], nextCursor: null });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/sessions');
    expect(url.searchParams.get('project_name')).toBe('Research Project');
    expect(url.searchParams.get('page_size')).toBe('25');
  });

  it('loads persisted execution and approval state for a session', async () => {
    const state = { session_id: 'session/one', run_id: 'run-1', run_status: 'waiting_for_approval', approval: null };
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => state });
    vi.stubGlobal('fetch', fetch);

    await expect(api.fetchSessionExecutionState('session/one')).resolves.toEqual(state);
    expect(fetch).toHaveBeenCalledWith('/v1/sessions/session%2Fone/state');
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

  it('loads one notes page with a bounded page size and optional cursor', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'note-51' }], 'next-notes'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchWorkspaceNotesPage('prior-notes');

    expect(page).toEqual({ items: [{ id: 'note-51' }], nextCursor: 'next-notes' });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/workspace/notes');
    expect(url.searchParams.get('page_size')).toBe('50');
    expect(url.searchParams.get('cursor')).toBe('prior-notes');
  });

  it('loads one Library reference page with a bounded page size and optional cursor', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'library-51' }], 'next-library'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchWorkspaceLibraryPage('prior-library');

    expect(page).toEqual({ items: [{ id: 'library-51' }], nextCursor: 'next-library' });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/workspace/library');
    expect(url.searchParams.get('page_size')).toBe('50');
    expect(url.searchParams.get('cursor')).toBe('prior-library');
  });

  it('returns one Study sessions page and its cursor for on-demand loading', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'session-101' }], 'next-sessions'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchStudySessionsPage('prior-sessions');

    expect(page).toEqual({ items: [{ id: 'session-101' }], nextCursor: 'next-sessions' });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/study/sessions');
    expect(url.searchParams.get('page_size')).toBe('100');
    expect(url.searchParams.get('cursor')).toBe('prior-sessions');
  });

  it('returns one Study cards page and its cursor for on-demand loading', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'card-101' }], 'next-cards'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchStudyCardsPage('prior-cards');

    expect(page).toEqual({ items: [{ id: 'card-101' }], nextCursor: 'next-cards' });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/study/cards');
    expect(url.searchParams.get('page_size')).toBe('100');
    expect(url.searchParams.get('cursor')).toBe('prior-cards');
  });

  it('loads one bounded Study review queue page and its cursor', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'due-card-51' }], 'next-due-cards'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchStudyReviewQueuePage('prior-due-cards');

    expect(page).toEqual({ items: [{ id: 'due-card-51' }], nextCursor: 'next-due-cards' });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/study/review-queue');
    expect(url.searchParams.get('page_size')).toBe('50');
    expect(url.searchParams.get('cursor')).toBe('prior-due-cards');
  });

  it('returns one automation page and its cursor for on-demand loading', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'automation-1' }], 'next-automations'));
    vi.stubGlobal('fetch', fetch);

    const page = await api.fetchAutomations();

    expect(page).toEqual({ automations: [{ id: 'automation-1' }], nextCursor: 'next-automations' });
    expect(fetch).toHaveBeenCalledTimes(1);
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/automations');
    expect(url.searchParams.get('page_size')).toBe('50');
  });

  it('batches automation status refreshes without fetching the full collection', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ id: 'automation/one' }]));
    vi.stubGlobal('fetch', fetch);

    await expect(api.fetchAutomationStatuses(['automation/one', 'automation-two'])).resolves.toEqual([{ id: 'automation/one' }]);
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/automations/status');
    expect(url.searchParams.getAll('automation_ids')).toEqual(['automation/one', 'automation-two']);
  });

  it('fetches automation aggregate counts', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ total: 8, enabled: 6 }));
    vi.stubGlobal('fetch', fetch);

    await expect(api.fetchAutomationSummary()).resolves.toEqual({ total: 8, enabled: 6 });
    expect(new URL(fetch.mock.calls[0][0] as string, 'http://aura.test').pathname).toBe('/v1/automations/summary');
  });

  it('updates a saved automation without changing its scope', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ id: 'automation/one', name: 'Updated' }));
    vi.stubGlobal('fetch', fetch);

    await api.updateAutomation('automation/one', {
      name: 'Updated', description: 'New description', instruction: 'New instruction.', interval_seconds: 7200,
    });

    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, 'http://aura.test').pathname).toBe('/v1/automations/automation%2Fone');
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(String(init.body))).toEqual({
      name: 'Updated', description: 'New description', instruction: 'New instruction.', interval_seconds: 7200,
    });
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

  it('fetches canonical workspace collection counts for the active project', async () => {
    const summary = {
      note_count: 42, library_count: 18, linked_library_count: 9,
      project_name: 'AURA', project_note_count: 3, project_library_count: 5,
    };
    const fetch = vi.fn().mockResolvedValue(jsonResponse(summary));
    vi.stubGlobal('fetch', fetch);

    await expect(api.fetchWorkspaceSummary('AURA')).resolves.toEqual(summary);
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.pathname).toBe('/v1/workspace/summary');
    expect(url.searchParams.get('project_name')).toBe('AURA');
  });
});
