import {
  Box,
  Braces,
  Database,
  Network,
  NotebookPen,
  Route,
  Search,
  X,
} from 'lucide-react';
import { useState } from 'react';
import type {
  AuraFlowNode,
  MemoryItem,
  ResearchInspectorData,
  RunDetail,
} from '../../types';

export interface InspectorPanelProps {
  selectedNode?: AuraFlowNode;
  runDetail?: RunDetail | null;
  researchData?: ResearchInspectorData | null;
  memories?: MemoryItem[];
  onClose: () => void;
  onContextSelect?: (nodeId: string) => void;
}

export type InspectorTab = 'routing' | 'execution' | 'research' | 'memory' | 'context' | 'object';

const tabs: { id: InspectorTab; label: string; icon: any }[] = [
  { id: 'routing', label: 'Routing', icon: Route },
  { id: 'execution', label: 'Execution', icon: Braces },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'memory', label: 'Memory', icon: Database },
  { id: 'context', label: 'Context', icon: Network },
  { id: 'object', label: 'Object', icon: Box },
];

export function InspectorPanel({
  selectedNode,
  runDetail,
  researchData,
  memories = [],
  onClose,
  onContextSelect,
}: InspectorPanelProps) {
  const [tab, setTab] = useState<InspectorTab>('execution');
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({});
  const [expandedEvidence, setExpandedEvidence] = useState<Record<string, boolean>>({});

  const toggleEvent = (id: string) => {
    setExpandedEvents((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const toggleEvidence = (id: string) => {
    setExpandedEvidence((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <aside className="inspector-panel" data-testid="inspector-panel">
      <div className="inspector-panel__header">
        <div>
          <span className="eyebrow">INSPECTOR</span>
          <strong>{selectedNode?.data.title ?? runDetail?.session_id ?? 'Live Workspace'}</strong>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close inspector">
          <X size={16} />
        </button>
      </div>

      <div className="inspector-tabs">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            className={tab === id ? 'is-active' : ''}
            type="button"
            key={id}
            data-testid={`inspector-tab-${id}`}
            onClick={() => setTab(id)}
          >
            <Icon size={13} />
            <span>{label}</span>
          </button>
        ))}
      </div>

      <div className="inspector-content">
        {tab === 'routing' ? (
          <div data-testid="inspector-routing">
            <div className="inspector-kpi">
              <span>Routing Profile</span>
              <strong>Balanced · Session</strong>
              <small style={{ color: '#ffb366' }}>Prototype Adapter (Routing Studio v2 next sprint)</small>
            </div>
            <InspectorGroup
              title="Routing Invariants"
              rows={[
                ['Status', 'Demo / Prototype Isolated'],
                ['Active Route', 'Balanced (Auto · Adaptive)'],
                ['Reasoning Override', 'Profile Invariant'],
                ['Locked Model', 'Model C (Default)'],
              ]}
            />
          </div>
        ) : null}

        {tab === 'execution' ? (
          <div data-testid="inspector-execution">
            {runDetail ? (
              <>
                <div className="inspector-kpi">
                  <span>Run ID: {runDetail.id.slice(0, 12)}…</span>
                  <strong>Status: {runDetail.status}</strong>
                  <small>Real Execution Trace · No Chain-of-Thought Exposed</small>
                </div>
                <div style={{ marginTop: 12 }}>
                  <div className="context-blocks__head" style={{ marginBottom: 8 }}>
                    <span>Persisted Events ({runDetail.events?.length ?? 0})</span>
                  </div>
                  {runDetail.events && runDetail.events.length > 0 ? (
                    runDetail.events.map((ev, idx) => {
                      const evKey = ev.id || `event-${idx}`;
                      const isExpanded = Boolean(expandedEvents[evKey]);
                      return (
                        <div key={evKey} className="inspector-event-item" data-testid="run-event-item">
                          <div className="inspector-event-header">
                            <span className="inspector-event-type">{ev.event_type}</span>
                            <span className="inspector-event-time">
                              {ev.created_at ? new Date(ev.created_at).toLocaleTimeString() : ''}
                            </span>
                          </div>
                          {ev.payload && Object.keys(ev.payload).length > 0 ? (
                            <>
                              <button
                                type="button"
                                className="inspector-payload-toggle"
                                onClick={() => toggleEvent(evKey)}
                              >
                                {isExpanded ? '▾ Hide payload' : '▸ View raw payload'}
                              </button>
                              {isExpanded ? (
                                <pre className="inspector-event-payload">
                                  {JSON.stringify(ev.payload, null, 2)}
                                </pre>
                              ) : null}
                            </>
                          ) : null}
                        </div>
                      );
                    })
                  ) : (
                    <div style={{ color: '#687f8d', fontSize: 11 }}>No events recorded for this run.</div>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="inspector-kpi">
                  <span>Last execution</span>
                  <strong>{selectedNode?.data.chip ?? 'Research · 8 sources'}</strong>
                  <small>No hidden chain-of-thought is displayed.</small>
                </div>
                <InspectorGroup
                  title="Operational trace"
                  rows={[
                    ['Router', 'done'],
                    ['GitNexus', 'done'],
                    ['Files read', '3'],
                    ['pytest', '42 passed'],
                  ]}
                />
              </>
            )}
          </div>
        ) : null}

        {tab === 'research' ? (
          <div data-testid="inspector-research">
            {researchData ? (
              <>
                <div className="inspector-kpi">
                  <span>Research Specialist</span>
                  <strong>Status: {researchData.status}</strong>
                  {researchData.child_run_id ? (
                    <small>Child Run: {researchData.child_run_id.slice(0, 10)}…</small>
                  ) : null}
                </div>

                {researchData.goal ? (
                  <InspectorGroup
                    title="Goal"
                    rows={[
                      ['Query', researchData.goal.user_query || '—'],
                      ['Project', researchData.goal.project_name || '—'],
                    ]}
                  />
                ) : null}

                <div style={{ marginTop: 12 }}>
                  <div className="context-blocks__head" style={{ marginBottom: 6 }}>
                    <span>Queries ({researchData.queries?.length ?? 0})</span>
                  </div>
                  {researchData.queries?.map((q, idx) => (
                    <div key={q.query_id || idx} className="inspector-event-item">
                      <div className="inspector-event-header">
                        <span className="inspector-event-type">{q.query_text}</span>
                        <span className="inspector-event-time">
                          {q.results_count !== undefined ? `${q.results_count} results` : ''}
                        </span>
                      </div>
                      <small style={{ color: '#66808e', fontSize: 10 }}>
                        type: {q.search_type || 'default'} · iter: {q.iteration ?? 1}
                      </small>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 12 }}>
                  <div className="context-blocks__head" style={{ marginBottom: 6 }}>
                    <span>Sources ({researchData.sources?.length ?? 0})</span>
                  </div>
                  {researchData.sources?.map((s, idx) => (
                    <div key={s.source_id || idx} className="inspector-event-item">
                      <div className="inspector-event-header">
                        <strong style={{ fontSize: 11, color: '#c9d8e0' }}>{s.title}</strong>
                        <span className="inspector-event-time">{s.year || ''}</span>
                      </div>
                      <small style={{ color: '#68818f', fontSize: 10 }}>
                        {s.canonical_id} {s.authors ? `· ${s.authors.join(', ')}` : ''}
                      </small>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 12 }}>
                  <div className="context-blocks__head" style={{ marginBottom: 6 }}>
                    <span>Evidence ({researchData.evidence?.length ?? 0})</span>
                  </div>
                  {researchData.evidence?.map((ev, idx) => {
                    const isExp = Boolean(expandedEvidence[ev.evidence_id || String(idx)]);
                    return (
                      <div key={ev.evidence_id || idx} className="inspector-event-item">
                        <div className="inspector-event-header">
                          <span style={{ fontSize: 11, color: '#a2c4d4' }}>
                            {ev.source_title || 'Evidence snippet'}
                          </span>
                          {ev.confidence !== undefined ? (
                            <span className="inspector-event-time">
                              {(ev.confidence * 100).toFixed(0)}% conf
                            </span>
                          ) : null}
                        </div>
                        <p style={{ margin: '4px 0', fontSize: 11, color: '#cfdde4' }}>
                          {isExp
                            ? ev.extracted_text
                            : ev.extracted_text.length > 90
                            ? `${ev.extracted_text.slice(0, 90)}…`
                            : ev.extracted_text}
                        </p>
                        {ev.extracted_text.length > 90 ? (
                          <button
                            type="button"
                            className="inspector-payload-toggle"
                            onClick={() => toggleEvidence(ev.evidence_id || String(idx))}
                          >
                            {isExp ? 'Show less' : 'Show full snippet'}
                          </button>
                        ) : null}
                      </div>
                    );
                  })}
                </div>

                <div style={{ marginTop: 12 }}>
                  <div className="context-blocks__head" style={{ marginBottom: 6 }}>
                    <span>Claims ({researchData.claims?.length ?? 0})</span>
                  </div>
                  {researchData.claims?.map((cl, idx) => (
                    <div key={cl.claim_id || idx} className="inspector-event-item">
                      <div className="inspector-event-header">
                        <span style={{ fontSize: 11, fontWeight: 600, color: '#e0ecf2' }}>
                          {cl.claim_type}
                        </span>
                        <span className="inspector-event-time">
                          {cl.evidence_ids?.length ?? 0} citations
                        </span>
                      </div>
                      <p style={{ margin: '3px 0 0', fontSize: 11, color: '#a1b5c2' }}>
                        {cl.claim_text}
                      </p>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div style={{ color: '#6a8290', fontSize: 11.5, padding: 12 }}>
                No active Research Specialist execution data for this session.
              </div>
            )}
          </div>
        ) : null}

        {tab === 'memory' ? (
          <div data-testid="inspector-memory">
            <div className="inspector-kpi">
              <span>Project Memory</span>
              <strong>{memories.length} Persisted Items</strong>
              <small>Retrieved from /v1/memory</small>
            </div>
            <div style={{ marginTop: 12 }}>
              {memories.length > 0 ? (
                memories.map((m) => (
                  <div key={m.id} className="inspector-event-item" data-testid="memory-item">
                    <div className="inspector-event-header">
                      <strong style={{ fontSize: 11.5, color: '#b9d4e2' }}>{m.key}</strong>
                      <span className="risk-badge risk-low" style={{ fontSize: 9 }}>
                        {m.memory_type}
                      </span>
                    </div>
                    <p style={{ margin: '4px 0 0', fontSize: 11, color: '#cfdce2' }}>{m.content}</p>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
                      <small style={{ color: '#566e7c', fontSize: 10 }}>
                        Confidence: {(m.confidence * 100).toFixed(0)}%
                      </small>
                      <small style={{ color: '#566e7c', fontSize: 10 }}>
                        {m.created_at ? new Date(m.created_at).toLocaleDateString() : ''}
                      </small>
                    </div>
                  </div>
                ))
              ) : (
                <div style={{ color: '#68808e', fontSize: 11.5, padding: 12 }}>
                  No memories stored for this project yet.
                </div>
              )}
            </div>
          </div>
        ) : null}

        {tab === 'context' ? (
          <>
            <div className="inspector-kpi inspector-kpi--context">
              <span>Context used</span>
              <strong>12.4k tokens</strong>
              <small>6 inherited / selected objects</small>
            </div>
            <div className="context-blocks">
              <div className="context-blocks__head">
                <span>Context manifest</span>
                <small>click to focus</small>
              </div>
              <button
                className="context-block is-active"
                type="button"
                onClick={() => onContextSelect?.('root-answer')}
              >
                <span className="context-block__icon">
                  <NotebookPen size={14} />
                </span>
                <span className="context-block__copy">
                  <span className="context-block__meta">
                    <small>Turn</small>
                    <em>2.1k</em>
                  </span>
                  <strong>Root synthesis</strong>
                  <small>branch ancestry</small>
                </span>
              </button>
            </div>
          </>
        ) : null}

        {tab === 'object' ? (
          <InspectorGroup
            title="Metadata"
            rows={[
              ['Type', selectedNode?.data.kind ?? 'workspace'],
              ['Branch', selectedNode?.data.branch ?? '—'],
              ['Layer', selectedNode?.data.layer ?? '—'],
              ['Density', selectedNode?.data.density ?? '—'],
            ]}
          />
        ) : null}
      </div>
    </aside>
  );
}

function InspectorGroup({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <section className="inspector-group">
      <h4>{title}</h4>
      {rows.map(([label, value]) => (
        <div className="inspector-row" key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
        </div>
      ))}
    </section>
  );
}
