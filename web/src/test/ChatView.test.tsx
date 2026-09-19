import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { ChatView } from '../components/chat/ChatView'
import { ChatMessage } from '../types'

const sampleMessages: ChatMessage[] = [
  { role: 'user', content: 'Hello AURA', created_at: new Date().toISOString() },
  { role: 'assistant', content: 'Hello! How can I assist you today?', created_at: new Date().toISOString() },
]

describe('ChatView Component', () => {
  it('renders messages and active model badge correctly', () => {
    render(
      <ChatView
        messages={sampleMessages}
        activeSessionId="sess-123"
        activeProjectName="Atlas_Architecture"
        selectedModelOverride="ollama:llama3.2:3b"
        currentRunStatus="completed"
        currentApproval={null}
        isInspectorOpen={true}
        onToggleInspector={vi.fn()}
        onSendMessage={vi.fn()}
        onApprovalDecision={vi.fn()}
      />
    )

    expect(screen.getByText('Hello AURA')).toBeInTheDocument()
    expect(screen.getByText('Hello! How can I assist you today?')).toBeInTheDocument()
    expect(screen.getByText('LOCAL')).toBeInTheDocument()
    expect(screen.getByText('OLLAMA')).toBeInTheDocument()
    expect(screen.getByText('llama3.2:3b')).toBeInTheDocument()
  })

  it('renders AUTO badge when selectedModelOverride is null', () => {
    render(
      <ChatView
        messages={sampleMessages}
        activeSessionId="sess-123"
        activeProjectName="Atlas_Architecture"
        selectedModelOverride={null}
        currentRunStatus="completed"
        currentApproval={null}
        isInspectorOpen={true}
        onToggleInspector={vi.fn()}
        onSendMessage={vi.fn()}
        onApprovalDecision={vi.fn()}
      />
    )

    expect(screen.getByText('AUTO ROUTING')).toBeInTheDocument()
  })

  it('sends user message when typing and clicking send', async () => {
    const onSendMock = vi.fn().mockResolvedValue(undefined)
    render(
      <ChatView
        messages={[]}
        activeSessionId="sess-123"
        activeProjectName="Atlas_Architecture"
        selectedModelOverride={null}
        currentRunStatus={null}
        currentApproval={null}
        isInspectorOpen={true}
        onToggleInspector={vi.fn()}
        onSendMessage={onSendMock}
        onApprovalDecision={vi.fn()}
      />
    )

    const textarea = screen.getByPlaceholderText(/Type your message or instruction for AURA/i)
    fireEvent.change(textarea, { target: { value: 'Investigate transformers' } })

    const sendBtn = screen.getByRole('button', { name: /Send/i })
    await act(async () => {
      fireEvent.click(sendBtn)
    })

    expect(onSendMock).toHaveBeenCalledWith('Investigate transformers')
  })
})
