import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { Inspector } from '../components/inspector/Inspector'
import { MemoryItem, ResearchInspectorData, RunDetail } from '../types'

const sampleRunDetail: RunDetail = {
  id: 'run-100',
  session_id: 'sess-100',
  status: 'completed',
  user_message: 'Investigate architecture',
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  events: [
    {
      id: 'ev-1',
      event_type: 'model_called',
      payload: {
        routing_decision: {
          provider: 'ollama',
          model: 'llama3.2:3b',
          reason: 'explicit_model_override',
        },
      },
      created_at: new Date().toISOString(),
    },
    {
      id: 'ev-2',
      event_type: 'tool_executed',
      payload: {
        tool: 'delegate_task',
        result: { success: true, output: 'Specialist completed' },
      },
      created_at: new Date().toISOString(),
    },
  ],
}

const sampleResearch: ResearchInspectorData = {
  run_id: 'run-100',
  child_run_id: 'run-child-200',
  status: 'completed',
  goal: { user_query: 'Investigate stateful LLM' },
  queries: [{ query_text: 'selective state spaces', results_count: 3 }],
  sources: [
    {
      canonical_id: 'arxiv:2312.00752',
      title: 'Mamba Linear Sequence Modeling',
      year: 2023,
      metadata: { full_text_status: 'available' },
    },
  ],
  inspected_source_ids: ['arxiv:2312.00752'],
  evidence: [
    {
      evidence_id: 'ev_01',
      source_locator: 'Section: methods',
      extracted_text: 'Selective SSM parameterizes input-dependent state transitions.',
      confidence: 0.98,
    },
  ],
  claims: [
    {
      claim_id: 'cl_01',
      claim_text: 'Mamba maintains recurrent internal state during inference.',
      claim_type: 'source_supported_fact',
      evidence_ids: ['ev_01'],
    },
  ],
}

const sampleMemories: MemoryItem[] = [
  {
    id: 'mem-1',
    key: 'finding_mamba',
    content: 'Mamba replaces attention with selective state space.',
    memory_type: 'semantic',
    confidence: 0.95,
    metadata_json: { claim_ids: ['cl_01'] },
    created_at: new Date().toISOString(),
  },
]

describe('Inspector Component', () => {
  it('renders Run timeline events with provider, model, and tool names', () => {
    render(
      <Inspector
        isOpen={true}
        runDetail={sampleRunDetail}
        researchData={null}
        memories={[]}
        onClose={vi.fn()}
      />
    )

    expect(screen.getByText('model_called')).toBeInTheDocument()
    expect(screen.getByText(/llama3.2:3b/i)).toBeInTheDocument()
    expect(screen.getByText(/explicit_model_override/i)).toBeInTheDocument()
    expect(screen.getByText('tool_executed')).toBeInTheDocument()
    expect(screen.getByText(/delegate_task/i)).toBeInTheDocument()
  })

  it('renders Research tab with queries, sources, grounded evidence, and claims', () => {
    render(
      <Inspector
        isOpen={true}
        runDetail={sampleRunDetail}
        researchData={sampleResearch}
        memories={[]}
        onClose={vi.fn()}
      />
    )

    // Switch to Research Tab
    fireEvent.click(screen.getByRole('button', { name: /Research/i }))

    expect(screen.getByText(/selective state spaces/i)).toBeInTheDocument()
    expect(screen.getByText(/Mamba Linear Sequence Modeling/i)).toBeInTheDocument()
    expect(screen.getByText(/Section: methods/i)).toBeInTheDocument()
    expect(screen.getByText(/Selective SSM parameterizes input-dependent state transitions/i)).toBeInTheDocument()
    expect(screen.getByText(/Mamba maintains recurrent internal state during inference/i)).toBeInTheDocument()
    expect(screen.getByText(/source_supported_fact/i)).toBeInTheDocument()
  })

  it('renders Memory tab with read-only project memory and claim lineage', () => {
    render(
      <Inspector
        isOpen={true}
        runDetail={sampleRunDetail}
        researchData={null}
        memories={sampleMemories}
        onClose={vi.fn()}
      />
    )

    // Switch to Memory Tab
    fireEvent.click(screen.getByRole('button', { name: /Memory/i }))

    expect(screen.getByText('finding_mamba')).toBeInTheDocument()
    expect(screen.getByText(/Mamba replaces attention with selective state space/i)).toBeInTheDocument()
    expect(screen.getByText(/Claims: cl_01/i)).toBeInTheDocument()
  })
})
