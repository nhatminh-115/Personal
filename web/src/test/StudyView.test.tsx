import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StudyView } from '../components/global/StudyView';
import type { StudySessionRecord } from '../types';

describe('StudyView', () => {
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
        onCompleteSession={vi.fn()}
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
    ));
  });
});
