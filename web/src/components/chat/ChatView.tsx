import React, { useState, useRef, useEffect } from 'react'
import { ApprovalDetail, ChatMessage } from '../../types'
import { ApprovalCard } from '../approvals/ApprovalCard'
import { Send, PanelRight, Bot, User, Loader2, AlertCircle } from 'lucide-react'

interface ChatViewProps {
  messages: ChatMessage[]
  activeSessionId: string | null
  activeProjectName: string
  selectedModelOverride: string | null
  currentRunStatus: string | null
  currentApproval: ApprovalDetail | null
  isInspectorOpen: boolean
  onToggleInspector: () => void
  onSendMessage: (message: string) => Promise<void>
  onApprovalDecision: (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => Promise<void>
}

export const ChatView: React.FC<ChatViewProps> = ({
  messages,
  activeSessionId,
  activeProjectName,
  selectedModelOverride,
  currentRunStatus,
  currentApproval,
  isInspectorOpen,
  onToggleInspector,
  onSendMessage,
  onApprovalDecision,
}) => {
  const [inputText, setInputText] = useState('')
  const [isSending, setIsSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, currentRunStatus])

  const handleSend = async () => {
    if (!inputText.trim() || isSending) return
    const msg = inputText
    setInputText('')
    setIsSending(true)
    try {
      await onSendMessage(msg)
    } finally {
      setIsSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Model badge formatting
  const renderModelBadge = () => {
    if (!selectedModelOverride) {
      return <span className="app-badge">AUTO ROUTING</span>
    }
    const [prov, ...rest] = selectedModelOverride.split(':')
    const model = rest.join(':')
    const isLocal = prov === 'ollama' || prov === 'lmstudio'
    return (
      <span className="active-model-pill">
        <span className={isLocal ? 'badge-privacy-local' : 'badge-privacy-cloud'}>
          {isLocal ? 'LOCAL' : 'CLOUD'}
        </span>
        <span>{prov.toUpperCase()}</span>
        <span style={{ color: 'var(--text-muted)' }}>·</span>
        <span style={{ color: '#fff' }}>{model}</span>
      </span>
    )
  }

  return (
    <main className="chat-main">
      <header className="chat-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div className="chat-header-title" title={activeSessionId ? `Session: ${activeSessionId}` : undefined}>
            {activeProjectName ? `Project: ${activeProjectName}` : 'General Workspace'}
          </div>
          {renderModelBadge()}
        </div>

        <button
          type="button"
          onClick={onToggleInspector}
          style={{
            background: 'none',
            border: '1px solid var(--border-color)',
            color: isInspectorOpen ? 'var(--accent-blue)' : 'var(--text-secondary)',
            borderRadius: 6,
            padding: '6px 10px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 12,
          }}
          title="Toggle Inspection Panel"
        >
          <PanelRight size={14} />
          <span>Inspector</span>
        </button>
      </header>

      <div className="chat-messages">
        {messages.length === 0 ? (
          <div style={{ textAlign: 'center', margin: 'auto 0', color: 'var(--text-muted)' }}>
            <Bot size={40} style={{ margin: '0 auto 12px auto', opacity: 0.3 }} />
            <h3 style={{ color: 'var(--text-secondary)', marginBottom: 6 }}>Ready for instructions</h3>
            <p style={{ fontSize: 13, maxWidth: 450, margin: '0 auto' }}>
              Interact with AURA directly. You can delegate research, run coding tasks, or inspect model
              decisions and tool execution in real-time.
            </p>
          </div>
        ) : (
          messages.map((m, idx) => (
            <div key={idx} className={`message-turn ${m.role}`}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                {m.role === 'user' ? <User size={12} /> : <Bot size={12} color="var(--accent-blue)" />}
                <span>{m.role === 'user' ? 'You' : 'AURA Assistant'}</span>
              </div>
              <div className="message-bubble" style={{ whiteSpace: 'pre-wrap' }}>
                {m.content}
              </div>
            </div>
          ))
        )}

        {currentRunStatus === 'running' && (
          <div className="message-turn assistant">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', padding: '8px 12px' }}>
              <Loader2 size={16} className="animate-spin" color="var(--accent-blue)" />
              <span style={{ fontSize: 13 }}>Agent thinking and executing tools...</span>
            </div>
          </div>
        )}

        {currentRunStatus === 'failed' && (
          <div style={{ margin: '8px 0', padding: '10px 14px', backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.3)', borderRadius: 6, color: '#f87171', display: 'flex', alignItems: 'center', gap: 8 }}>
            <AlertCircle size={16} />
            <span style={{ fontSize: 13 }}>Run failed or returned an execution error. Check inspector for details.</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {currentApproval && currentRunStatus === 'waiting_for_approval' && (
        <ApprovalCard approval={currentApproval} onDecision={onApprovalDecision} />
      )}

      <div className="chat-input-container">
        <div className="chat-input-box">
          <textarea
            className="chat-textarea"
            placeholder="Type your message or instruction for AURA... (Enter to send, Shift+Enter for newline)"
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isSending || currentRunStatus === 'running' || currentRunStatus === 'waiting_for_approval'}
          />
          <div className="chat-input-footer">
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {selectedModelOverride ? `Targeting: ${selectedModelOverride}` : 'Routing: Auto'}
            </div>
            <button
              type="button"
              className="btn-send"
              onClick={handleSend}
              disabled={!inputText.trim() || isSending || currentRunStatus === 'running' || currentRunStatus === 'waiting_for_approval'}
            >
              {isSending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              <span>Send</span>
            </button>
          </div>
        </div>
      </div>
    </main>
  )
}
