import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { NotesView } from '../components/global/NotesView';
import type { ProjectRecord, WorkspaceNote } from '../data/workspaceData';

describe('NotesView project scope', () => {
  const projects: ProjectRecord[] = [
    { id: 'project-a', name: 'Field Notes', subtitle: 'Research workspace', status: 'active', accent: 'cyan', updated: 'today', meta: '0 chats', thesis: '', next: '', source: 'user' },
    { id: 'project-b', name: 'Other Project', subtitle: 'Separate context', status: 'active', accent: 'purple', updated: 'today', meta: '0 chats', thesis: '', next: '', source: 'user' },
  ];
  const notes: WorkspaceNote[] = [
    { id: 'note-a', title: 'Project note', body: 'Field work', updated: 'today', tags: [], projectIds: ['project-a'], source: 'live' },
    { id: 'note-b', title: 'Personal note', body: 'General idea', updated: 'today', tags: [], projectIds: [], source: 'live' },
    { id: 'note-c', title: 'Other project note', body: 'Separate idea', updated: 'today', tags: [], projectIds: ['project-b'], source: 'live' },
  ];

  it('shows only linked notes and creates new notes linked to the selected project', () => {
    const onNotesChange = vi.fn();
    render(
      <NotesView
        projects={projects}
        notes={notes}
        projectId="project-a"
        onNotesChange={onNotesChange}
        onOpenProject={vi.fn()}
        onShowAllNotes={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Field Notes notes' })).toBeInTheDocument();
    expect(screen.getByText('Project note')).toBeInTheDocument();
    expect(screen.queryByText('Personal note')).not.toBeInTheDocument();
    expect(screen.queryByText('Other project note')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'New note' }));
    expect(screen.getByText('Linked to Field Notes')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Create blank note/ }));

    expect(onNotesChange).toHaveBeenCalledOnce();
    expect(onNotesChange.mock.calls[0][0][0]).toMatchObject({ projectIds: ['project-a'], source: 'local' });
  });
});
