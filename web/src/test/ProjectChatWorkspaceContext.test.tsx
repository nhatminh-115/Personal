import { fireEvent, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectChatWorkspace } from '../components/chat/ProjectChatWorkspace';
import { api } from '../services/api';

vi.mock('../services/api', () => ({
  api: { fetchWorkspaceGraph: vi.fn() },
}));

vi.mock('../components/chat/ChatPane', () => ({
  ChatPane: (props: {
    onContextPanelOpenChange?: (open: boolean) => void;
    onContextObjectIdsChange?: (objectIds: string[]) => void;
  }) => (
    <div>
      <button onClick={() => props.onContextPanelOpenChange?.(true)}>Open context</button>
      <button onClick={() => props.onContextObjectIdsChange?.(['object-1'])}>Select object</button>
    </div>
  ),
}));

const project = { id: 'project-1', name: 'AURA', title: 'AURA' } as any;
const thread = {
  id: 'thread-1',
  title: 'Live chat',
  summary: '',
  source: 'live',
  sessionId: 'session-1',
  messages: [],
  initialContextObjectIds: [],
} as any;

function renderWorkspace() {
  return render(
    <ProjectChatWorkspace
      project={project}
      threads={[thread]}
      activeThreadId={thread.id}
      libraryItems={[]}
      notes={[]}
      onSelectThread={vi.fn()}
      onNewThread={vi.fn()}
      onUpdateMessages={vi.fn()}
      onContextObjectIdsChange={vi.fn()}
    />,
  );
}

describe('live chat context loading', () => {
  beforeEach(() => vi.clearAllMocks());

  it('loads the project graph when Context opens and does not reload it for selection changes', async () => {
    vi.mocked(api.fetchWorkspaceGraph).mockResolvedValue({
      project_name: 'AURA',
      objects: [{
        id: 'object-1',
        project_name: 'AURA',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Saved note',
        content: 'Note contents',
        metadata_json: {},
        created_at: '2026-10-03T00:00:00Z',
        updated_at: '2026-10-03T00:00:00Z',
      }],
      edges: [],
      layout: { project_name: 'AURA', layout: {}, revision: 0 },
    });

    const view = renderWorkspace();
    expect(api.fetchWorkspaceGraph).not.toHaveBeenCalled();

    fireEvent.click(view.getByRole('button', { name: 'Open context' }));
    await waitFor(() => expect(api.fetchWorkspaceGraph).toHaveBeenCalledTimes(1));

    fireEvent.click(view.getByRole('button', { name: 'Select object' }));
    await waitFor(() => expect(api.fetchWorkspaceGraph).toHaveBeenCalledTimes(1));
  });
});
