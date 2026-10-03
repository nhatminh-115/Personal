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
        edges_next_cursor: 'edge-next',
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
        edges_next_cursor: null,
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
    expect(secondUrl.searchParams.get('edge_cursor')).toBe('edge-next');
    expect(secondUrl.searchParams.get('objects_exhausted')).toBeNull();
    expect(secondUrl.searchParams.get('edges_exhausted')).toBeNull();
    expect(secondUrl.searchParams.get('include_project_state')).toBe('false');
    expect(secondUrl.searchParams.get('execution_cursor')).toBe('execution-start');
  });

  it('fetches one newest-first workspace object page without edges or project state', async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({
      project_name: 'Project Name',
      objects: [{ id: 'newest-object' }],
      edges: [],
      layout: { project_name: 'Project Name', layout: {}, revision: 0 },
      objects_next_cursor: 'older-cursor',
      edges_next_cursor: null,
      execution_traces: [],
      execution_history_truncated: false,
      execution_next_cursor: null,
    }));
    vi.stubGlobal('fetch', fetch);

    await expect(api.fetchWorkspaceObjectPage('Project Name')).resolves.toEqual({
      objects: [{ id: 'newest-object' }], nextCursor: 'older-cursor',
    });
    const url = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(url.searchParams.get('object_page_size')).toBe('50');
    expect(url.searchParams.get('newest_first')).toBe('true');
    expect(url.searchParams.get('edges_exhausted')).toBe('true');
    expect(url.searchParams.get('include_project_state')).toBe('false');
  });

  it('loads one Board graph page and fetches layout state separately for later pages', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        project_name: 'Project Name', objects: [{ id: 'newest' }], edges: [{ id: 'edge-1' }],
        layout: { project_name: 'Project Name', layout: { positions: { newest: { x: 1, y: 2 } } }, revision: 3 },
        objects_next_cursor: 'older-object', edges_next_cursor: 'older-edge', execution_traces: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        project_name: 'Project Name', objects: [{ id: 'older' }], edges: [{ id: 'edge-2' }],
        layout: { project_name: 'Project Name', layout: {}, revision: 0 }, objects_next_cursor: null,
        edges_next_cursor: null, execution_traces: [],
      }))
      .mockResolvedValueOnce(jsonResponse({
        project_name: 'Project Name', layout: { positions: { older: { x: 8, y: 9 } } }, revision: 3,
      }));
    vi.stubGlobal('fetch', fetch);

    const first = await api.fetchWorkspaceGraphPage('Project Name');
    const firstUrl = new URL(fetch.mock.calls[0][0] as string, 'http://aura.test');
    expect(firstUrl.searchParams.get('newest_first')).toBe('true');
    expect(firstUrl.searchParams.get('object_page_size')).toBe('50');
    const older = await api.fetchWorkspaceGraphPage('Project Name', { object: first.objects_next_cursor, edge: first.edges_next_cursor });

    expect(first.objects.map((item) => item.id)).toEqual(['newest']);
    expect(older.objects.map((item) => item.id)).toEqual(['older']);
    expect(older.layout.revision).toBe(3);
    expect(older.layout.layout.positions).toEqual({ older: { x: 8, y: 9 } });
    const pageUrl = new URL(fetch.mock.calls[1][0] as string, 'http://aura.test');
    expect(pageUrl.searchParams.get('object_cursor')).toBe('older-object');
    expect(pageUrl.searchParams.get('edge_cursor')).toBe('older-edge');
    expect(pageUrl.searchParams.get('include_project_state')).toBe('false');
    expect(fetch.mock.calls[2][0]).toContain('/v1/workspace/projects/Project%20Name/layout');
  });
});
