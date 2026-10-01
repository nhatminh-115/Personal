import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';

describe('Workspace context chat requests', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends explicit selected object IDs with a live chat turn', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ run_id: 'run-1' }) });
    vi.stubGlobal('fetch', fetchMock);

    await api.sendChat('session-1', 'Use these constraints', 'AURA Project', null, null, ['note-1', 'bridge-1', 'note-1']);

    const payload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(payload.context_object_ids).toEqual(['note-1', 'bridge-1']);
    expect(payload.project_name).toBe('AURA Project');
  });

  it('omits context selection for ordinary chat turns', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ run_id: 'run-2' }) });
    vi.stubGlobal('fetch', fetchMock);

    await api.sendChat('session-2', 'Hello', 'AURA Project');

    const payload = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(payload).not.toHaveProperty('context_object_ids');
  });
});
