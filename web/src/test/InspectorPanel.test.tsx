import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { InspectorPanel } from '../components/layout/InspectorPanel';
import { api } from '../services/api';
import type { MemoryItem, ResearchInspectorData, RunDetail } from '../types';

const sampleRunDetail: RunDetail = {
  id: 'run-inspect-123456',
  session_id: 'sess-inspect-001',
  status: 'completed',
  user_message: 'Compare novelty bounds for test-time training',
  final_response: 'Synthesis concluded successfully.',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  events: [
    {
      id: 'ev-1',
      event_type: 'routing_profile_resolved',
      payload: { profile_name: 'Balanced', profile_version: 1 },
      created_at: new Date().toISOString(),
    },
    {
      id: 'ev-2',
      event_type: 'model_selected',
      payload: { model_id: 'gpt-4o', provider_id: 'openai' },
      created_at: new Date().toISOString(),
    },
    {
      id: 'ev-3',
      event_type: 'tool_executed',
      payload: { tool_name: 'retrieve_sources', status: 'success' },
      created_at: new Date().toISOString(),
    },
  ],
};

const sampleResearchData: ResearchInspectorData = {
  run_id: 'run-inspect-123456',
  child_run_id: 'run-child-789',
  status: 'completed',
  goal: {
    goal_id: 'goal-1',
    user_query: 'Investigate test-time training literature',
    project_name: 'stateful',
  },
  queries: [
    { query_id: 'q-1', query_text: 'Test-time training recurrent memory', search_type: 'semantic', results_count: 5 },
  ],
  sources: [
    {
      source_id: 'src-1',
      canonical_id: 'arXiv:2401.0001',
      title: 'Learning to Learn at Test Time',
      authors: ['Sun et al.'],
      year: 2024,
    },
  ],
  inspected_source_ids: ['src-1'],
  evidence: [
    {
      evidence_id: 'ev-item-1',
      source_title: 'Learning to Learn at Test Time',
      extracted_text: 'We demonstrate constant state representation under streaming sequence bounds.',
      confidence: 0.94,
    },
  ],
  claims: [
    {
      claim_id: 'claim-1',
      claim_text: 'Test-time updates maintain fixed memory overhead.',
      claim_type: 'empirical',
      evidence_ids: ['ev-item-1'],
    },
  ],
};

const sampleMemories: MemoryItem[] = [
  {
    id: 'mem-1',
    key: 'project_architecture_thesis',
    memory_type: 'core_thesis',
    is_active: true,
    content: 'AURA workspace maintains explicit project-level context manifests.',
    confidence: 0.98,
    created_at: new Date().toISOString(),
  },
];

