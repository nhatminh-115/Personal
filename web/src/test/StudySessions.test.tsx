import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StudyView } from '../components/global/StudyView';
import type { LibraryItem, WorkspaceNote } from '../data/workspaceData';

const studyMaterial: LibraryItem = {
  id: 'library-study-1', name: 'Language notes.pdf', kind: 'PDF', collection: 'Study',
  detail: 'Personal notes for vocabulary practice.', updated: 'today', tags: ['language'],
  source: 'imported', syncState: 'synced',
};

describe('Study sessions use shared Library materials', () => {
  it('creates, reveals, edits, and deletes reusable learning cards', async () => {
    const sessionId = 'study-session-cards';
    const card = {
      id: 'study-card-1', session_id: sessionId, question: 'What is a noun?',
      answer: 'A person, place, or thing.', created_at: '2026-10-02T00:00:00Z',
      updated_at: '2026-10-02T00:00:00Z',
    };
    const onCreateCard = vi.fn().mockResolvedValue(undefined);
    const onUpdateCard = vi.fn().mockResolvedValue(undefined);
    const onDeleteCard = vi.fn().mockResolvedValue(undefined);
    const props = {
      libraryItems: [],
      sessions: [{
        id: sessionId, track_id: 'german', track_title: 'German A1',
        status: 'completed' as const, reflection: '', started_at: '2026-10-02T00:00:00Z',
      }],
      cards: [card],
      onOpenItem: vi.fn(),
      onBrowseLibrary: vi.fn(),
      onStartSession: vi.fn(),
      onCompleteSession: vi.fn(),
      onSaveReflection: vi.fn().mockResolvedValue(undefined),
      onCreateCard,
      onUpdateCard,
      onDeleteCard,
    };
    render(<StudyView {...props} />);

    expect(screen.queryByText('A person, place, or thing.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reveal answer' }));
    expect(screen.getByText('A person, place, or thing.')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByDisplayValue('What is a noun?'), { target: { value: 'Define a noun.' } });
    fireEvent.change(screen.getByDisplayValue('A person, place, or thing.'), { target: { value: 'A naming word.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save card' }));
    await waitFor(() => expect(onUpdateCard).toHaveBeenCalledWith(card.id, sessionId, 'Define a noun.', 'A naming word.'));

    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(onDeleteCard).toHaveBeenCalledWith(card.id, sessionId));
  });

  it('submits a user-authored learning card from the session', async () => {
    const sessionId = 'study-session-new-card';
    const onCreateCard = vi.fn().mockResolvedValue(undefined);
    render(<StudyView
      libraryItems={[]}
      sessions={[{
        id: sessionId, track_id: 'german', track_title: 'German A1',
        status: 'in_progress', reflection: '', started_at: '2026-10-02T00:00:00Z',
      }]}
      cards={[]}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
      onCreateCard={onCreateCard}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
    />);

    fireEvent.change(screen.getByPlaceholderText('What should you remember?'), { target: { value: 'What is a noun?' } });
    fireEvent.change(screen.getByPlaceholderText('Write the answer in your own words…'), { target: { value: 'A naming word.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add learning card' }));
    await waitFor(() => expect(onCreateCard).toHaveBeenCalledWith(sessionId, 'What is a noun?', 'A naming word.'));
  });
  it('starts and completes a durable session linked to a personal Library reference', () => {
    const onStartSession = vi.fn();
    const onCompleteSession = vi.fn();
    const props = {
      libraryItems: [studyMaterial],
      onOpenItem: vi.fn(),
      onBrowseLibrary: vi.fn(),
      onStartSession,
      sessions: [],
      cards: [],
      onCompleteSession,
      onCreateCard: vi.fn().mockResolvedValue(undefined),
      onUpdateCard: vi.fn().mockResolvedValue(undefined),
      onDeleteCard: vi.fn().mockResolvedValue(undefined),
      onSaveReflection: vi.fn().mockResolvedValue(undefined),
    };
    const { rerender } = render(<StudyView {...props} />);

    expect(screen.getByText('Workspace reference')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start short session' }));
    expect(onStartSession).toHaveBeenCalledWith(studyMaterial);

    rerender(<StudyView {...props} sessions={[{
      id: 'study-session-1', track_id: studyMaterial.id, track_title: studyMaterial.name,
      material_id: studyMaterial.id, status: 'in_progress', reflection: '', started_at: '2026-10-02T00:00:00Z',
    }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Mark complete' }));
    expect(onCompleteSession).toHaveBeenCalledWith('study-session-1');
  });

  it('prevents starting a second session while a different material is active', () => {
    const otherMaterial: LibraryItem = {
      ...studyMaterial, id: 'library-study-2', name: 'Grammar guide.pdf',
    };
    render(<StudyView
      libraryItems={[studyMaterial, otherMaterial]}
      sessions={[{
        id: 'active-study-session', track_id: studyMaterial.id, track_title: studyMaterial.name,
        material_id: studyMaterial.id, status: 'in_progress', reflection: '', started_at: '2026-10-02T00:00:00Z',
      }]}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(screen.queryByRole('button', { name: 'Start short session' })).not.toBeInTheDocument();
    expect(screen.getByText(/Finish “Language notes.pdf” before starting another Study session/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Mark complete' })).toBeInTheDocument();
  });

  it('does not start workspace sessions from bundled preview materials', () => {
    const preview: LibraryItem = {
      ...studyMaterial, id: 'bundled-study-preview', name: 'Bundled example', source: 'bundled', syncState: undefined,
    };
    render(<StudyView
      libraryItems={[preview]}
      sessions={[]}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
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
        status: 'in_progress', reflection: '', started_at: '2026-10-02T00:00:00Z',
      }]}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
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
        material_id: studyMaterial.id, status: 'completed', reflection: '', started_at: '2026-10-02T00:00:00Z',
      }]}
      focusSessionId={sessionId}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
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
        status: 'completed', reflection: '', started_at: '2026-10-02T00:00:00Z',
      }]}
      focusSessionId={sessionId}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
    />);

    const row = document.getElementById(`study-session-${sessionId}`);
    expect(row).toHaveTextContent('Archived notes');
    expect(row).toHaveClass('is-focused');
    await waitFor(() => expect(row?.scrollIntoView).toHaveBeenCalledWith({ behavior: 'smooth', block: 'center' }));
  });

  it('starts a durable Study session from a saved Note and preserves its privacy cue', async () => {
    const note: WorkspaceNote = {
      id: 'saved-note-1',
      title: 'Local study note',
      body: 'Keep this material on the device.',
      updated: 'today',
      tags: ['study'],
      projectIds: ['aura'],
      privacyPolicy: 'local_only',
      source: 'live',
    };
    const onStartNoteSession = vi.fn();
    render(<StudyView
      libraryItems={[]}
      notes={[note]}
      sessions={[]}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onStartNoteSession={onStartNoteSession}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(screen.getByText(/Privacy · local only/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Study this Note' }));
    expect(onStartNoteSession).toHaveBeenCalledWith(note);
    expect(screen.queryByText('No Study sources yet')).not.toBeInTheDocument();
  });

  it('does not start a durable session from an unsaved local Note', () => {
    const note: WorkspaceNote = {
      id: 'local-note-1',
      title: 'Draft note',
      body: 'Not saved yet.',
      updated: 'today',
      tags: [],
      projectIds: [],
      source: 'local',
    };
    const onStartNoteSession = vi.fn();
    render(<StudyView
      libraryItems={[]}
      notes={[note]}
      sessions={[]}
      cards={[]}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onStartNoteSession={onStartNoteSession}
      onCompleteSession={vi.fn()}
      onSaveReflection={vi.fn().mockResolvedValue(undefined)}
    />);

    expect(screen.getByText('Save this Note before starting a durable Study session.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Study this Note' })).not.toBeInTheDocument();
    expect(onStartNoteSession).not.toHaveBeenCalled();
  });

});
