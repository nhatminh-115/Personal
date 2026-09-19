import React, { useState } from 'react'
import { MemoryItem, ResearchInspectorData, RunDetail } from '../../types'
import { X, Clock, Wrench, Search, Database, CheckCircle2 } from 'lucide-react'

interface InspectorProps {
  isOpen: boolean
  runDetail: RunDetail | null
  researchData: ResearchInspectorData | null
  memories: MemoryItem[]
  onClose: () => void
}

type TabType = 'run' | 'tools' | 'research' | 'memory'

export const Inspector: React.FC<InspectorProps> = ({
  isOpen,
  runDetail,
  researchData,
  memories,
  onClose,
}) => {
  const [activeTab, setActiveTab] = useState<TabType>('run')

  if (!isOpen) {
    return <aside className="inspector collapsed" />
  }

  // Filter tool execution events for Tools tab
  const toolEvents = (runDetail?.events || []).filter(
    (e) => e.event_type === 'tool_executed' || e.event_type === 'tool_requested'
  )

  return (
    <aside className="inspector">
      <div className="inspector-header">
        <div className="inspector-title">Inspector & Provenance</div>
        <button
          type="button"
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
          }}
          title="Close Inspector"
        >
          <X size={16} />
        </button>
      </div>

      <nav className="inspector-tabs" aria-label="Inspector Tabs">
        <button
          type="button"
          className={`inspector-tab ${activeTab === 'run' ? 'active' : ''}`}
          onClick={() => setActiveTab('run')}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Clock size={12} /> Run
          </span>
        </button>
        <button
          type="button"
          className={`inspector-tab ${activeTab === 'tools' ? 'active' : ''}`}
          onClick={() => setActiveTab('tools')}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Wrench size={12} /> Tools ({toolEvents.length})
          </span>
        </button>
        <button
          type="button"
          className={`inspector-tab ${activeTab === 'research' ? 'active' : ''}`}
          onClick={() => setActiveTab('research')}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Search size={12} /> Research
          </span>
        </button>
        <button
          type="button"
          className={`inspector-tab ${activeTab === 'memory' ? 'active' : ''}`}
          onClick={() => setActiveTab('memory')}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Database size={12} /> Memory ({memories.length})
          </span>
        </button>
      </nav>

      <div className="inspector-content">
        {/* TAB 1: RUN TIMELINE */}
        {activeTab === 'run' && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
              Chronological Audit Trail ({runDetail ? runDetail.events.length : 0} events)
            </div>

            {!runDetail || runDetail.events.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No execution events recorded yet.</div>
            ) : (
              runDetail.events.map((e, idx) => {
                const routing = e.payload?.routing_decision
                const isModelCall = e.event_type === 'model_called'
                const isToolExec = e.event_type === 'tool_executed'

                return (
                  <div key={idx} className="timeline-event">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span className="event-type">{e.event_type}</span>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        {new Date(e.created_at).toLocaleTimeString()}
                      </span>
                    </div>

                    {isModelCall && routing && (
                      <div className="event-details" style={{ marginTop: 4 }}>
                        <div><strong>Provider:</strong> {routing.provider}</div>
                        <div><strong>Model:</strong> {routing.model}</div>
                        <div><strong>Reason:</strong> {routing.reason}</div>
                      </div>
                    )}

                    {isToolExec && (
                      <div className="event-details" style={{ marginTop: 4 }}>
                        <div><strong>Tool:</strong> <code>{e.payload?.tool}</code></div>
                        {e.payload?.result && (
                          <div style={{ fontSize: 11, color: e.payload.result.success ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                            {e.payload.result.success ? '✓ Succeeded' : '✕ Failed'}
                          </div>
                        )}
                      </div>
                    )}

                    {!isModelCall && !isToolExec && (
                      <div className="event-details" style={{ marginTop: 4, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                        {JSON.stringify(e.payload)}
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>
        )}

        {/* TAB 2: TOOLS */}
        {activeTab === 'tools' && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
              Executed Tools & Results
            </div>

            {toolEvents.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No tool executions in this turn.</div>
            ) : (
              toolEvents.map((e, idx) => (
                <div key={idx} className="timeline-event">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, color: '#fff' }}>{e.payload?.tool || 'Unknown Tool'}</span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {new Date(e.created_at).toLocaleTimeString()}
                    </span>
                  </div>

                  {e.payload?.arguments && (
                    <div style={{ marginBottom: 6 }}>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>INPUT:</div>
                      <pre style={{ fontSize: 11, fontFamily: 'var(--font-mono)', backgroundColor: '#070b14', padding: 6, borderRadius: 4, overflowX: 'auto' }}>
                        {JSON.stringify(e.payload.arguments, null, 2)}
                      </pre>
                    </div>
                  )}

                  {e.payload?.result && (
                    <div>
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>RESULT:</div>
                      <pre style={{ fontSize: 11, fontFamily: 'var(--font-mono)', backgroundColor: '#070b14', padding: 6, borderRadius: 4, overflowX: 'auto', maxHeight: 150 }}>
                        {typeof e.payload.result.output === 'string'
                          ? e.payload.result.output
                          : JSON.stringify(e.payload.result, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* TAB 3: RESEARCH SPECIALIST */}
        {activeTab === 'research' && (
          <div>
            {!researchData || researchData.status === 'none' ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>
                No active Research Specialist child run for this turn.
              </div>
            ) : (
              <div>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                  <span style={{ fontSize: 12, fontWeight: 600 }}>Specialist Synthesis</span>
                  <span className="claim-pill">Status: {researchData.status}</span>
                </div>

                {researchData.goal && (
                  <div className="research-card">
                    <div className="research-card-title">Research Goal</div>
                    <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      {researchData.goal.user_query}
                    </div>
                  </div>
                )}

                {/* Queries */}
                <div style={{ marginTop: 12, marginBottom: 6, fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Model-Generated Queries ({researchData.queries.length})
                </div>
                {researchData.queries.map((q, idx) => (
                  <div key={idx} style={{ fontSize: 12, padding: '4px 8px', backgroundColor: 'var(--bg-secondary)', borderRadius: 4, marginBottom: 4 }}>
                    • "{q.query_text}" <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>({q.results_count ?? 0} hits)</span>
                  </div>
                ))}

                {/* Sources */}
                <div style={{ marginTop: 14, marginBottom: 6, fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Discovered Sources ({researchData.sources.length})
                </div>
                {researchData.sources.map((s, idx) => (
                  <div key={idx} className="research-card">
                    <div style={{ fontWeight: 500, fontSize: 12, color: '#fff' }}>{s.title}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                      {s.canonical_id} {s.year ? `(${s.year})` : ''}
                    </div>
                    {s.metadata?.full_text_status && (
                      <div style={{ fontSize: 10, color: 'var(--accent-cyan)', marginTop: 2 }}>
                        Full text: {s.metadata.full_text_status}
                      </div>
                    )}
                  </div>
                ))}

                {/* Evidence */}
                <div style={{ marginTop: 14, marginBottom: 6, fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Grounded Evidence ({researchData.evidence.length})
                </div>
                {researchData.evidence.map((ev, idx) => (
                  <div key={idx} className="research-card">
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11 }}>
                      <span style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>{ev.evidence_id}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{ev.source_locator}</span>
                    </div>
                    <div className="research-excerpt">"{ev.extracted_text}"</div>
                    {ev.confidence && (
                      <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>Confidence: {(ev.confidence * 100).toFixed(0)}%</div>
                    )}
                  </div>
                ))}

                {/* Claims */}
                <div style={{ marginTop: 14, marginBottom: 6, fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase' }}>
                  Validated Claims ({researchData.claims.length})
                </div>
                {researchData.claims.map((cl, idx) => (
                  <div key={idx} className="research-card">
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <CheckCircle2 size={13} color="var(--accent-green)" />
                      <span style={{ fontSize: 11, fontWeight: 600, color: '#fff' }}>{cl.claim_id}</span>
                      <span className="app-badge" style={{ fontSize: 9 }}>{cl.claim_type}</span>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-primary)' }}>{cl.claim_text}</div>
                    {cl.evidence_ids && (
                      <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                        Cites: {cl.evidence_ids.join(', ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* TAB 4: PROJECT MEMORY */}
        {activeTab === 'memory' && (
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 10 }}>
              Read-Only Project Memories ({memories.length})
            </div>

            {memories.length === 0 ? (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No memories stored for this scope.</div>
            ) : (
              memories.map((m) => (
                <div key={m.id} className="research-card">
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--accent-purple)', fontWeight: 600 }}>
                      {m.key}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {new Date(m.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text-primary)', marginBottom: 6 }}>{m.content}</div>

                  {m.metadata_json && (
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', backgroundColor: 'rgba(0,0,0,0.2)', padding: '4px 6px', borderRadius: 4 }}>
                      {m.metadata_json.claim_ids && <div>Claims: {m.metadata_json.claim_ids.join(', ')}</div>}
                      {m.metadata_json.sources_cited && <div>Sources: {m.metadata_json.sources_cited.join(', ')}</div>}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  )
}
