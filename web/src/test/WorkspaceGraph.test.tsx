import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BoardCanvas } from '../components/board/BoardCanvas';
import { ProjectChatWorkspace } from '../components/chat/ProjectChatWorkspace';
import { api } from '../services/api';
import { projects } from '../data/workspaceData';
import type { AuraFlowNode, WorkspaceExecutionHistory, WorkspaceGraph, WorkspaceObject } from '../types';

const savedGraph: WorkspaceGraph = {
  project_name: 'AURA Project',
  objects: [{
    id: 'turn-1', project_name: 'AURA Project', session_id: 'session-1', source_message_id: 'message-1',
    object_type: 'conversation_turn', created_by: 'assistant', title: 'Persistent answer',
    content: 'Loaded from the shared workspace object graph.', metadata_json: { role: 'assistant' },
    revision: 1,
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
  }],
  edges: [],
  layout: { project_name: 'AURA Project', layout: { positions: { 'turn-1': { x: 80, y: 60 } } }, revision: 3 },
};

describe('Persistent workspace graph Board projection', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchWorkspaceGraphPage').mockImplementation(async (projectName) => api.fetchWorkspaceGraph(projectName));
  });

  it('exposes older saved chats and retries a failed page', () => {
    const loadOlder = vi.fn().mockResolvedValue(undefined);
    const retry = vi.fn().mockResolvedValue(undefined);
    const thread = {
      id: 'demo-thread', projectId: projects[0].id, title: 'Demo', summary: 'Sample', updated: 'today', messages: [], source: 'demo' as const,
    };
    render(
      <ProjectChatWorkspace
        project={projects[0]} threads={[thread]} activeThreadId={thread.id} libraryItems={[]} notes={[]}
        onSelectThread={() => {}} onNewThread={() => {}} onUpdateMessages={() => {}}
        hasOlderSessions onLoadOlderSessions={loadOlder} sessionLoadError="Could not load saved chats. Retry to continue."
        onRetryLoadSessions={retry}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Load older chats' }));
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(loadOlder).toHaveBeenCalledOnce();
    expect(retry).toHaveBeenCalledOnce();
  });

  it('hydrates the project Board from backend objects and does not mix in demo seed nodes', async () => {
    const fetchGraph = vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(savedGraph);
    const attachSession = vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    const seedNodes: AuraFlowNode[] = [{
      id: 'demo-only', type: 'aura', position: { x: 0, y: 0 },
      data: { kind: 'answer', title: 'Demo seed transcript', body: 'Demo', density: 'compact', layer: 'conversation' },
    }];

    render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="aura-project" seedNodes={seedNodes} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('Persistent answer')).toBeInTheDocument();
    expect(screen.getByText('Loaded from the shared workspace object graph.')).toBeInTheDocument();
    await waitFor(() => expect(attachSession).toHaveBeenCalledWith('AURA Project', 'session-1'));
    await waitFor(() => expect(fetchGraph).toHaveBeenCalledWith('AURA Project'));
    expect(screen.queryByText('Demo seed transcript')).not.toBeInTheDocument();
  });

  it('does not reload for session array identity changes and merges graph revisions without moving existing nodes', async () => {
    const nextTurn = { ...savedGraph.objects[0], id: 'turn-2', title: 'New live answer', content: 'Added after the chat send.' };
    const updatedGraph: WorkspaceGraph = {
      ...savedGraph,
      objects: [...savedGraph.objects, nextTurn],
      execution_traces: [{
        run_id: 'live-run-2', session_id: 'session-1', user_object_id: 'turn-1', response_object_id: 'turn-2',
        events: [{ id: 'live-model-selection', event_type: 'model_selected', created_at: '2026-10-02T00:00:00Z', agent_role: 'root', provider: 'ollama', model: 'live-test-model' }],
      }],
      execution_history_truncated: true,
      execution_next_cursor: 'older-execution-page',
      layout: {
        ...savedGraph.layout,
        layout: { positions: { 'turn-1': { x: 900, y: 700 }, 'turn-2': { x: 420, y: 240 } } },
      },
    };
    const fetchPage = vi.spyOn(api, 'fetchWorkspaceGraphPage')
      .mockResolvedValueOnce(savedGraph)
      .mockResolvedValueOnce(updatedGraph);
    const fetchOlderExecution = vi.spyOn(api, 'fetchWorkspaceExecutionHistory').mockResolvedValue({ execution_traces: [], execution_history_truncated: false, execution_next_cursor: null });
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    vi.spyOn(api, 'putWorkspaceLayout').mockResolvedValue(savedGraph.layout);

    const renderBoard = (sessionIds: string[], revision = 0) => (
      <ReactFlowProvider>
        <BoardCanvas boardKey="revision-refresh" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={sessionIds} workspaceGraphRevision={revision} executionExpanded />
      </ReactFlowProvider>
    );
    const view = render(renderBoard(['session-1']));

    expect(await screen.findByText('Persistent answer')).toBeInTheDocument();
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1));
    view.rerender(renderBoard(['session-1']));
    expect(fetchPage).toHaveBeenCalledTimes(1);

    view.rerender(renderBoard(['session-1'], 1));
    expect(await screen.findByText('New live answer')).toBeInTheDocument();
    expect(await screen.findByText('Root · live-test-model')).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Load older runs' }));
    await waitFor(() => expect(fetchOlderExecution).toHaveBeenCalledWith('AURA Project', 'older-execution-page'));
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(view.container.querySelector('[data-id="turn-1"]')).toHaveStyle({ transform: 'translate(80px,60px)' });
  });

  it('attaches a newly opened live session and incrementally refreshes without reloading the Board', async () => {
    const secondSessionTurn = { ...savedGraph.objects[0], id: 'turn-session-2', title: 'Second session answer', content: 'Loaded after attaching a second session.' };
    const secondSessionGraph: WorkspaceGraph = { ...savedGraph, objects: [...savedGraph.objects, secondSessionTurn] };
    const fetchPage = vi.spyOn(api, 'fetchWorkspaceGraphPage')
      .mockResolvedValueOnce(savedGraph)
      .mockResolvedValueOnce(secondSessionGraph);
    const attachSession = vi.spyOn(api, 'attachWorkspaceSession').mockImplementation(async (_projectName, sessionId) => ({ session_id: sessionId, project_name: 'AURA Project' }));
    vi.spyOn(api, 'putWorkspaceLayout').mockResolvedValue(savedGraph.layout);

    const renderBoard = (sessionIds: string[]) => (
      <ReactFlowProvider>
        <BoardCanvas boardKey="session-attach" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={sessionIds} />
      </ReactFlowProvider>
    );
    const view = render(renderBoard(['session-1']));
    expect(await screen.findByText('Persistent answer')).toBeInTheDocument();
    await waitFor(() => expect(fetchPage).toHaveBeenCalledTimes(1));

    view.rerender(renderBoard(['session-1', 'session-2']));
    expect(await screen.findByText('Second session answer')).toBeInTheDocument();
    expect(attachSession).toHaveBeenCalledTimes(2);
    expect(attachSession).toHaveBeenCalledWith('AURA Project', 'session-2');
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(view.container.querySelector('[data-id="turn-1"]')).toHaveStyle({ transform: 'translate(80px,60px)' });
  });

  it('loads older Board graph objects only when requested', async () => {
    const initial: WorkspaceGraph = { ...savedGraph, objects_next_cursor: 'older-object-cursor' };
    const older: WorkspaceGraph = {
      ...savedGraph,
      objects: [{ ...savedGraph.objects[0], id: 'older-turn', title: 'Older saved answer', content: 'Loaded on demand.' }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(initial);
    const fetchPage = vi.spyOn(api, 'fetchWorkspaceGraphPage')
      .mockResolvedValueOnce(initial)
      .mockResolvedValueOnce(older);
    vi.spyOn(api, 'putWorkspaceLayout').mockResolvedValue(savedGraph.layout);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });

    render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="paged-graph" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('Persistent answer')).toBeInTheDocument();
    expect(screen.queryByText('Older saved answer')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load older objects' }));
    expect(await screen.findByText('Older saved answer')).toBeInTheDocument();
    expect(fetchPage).toHaveBeenLastCalledWith('AURA Project', { object: 'older-object-cursor', edge: null });
  });

  it('loads older execution runs from a paged execution history response', async () => {
    const recentGraph: WorkspaceExecutionHistory = {
      execution_history_truncated: true,
      execution_next_cursor: 'older-page-token',
      execution_traces: [{
        run_id: 'recent-run', session_id: 'session-1',
        events: [{ id: 'recent-event', event_type: 'run_completed', created_at: '2026-10-02T00:00:00Z' }],
      }],
    };
    const olderGraph: WorkspaceExecutionHistory = {
      execution_history_truncated: false,
      execution_next_cursor: null,
      execution_traces: [{
        run_id: 'older-run', session_id: 'session-1',
        events: [{ id: 'older-event', event_type: 'run_completed', created_at: '2026-10-01T00:00:00Z' }],
      }],
    };
    const initialGraph: WorkspaceGraph = { ...savedGraph, ...recentGraph };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(initialGraph);
    const fetchGraph = vi.spyOn(api, 'fetchWorkspaceExecutionHistory').mockImplementation(async (_projectName, cursor) => cursor ? olderGraph : recentGraph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });

    render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="paged-execution" workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    const loadOlder = await screen.findByRole('button', { name: 'Load older runs' });
    fireEvent.click(loadOlder);
    await waitFor(() => expect(fetchGraph).toHaveBeenLastCalledWith('AURA Project', 'older-page-token'));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Load older runs' })).not.toBeInTheDocument());
  });

  it('projects research-linked study sessions as study nodes with provenance edges', async () => {
    const studySession: WorkspaceObject = {
      id: 'study-session-1', project_name: null, object_type: 'study_session', created_by: 'user',
      title: 'Verified finding', content: '',
      metadata_json: { material_id: 'turn-1', material_project_name: 'AURA Project', status: 'in_progress' },
      revision: 1,
      created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    };
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [...savedGraph.objects, studySession],
      edges: [{
        id: 'study-provenance-1', project_name: 'AURA Project', source_object_id: 'turn-1',
        target_object_id: 'study-session-1', relation_type: 'studied_in', edge_family: 'provenance',
        created_by: 'user', metadata_json: {}, created_at: '2026-10-01T00:00:00Z',
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });

    render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="study-provenance" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('STUDY SESSION')).toBeInTheDocument();
    expect(screen.getByText('Learning session linked to verified research.')).toBeInTheDocument();
  });

  it('renders backend execution provenance only when the execution layer is expanded', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      execution_traces: [{
        run_id: 'run-1', session_id: 'session-1', response_object_id: 'turn-1',
        events: [{
          id: 'model-event', event_type: 'model_selected', created_at: '2026-10-01T00:00:00Z',
          agent_role: 'root', provider: 'local', model: 'test-model',
        }],
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });

    render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="aura-project-trace" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} executionExpanded />
      </ReactFlowProvider>,
    );

    expect((await screen.findAllByText('Root · test-model')).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Provider: local').length).toBeGreaterThan(0);
  });

  it('hydrates and persists user-authored Context Bridge sections', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        id: 'bridge-1', project_name: 'AURA Project', session_id: null, source_message_id: null,
        object_type: 'context_bridge', created_by: 'user', title: 'Migration handoff',
        content: 'Keep the rollout reversible.',
        metadata_json: {
          privacy_policy: 'confidential',
          required_capabilities: ['document_parse'],
          bridge_options: { conclusions: true, observations: false, failed: false, artifacts: false, constraints: false, decisions: false },
          bridge_sections: { conclusions: 'Preserve the rollback path.', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
        },
        revision: 1,
        created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    let revision = 1;
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockImplementation(async () => ({ revision: ++revision } as never));

    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="bridge-hydration" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    fireEvent.click(await screen.findByTitle('Current density: compact'));
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const section = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Context Bridge Conclusions"]');
    expect(section).not.toBeNull();
    expect(section).toHaveValue('Preserve the rollback path.');
    expect(container.querySelector('textarea[aria-label="Context Bridge Important observations"]')).toBeNull();
    fireEvent.change(section!, { target: { value: 'Keep rollback available.' } });

    await waitFor(() => expect(updateObject).toHaveBeenCalledWith('AURA Project', 'bridge-1', expect.objectContaining({
      metadata_json: expect.objectContaining({
        privacy_policy: 'confidential',
        required_capabilities: ['document_parse'],
        bridge_options: { conclusions: true, observations: false, failed: false, artifacts: false, constraints: false, decisions: false },
        bridge_sections: { conclusions: 'Keep rollback available.', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
      }),
      expected_revision: 1,
    })), { timeout: 2000 });
  });

  it('preserves privacy and capability metadata when editing a manual note', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: 'classified-note',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Classified note',
        content: 'Keep this internal.',
        metadata_json: { privacy_policy: 'confidential', required_capabilities: ['code_graph.read'] },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    let revision = 1;
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockImplementation(async () => ({ revision: ++revision } as never));
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="classified-note" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    await screen.findByText('Classified note');
    fireEvent.click(container.querySelector('[data-id="classified-note"] button[title^="Current density"]')!);
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    fireEvent.change(container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Edit manual note"]')!, { target: { value: 'Updated internal wording.' } });

    await waitFor(() => expect(updateObject).toHaveBeenCalledWith('AURA Project', 'classified-note', expect.objectContaining({
      content: 'Updated internal wording.',
      metadata_json: { privacy_policy: 'confidential', required_capabilities: ['code_graph.read'] },
      expected_revision: 1,
    })), { timeout: 2000 });

    fireEvent.click(screen.getByTitle('Undo · Ctrl Z'));
    await waitFor(() => expect(updateObject).toHaveBeenLastCalledWith('AURA Project', 'classified-note', expect.objectContaining({
      content: 'Keep this internal.',
      metadata_json: { privacy_policy: 'confidential', required_capabilities: ['code_graph.read'] },
      expected_revision: 2,
    })));
  });

  it('lets users set and clear a saved note privacy classification', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: 'privacy-note',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Privacy note',
        content: 'Only for my local model.',
        metadata_json: { required_capabilities: ['document_parse'] },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    let revision = 1;
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockImplementation(async () => ({ revision: ++revision } as never));
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="privacy-note" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    await screen.findByText('Privacy note');
    fireEvent.click(container.querySelector('[data-id="privacy-note"] button[title^="Current density"]')!);
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const privacySelect = container.querySelector<HTMLSelectElement>('select[aria-label="Privacy classification"]')!;
    expect(privacySelect).toHaveValue('');

    fireEvent.change(privacySelect, { target: { value: 'local_only' } });
    await waitFor(() => expect(updateObject).toHaveBeenCalledWith('AURA Project', 'privacy-note', expect.objectContaining({
      metadata_json: { required_capabilities: ['document_parse'], privacy_policy: 'local_only' },
      expected_revision: 1,
    })));

    fireEvent.change(privacySelect, { target: { value: '' } });
    await waitFor(() => expect(updateObject).toHaveBeenLastCalledWith('AURA Project', 'privacy-note', expect.objectContaining({
      metadata_json: { required_capabilities: ['document_parse'] },
      expected_revision: 2,
    })));
  });

  it('restores the persisted privacy classification when a Board update fails', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: 'privacy-note',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Privacy note',
        content: 'Keep this local.',
        metadata_json: { privacy_policy: 'confidential' },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockRejectedValue(new Error('offline'));
    const onToast = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="privacy-update-failure" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} onToast={onToast} />
      </ReactFlowProvider>,
    );

    await screen.findByText('Privacy note');
    fireEvent.click(container.querySelector('[data-id="privacy-note"] button[title^="Current density"]')!);
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const privacySelect = container.querySelector<HTMLSelectElement>('select[aria-label="Privacy classification"]')!;
    expect(privacySelect).toHaveValue('confidential');

    fireEvent.change(privacySelect, { target: { value: 'local_only' } });
    await waitFor(() => expect(updateObject).toHaveBeenCalledWith('AURA Project', 'privacy-note', expect.objectContaining({
      metadata_json: { privacy_policy: 'local_only' },
    })));
    await waitFor(() => expect(privacySelect).toHaveValue('confidential'));
    expect(onToast).toHaveBeenCalledWith('Privacy setting was not saved', 'The previous saved classification remains active.');
  });

  it('serializes manual note autosaves so a slow earlier write cannot race a newer edit', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: 'note-save-order',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Autosave ordering',
        content: 'Original content.',
        metadata_json: { privacy_policy: 'confidential' },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    let releaseFirstSave!: () => void;
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockImplementation(async () => {
      if (updateObject.mock.calls.length === 1) {
        return new Promise((resolve) => { releaseFirstSave = () => resolve({ revision: 2 } as never); });
      }
      return { revision: 3 } as never;
    });
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="note-save-order" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );

    await screen.findByText('Autosave ordering');
    fireEvent.click(container.querySelector('[data-id="note-save-order"] button[title^="Current density"]')!);
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const editor = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Edit manual note"]')!;
    fireEvent.change(editor, { target: { value: 'First saved draft.' } });
    await waitFor(() => expect(updateObject).toHaveBeenCalledTimes(1), { timeout: 2000 });

    fireEvent.change(editor, { target: { value: 'Newest saved draft.' } });
    await new Promise((resolve) => window.setTimeout(resolve, 600));
    expect(updateObject).toHaveBeenCalledTimes(1);

    releaseFirstSave();
    await waitFor(() => expect(updateObject).toHaveBeenCalledTimes(2));
    expect(updateObject.mock.calls[1][2]).toEqual(expect.objectContaining({
      content: 'Newest saved draft.',
      metadata_json: { privacy_policy: 'confidential' },
      expected_revision: 2,
    }));
  });

  it('keeps a failed Note draft visible and exposes an explicit retry', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: 'retryable-note-save',
        object_type: 'manual_note',
        created_by: 'user',
        title: 'Retryable note',
        content: 'Saved content.',
        metadata_json: { privacy_policy: 'internal' },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ revision: 2 } as never);
    const onToast = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="retryable-note-save" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} onToast={onToast} />
      </ReactFlowProvider>,
    );

    await screen.findByText('Retryable note');
    fireEvent.click(container.querySelector('[data-id="retryable-note-save"] button[title^="Current density"]')!);
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const editor = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="Edit manual note"]')!;
    fireEvent.change(editor, { target: { value: 'Unsaved but recoverable content.' } });

    await waitFor(() => expect(updateObject).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(editor).toHaveValue('Unsaved but recoverable content.');
    const retryButton = container.querySelector<HTMLButtonElement>(
      '[data-id="retryable-note-save"] button[aria-label="Retry save"]',
    );
    expect(retryButton).toBeInTheDocument();

    fireEvent.click(retryButton!);
    await waitFor(() => expect(updateObject).toHaveBeenCalledTimes(2));
    expect(updateObject.mock.calls[1][2]).toEqual(expect.objectContaining({
      content: 'Unsaved but recoverable content.',
      metadata_json: { privacy_policy: 'internal' },
      expected_revision: 1,
    }));
    await waitFor(() => expect(container.querySelector('[data-id="retryable-note-save"] button[aria-label="Retry save"]')).not.toBeInTheDocument());
  });

  it('persists undo and redo for a user-created note using its stable workspace ID', async () => {
    let graph: WorkspaceGraph = { ...savedGraph, objects: [...savedGraph.objects] };
    const fetchGraph = vi.spyOn(api, 'fetchWorkspaceGraph').mockImplementation(async () => graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    vi.spyOn(api, 'putWorkspaceLayout').mockImplementation(async (_project, layout, expectedRevision) => {
      const revision = expectedRevision + 1;
      graph = { ...graph, layout: { ...graph.layout, layout, revision } };
      return graph.layout;
    });
    const createObject = vi.spyOn(api, 'createWorkspaceObject').mockImplementation(async (_project, input) => {
      const object = {
        id: input.id ?? 'restored-note-id', project_name: 'AURA Project', session_id: null, source_message_id: null,
        object_type: input.object_type, created_by: 'user', title: input.title, content: input.content,
        metadata_json: input.metadata_json ?? {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
      } as WorkspaceObject;
      graph = { ...graph, objects: [...graph.objects.filter((item) => item.id !== object.id), object] };
      return object;
    });
    const deleteObject = vi.spyOn(api, 'deleteWorkspaceObject').mockImplementation(async (_project, id) => {
      graph = { ...graph, objects: graph.objects.filter((item) => item.id !== id) };
    });

    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="undo-persistent-note" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} />
      </ReactFlowProvider>,
    );
    await screen.findByText('Persistent answer');
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    fireEvent.click(container.querySelector('.react-flow__pane')!, { clientX: 500, clientY: 300 });
    await waitFor(() => expect(createObject).toHaveBeenCalledTimes(1));
    const createdId = 'restored-note-id';

    const undoButton = screen.getByTitle('Undo · Ctrl Z');
    await waitFor(() => expect(undoButton).toBeEnabled());
    fireEvent.click(undoButton);
    await waitFor(() => expect(deleteObject).toHaveBeenCalledWith('AURA Project', createdId!));
    await waitFor(() => expect(screen.queryByText('Untitled note')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTitle('Redo · Ctrl ⇧ Z'));
    await waitFor(() => expect(createObject).toHaveBeenCalledTimes(2));
    expect(createObject.mock.calls[1][1].id).toBe(createdId);
    expect(graph.objects.some((object) => object.id === createdId)).toBe(true);
    expect(fetchGraph).toHaveBeenCalledTimes(1);
  });

  it('serializes layout writes from live Board changes and undo/redo against the latest revision', async () => {
    const initialGraph: WorkspaceGraph = {
      ...savedGraph,
      layout: {
        ...savedGraph.layout,
        layout: {
          positions: { 'turn-1': { x: 80, y: 60 } },
          densities: { 'turn-1': 'compact' },
        },
      },
    };
    let graph = initialGraph;
    const fetchGraph = vi.spyOn(api, 'fetchWorkspaceGraph').mockImplementation(async () => graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });

    let releaseFirstSave!: () => void;
    const saveCalls: number[] = [];
    vi.spyOn(api, 'putWorkspaceLayout').mockImplementation(async (_project, layout, expectedRevision) => {
      saveCalls.push(expectedRevision);
      if (saveCalls.length === 1) {
        const savedLayout = { ...graph.layout, layout, revision: expectedRevision + 1 };
        graph = { ...graph, layout: savedLayout };
        return new Promise((resolve) => { releaseFirstSave = () => resolve(savedLayout); });
      }
      graph = { ...graph, layout: { ...graph.layout, layout, revision: expectedRevision + 1 } };
      return graph.layout;
    });
    const createObject = vi.spyOn(api, 'createWorkspaceObject').mockImplementation(async (_project, input) => {
      const object = {
        id: input.id ?? 'restored-note-id', project_name: 'AURA Project', session_id: null, source_message_id: null,
        object_type: input.object_type, created_by: 'user', title: input.title, content: input.content,
        metadata_json: input.metadata_json ?? {}, created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
      } as WorkspaceObject;
      graph = { ...graph, objects: [...graph.objects.filter((item) => item.id !== object.id), object] };
      return object;
    });
    const deleteObject = vi.spyOn(api, 'deleteWorkspaceObject').mockImplementation(async (_project, id) => {
      graph = { ...graph, objects: graph.objects.filter((item) => item.id !== id) };
    });
    const onToast = vi.fn();

    const renderBoard = (revision: number) => (
      <ReactFlowProvider>
        <BoardCanvas boardKey="serialized-layout-writes" seedNodes={[]} seedEdges={[]} workspaceProjectName="AURA Project" workspaceSessionIds={['session-1']} workspaceGraphRevision={revision} onToast={onToast} />
      </ReactFlowProvider>
    );
    const view = render(renderBoard(0));
    const { container } = view;
    await screen.findByText('Persistent answer');
    fireEvent.click(screen.getByRole('button', { name: 'Note' }));
    fireEvent.click(container.querySelector('.react-flow__pane')!, { clientX: 500, clientY: 300 });
    await waitFor(() => expect(createObject).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveCalls).toHaveLength(1), { timeout: 2500 });

    view.rerender(renderBoard(1));
    await waitFor(() => expect(fetchGraph).toHaveBeenCalledTimes(2));
    expect(onToast).not.toHaveBeenCalledWith('Board layout changed elsewhere', expect.anything());

    fireEvent.click(screen.getByTitle('Undo · Ctrl Z'));
    const noteId = createObject.mock.calls[0][1].id ?? 'restored-note-id';
    await waitFor(() => expect(deleteObject).toHaveBeenCalledWith('AURA Project', noteId));
    expect(saveCalls).toEqual([3]);

    releaseFirstSave();
    await waitFor(() => expect(saveCalls).toEqual([3, 4]));
    await waitFor(() => expect(screen.queryByText('Untitled note')).not.toBeInTheDocument());
    expect(fetchGraph).toHaveBeenCalledTimes(2);
  });

  it('offers a live chat action on saved branches and restores the selected branch context', async () => {
    const branchId = 'branch-object-1';
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: branchId,
        session_id: null,
        source_message_id: null,
        object_type: 'conversation_branch',
        created_by: 'user',
        title: 'Continue after the handoff',
        content: 'Saved branch point.',
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    const fetchBranchObjects = vi.spyOn(api, 'fetchWorkspaceObjectPage').mockResolvedValue({ objects: graph.objects, nextCursor: null });
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-branch', project_name: projects[0].name });

    const onContinueBranch = vi.fn();
    const { rerender, container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="branch-live-action" seedNodes={[]} seedEdges={[]} workspaceProjectName={projects[0].name} onUseWorkspaceContext={onContinueBranch} />
      </ReactFlowProvider>,
    );
    expect(await screen.findByText('Continue after the handoff')).toBeInTheDocument();
    const continueButton = [...container.querySelectorAll('[data-id="branch-object-1"] button')]
      .find((button) => button.textContent?.includes('Continue in Chat'))!;
    fireEvent.click(continueButton);
    expect(onContinueBranch).toHaveBeenCalledWith(branchId);

    const thread = {
      id: 'branch-live-thread', projectId: projects[0].id, title: 'Continue after the handoff',
      summary: 'Live backend session', updated: 'just now', messages: [], sessionId: 'session-branch',
      source: 'live' as const, initialContextObjectIds: [branchId],
    };
    rerender(
      <ProjectChatWorkspace
        project={projects[0]} threads={[thread]} activeThreadId={thread.id} libraryItems={[]} notes={[]}
        onSelectThread={() => {}} onNewThread={() => {}} onUpdateMessages={() => {}}
        onContextObjectIdsChange={(_, ids) => onContinueBranch('selected:' + ids.join(','))}
      />,
    );
    fireEvent.click(screen.getByText('Context').closest('button')!);
    await screen.findByText('Project objects');
    await waitFor(() => expect(fetchBranchObjects).toHaveBeenCalledWith(projects[0].name, null));
    await waitFor(() => expect(container.querySelectorAll('.ai-context-item')).toHaveLength(1));
    const contextItem = container.querySelector<HTMLButtonElement>('.ai-context-item')!;
    await waitFor(() => expect(contextItem).toHaveAttribute('aria-pressed', 'true'));
    fireEvent.click(contextItem);
    expect(onContinueBranch).toHaveBeenLastCalledWith('selected:');
  });

  it('offers a saved Context Set directly to a new live chat without mutating the set', async () => {
    const contextSetId = 'saved-context-set';
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: contextSetId,
        session_id: null,
        source_message_id: null,
        object_type: 'context_set',
        created_by: 'user',
        title: 'Release review context',
        content: '',
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-context-set', project_name: projects[0].name });
    const createObject = vi.spyOn(api, 'createWorkspaceObject').mockResolvedValue({} as never);
    const onUseWorkspaceContext = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="context-set-live-action" seedNodes={[]} seedEdges={[]} workspaceProjectName={projects[0].name} onUseWorkspaceContext={onUseWorkspaceContext} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('Release review context')).toBeInTheDocument();
    const useButton = [...container.querySelectorAll('[data-id="saved-context-set"] button')]
      .find((button) => button.textContent?.includes('Use in Chat'))!;
    fireEvent.click(useButton);
    expect(onUseWorkspaceContext).toHaveBeenCalledWith(contextSetId);
    expect(createObject).not.toHaveBeenCalled();
  });

  it('offers a persisted Context Bridge directly to chat with the bridge object selected', async () => {
    const bridgeId = 'saved-context-bridge';
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [{
        ...savedGraph.objects[0],
        id: bridgeId,
        session_id: null,
        source_message_id: null,
        object_type: 'context_bridge',
        created_by: 'user',
        title: 'Experiment handoff',
        content: 'Carry forward the verified constraints.',
        metadata_json: { bridge_options: { conclusions: true, observations: false, failed: false, artifacts: false } },
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-context-bridge', project_name: projects[0].name });
    const createObject = vi.spyOn(api, 'createWorkspaceObject').mockResolvedValue({} as never);
    const onUseWorkspaceContext = vi.fn();
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="context-bridge-live-action" seedNodes={[]} seedEdges={[]} workspaceProjectName={projects[0].name} onUseWorkspaceContext={onUseWorkspaceContext} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('Experiment handoff')).toBeInTheDocument();
    fireEvent.click(await screen.findByTitle('Current density: compact'));
    await waitFor(() => expect(container.querySelector('.aura-node--full')).toBeInTheDocument());
    const useButton = [...container.querySelectorAll('[data-id="saved-context-bridge"] button')]
      .find((button) => button.textContent?.includes('Use in Chat'))!;
    fireEvent.click(useButton);
    expect(onUseWorkspaceContext).toHaveBeenCalledWith(bridgeId);
    expect(createObject).not.toHaveBeenCalled();
  });

  it('projects Research Specialist sources, evidence, claims, and provenance into the shared Board', async () => {
    const graph: WorkspaceGraph = {
      ...savedGraph,
      objects: [
        { ...savedGraph.objects[0], id: 'research-source-node', session_id: null, source_message_id: null, object_type: 'research_source', created_by: 'research', title: 'Durable Workflows', content: 'Workflow overview.', metadata_json: { canonical_id: 'doi:10.1000/workflows', authors: ['A. Researcher'], year: 2025, url: 'https://example.org/paper' } },
        { ...savedGraph.objects[0], id: 'research-unsafe-source-node', session_id: null, source_message_id: null, object_type: 'research_source', created_by: 'research', title: 'Unsafe Link Record', content: 'Metadata URL must not become a script link.', metadata_json: { url: 'javascript:alert(1)' } },
        { ...savedGraph.objects[0], id: 'research-evidence-node', session_id: null, source_message_id: null, object_type: 'research_evidence', created_by: 'research', title: 'Evidence · Durable Workflows', content: 'Execution resumes from a persisted checkpoint.', metadata_json: { source_locator: 'Section 3' } },
        { ...savedGraph.objects[0], id: 'research-claim-node', session_id: null, source_message_id: null, object_type: 'research_claim', created_by: 'research', title: 'source_supported_fact · Durable state', content: 'Claim type: source_supported_fact\nVerification: verified\n\nDurable state resumes after restart.', metadata_json: { verification_status: 'verified' } },
      ],
      edges: [
        { id: 'research-source-evidence', project_name: projects[0].name, source_object_id: 'research-source-node', target_object_id: 'research-evidence-node', relation_type: 'contains_evidence', edge_family: 'provenance', created_by: 'research', metadata_json: {}, created_at: '2026-10-01T00:00:00Z' },
        { id: 'research-evidence-claim', project_name: projects[0].name, source_object_id: 'research-evidence-node', target_object_id: 'research-claim-node', relation_type: 'supports_claim', edge_family: 'provenance', created_by: 'research', metadata_json: {}, created_at: '2026-10-01T00:00:00Z' },
      ],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-research', project_name: projects[0].name });
    const { container } = render(
      <ReactFlowProvider>
        <BoardCanvas boardKey="research-shared-graph" seedNodes={[]} seedEdges={[]} workspaceProjectName={projects[0].name} workspaceSessionIds={['session-research']} />
      </ReactFlowProvider>,
    );

    expect(await screen.findByText('Durable Workflows')).toBeInTheDocument();
    expect(screen.getByText('Evidence · Durable Workflows')).toBeInTheDocument();
    expect(screen.getByText('source_supported_fact · Durable state')).toBeInTheDocument();
    expect(container.querySelector('[data-id="research-source-node"] .aura-node__eyebrow')).toHaveTextContent('RESEARCH SOURCE');
    expect(container.querySelector('[data-id="research-evidence-node"] .aura-node__eyebrow')).toHaveTextContent('RESEARCH EVIDENCE');
    expect(container.querySelector('[data-id="research-claim-node"] .aura-node__eyebrow')).toHaveTextContent('RESEARCH CLAIM');
    expect(container.querySelector('[data-id="research-source-node"] .research-node-meta')).toHaveTextContent('doi:10.1000/workflows · 2025 · A. Researcher');
    expect(container.querySelector<HTMLAnchorElement>('[data-id="research-source-node"] a[aria-label="Open source: Durable Workflows"]')).toHaveAttribute('href', 'https://example.org/paper');
    expect(container.querySelector('[data-id="research-evidence-node"] .research-node-meta')).toHaveTextContent('Section 3');
    expect(container.querySelector('[data-id="research-unsafe-source-node"] a[aria-label^="Open source:"]')).toBeNull();
    expect(container.querySelectorAll('[data-id^="research-"]')).toHaveLength(4);
  });




});
