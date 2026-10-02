import { describe, expect, it } from 'vitest';
import { projectExecutionGraph } from '../components/board/executionProjection';
import type { AuraFlowNode, WorkspaceExecutionTrace } from '../types';

const workspaceNodes: AuraFlowNode[] = [
  { id: 'user', type: 'aura', position: { x: 10, y: 20 }, data: { kind: 'user', title: 'Question', body: '', density: 'compact', layer: 'conversation' } },
  { id: 'answer', type: 'aura', position: { x: 900, y: 20 }, data: { kind: 'answer', title: 'Answer', body: '', density: 'compact', layer: 'conversation' } },
];

const traces: WorkspaceExecutionTrace[] = [
  {
    run_id: 'root-run', session_id: 'session', user_object_id: 'user', response_object_id: 'answer',
    events: [
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
    expect(links).toContain('user->execution-root-model');
    expect(links).toContain('execution-root-done->answer');
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

  it('renders persisted model, reasoning, and fallback routing provenance', () => {
    const trace: WorkspaceExecutionTrace = {
      run_id: 'provenance-run',
      session_id: 'session',
      events: [
        {
          id: 'route',
          event_type: 'model_selected',
          created_at: '2026-10-02T00:00:00Z',
          agent_role: 'root',
          provider: 'ollama',
          model: 'local-model',
          profile_id: 'balanced',
          profile_version: 3,
          winning_scope: 'project',
          privacy: 'local_only',
          fallback_policy: 'none',
        },
        {
          id: 'reasoning',
          event_type: 'reasoning_effort_selected',
          created_at: '2026-10-02T00:00:01Z',
          reasoning_policy: 'adaptive',
          reasoning_bounds: { min: 'low', max: 'high' },
          selected_effort: 'medium',
        },
        {
          id: 'fallback',
          event_type: 'fallback_considered',
          created_at: '2026-10-02T00:00:02Z',
          fallback_policy: 'local_only',
          primary_provider: 'cloud',
          selected_provider: 'ollama',
        },
        {
          id: 'blocked',
          event_type: 'fallback_blocked',
          created_at: '2026-10-02T00:00:03Z',
          fallback_policy: 'ask_before_cloud',
          privacy_boundary: 'confidential',
          error_type: 'RoutingConfirmationRequired',
          proposed_provider: 'cloud-provider',
          proposed_model: 'exact-model',
        },
      ],
    };

    const nodes = projectExecutionGraph([trace], workspaceNodes).nodes;
    const byId = new Map(nodes.map((node) => [node.id, node.data]));
    expect(byId.get('execution-route')?.body).toContain('Profile balanced v3');
    expect(byId.get('execution-route')?.body).toContain('Scope project');
    expect(byId.get('execution-reasoning')?.title).toContain('medium');
    expect(byId.get('execution-reasoning')?.body).toContain('Bounds low–high');
    expect(byId.get('execution-fallback')?.body).toContain('cloud → ollama');
    expect(byId.get('execution-blocked')?.body).toContain('Proposed cloud-provider:exact-model');
  });


  it('connects directly selected and linked context objects to the compilation event', () => {
    const selected = {
      id: 'selected-note',
      type: 'aura',
      position: { x: -300, y: 20 },
      data: { kind: 'note', title: 'Selected constraint', body: '', density: 'compact', layer: 'knowledge' },
    } as AuraFlowNode;
    const linked = {
      id: 'linked-bridge',
      type: 'aura',
      position: { x: -300, y: 180 },
      data: { kind: 'bridge', title: 'Linked handoff', body: '', density: 'compact', layer: 'knowledge' },
    } as AuraFlowNode;
    const trace: WorkspaceExecutionTrace = {
      run_id: 'context-run',
      session_id: 'session',
      events: [{
        id: 'compile',
        event_type: 'context_compiled',
        created_at: '2026-10-02T00:00:00Z',
        context_objects: [
          { object_id: selected.id, object_type: 'manual_note', selected_by_user: true, source_object_ids: [] },
          { object_id: linked.id, object_type: 'context_bridge', selected_by_user: false, source_object_ids: [selected.id] },
        ],
        context_estimated_tokens: 42,
        context_privacy_requirement: 'internal',
      }],
    };

    const projection = projectExecutionGraph([trace], [selected, linked]);
    const contextNode = projection.nodes.find((node) => node.id === 'execution-compile');
    expect(contextNode?.data.title).toBe('Context compiled · 2 objects');
    expect(contextNode?.data.body).toBe('1 selected · 1 linked · about 42 tokens · Privacy internal');
    const provenanceEdges = projection.edges.filter((edge) => edge.target === 'execution-compile');
    expect(provenanceEdges).toHaveLength(2);
    expect(provenanceEdges.find((edge) => edge.source === selected.id)?.data?.contextOrigin).toBe('selected');
    expect(provenanceEdges.find((edge) => edge.source === linked.id)?.data?.contextOrigin).toBe('linked');
  });


  it('renders automation origin and trigger IDs as execution provenance', () => {
    const trace: WorkspaceExecutionTrace = {
      run_id: 'automation-run',
      session_id: 'session',
      events: [{
        id: 'automation-trigger',
        event_type: 'automation_triggered',
        created_at: '2026-10-02T00:00:00Z',
        trigger_event_id: 'event-123',
        automation_id: 'automation-456',
        automation_name: 'Atlas review',
      }],
    };
    const node = projectExecutionGraph([trace], workspaceNodes).nodes[0];
    expect(node.data.title).toBe('Automation · Atlas review');
    expect(node.data.body).toBe('Trigger event event-123');
    expect(node.data.chip).toBe('AUTOMATION');
    expect(node.data.body).not.toContain('instruction');
  });

});
