import { render, screen, waitFor } from '@testing-library/react';
import { ReactFlowProvider } from '@xyflow/react';
import { describe, expect, it, vi } from 'vitest';
import { BoardCanvas } from '../components/board/BoardCanvas';
import { api } from '../services/api';
import type { AuraFlowNode, WorkspaceGraph } from '../types';

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

});
