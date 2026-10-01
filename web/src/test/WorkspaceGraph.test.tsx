import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { describe, expect, it, vi } from 'vitest';
import { BoardCanvas } from '../components/board/BoardCanvas';
import { ProjectChatWorkspace } from '../components/chat/ProjectChatWorkspace';
import { api } from '../services/api';
import { projects } from '../data/workspaceData';
import type { AuraFlowNode, WorkspaceGraph, WorkspaceObject } from '../types';

const savedGraph: WorkspaceGraph = {
  project_name: 'AURA Project',
  objects: [{
    id: 'turn-1', project_name: 'AURA Project', session_id: 'session-1', source_message_id: 'message-1',
    object_type: 'conversation_turn', created_by: 'assistant', title: 'Persistent answer',
    content: 'Loaded from the shared workspace object graph.', metadata_json: { role: 'assistant' },
    created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
  }],
  edges: [],
  layout: { project_name: 'AURA Project', layout: { positions: { 'turn-1': { x: 80, y: 60 } } }, revision: 3 },
};

describe('Persistent workspace graph Board projection', () => {
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
          bridge_options: { conclusions: true, observations: false, failed: false, artifacts: false },
          bridge_sections: { conclusions: 'Preserve the rollback path.', observations: '', failed: '', artifacts: '' },
        },
        created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
      }],
    };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
    vi.spyOn(api, 'attachWorkspaceSession').mockResolvedValue({ session_id: 'session-1', project_name: 'AURA Project' });
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockResolvedValue({} as never);

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
        bridge_options: { conclusions: true, observations: false, failed: false, artifacts: false },
        bridge_sections: { conclusions: 'Keep rollback available.', observations: '', failed: '', artifacts: '' },
      }),
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
    const updateObject = vi.spyOn(api, 'updateWorkspaceObject').mockResolvedValue({} as never);
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
    })), { timeout: 2000 });

    fireEvent.click(screen.getByTitle('Undo · Ctrl Z'));
    await waitFor(() => expect(updateObject).toHaveBeenLastCalledWith('AURA Project', 'classified-note', expect.objectContaining({
      content: 'Keep this internal.',
      metadata_json: { privacy_policy: 'confidential', required_capabilities: ['code_graph.read'] },
    })));
  });

  it('persists undo and redo for a user-created note using its stable workspace ID', async () => {
    let graph: WorkspaceGraph = { ...savedGraph, objects: [...savedGraph.objects] };
    vi.spyOn(api, 'fetchWorkspaceGraph').mockImplementation(async () => graph);
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
    const fetchBranchGraph = vi.spyOn(api, 'fetchWorkspaceGraph').mockResolvedValue(graph);
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
    await waitFor(() => expect(fetchBranchGraph).toHaveBeenCalledWith(projects[0].name));
    fireEvent.click(screen.getByText('Context').closest('button')!);
    await screen.findByText('Project objects');
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

});
