import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { StudyView } from '../components/global/StudyView';

describe('Study session controls', () => {
  it('starts a session through the supplied action and offers completion for persisted active sessions', () => {
    const onStartSession = vi.fn();
    const onCompleteSession = vi.fn();
    const { rerender } = render(
      <StudyView
        libraryItems={[]}
        sessions={[]}
        onOpenItem={vi.fn()}
        onStartSession={onStartSession}
        onCompleteSession={onCompleteSession}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: 'Start short session' })[1]);
    expect(onStartSession).toHaveBeenCalledWith('german');

    rerender(
      <StudyView
        libraryItems={[]}
        sessions={[{
          id: 'study-session-1', track_id: 'german', track_title: 'German A1',
          status: 'in_progress', started_at: '2026-10-02T00:00:00Z',
        }]}
        onOpenItem={vi.fn()}
        onStartSession={onStartSession}
        onCompleteSession={onCompleteSession}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Mark session complete' }));
    expect(onCompleteSession).toHaveBeenCalledWith('study-session-1');
  });
});
