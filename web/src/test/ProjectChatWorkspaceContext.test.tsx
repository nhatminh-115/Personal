import { fireEvent, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectChatWorkspace } from '../components/chat/ProjectChatWorkspace';
import { api } from '../services/api';
import type { AIContextItem } from '../types';

vi.mock('../services/api', () => ({
  api: { fetchWorkspaceObjectPage: vi.fn() },
}));

vi.mock('../components/chat/ChatPane', () => ({
  ChatPane: (props: {
    contextItems?: AIContextItem[];
    onContextPanelOpenChange?: (open: boolean) => void;
    onContextObjectIdsChange?: (objectIds: string[]) => void;
  }) => (
    <div>
      {props.contextItems?.map((item) => <span key={item.id}>{`${item.kind}|${item.title}|${item.detail}|${item.tokens}`}</span>)}
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

  it('loads one object page when Context opens and does not reload it for selection changes', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
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
      } as any],
      nextCursor: null,
    });

    const view = renderWorkspace();
    expect(api.fetchWorkspaceObjectPage).not.toHaveBeenCalled();

    fireEvent.click(view.getByRole('button', { name: 'Open context' }));
    await waitFor(() => expect(api.fetchWorkspaceObjectPage).toHaveBeenCalledWith('AURA', null));

    fireEvent.click(view.getByRole('button', { name: 'Select object' }));
    await waitFor(() => expect(api.fetchWorkspaceObjectPage).toHaveBeenCalledTimes(1));
  });

  it('labels Library file references as metadata-only context with no content tokens', async () => {
    vi.mocked(api.fetchWorkspaceObjectPage).mockResolvedValue({
      objects: [{
        id: 'file-reference-1',
        project_name: null,
        object_type: 'file_reference',
        created_by: 'user',
        title: 'Local budget.pdf',
        content: '',
        metadata_json: { storage_location: 'browser_local' },
        created_at: '2026-10-03T00:00:00Z',
        updated_at: '2026-10-03T00:00:00Z',
      } as any],
      nextCursor: null,
    });

    const view = renderWorkspace();
    fireEvent.click(view.getByRole('button', { name: 'Open context' }));

    expect(await view.findByText(/file\|Local budget\.pdf\|file reference · metadata only/)).toHaveTextContent(
      'file reference · metadata only · file content stays in your browser; only this reference is available to AURA|0',
    );
  });
});
