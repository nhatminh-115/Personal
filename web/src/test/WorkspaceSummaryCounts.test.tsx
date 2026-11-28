import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GlobalHome } from '../components/global/GlobalHome';
import type { ChatThreadRecord, ProjectRecord } from '../data/workspaceData';

const project: ProjectRecord = {
  id: 'project-a', name: 'Research', subtitle: 'Research context', status: 'active', accent: 'purple', updated: 'today', meta: '2 conversations', thesis: '', next: '', source: 'user',
};

const thread: ChatThreadRecord = {
  id: 'thread-a', projectId: project.id, title: 'Review the outline', summary: 'A saved live conversation', updated: 'just now', messages: [], source: 'live', sessionId: 'session-a',
};

describe('V16 Home', () => {
  it('starts a project conversation with the submitted prompt', () => {
    const onStartConversation = vi.fn();
    render(<GlobalHome
      projects={[project]}
      conversations={[]}
      defaultProjectId={project.id}
      onStartConversation={onStartConversation}
      onImportContextFiles={vi.fn().mockResolvedValue([])}
      onOpenConversation={vi.fn()}
      onOpenConversations={vi.fn()}
      onOpenProjects={vi.fn()}
    />);

    fireEvent.change(screen.getByRole('textbox', { name: 'Start a conversation' }), { target: { value: 'Help me compare these sources.' } });
    fireEvent.click(screen.getByRole('button', { name: 'Start conversation' }));

    expect(onStartConversation).toHaveBeenCalledWith(project.id, 'Help me compare these sources.', undefined, []);
  });

  it('opens a real recent conversation and exposes the all-conversations route', () => {
    const onOpenConversation = vi.fn();
    const onOpenConversations = vi.fn();
    render(<GlobalHome
      projects={[project]}
      conversations={[{ thread, project }]}
      defaultProjectId={project.id}
      onStartConversation={vi.fn()}
      onImportContextFiles={vi.fn().mockResolvedValue([])}
      onOpenConversation={onOpenConversation}
      onOpenConversations={onOpenConversations}
      onOpenProjects={vi.fn()}
    />);

    fireEvent.click(screen.getByRole('button', { name: /Review the outline/ }));
    fireEvent.click(screen.getByRole('button', { name: /All conversations/ }));

    expect(onOpenConversation).toHaveBeenCalledWith(project.id, thread.id);
    expect(onOpenConversations).toHaveBeenCalledOnce();
  });
});
