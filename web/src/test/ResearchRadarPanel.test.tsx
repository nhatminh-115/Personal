import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { ProjectRecord } from '../data/workspaceData';
import { api } from '../services/api';
import type { WorkspaceGraph, WorkspaceObject } from '../types';
import { LibraryView } from '../components/global/LibraryView';
import { ResearchRadarPanel } from '../components/global/ResearchRadarPanel';

const savedProjects: ProjectRecord[] = [
  {
    id: 'research-project', name: 'Research project', subtitle: '', status: 'active', accent: 'cyan',
    updated: '', meta: '', thesis: '', next: '', source: 'user',
  },
  {
    id: 'demo-project', name: 'Demo project', subtitle: '', status: 'active', accent: 'purple',
    updated: '', meta: '', thesis: '', next: '', source: 'demo',
  },
];

function researchObject(id: string, object_type: string, title: string, metadata_json: Record<string, unknown> = {}, content = ''): WorkspaceObject {
  return {
    id, project_name: 'Research project', object_type, created_by: 'research', title, content,
    metadata_json, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    revision: 1,
  };
}

function graph(objects: WorkspaceObject[], edges: WorkspaceGraph['edges'] = [], cursors: { objects?: string | null; edges?: string | null } = {}): WorkspaceGraph {
  return {
    project_name: 'Research project', objects, edges,
    layout: { project_name: 'Research project', layout: {}, revision: 0 },
    objects_next_cursor: cursors.objects ?? null,
    edges_next_cursor: cursors.edges ?? null,
  };
}

describe('Research Radar', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('requests only research artifacts and provenance edges from the graph API', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(graph([])), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    await api.fetchWorkspaceResearchPage('Research project');

    const requestedUrl = new URL(fetchMock.mock.calls[0][0] as string, 'http://localhost');
    expect(requestedUrl.pathname).toBe('/v1/workspace/projects/Research%20project/graph');
    expect(requestedUrl.searchParams.getAll('object_types')).toEqual(['research_source', 'research_evidence', 'research_claim']);
    expect(requestedUrl.searchParams.getAll('edge_families')).toEqual(['provenance']);
    expect(requestedUrl.searchParams.get('include_project_state')).toBe('false');
  });

  it('shows source, evidence, verified claim, and their saved provenance links', async () => {
    const source = researchObject('source-1', 'research_source', 'A durable workspace study', {
      status: 'inspected', year: 2025, url: 'https://example.org/paper',
    }, 'A short paper abstract.');
    const evidence = researchObject('evidence-1', 'research_evidence', 'Evidence · A durable workspace study', {}, 'A measured result from section 3.');
    const claim = researchObject('claim-1', 'research_claim', 'source_supported_fact · A measured finding', {
      verification_status: 'verified',
    }, 'Claim type: source_supported_fact\nVerification: verified\n\nA measured finding.');
    vi.spyOn(api, 'fetchWorkspaceResearchPage').mockResolvedValue(graph([source, evidence, claim], [
      { id: 'edge-1', project_name: 'Research project', source_object_id: 'source-1', target_object_id: 'evidence-1', relation_type: 'contains_evidence', edge_family: 'provenance', created_by: 'research', metadata_json: {}, created_at: '2026-10-01T00:00:00Z' },
      { id: 'edge-2', project_name: 'Research project', source_object_id: 'evidence-1', target_object_id: 'claim-1', relation_type: 'supports_claim', edge_family: 'provenance', created_by: 'research', metadata_json: {}, created_at: '2026-10-01T00:00:00Z' },
    ]));
    const onStudy = vi.fn();
    const onOpenObject = vi.fn();

    render(<ResearchRadarPanel projects={savedProjects} onStudyResearchClaim={onStudy} onOpenProjectObject={onOpenObject} />);

    expect(await screen.findByText('A durable workspace study')).toBeInTheDocument();
    expect(screen.getByText('1 sources')).toBeInTheDocument();
    expect(screen.getByText('1 evidence')).toBeInTheDocument();
    expect(screen.getByText('1 claims')).toBeInTheDocument();
    expect(screen.getByText('verified')).toBeInTheDocument();
    expect(screen.getByText(/contains evidence · Evidence · A durable workspace study/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open source' })).toHaveAttribute('href', 'https://example.org/paper');
    expect(api.fetchWorkspaceResearchPage).toHaveBeenCalledWith('Research project');
    fireEvent.click(screen.getByRole('button', { name: 'Study this finding' }));
    expect(onStudy).toHaveBeenCalledWith('claim-1', 'source_supported_fact · A measured finding', 'Research project');
    fireEvent.click(screen.getAllByRole('button', { name: 'Open in Board' })[1]);
    expect(onOpenObject).toHaveBeenCalledWith('evidence-1', 'Research project');
  });

  it('loads older graph pages on demand and excludes untrusted URL schemes', async () => {
    const first = researchObject('source-1', 'research_source', 'First source', { status: 'selected', url: 'javascript:alert(1)' });
    const older = researchObject('claim-2', 'research_claim', 'Older claim', { verification_status: 'qualified' }, 'A qualified result.');
    const fetchPage = vi.spyOn(api, 'fetchWorkspaceResearchPage')
      .mockResolvedValueOnce(graph([first], [], { objects: 'older-objects' }))
      .mockResolvedValueOnce(graph([older], [], {}));

    render(<ResearchRadarPanel projects={savedProjects} />);
    expect(await screen.findByText('First source')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open source' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load older research artifacts' }));

    expect(await screen.findByText('Older claim')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Study this finding' })).not.toBeInTheDocument();
    await waitFor(() => expect(fetchPage).toHaveBeenLastCalledWith('Research project', { object: 'older-objects', edge: null }));
  });

  it('keeps the Radar inside Library and reveals it from the Research collection', async () => {
    vi.spyOn(api, 'fetchWorkspaceGraphPage').mockResolvedValue(graph([]));
    render(<LibraryView
      projects={savedProjects}
      items={[]}
      connections={[]}
      directoryPickerSupported
      onOpenItem={vi.fn()}
      onImportFiles={vi.fn()}
      onToggleProjectLink={vi.fn()}
      onRemoveItem={vi.fn()}
      onConnectFolder={vi.fn()}
      onOpenConnection={vi.fn()}
      onDisconnectConnection={vi.fn()}
    />);

    expect(screen.queryByRole('button', { name: 'Research Radar' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Research' }));
    fireEvent.click(screen.getByRole('button', { name: 'Research Radar' }));

    expect(await screen.findByRole('region', { name: 'Research Radar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Research Radar' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('No Library references here yet.')).toBeInTheDocument();
  });

  it('offers pagination when the newest project page has no research objects', async () => {
    const fetchPage = vi.spyOn(api, 'fetchWorkspaceResearchPage')
      .mockResolvedValueOnce(graph([], [], { objects: 'older-objects' }))
      .mockResolvedValueOnce(graph([researchObject('claim-1', 'research_claim', 'Older verified claim', { verification_status: 'verified' })]));

    render(<ResearchRadarPanel projects={savedProjects} />);
    expect(await screen.findByText(/No Research artifacts on this page/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load older research artifacts' }));
    expect(await screen.findByText('Older verified claim')).toBeInTheDocument();
    expect(fetchPage).toHaveBeenLastCalledWith('Research project', { object: 'older-objects', edge: null });
    expect(fetchPage).not.toHaveBeenCalledWith('Demo project');
  });
});
