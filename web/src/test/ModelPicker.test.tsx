import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ModelPicker } from '../components/model/ModelPicker'
import { ModelCatalog } from '../types'

const sampleCatalog: ModelCatalog = {
  providers: [
    {
      id: 'ollama',
      label: 'Ollama',
      kind: 'local',
      available: true,
      base_url: 'http://127.0.0.1:11434/v1',
      models: [
        {
          id: 'llama3.2:3b',
          label: 'llama3.2:3b',
          capabilities: ['general', 'code', 'local'],
          tool_support: 'supported',
        },
        {
          id: 'custom-experimental:latest',
          label: 'custom-experimental:latest',
          capabilities: ['general'],
          tool_support: 'unknown',
        },
      ],
      privacy_status: 'local',
    },
    {
      id: 'lmstudio',
      label: 'LM Studio',
      kind: 'local',
      available: false,
      base_url: 'http://127.0.0.1:1234/v1',
      models: [],
      privacy_status: 'local',
    },
    {
      id: 'openai',
      label: 'OpenAI',
      kind: 'cloud',
      available: true,
      base_url: 'https://api.openai.com/v1',
      models: [
        {
          id: 'gpt-4o-mini',
          label: 'gpt-4o-mini',
          capabilities: ['general', 'code', 'reasoning'],
          tool_support: 'supported',
        },
      ],
      privacy_status: 'cloud',
    },
  ],
}

describe('ModelPicker Component', () => {
  it('renders Auto routing by default and displays trigger', () => {
    render(
      <ModelPicker
        catalog={sampleCatalog}
        selectedOverride={null}
        onSelectModel={vi.fn()}
        onCatalogRefresh={vi.fn()}
      />
    )

    expect(screen.getByText('AUTO')).toBeInTheDocument()
    expect(screen.getByText('Auto (AURA Dynamic Routing)')).toBeInTheDocument()
  })

  it('renders provider groups, models, and handles unavailable state when opened', () => {
    render(
      <ModelPicker
        catalog={sampleCatalog}
        selectedOverride={null}
        onSelectModel={vi.fn()}
        onCatalogRefresh={vi.fn()}
      />
    )

    // Open dropdown
    fireEvent.click(screen.getByRole('button', { name: /Select Model/i }))

    // Check group headers
    expect(screen.getByText('Local Runtimes')).toBeInTheDocument()
    expect(screen.getByText('Cloud Providers')).toBeInTheDocument()

    // Check Ollama available models & tool badges
    expect(screen.getByText('llama3.2:3b')).toBeInTheDocument()
    expect(screen.getByText('✓ Tool Calls')).toBeInTheDocument()
    expect(screen.getByText('custom-experimental:latest')).toBeInTheDocument()
    expect(screen.getByText('? Experimental')).toBeInTheDocument()

    // Check LM Studio unavailable state
    expect(screen.getByText('LM Studio')).toBeInTheDocument()
    expect(screen.getByText('Offline')).toBeInTheDocument()

    // Check OpenAI cloud models
    expect(screen.getByText('gpt-4o-mini')).toBeInTheDocument()
  })

  it('invokes onSelectModel with provider:model when a specific model is chosen', () => {
    const onSelectMock = vi.fn()
    render(
      <ModelPicker
        catalog={sampleCatalog}
        selectedOverride={null}
        onSelectModel={onSelectMock}
        onCatalogRefresh={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Select Model/i }))
    fireEvent.click(screen.getByText('llama3.2:3b'))

    expect(onSelectMock).toHaveBeenCalledWith('ollama:llama3.2:3b')
  })

  it('invokes onSelectModel with null when Auto is selected', () => {
    const onSelectMock = vi.fn()
    render(
      <ModelPicker
        catalog={sampleCatalog}
        selectedOverride="ollama:llama3.2:3b"
        onSelectModel={onSelectMock}
        onCatalogRefresh={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Select Model/i }))
    fireEvent.click(screen.getByText('Auto (Adaptive Policy)'))

    expect(onSelectMock).toHaveBeenCalledWith(null)
  })
})
