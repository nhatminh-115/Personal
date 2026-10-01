import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { LibraryItem } from '../data/workspaceData';
import type { StudySessionRecord } from '../types';
import { StudyView } from '../components/global/StudyView';

describe('Study focus sessions', () => {
  it('shows a resumed durable timer and completes that session', () => {
    const active: StudySessionRecord = {
      id: 'focus-1', track_id: 'toeic', status: 'active',
      started_at: new Date(Date.now() - 65_000).toISOString(), completed_at: null, duration_seconds: null,
    };
    const onCompleteSession = vi.fn().mockResolvedValue(undefined);

    render(
      <StudyView
        libraryItems={[] as LibraryItem[]}
        sessions={[active]}
        onOpenItem={() => undefined}
        onStartSession={vi.fn().mockResolvedValue(undefined)}
        onCompleteSession={onCompleteSession}
      />,
    );

    const finish = screen.getByRole('button', { name: /Finish session · 01:05/ });
    fireEvent.click(finish);
    expect(onCompleteSession).toHaveBeenCalledWith('focus-1');
    expect(screen.getAllByRole('button', { name: 'Start short session' }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  });
});
