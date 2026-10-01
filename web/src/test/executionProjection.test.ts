import { describe, expect, it } from 'vitest';
import { projectExecutionGraph } from '../components/board/executionProjection';
import type { AuraFlowNode, WorkspaceExecutionTrace } from '../types';

const workspaceNodes: AuraFlowNode[] = [
  { id: 'user', type: 'aura', position: { x: 10, y: 20 }, data: { kind: 'user', title: 'Question', body: '', density: 'compact', layer: 'conversation' } },
  { id: 'selected-note', type: 'aura', position: { x: -300, y: 20 }, data: { kind: 'note', title: 'Selected constraint', body: '', density: 'compact', layer: 'knowledge' } },
  { id: 'answer', type: 'aura', position: { x: 900, y: 20 }, data: { kind: 'answer', title: 'Answer', body: '', density: 'compact', layer: 'conversation' } },
];

const traces: WorkspaceExecutionTrace[] = [
  {
    run_id: 'root-run', session_id: 'session', user_object_id: 'user', response_object_id: 'answer',
    events: [
      {
        id: 'context-compiled', event_type: 'context_compiled', created_at: '2026-10-01T00:00:00Z',
        context_objects: [{ object_id: 'selected-note', object_type: 'manual_note', selected_by_user: true, source_object_ids: [] }],
        context_estimated_tokens: 42,
      },
      { id: 'root-model', event_type: 'model_selected', created_at: '2026-10-01T00:00:00Z', agent_role: 'root', provider: 'local', model: 'safe-model' },
      { id: 'delegate-start', event_type: 'delegation_started', created_at: '2026-10-01T00:00:01Z', specialist: 'research', child_run_id: 'child-run' },
      { id: 'delegate-end', event_type: 'delegation_completed', created_at: '2026-10-01T00:00:04Z', specialist: 'research', child_run_id: 'child-run' },
      { id: 'root-done', event_type: 'run_completed', created_at: '2026-10-01T00:00:05Z' },
    ],
  },
  {
    run_id: 'child-run', parent_run_id: 'root-run', session_id: 'session',
    events: [
      { id: 'tool-request', event_type: 'tool_requested', created_at: '2026-10-01T00:00:02Z', tool_name: 'search.web' },
      { id: 'tool-result', event_type: 'tool_executed', created_at: '2026-10-01T00:00:03Z', tool_name: 'search.web', success: true },
    ],
  },
];

describe('execution trace projection', () => {
  it('connects persisted events from the user turn to the response and links specialist handoffs', () => {
    const projection = projectExecutionGraph(traces, workspaceNodes);
    const links = new Set(projection.edges.map(({ source, target }) => `${source}->${target}`));
    expect(links).toContain('user->execution-context-compiled');
    expect(links).toContain('execution-context-compiled->execution-root-model');
    expect(links).toContain('execution-root-done->answer');
    expect(links).toContain('selected-note->execution-context-compiled');
    const contextNode = projection.nodes.find((node) => node.id === 'execution-context-compiled');
    expect(contextNode?.data.title).toBe('Context compiled · 1 object');
    expect(contextNode?.data.body).toBe('1 selected · about 42 tokens');
    expect(links).toContain('execution-delegate-start->execution-tool-request');
    expect(links).toContain('execution-tool-result->execution-delegate-end');
    expect(projection.nodes.every((node) => node.draggable === false && node.selectable === false && node.connectable === false)).toBe(true);
    expect(projection.edges.every((edge) => edge.selectable === false && edge.deletable === false)).toBe(true);
  });

  it('uses only operational labels and ignores cycles in parent relationships', () => {
    const cyclic = traces.map((trace) => ({ ...trace }));
    cyclic[0] = { ...cyclic[0], parent_run_id: 'child-run' };
    expect(() => projectExecutionGraph(cyclic, workspaceNodes)).not.toThrow();
    const projection = projectExecutionGraph(traces, workspaceNodes);
    expect(projection.nodes.map((node) => node.data.title).join(' ')).not.toContain('secret');
    expect(projection.nodes.map((node) => node.data.body).join(' ')).not.toContain('prompt');
  });
});
