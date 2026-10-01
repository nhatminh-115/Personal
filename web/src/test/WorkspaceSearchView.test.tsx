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
    render(<WorkspaceSearchView query="study" results={[result]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={() => {}} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onOpenFile={onOpenFile} />);

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
    render(<WorkspaceSearchView query="experiment" results={[result]} loading={false} error={null} onOpenProject={onOpenProject} onOpenNote={() => {}} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Board' }));
    expect(onOpenProject).toHaveBeenCalledWith('AURA Project', 'bridge-object-9');
  });

  it('opens a personal note in Notes', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'personal-note-7', object_type: 'manual_note', title: 'Local constraints',
      excerpt: 'Do not upload external files.', project_name: null, created_by: 'user', updated_at: '2026-10-02T12:00:00Z',
    };
    const onOpenNote = vi.fn();
    render(<WorkspaceSearchView query="constraints" results={[result]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={onOpenNote} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open note' }));
    expect(onOpenNote).toHaveBeenCalledWith('personal-note-7');
  });

  it('keeps a project Board note in its project graph', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'board-note-3', object_type: 'manual_note', title: 'Board note',
      excerpt: 'Project-specific finding.', project_name: 'AURA Project', created_by: 'user', updated_at: '2026-10-02T12:00:00Z',
    };
    const onOpenProject = vi.fn();
    const onOpenNote = vi.fn();
    render(<WorkspaceSearchView query="finding" results={[result]} loading={false} error={null} onOpenProject={onOpenProject} onOpenNote={onOpenNote} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Board' }));
    expect(onOpenProject).toHaveBeenCalledWith('AURA Project', 'board-note-3');
    expect(onOpenNote).not.toHaveBeenCalled();
  });

  it('keeps project-scoped file references in their project graph', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'project-file-4', object_type: 'file_reference', title: 'Project attachment',
      excerpt: 'Architecture sketch.', project_name: 'AURA Project', created_by: 'user', updated_at: '2026-10-02T12:00:00Z',
    };
    const onOpenProject = vi.fn();
    const onOpenLibraryItem = vi.fn();
    render(<WorkspaceSearchView query="architecture" results={[result]} loading={false} error={null} onOpenProject={onOpenProject} onOpenNote={() => {}} onOpenLibraryItem={onOpenLibraryItem} onOpenStudySession={() => {}} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Board' }));
    expect(onOpenProject).toHaveBeenCalledWith('AURA Project', 'project-file-4');
    expect(onOpenLibraryItem).not.toHaveBeenCalled();
  });

  it('opens a personal Library reference in its Library list', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'library-item-5', object_type: 'file_reference', title: 'Methods paper',
      excerpt: 'Research · Imported PDF', project_name: null, created_by: 'user', updated_at: '2026-10-02T12:00:00Z',
    };
    const onOpenLibraryItem = vi.fn();
    render(<WorkspaceSearchView query="methods" results={[result]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={() => {}} onOpenLibraryItem={onOpenLibraryItem} onOpenStudySession={() => {}} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Open in Library' }));
    expect(onOpenLibraryItem).toHaveBeenCalledWith('library-item-5');
  });
  it('opens a persisted Study session by its workspace object id', () => {
    const result: WorkspaceSearchResult = {
      object_id: 'study-session-12', object_type: 'study_session', title: 'Language notes session',
      excerpt: 'Completed Study session.', project_name: null, created_by: 'user', updated_at: '2026-10-02T12:00:00Z',
    };
    const onOpenStudySession = vi.fn();
    render(<WorkspaceSearchView query="language" results={[result]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={() => {}} onOpenLibraryItem={() => {}} onOpenStudySession={onOpenStudySession} onOpenFile={() => {}} />);

    expect(screen.getByText('Study session')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open session' }));
    expect(onOpenStudySession).toHaveBeenCalledWith('study-session-12');
  });


  it('offers a Study session only for verified project research claims', () => {
    const verified: WorkspaceSearchResult = {
      object_id: 'verified-claim-1', object_type: 'research_claim', title: 'Verified finding',
      excerpt: 'Supported by cited evidence.', project_name: 'Research Project', created_by: 'research',
      verification_status: 'verified', updated_at: '2026-10-02T12:00:00Z',
    };
    const onStudyResearchClaim = vi.fn();
    const { rerender } = render(<WorkspaceSearchView query="finding" results={[verified]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={() => {}} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onStudyResearchClaim={onStudyResearchClaim} onOpenFile={() => {}} />);

    fireEvent.click(screen.getByRole('button', { name: 'Study verified finding' }));
    expect(onStudyResearchClaim).toHaveBeenCalledWith('verified-claim-1', 'Verified finding', 'Research Project');

    rerender(<WorkspaceSearchView query="finding" results={[{ ...verified, verification_status: 'unsupported' }]} loading={false} error={null} onOpenProject={() => {}} onOpenNote={() => {}} onOpenLibraryItem={() => {}} onOpenStudySession={() => {}} onStudyResearchClaim={onStudyResearchClaim} onOpenFile={() => {}} />);
    expect(screen.queryByRole('button', { name: 'Study verified finding' })).not.toBeInTheDocument();
  });

});

