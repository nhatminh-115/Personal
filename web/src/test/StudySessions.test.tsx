import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StudyView } from '../components/global/StudyView';
import type { LibraryItem } from '../data/workspaceData';

const studyMaterial: LibraryItem = {
  id: 'library-study-1', name: 'Language notes.pdf', kind: 'PDF', collection: 'Study',
  detail: 'Personal notes for vocabulary practice.', updated: 'today', tags: ['language'],
  source: 'imported', syncState: 'synced',
};

describe('Study sessions use shared Library materials', () => {
  it('starts and completes a durable session linked to a personal Library reference', () => {
    const onStartSession = vi.fn();
    const onCompleteSession = vi.fn();
    const props = {
      libraryItems: [studyMaterial],
      onOpenItem: vi.fn(),
      onBrowseLibrary: vi.fn(),
      onStartSession,
      sessions: [],
      onCompleteSession,
    };
    const { rerender } = render(<StudyView {...props} />);

    expect(screen.getByText('Workspace reference')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start short session' }));
    expect(onStartSession).toHaveBeenCalledWith(studyMaterial);

    rerender(<StudyView {...props} sessions={[{
      id: 'study-session-1', track_id: studyMaterial.id, track_title: studyMaterial.name,
      material_id: studyMaterial.id, status: 'in_progress', started_at: '2026-10-02T00:00:00Z',
    }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    expect(onCompleteSession).toHaveBeenCalledWith('study-session-1');
  });

  it('does not start workspace sessions from bundled preview materials', () => {
    const preview: LibraryItem = {
      ...studyMaterial, id: 'bundled-study-preview', name: 'Bundled example', source: 'bundled', syncState: undefined,
    };
    render(<StudyView
      libraryItems={[preview]}
      sessions={[]}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
    />);

    expect(screen.getByText('Preview reference')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start short session' })).not.toBeInTheDocument();
    expect(screen.getByText(/Save a personal Study or Research reference/i)).toBeInTheDocument();
  });

  it('preserves previous sessions whose material is no longer in the Library', () => {
    render(<StudyView
      libraryItems={[]}
      sessions={[{
        id: 'legacy-session', track_id: 'german', track_title: 'German A1',
        status: 'in_progress', started_at: '2026-10-02T00:00:00Z',
      }]}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
    />);

    expect(screen.getByText('German A1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
  });
  it('scrolls to the exact session opened from workspace search', async () => {
    const sessionId = 'study-session-search-target';
    render(<StudyView
      libraryItems={[studyMaterial]}
      sessions={[{
        id: sessionId, track_id: studyMaterial.id, track_title: studyMaterial.name,
        material_id: studyMaterial.id, status: 'completed', started_at: '2026-10-02T00:00:00Z',
      }]}
      focusSessionId={sessionId}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
    />);

    const row = document.getElementById(`study-session-${sessionId}`);
    expect(row).toHaveTextContent('Completed');
    expect(row).toHaveClass('is-focused');
    await waitFor(() => expect(row?.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' }));
  });


  it('focuses a searched legacy session whose Library material is no longer present', async () => {
    const sessionId = 'legacy-search-target';
    render(<StudyView
      libraryItems={[]}
      sessions={[{
        id: sessionId, track_id: 'removed-material', track_title: 'Archived notes',
        status: 'completed', started_at: '2026-10-02T00:00:00Z',
      }]}
      focusSessionId={sessionId}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
    />);

    const row = document.getElementById(`study-session-${sessionId}`);
    expect(row).toHaveTextContent('Archived notes');
    expect(row).toHaveClass('is-focused');
    await waitFor(() => expect(row?.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' }));
  });

});
