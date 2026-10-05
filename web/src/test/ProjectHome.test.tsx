import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ProjectHome } from '../components/home/ProjectHome';
import type { ProjectRecord } from '../data/workspaceData';

describe('ProjectHome', () => {
  it('opens the real Notes workspace from the project summary', () => {
    const project: ProjectRecord = {
      id: 'project-1', name: 'Field Notes', subtitle: 'Research workspace', status: 'active',
      accent: 'cyan', updated: 'today', meta: '0 chats', thesis: '', next: '', source: 'user',
    };
    const onOpenNotes = vi.fn();
    const onMockObject = vi.fn();

    render(
      <ProjectHome
        projects={[project]}
        projectId={project.id}
        chatCount={0}
        fileCount={0}
        noteCount={2}
        onBack={vi.fn()}
        onOpenNode={vi.fn()}
        onOpenChats={vi.fn()}
        onOpenFiles={vi.fn()}
        onOpenNotes={onOpenNotes}
        onMockObject={onMockObject}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Notes 2 Linked workspace notes/i }));

    expect(onOpenNotes).toHaveBeenCalledOnce();
    expect(onMockObject).not.toHaveBeenCalled();
  });
});