describe('InspectorPanel Component', () => {
  it('loads older pages of persisted project memory on demand', async () => {
    const onLoadMoreMemories = vi.fn().mockResolvedValue(undefined);
    render(
      <InspectorPanel
        memories={sampleMemories}
        memoryNextCursor="older-memory-cursor"
        onLoadMoreMemories={onLoadMoreMemories}
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('inspector-tab-memory'));
    expect(screen.getByText('Showing 1 item')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load older memories' }));
    expect(onLoadMoreMemories).toHaveBeenCalledOnce();
  });

  it('renders live run events in the execution tab with togglable payload', () => {
    render(
      <InspectorPanel
        runDetail={sampleRunDetail}
        onClose={vi.fn()}
      />
    );

    // Click execution tab
    fireEvent.click(screen.getByTestId('inspector-tab-execution'));

    expect(screen.getByText(/run-inspect/i)).toBeInTheDocument();
    expect(screen.getByText('routing_profile_resolved')).toBeInTheDocument();
    expect(screen.getByText('model_selected')).toBeInTheDocument();
    expect(screen.getByText('tool_executed')).toBeInTheDocument();

    // Toggle payload
    const toggleButtons = screen.getAllByText(/View operational details/i);
    expect(toggleButtons.length).toBeGreaterThan(0);
    fireEvent.click(toggleButtons[0]);
    expect(screen.getByText(/Hide details/i)).toBeInTheDocument();
    expect(screen.getByText((content) => content.includes('"profile_name": "Balanced"'))).toBeInTheDocument();
  });

  it('renders detailed Research Specialist data in the research tab', () => {
    render(
      <InspectorPanel
        researchData={sampleResearchData}
        onClose={vi.fn()}
      />
    );

    // Switch to research tab
    fireEvent.click(screen.getByTestId('inspector-tab-research'));

    expect(screen.getByText(/Investigate test-time training literature/i)).toBeInTheDocument();
    expect(screen.getByText('Test-time training recurrent memory')).toBeInTheDocument();
    expect(screen.getAllByText('Learning to Learn at Test Time').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/94% conf/i)).toBeInTheDocument();
    expect(screen.getByText(/We demonstrate constant state representation/i)).toBeInTheDocument();
    expect(screen.getByText(/Test-time updates maintain fixed memory overhead/i)).toBeInTheDocument();
  });

  it('renders persisted project memories in the memory tab', () => {
    render(
      <InspectorPanel
        memories={sampleMemories}
        onClose={vi.fn()}
      />
    );

    // Switch to memory tab
    fireEvent.click(screen.getByTestId('inspector-tab-memory'));

    expect(screen.getByText('project_architecture_thesis')).toBeInTheDocument();
    expect(screen.getByText(/AURA workspace maintains explicit project-level context manifests/i)).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 98%/i)).toBeInTheDocument();
  });

  it('shows memory provenance without exposing the stored evidence snapshot', () => {
    const onOpenSourceChat = vi.fn();
    const onOpenSourceRun = vi.fn();
    const memory: MemoryItem = {
      ...sampleMemories[0],
      metadata_json: {
        explicit: true,
        source_session_id: 'source-session-1',
        source_run_id: 'source-run-1',
        privacy_policy: 'confidential',
        claim_ids: ['claim-1'],
        evidence_ids: ['evidence-1'],
        source_references: ['arXiv:2401.0001'],
        evidence_snapshot: [{ snippet: 'Sensitive source excerpt is not shown here.' }],
      },
      superseded_by_id: 'memory-next-version',
    };
    render(<InspectorPanel memories={[memory]} onOpenSourceChat={onOpenSourceChat} onOpenSourceRun={onOpenSourceRun} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('inspector-tab-memory'));
    fireEvent.click(screen.getByRole('button', { name: 'Why AURA remembers this' }));

    expect(screen.getByText('Explicit remember request')).toBeInTheDocument();
    expect(screen.getByText('source-session-1')).toBeInTheDocument();
    expect(screen.getByText('source-run-1')).toBeInTheDocument();
    expect(screen.getByText('claim-1')).toBeInTheDocument();
    expect(screen.getByText('evidence-1')).toBeInTheDocument();
    expect(screen.getByText('arXiv:2401.0001')).toBeInTheDocument();
    expect(screen.getByText('memory-next-version')).toBeInTheDocument();
    expect(screen.queryByText(/Sensitive source excerpt/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open source chat' }));
    expect(onOpenSourceChat).toHaveBeenCalledWith('source-session-1');
    fireEvent.click(screen.getByRole('button', { name: 'Open source run' }));
    expect(onOpenSourceRun).toHaveBeenCalledWith('source-run-1');
  });

  it('opens the execution tab for the exact run selected from memory provenance', () => {
    render(<InspectorPanel
      runDetail={{
        id: 'source-run-1', session_id: 'source-session-1', status: 'completed',
        user_message: 'Explain the persisted route', created_at: '2026-10-04T00:00:00Z',
        updated_at: '2026-10-04T00:00:01Z',
        events: [{ id: 'event-source-1', event_type: 'model_selected', created_at: '2026-10-04T00:00:00Z', payload: {} }],
      }}
      focusRunId="source-run-1"
      onClose={vi.fn()}
    />);

    expect(screen.getByTestId('inspector-execution')).toBeInTheDocument();
    expect(screen.getByText(/Run ID: source-run-1/)).toBeInTheDocument();
    expect(screen.getByText('model_selected')).toBeInTheDocument();
  });

  it('renders routing tab without invented prototype routing data', () => {
    render(
      <InspectorPanel
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('inspector-tab-routing'));
    expect(screen.getByText(/Effective routing profile is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/Model C/i)).not.toBeInTheDocument();
  });

  it('renders persisted parent and specialist routing plus blocked fallback events', () => {
    render(<InspectorPanel
      effectiveRouting={{ profile: { id: 'p', name: 'Private', version: 4, is_active: true, is_default: true, global_privacy_policy: 'local_only', global_fallback_policy: 'none', cost_preference: 'normal', latency_preference: 'normal', routes: {} }, winning_scope: 'project' }}
      routingData={[
        { run_id: 'root-run', snapshot: { role: 'root', profile_id: 'p', profile_version: 4, winning_scope: 'project', privacy_policy: 'local_only', fallback_policy: 'none' }, model_selection: { provider: 'ollama', model: 'root-model', context_window: 8192, estimated_input_tokens: 2048, reserved_output_tokens: 1024, requires_vision: true, required_capabilities: ['code_graph'] }, reasoning_selection: { selected_effort: 'medium' }, memory_privacy_sources: [{ memory_id: 'memory-profile-1', privacy_policy: 'local_only' }], fallback_events: [] },
        { run_id: 'child-run', parent_run_id: 'root-run', snapshot: { role: 'research', profile_id: 'p', profile_version: 4, winning_scope: 'project', privacy_policy: 'local_only', fallback_policy: 'none' }, model_selection: { provider: 'ollama', model: 'research-model' }, context_manifest: { required_tool_capabilities: ['code_graph.read'], resolved_tool_names: ['read_workspace_file'] }, reasoning_selection: { selected_effort: 'high' }, fallback_events: [{ event_type: 'fallback_blocked', payload: { reason: 'local_only boundary' } }] },
      ]}
      onClose={vi.fn()}
    />);
    fireEvent.click(screen.getByTestId('inspector-tab-routing'));
    expect(screen.getByText('root routing')).toBeInTheDocument();
    expect(screen.getByText('research routing')).toBeInTheDocument();
    expect(screen.getByText('ollama:research-model')).toBeInTheDocument();
    expect(screen.getByText('code_graph.read')).toBeInTheDocument();
    expect(screen.getByText('read_workspace_file')).toBeInTheDocument();
    expect(screen.getByText('code_graph · vision')).toBeInTheDocument();
    expect(screen.getByText('memory-profile-1 · local_only')).toBeInTheDocument();
    expect(screen.getByText((text) => text.replace(/[.,]/g, '') === '2048 input + 1024 reserved / 8192 tokens')).toBeInTheDocument();
    expect(screen.getByText('fallback_blocked')).toBeInTheDocument();
    expect(screen.getByText('local_only boundary')).toBeInTheDocument();
    expect(screen.getByText(/Persisted routing decisions/i)).toBeInTheDocument();
  });

  it('renders the persisted compiled context manifest without exposing source text', () => {
    const onContextSelect = vi.fn();
    const runDetail: RunDetail = {
      ...sampleRunDetail,
      events: [...sampleRunDetail.events, {
        id: 'context-compiled-1',
        event_type: 'context_compiled',
        created_at: new Date().toISOString(),
        payload: {
          project_name: 'Atlas',
          estimated_tokens: 128,
          character_count: 511,
          privacy_requirement: 'confidential',
          privacy_sources: [{ object_id: 'selected-bridge', privacy_policy: 'local_only' }],
          required_capabilities: ['code_graph.read'],
          capability_requirements: { requires_tools: true, requires_vision: false },
          objects: [
            { object_id: 'selected-context-set', object_type: 'context_set', selected_by_user: true, source_object_ids: ['source-note-1'] },
            { object_id: 'source-note-1', object_type: 'manual_note', selected_by_user: false },
            { object_id: 'selected-bridge', object_type: 'context_bridge', selected_by_user: true, selected_sections: { conclusions: true, failed: false } },
          ],
          prompt_text: 'This private source text must not be shown in the Inspector.',
        },
      }],
    };

    render(<InspectorPanel runDetail={runDetail} onClose={vi.fn()} onContextSelect={onContextSelect} />);
    fireEvent.click(screen.getByTestId('inspector-tab-context'));

    expect(screen.getByText('1 compiled manifest')).toBeInTheDocument();
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('3 compiled objects across the run tree')).toBeInTheDocument();
    expect(screen.getByText('confidential')).toBeInTheDocument();
    expect(screen.getByText('selected-bridge · local_only')).toBeInTheDocument();
    expect(screen.getByText('code_graph.read · tools')).toBeInTheDocument();
    expect(screen.getByText('selected-context-set')).toBeInTheDocument();
    expect(screen.getByText('Provenance links: source-note-1')).toBeInTheDocument();
    expect(screen.getByText('Bridge sections: conclusions')).toBeInTheDocument();
    expect(screen.queryByText(/private source text/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /selected-context-set/i }));
    expect(onContextSelect).toHaveBeenCalledWith('selected-context-set');
  });

  it('shows tiered saved memory provenance and opens a known memory for review', () => {
    const profileMemory: MemoryItem = {
      id: 'profile-memory-1',
      key: 'preferred_work_style',
      memory_type: 'profile',
      is_active: true,
      content: 'Private profile memory content.',
      confidence: 0.9,
      created_at: new Date().toISOString(),
    };
    const runDetail: RunDetail = {
      ...sampleRunDetail,
      events: [...sampleRunDetail.events, {
        id: 'context-loaded-1',
        event_type: 'context_loaded',
        created_at: new Date().toISOString(),
        payload: {
          profile_memory_ids: ['profile-memory-1'],
          project_memory_ids: ['mem-1'],
          semantic_memory_ids: ['semantic-memory-1'],
          episode_memory_ids: ['episode-memory-1'],
          memory_privacy_sources: [{ memory_id: 'mem-1', privacy_policy: 'confidential' }],
          memory_text: 'Private trace memory content.',
        },
      }],
    };

    render(<InspectorPanel runDetail={runDetail} memories={sampleMemories} profileMemories={[profileMemory]} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('inspector-tab-context'));

    expect(screen.getByText('Saved memories used')).toBeInTheDocument();
    expect(screen.getByText('Profile memory')).toBeInTheDocument();
    expect(screen.getByText('Project memory')).toBeInTheDocument();
    expect(screen.getByText('Semantic memory')).toBeInTheDocument();
    expect(screen.getByText('Episode memory')).toBeInTheDocument();
    expect(screen.getByText('project_architecture_thesis')).toBeInTheDocument();
    expect(screen.getByText(/confidential/)).toBeInTheDocument();
    expect(screen.queryByText(/Private trace memory content/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Private profile memory content/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Review memory project_architecture_thesis' }));
    expect(screen.getByText(/AURA workspace maintains explicit project-level context manifests/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Hide provenance' })).toBeInTheDocument();
  });

  it('shows context manifests for the root and specialist runs', () => {
    render(<InspectorPanel
      runDetail={sampleRunDetail}
      routingData={[
        { run_id: 'root-context-run', snapshot: { role: 'root' }, context_manifest: {
          estimated_tokens: 80,
          objects: [{ object_id: 'root-note', object_type: 'manual_note', selected_by_user: true }],
        }, fallback_events: [] },
        { run_id: 'research-context-run', parent_run_id: 'root-context-run', snapshot: { role: 'research' }, context_manifest: {
          estimated_tokens: 160,
          objects: [
            { object_id: 'research-bridge', object_type: 'context_bridge', selected_by_user: true },
            { object_id: 'paper-evidence', object_type: 'research_evidence', selected_by_user: false },
          ],
        }, fallback_events: [] },
      ]}
      onClose={vi.fn()}
    />);
    fireEvent.click(screen.getByTestId('inspector-tab-context'));

    expect(screen.getByText('2 compiled manifests')).toBeInTheDocument();
    expect(screen.getByText('3 compiled objects across the run tree')).toBeInTheDocument();
    expect(screen.getByText(/root · root-conte/i)).toBeInTheDocument();
    expect(screen.getByText(/research · research-co/i)).toBeInTheDocument();
    expect(screen.getByText('research-bridge')).toBeInTheDocument();
    expect(screen.getByText('paper-evidence')).toBeInTheDocument();
  });

  it('loads and displays sanitized capability provider metadata on demand', async () => {
    const fetchProviders = vi.spyOn(api, 'fetchCapabilityProviders').mockResolvedValue({
      providers: [{
        provider_id: 'aura.workspace',
        name: 'AURA Workspace',
        version: null,
        health: 'unknown',
        health_checked_at: null,
        enabled: true,
        capabilities: ['workspace.read', 'code_graph.query'],
        capability_tools: {},
        declared_capability_tools: { 'code_graph.query': ['mcp_graph_symbol_search'] },
        privacy_boundary: 'local',
        network_requirement: 'unknown',
        data_touched: null,
        permissions: null,
        approval_requirement: 'unknown',
      }],
    });
    render(<InspectorPanel onClose={vi.fn()} />);
    expect(fetchProviders).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('inspector-tab-capabilities'));
    await waitFor(() => expect(fetchProviders).toHaveBeenCalledOnce());
    expect(screen.getByText(/refresh checks tool discovery only/i)).toBeInTheDocument();
    expect(await screen.findByText('AURA Workspace')).toBeInTheDocument();
    expect(screen.getByText('aura.workspace')).toBeInTheDocument();
    expect(screen.getByText('Local')).toBeInTheDocument();
    expect(screen.getByText('workspace.read · code_graph.query')).toBeInTheDocument();
    expect(screen.getByText('Configured capability → AURA tools')).toBeInTheDocument();
    expect(screen.getByText('Verified available capability → AURA tools')).toBeInTheDocument();
    expect(screen.getByText('mcp_graph_symbol_search')).toBeInTheDocument();
    expect(screen.getByText('No tools verified available')).toBeInTheDocument();
    expect(screen.getAllByText('Unknown').length).toBeGreaterThan(1);
    expect(screen.queryByText(/endpoint|credential|secret/i)).not.toBeInTheDocument();
  });

  it('lets users deactivate and restore project memories', async () => {
    const onSetMemoryActive = vi.fn().mockResolvedValue(undefined);
    const projectMemory = { ...sampleMemories[0], memory_type: 'project', is_active: true };
    const { rerender } = render(
      <InspectorPanel memories={[projectMemory]} onSetMemoryActive={onSetMemoryActive} onClose={vi.fn()} />
    );
    fireEvent.click(screen.getByTestId('inspector-tab-memory'));
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate memory' }));
    await waitFor(() => expect(onSetMemoryActive).toHaveBeenCalledWith(projectMemory, false));

    const archivedMemory = { ...projectMemory, is_active: false };
    rerender(
      <InspectorPanel memories={[archivedMemory]} onSetMemoryActive={onSetMemoryActive} onClose={vi.fn()} />
    );
    fireEvent.click(screen.getByRole('button', { name: 'Restore memory' }));
    await waitFor(() => expect(onSetMemoryActive).toHaveBeenLastCalledWith(archivedMemory, true));
  });

  it('loads and manages cross-project profile memories separately', async () => {
    const onLoadProfileMemories = vi.fn().mockResolvedValue(undefined);
    const onSetMemoryActive = vi.fn().mockResolvedValue(undefined);
    const profileMemory: MemoryItem = {
      id: 'profile-1', key: 'preferred_language', memory_type: 'profile',
      content: 'Vietnamese', confidence: 1, is_active: true, created_at: new Date().toISOString(),
    };
    const { rerender } = render(
      <InspectorPanel
        memories={sampleMemories}
        profileMemories={null}
        onLoadProfileMemories={onLoadProfileMemories}
        onSetMemoryActive={onSetMemoryActive}
        onClose={vi.fn()}
      />
    );
    fireEvent.click(screen.getByTestId('inspector-tab-memory'));
    fireEvent.click(screen.getByRole('button', { name: 'Personal profile' }));
    expect(onLoadProfileMemories).toHaveBeenCalled();
    expect(screen.getByText(/Loading personal memories/)).toBeInTheDocument();
    rerender(
      <InspectorPanel
        memories={sampleMemories}
        profileMemories={[profileMemory]}
        onLoadProfileMemories={onLoadProfileMemories}
        onSetMemoryActive={onSetMemoryActive}
        onClose={vi.fn()}
      />
    );
    expect(screen.getByText('preferred_language')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Deactivate memory' }));
    await waitFor(() => expect(onSetMemoryActive).toHaveBeenCalledWith(profileMemory, false));
  });

  it('refreshes MCP provider health without invoking a provider tool', async () => {
    vi.spyOn(api, 'fetchCapabilityProviders').mockResolvedValue({
      providers: [{
        provider_id: 'mcp.codegraph',
        name: 'CodeGraph MCP',
        version: '0.20.1',
        health: 'unavailable',
        health_checked_at: null,
        enabled: true,
        capabilities: ['code_graph.query'],
        capability_tools: {},
        declared_capability_tools: { 'code_graph.query': ['mcp_codegraph_codegraph_symbol_search'] },
        privacy_boundary: 'local',
        network_requirement: 'unknown',
        data_touched: ['repository_source'],
        permissions: ['read'],
        approval_requirement: 'per_tool_policy',
      }],
    });
    const refreshProvider = vi.spyOn(api, 'refreshCapabilityProvider').mockResolvedValue({
      provider_id: 'mcp.codegraph',
      name: 'CodeGraph MCP',
      version: '0.20.1',
      health: 'healthy',
      health_checked_at: '2026-10-04T14:00:00Z',
      enabled: true,
      capabilities: ['code_graph.query'],
      capability_tools: { 'code_graph.query': ['mcp_codegraph_codegraph_symbol_search'] },
      declared_capability_tools: { 'code_graph.query': ['mcp_codegraph_codegraph_symbol_search'] },
      privacy_boundary: 'local',
      network_requirement: 'unknown',
      data_touched: ['repository_source'],
      permissions: ['read'],
      approval_requirement: 'per_tool_policy',
    });
    render(<InspectorPanel onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('inspector-tab-capabilities'));
    expect(await screen.findByText('Unavailable')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh health for CodeGraph MCP' }));
    await waitFor(() => expect(refreshProvider).toHaveBeenCalledWith('mcp.codegraph'));
    expect(await screen.findByText('Healthy')).toBeInTheDocument();
  });

  it('does not invent context usage when a run has no compiled manifest event', () => {
    render(<InspectorPanel runDetail={sampleRunDetail} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('inspector-tab-context'));
    expect(screen.getByText('Not recorded')).toBeInTheDocument();
    expect(screen.getByText('No compiled context manifest is recorded for this run.')).toBeInTheDocument();
    expect(screen.queryByText('Root synthesis')).not.toBeInTheDocument();
  });
});
