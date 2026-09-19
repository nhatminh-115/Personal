import React from 'react'
import { ModelCatalog, SessionSummary } from '../../types'
import { ModelPicker } from '../model/ModelPicker'
import { Plus, MessageSquare, Bot } from 'lucide-react'

interface SidebarProps {
  sessions: SessionSummary[]
  activeSessionId: string | null
  activeProjectName: string
  catalog: ModelCatalog
  selectedModelOverride: string | null
  onNewChat: () => void
  onSelectSession: (id: string) => void
  onProjectChange: (name: string) => void
  onSelectModel: (override: string | null) => void
  onCatalogRefresh: (catalog: ModelCatalog) => void
}

export const Sidebar: React.FC<SidebarProps> = ({
  sessions,
  activeSessionId,
  activeProjectName,
  catalog,
  selectedModelOverride,
  onNewChat,
  onSelectSession,
  onProjectChange,
  onSelectModel,
  onCatalogRefresh,
}) => {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div className="app-brand">
          <Bot size={20} color="var(--accent-blue)" />
          <span>AURA</span>
          <span className="app-badge">DEV</span>
        </div>
      </div>

      <button type="button" className="btn-new-chat" onClick={onNewChat}>
        <Plus size={16} />
        <span>New Conversation</span>
      </button>

      <div className="project-select-container">
        <label htmlFor="project-scope-input" className="project-select-label">
          Project Context Scope
        </label>
        <input
          id="project-scope-input"
          type="text"
          className="project-select-input"
          placeholder="e.g. Atlas_Architecture"
          value={activeProjectName}
          onChange={(e) => onProjectChange(e.target.value)}
        />
      </div>

      <div className="session-list">
        <div
          style={{
            fontSize: 11,
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            color: 'var(--text-muted)',
            padding: '4px 6px',
            marginBottom: 4,
          }}
        >
          Conversations ({sessions.length})
        </div>

        {sessions.length === 0 ? (
          <div style={{ padding: '12px 8px', fontSize: 12, color: 'var(--text-muted)' }}>
            No past sessions recorded
          </div>
        ) : (
          sessions.map((s) => (
            <div
              key={s.id}
              className={`session-item ${s.id === activeSessionId ? 'active' : ''}`}
              onClick={() => onSelectSession(s.id)}
              title={s.title || s.id}
            >
              <span style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
                <MessageSquare size={13} style={{ opacity: 0.6, flexShrink: 0 }} />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {s.title || `Session ${s.id.slice(0, 8)}`}
                </span>
              </span>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        <div style={{ marginBottom: 8 }}>
          <div
            style={{
              fontSize: 11,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              color: 'var(--text-muted)',
              marginBottom: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span>Model Selection</span>
          </div>
          <ModelPicker
            catalog={catalog}
            selectedOverride={selectedModelOverride}
            onSelectModel={onSelectModel}
            onCatalogRefresh={onCatalogRefresh}
          />
        </div>
      </div>
    </aside>
  )
}
