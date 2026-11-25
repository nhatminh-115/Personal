import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GlobalHome } from '../components/global/GlobalHome';
import type { ProjectRecord } from '../data/workspaceData';

const project: ProjectRecord = {
  id: 'project-a',
  name: 'Project A',
  subtitle: 'A real project',
  status: 'active',
  accent: 'purple',
  updated: 'today',
  meta: '0 conversations',
  thesis: '',
  next: '',
  source: 'user',
};

describe('GlobalHome', () => {
  it('preserves the selected task mode and imported local context for the first chat turn', async () => {
    const onStartConversation = vi.fn();
    const onImportContextFiles = vi.fn().mockResolvedValue([{ id: 'library-file-1', name: 'outline.md' }]);
    const { container } = render(
      <GlobalHome
        projects={[project]}
        conversations={[]}
        defaultProjectId={project.id}
        onStartConversation={onStartConversation}
        onImportContextFiles={onImportContextFiles}
        onOpenConversation={vi.fn()}
        onOpenConversations={vi.fn()}
        onOpenProjects={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByRole('textbox', { name: 'Start a conversation' }), { target: { value: 'Review the outline' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Conversation mode' }), { target: { value: 'research' } });

    const file = new File(['research notes'], 'outline.md', { type: 'text/markdown' });
    const input = container.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });
    await screen.findByText('outline.md');

    fireEvent.click(screen.getByRole('button', { name: /Start conversation/ }));
    await waitFor(() => expect(onStartConversation).toHaveBeenCalledWith(project.id, 'Review the outline', 'research', ['library-file-1']));
    expect(onImportContextFiles).toHaveBeenCalledWith([file], project.id);
  });

  it('uses Enter to submit the prompt while Shift+Enter remains available for a new line', () => {
    const onStartConversation = vi.fn();
    render(
      <GlobalHome
        projects={[project]}
        conversations={[]}
        defaultProjectId={project.id}
        onStartConversation={onStartConversation}
        onImportContextFiles={vi.fn().mockResolvedValue([])}
        onOpenConversation={vi.fn()}
        onOpenConversations={vi.fn()}
        onOpenProjects={vi.fn()}
      />,
    );

    const prompt = screen.getByRole('textbox', { name: 'Start a conversation' });
    fireEvent.change(prompt, { target: { value: 'A concise prompt' } });
    fireEvent.keyDown(prompt, { key: 'Enter', code: 'Enter', charCode: 13, shiftKey: false });
    expect(onStartConversation).toHaveBeenCalledWith(project.id, 'A concise prompt', undefined, []);
  });
});
