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
    const toggleButtons = screen.getAllByText(/View raw payload/i);
    expect(toggleButtons.length).toBeGreaterThan(0);
    fireEvent.click(toggleButtons[0]);
    expect(screen.getByText(/Hide payload/i)).toBeInTheDocument();
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

  it('renders routing tab with prototype isolation indication', () => {
    render(
      <InspectorPanel
        onClose={vi.fn()}
      />
    );

    fireEvent.click(screen.getByTestId('inspector-tab-routing'));
    expect(screen.getByText(/Balanced · Session/i)).toBeInTheDocument();
    expect(screen.getByText(/Routing Studio v2 next sprint/i)).toBeInTheDocument();
  });
});
