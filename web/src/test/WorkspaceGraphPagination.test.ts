import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../services/api';

function jsonResponse(body: unknown): Response {
  return { ok: true, json: async () => body } as Response;
}

describe('workspace graph API pagination', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('loads every object page while retaining project state from the first page', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        project_name: 'Project Name',
        objects: [{ id: 'object-1' }],
        edges: [{ id: 'edge-1' }],
        layout: { project_name: 'Project Name', layout: { revision: 'first-page' }, revision: 7 },
        execution_traces: [{ run_id: 'run-1' }],
        execution_history_truncated: true,
        execution_next_cursor: 'execution-next',
        objects_next_cursor: 'object-next',
      }))
      .mockResolvedValueOnce(jsonResponse({
        project_name: 'Project Name',
        objects: [{ id: 'object-2' }],
        edges: [{ id: 'edge-2' }],
        layout: { project_name: 'Project Name', layout: {}, revision: 0 },
        execution_traces: [],
        execution_history_truncated: false,
        execution_next_cursor: null,
        objects_next_cursor: null,
      }));
    vi.stubGlobal('fetch', fetch);

    const graph = await api.fetchWorkspaceGraph('Project Name', 'execution-start');

    expect(graph.objects.map((item) => item.id)).toEqual(['object-1', 'object-2']);
    expect(graph.edges.map((item) => item.id)).toEqual(['edge-1', 'edge-2']);
    expect(graph.layout.revision).toBe(7);
    expect(graph.execution_traces).toEqual([{ run_id: 'run-1' }]);
    expect(graph.objects_next_cursor).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(2);

    const firstUrl = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    const secondUrl = new URL(fetch.mock.calls[1][0] as string, 'http://aura.test');
    expect(firstUrl.pathname).toBe('/v1/workspace/projects/Project%20Name/graph');
    expect(firstUrl.searchParams.get('execution_cursor')).toBe('execution-start');
    expect(secondUrl.searchParams.get('object_cursor')).toBe('object-next');
    expect(secondUrl.searchParams.get('include_project_state')).toBe('false');
    expect(secondUrl.searchParams.get('execution_cursor')).toBe('execution-start');
  });
});
