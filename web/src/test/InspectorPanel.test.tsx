import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { InspectorPanel } from '../components/layout/InspectorPanel';
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
    content: 'AURA workspace maintains explicit project-level context manifests.',
    confidence: 0.98,
    created_at: new Date().toISOString(),
  },
];

describe('InspectorPanel Component', () => {
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
        { run_id: 'root-run', snapshot: { role: 'root', profile_id: 'p', profile_version: 4, winning_scope: 'project', privacy_policy: 'local_only', fallback_policy: 'none' }, model_selection: { provider: 'ollama', model: 'root-model', context_window: 8192, estimated_input_tokens: 2048, reserved_output_tokens: 1024, requires_vision: true, required_capabilities: ['code_graph'] }, reasoning_selection: { selected_effort: 'medium' }, fallback_events: [] },
        { run_id: 'child-run', parent_run_id: 'root-run', snapshot: { role: 'research', profile_id: 'p', profile_version: 4, winning_scope: 'project', privacy_policy: 'local_only', fallback_policy: 'none' }, model_selection: { provider: 'ollama', model: 'research-model' }, reasoning_selection: { selected_effort: 'high' }, fallback_events: [{ event_type: 'fallback_blocked', payload: { reason: 'local_only boundary' } }] },
      ]}
      onClose={vi.fn()}
    />);
    fireEvent.click(screen.getByTestId('inspector-tab-routing'));
    expect(screen.getByText('root routing')).toBeInTheDocument();
    expect(screen.getByText('research routing')).toBeInTheDocument();
    expect(screen.getByText('ollama:research-model')).toBeInTheDocument();
    expect(screen.getByText('code_graph · vision')).toBeInTheDocument();
    expect(screen.getByText('2,048 input + 1,024 reserved / 8,192 tokens')).toBeInTheDocument();
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
    expect(screen.getByText('code_graph.read · tools')).toBeInTheDocument();
    expect(screen.getByText('selected-context-set')).toBeInTheDocument();
    expect(screen.getByText('Provenance links: source-note-1')).toBeInTheDocument();
    expect(screen.getByText('Bridge sections: conclusions')).toBeInTheDocument();
    expect(screen.queryByText(/private source text/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /selected-context-set/i }));
    expect(onContextSelect).toHaveBeenCalledWith('selected-context-set');
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

  it('does not invent context usage when a run has no compiled manifest event', () => {
    render(<InspectorPanel runDetail={sampleRunDetail} onClose={vi.fn()} />);
    fireEvent.click(screen.getByTestId('inspector-tab-context'));
    expect(screen.getByText('Not recorded')).toBeInTheDocument();
    expect(screen.getByText('No compiled context manifest is recorded for this run.')).toBeInTheDocument();
    expect(screen.queryByText('Root synthesis')).not.toBeInTheDocument();
  });
});
