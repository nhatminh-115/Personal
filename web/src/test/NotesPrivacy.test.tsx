import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NotesView } from '../components/global/NotesView';

describe('Global Notes privacy controls', () => {
  it('sets and clears a saved privacy classification', () => {
    const onNotesChange = vi.fn();
    render(
      <NotesView
        projects={[]}
        notes={[{
          id: 'note-1', title: 'Private note', body: 'Saved locally.', updated: 'today',
          tags: [], projectIds: [], source: 'live',
        }]}
        onNotesChange={onNotesChange}
        onOpenProject={vi.fn()}
      />,
    );

    const privacy = screen.getByRole('combobox', { name: 'Note privacy classification' });
    fireEvent.change(privacy, { target: { value: 'local_only' } });
    expect(onNotesChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: 'note-1', privacyPolicy: 'local_only' }),
    ]);

    fireEvent.change(privacy, { target: { value: '' } });
    expect(onNotesChange).toHaveBeenLastCalledWith([
      expect.objectContaining({ id: 'note-1', privacyPolicy: undefined }),
    ]);
  });

  it('loads another saved-note page and offers retry after a page error', () => {
    const onLoadMoreNotes = vi.fn();
    const props = {
      projects: [],
      notes: [{ id: 'note-1', title: 'First note', body: 'Saved locally.', updated: 'today', tags: [], projectIds: [], source: 'live' as const }],
      onNotesChange: vi.fn(),
      onOpenProject: vi.fn(),
      hasMoreNotes: true,
      onLoadMoreNotes,
    };
    const { rerender } = render(<NotesView {...props} />);

    fireEvent.click(screen.getByRole('button', { name: 'Load more notes' }));
    expect(onLoadMoreNotes).toHaveBeenCalledTimes(1);

    rerender(<NotesView {...props} loadingMoreNotes notesLoadError="Temporary network failure" />);
    expect(screen.getByText(/Could not load notes: Temporary network failure/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onLoadMoreNotes).toHaveBeenCalledTimes(2);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeDisabled();
  });
});
