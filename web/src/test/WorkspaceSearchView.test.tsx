import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { WorkspaceSearchView } from '../components/global/WorkspaceSearchView';
import type { WorkspaceSearchResult } from '../types';

describe('WorkspaceSearchView', () => {
  it('shows indexed connected-folder metadata and opens only on explicit action', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'external:folder-1:papers/study.pdf',
      object_type: 'file_reference',
      title: 'study.pdf',
      excerpt: 'Research / papers/study.pdf',
      project_name: null,
      created_by: 'external',
      updated_at: '2026-09-30T12:00:00Z',
      source: 'connected-folder',
      connection_id: 'folder-1',
      connection_name: 'Research',
      relative_path: 'papers/study.pdf',
      size: 1200,
      mime_type: 'application/pdf',
    };
    const onOpenFile = vi.fn();
    render(<WorkspaceSearchView query="study" results={[result]} loading={false} error={null} onOpenProject={() => {}} onOpenFile={onOpenFile} />);

    expect(screen.getByText('Research / papers/study.pdf')).toBeInTheDocument();
    expect(screen.getByText('Connected file')).toBeInTheDocument();
    expect(screen.queryByText(/File contents stay/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open file' }));
    expect(onOpenFile).toHaveBeenCalledWith(result);
  });

  it('opens a persisted project object in its Board', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'bridge-object-9', object_type: 'context_bridge', title: 'Experiment handoff',
      excerpt: 'Carry forward only verified outcomes.', project_name: 'AURA Project', created_by: 'user',
      updated_at: '2026-10-01T12:00:00Z',
    };
    const onOpenProject = vi.fn();
    render(<WorkspaceSearchView query="experiment" results={[result]} loading={false} error={null} onOpenProject={onOpenProject} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Board' }));
    expect(onOpenProject).toHaveBeenCalledWith('AURA Project', 'bridge-object-9');
  });
});

