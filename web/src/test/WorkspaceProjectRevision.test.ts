import { beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';

describe('workspace project archive revisions', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ id: 'project-1', revision: 5, archived_at: '2026-10-05T00:00:00Z' }),
    } as Response);
  });

  it('sends the loaded project revision with archive state changes', async () => {
    await api.setWorkspaceProjectArchived('project-1', true, 4);

    expect(global.fetch).toHaveBeenCalledWith('/v1/workspace/projects/project-1/archive', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ expected_revision: 4 }),
    }));
  });
});
