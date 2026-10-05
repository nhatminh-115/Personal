import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StudyView } from '../components/global/StudyView';
import type { StudyCardRecord, StudySessionRecord } from '../types';
import { ApiError } from '../services/api';

describe('StudyView', () => {
  it('offers a confirmed reload after a concurrent reflection save conflict', async () => {
    const session: StudySessionRecord = {
      id: 'study-session-conflict', track_id: 'track-conflict', track_title: 'Concurrent session',
      material_id: null, material_project_name: null, status: 'in_progress', reflection: '',
      started_at: '2026-10-02T00:00:00Z', completed_at: null, revision: 2,
    };
    const onSaveReflection = vi.fn().mockRejectedValue(new ApiError(409, 'stale revision'));
    const onReloadStudyContent = vi.fn().mockResolvedValue(undefined);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<StudyView
      libraryItems={[]}
      sessions={[session]}
      cards={[]}
      onOpenItem={vi.fn()}
      onBrowseLibrary={vi.fn()}
      onStartSession={vi.fn()}
      onCompleteSession={vi.fn()}
      onCreateCard={vi.fn().mockResolvedValue(undefined)}
      onUpdateCard={vi.fn().mockResolvedValue(undefined)}
      onDeleteCard={vi.fn().mockResolvedValue(undefined)}
      onSaveReflection={onSaveReflection}
      onReloadStudyContent={onReloadStudyContent}
    />);

    fireEvent.change(screen.getByLabelText('What did you learn?'), { target: { value: 'Local draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save reflection' }));
    expect(await screen.findByText('This reflection changed elsewhere. Your draft is still here.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load saved version' }));
    await waitFor(() => expect(onReloadStudyContent).toHaveBeenCalledTimes(1));
    expect(confirm).toHaveBeenCalled();
    confirm.mockRestore();
  });

  it('saves an explicit reflection on a durable Study session', async () => {
    const session: StudySessionRecord = {
      id: 'study-session-1',
      track_id: 'track-1',
      track_title: 'A verified research finding',
      material_id: null,
      material_project_name: null,
      status: 'in_progress',
      reflection: '',
      started_at: '2026-10-02T00:00:00Z',
      revision: 1,
      completed_at: null,
    };
    const onSaveReflection = vi.fn().mockResolvedValue(undefined);

    render(
      <StudyView
        libraryItems={[]}
        onOpenItem={vi.fn()}
        onBrowseLibrary={vi.fn()}
        onStartSession={vi.fn()}
        sessions={[session]}
        cards={[]}
        onCompleteSession={vi.fn()}
        onCreateCard={vi.fn().mockResolvedValue(undefined)}
        onUpdateCard={vi.fn().mockResolvedValue(undefined)}
        onDeleteCard={vi.fn().mockResolvedValue(undefined)}
        onSaveReflection={onSaveReflection}
      />,
    );

    fireEvent.change(screen.getByLabelText('What did you learn?'), {
      target: { value: 'A verified claim is distinct from its evidence.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save reflection' }));

    await waitFor(() => expect(onSaveReflection).toHaveBeenCalledWith(
      'study-session-1',
      'A verified claim is distinct from its evidence.',
      session.revision,
    ));
  });

  it('opens the source research claim from its Study session', () => {
    const session: StudySessionRecord = {
      id: 'study-session-research',
      track_id: 'claim-1',
      track_title: 'A verified research claim',
      material_id: 'claim-object-1',
      material_project_name: 'Research project',
      status: 'completed',
      reflection: '',
      started_at: '2026-10-02T00:00:00Z',
      revision: 1,
      completed_at: '2026-10-02T01:00:00Z',
    };
    const onOpenResearchFinding = vi.fn();

    render(
      <StudyView
        libraryItems={[]}
        onOpenItem={vi.fn()}
        onBrowseLibrary={vi.fn()}
        onStartSession={vi.fn()}
        sessions={[session]}
        cards={[]}
        onCompleteSession={vi.fn()}
        onCreateCard={vi.fn().mockResolvedValue(undefined)}
        onUpdateCard={vi.fn().mockResolvedValue(undefined)}
        onDeleteCard={vi.fn().mockResolvedValue(undefined)}
        onSaveReflection={vi.fn().mockResolvedValue(undefined)}
        onOpenResearchFinding={onOpenResearchFinding}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Open Research finding' }));
    expect(onOpenResearchFinding).toHaveBeenCalledWith('claim-object-1', 'Research project');
  });

  it('persists a review rating and displays the next review date', async () => {
    const session: StudySessionRecord = {
      id: 'study-session-cards', track_id: 'track-cards', track_title: 'Learning cards',
      material_id: null, material_project_name: null, status: 'completed', reflection: '',
      started_at: '2026-10-02T00:00:00Z',
      revision: 1, completed_at: '2026-10-02T01:00:00Z',
    };
    const card: StudyCardRecord = {
      id: 'card-1', session_id: session.id, question: 'What is provenance?', answer: 'The recorded origin of information.',
      created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z', review_count: 0,
      revision: 1,
    };
    const onReviewCard = vi.fn().mockResolvedValue({
      ...card, review_count: 1,
      revision: 1, reviewed_at: '2026-10-03T00:00:00Z', next_review_at: '2026-10-06T00:00:00Z',
    });

    render(
      <StudyView
        libraryItems={[]}
        onOpenItem={vi.fn()}
        onBrowseLibrary={vi.fn()}
        onStartSession={vi.fn()}
        sessions={[session]}
        cards={[card]}
        onCompleteSession={vi.fn()}
        onCreateCard={vi.fn().mockResolvedValue(undefined)}
        onUpdateCard={vi.fn().mockResolvedValue(undefined)}
        onReviewCard={onReviewCard}
        onDeleteCard={vi.fn().mockResolvedValue(undefined)}
        onSaveReflection={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Reveal answer' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remembered · 3 days' }));

    await waitFor(() => expect(onReviewCard).toHaveBeenCalledWith('card-1', 'study-session-cards', 'remembered', card.revision));
    expect(await screen.findByText(/1 review · next/)).toBeInTheDocument();
  });

  it('shows unreviewed cards in the global review queue', () => {
    const card: StudyCardRecord = {
      id: 'queue-card', session_id: 'older-session', question: 'What is a keyset cursor?', answer: 'A stable position in a sorted collection.',
      created_at: '2026-10-02T00:00:00Z', updated_at: '2026-10-02T00:00:00Z', review_count: 0,
      revision: 1,
    };

    render(
      <StudyView
        libraryItems={[]}
        onOpenItem={vi.fn()}
        onBrowseLibrary={vi.fn()}
        onStartSession={vi.fn()}
        sessions={[]}
        cards={[]}
        dueCards={[card]}
        onCompleteSession={vi.fn()}
        onCreateCard={vi.fn().mockResolvedValue(undefined)}
        onUpdateCard={vi.fn().mockResolvedValue(undefined)}
        onReviewCard={vi.fn().mockResolvedValue(card)}
        onDeleteCard={vi.fn().mockResolvedValue(undefined)}
        onSaveReflection={vi.fn().mockResolvedValue(undefined)}
      />,
    );

    expect(screen.getByRole('region', { name: 'Cards due for review' })).toHaveTextContent('What is a keyset cursor?');
    expect(screen.getByText('Earlier Study session')).toBeInTheDocument();
  });
});
