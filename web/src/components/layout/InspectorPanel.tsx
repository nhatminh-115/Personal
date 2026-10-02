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
  EffectiveRouting,
  RunRoutingDecision,
  CompiledContextManifest,
  CapabilityProviderMetadata,
} from '../../types';
import { api } from '../../services/api';

export interface InspectorPanelProps {
  selectedNode?: AuraFlowNode;
  runDetail?: RunDetail | null;
  effectiveRouting?: EffectiveRouting | null;
  routingData?: RunRoutingDecision[] | null;
  researchData?: ResearchInspectorData | null;
  memories?: MemoryItem[];
  onClose: () => void;
  onContextSelect?: (nodeId: string) => void;
}

export type InspectorTab = 'routing' | 'execution' | 'research' | 'memory' | 'context' | 'capabilities' | 'object';

const tabs: { id: InspectorTab; label: string; icon: any }[] = [
  { id: 'routing', label: 'Routing', icon: Route },
  { id: 'execution', label: 'Execution', icon: Braces },
  { id: 'research', label: 'Research', icon: Search },
  { id: 'memory', label: 'Memory', icon: Database },
  { id: 'context', label: 'Context', icon: Network },
  { id: 'capabilities', label: 'Capabilities', icon: Network },
  { id: 'object', label: 'Object', icon: Box },
];

export function InspectorPanel({
  selectedNode,
  runDetail,
  effectiveRouting,
  routingData,
  researchData,
  memories = [],
  onClose,
  onContextSelect,
}: InspectorPanelProps) {
  const [tab, setTab] = useState<InspectorTab>('execution');
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({});
  const [expandedEvidence, setExpandedEvidence] = useState<Record<string, boolean>>({});
  const [capabilityProviders, setCapabilityProviders] = useState<CapabilityProviderMetadata[]>([]);
  const [capabilityState, setCapabilityState] = useState<'idle' | 'loading' | 'loaded' | 'error'>('idle');
  const [capabilityError, setCapabilityError] = useState<string | null>(null);

  const toggleEvent = (id: string) => {
    setExpandedEvents((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const loadCapabilityProviders = async () => {
    setCapabilityState('loading');
    setCapabilityError(null);
    try {
      const inventory = await api.fetchCapabilityProviders();
      setCapabilityProviders(inventory.providers);
      setCapabilityState('loaded');
    } catch {
      setCapabilityError('Provider inventory is unavailable. Check the AURA connection and retry.');
      setCapabilityState('error');
    }
  };

  const toggleEvidence = (id: string) => {
    setExpandedEvidence((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const detailContextEvent = runDetail?.events?.filter((event) => event.event_type === 'context_compiled').at(-1);
  const detailContextManifest = detailContextEvent?.payload as CompiledContextManifest | undefined;
  const contextManifestEntries = routingData?.flatMap((decision) => decision.context_manifest ? [{
    runId: decision.run_id,
    role: String(decision.snapshot.role ?? decision.model_selection?.agent_role ?? 'Run'),
    manifest: decision.context_manifest,
  }] : []) ?? [];
  if (!contextManifestEntries.length && detailContextManifest && runDetail) {
    contextManifestEntries.push({ runId: runDetail.id, role: 'Run', manifest: detailContextManifest });
  }
  const contextObjectCount = contextManifestEntries.reduce((count, entry) => count + (
    Array.isArray(entry.manifest.objects)
      ? entry.manifest.objects.filter((item) => typeof item.object_id === 'string' && typeof item.object_type === 'string').length
      : 0
  ), 0);

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
            onClick={() => {
              setTab(id);
              if (id === 'capabilities' && (capabilityState === 'idle' || capabilityState === 'error')) void loadCapabilityProviders();
            }}
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
              <strong>{effectiveRouting?.profile.name ?? 'Routing unavailable'} · {effectiveRouting?.winning_scope ?? '—'}</strong>
              <small>{runDetail || routingData?.length ? 'Persisted routing decisions · No model invocation' : 'Effective profile before the next run'}</small>
            </div>
            {routingData?.length ? routingData.map((decision) => <section className="inspector-group" key={decision.run_id}>
              <h4>{decision.snapshot.role ?? decision.model_selection?.agent_role ?? 'Run'} routing</h4>
              <div className="inspector-row"><span>Profile</span><strong>{decision.snapshot.profile_id ?? '—'} · v{decision.snapshot.profile_version ?? '?'}</strong></div>
              <div className="inspector-row"><span>Scope</span><strong>{decision.snapshot.winning_scope ?? '—'}</strong></div>
              <div className="inspector-row"><span>Privacy / fallback</span><strong>{decision.snapshot.privacy_policy ?? decision.model_selection?.privacy ?? '—'} / {decision.snapshot.fallback_policy ?? decision.model_selection?.fallback_policy ?? '—'}</strong></div>
              {decision.memory_privacy_sources?.length ? <div className="inspector-row"><span>Memory privacy sources</span><strong>{decision.memory_privacy_sources.map((source) => `${source.memory_id} · ${source.privacy_policy}`).join(' | ')}</strong></div> : null}
              <div className="inspector-row"><span>Selected model</span><strong>{decision.model_selection ? `${decision.model_selection.provider}:${decision.model_selection.model}` : decision.snapshot.explicit_model_override ?? 'Pending'}</strong></div>
              <div className="inspector-row"><span>Reasoning</span><strong>{decision.reasoning_selection?.selected_effort ?? decision.snapshot.reasoning_effort ?? 'Unknown'}</strong></div>
              {decision.context_manifest?.required_tool_capabilities?.length ? <div className="inspector-row"><span>Provider capabilities</span><strong>{decision.context_manifest.required_tool_capabilities.join(' · ')}</strong></div> : null}
              {decision.context_manifest?.resolved_tool_names?.length ? <div className="inspector-row"><span>Resolved tools</span><strong>{decision.context_manifest.resolved_tool_names.join(' · ')}</strong></div> : null}
              {decision.model_selection ? <>
                {(() => {
                  const selection = decision.model_selection;
                  const requirements = [
                    ...(Array.isArray(selection.required_capabilities) ? selection.required_capabilities : []),
                    ...(selection.requires_tools ? ['tools'] : []),
                    ...(selection.requires_vision ? ['vision'] : []),
                    ...(selection.requires_structured_output ? ['structured output'] : []),
                    ...(selection.requires_long_context ? ['long context'] : []),
                  ];
                  const uniqueRequirements = [...new Set(requirements)];
                  const contextWindow = typeof selection.context_window === 'number' ? selection.context_window : null;
                  const estimatedTokens = typeof selection.estimated_input_tokens === 'number' ? selection.estimated_input_tokens : null;
                  const reservedOutputTokens = typeof selection.reserved_output_tokens === 'number' ? selection.reserved_output_tokens : null;
                  const contextEstimate = estimatedTokens === null ? null : [
                    `${estimatedTokens.toLocaleString()} input`,
                    ...(reservedOutputTokens === null ? [] : [`${reservedOutputTokens.toLocaleString()} reserved`]),
                  ].join(' + ');
                  return <>
                    {uniqueRequirements.length ? <div className="inspector-row"><span>Requirements</span><strong>{uniqueRequirements.join(' · ')}</strong></div> : null}
                    {contextEstimate !== null ? <div className="inspector-row"><span>Context budget</span><strong>{contextWindow !== null ? `${contextEstimate} / ${contextWindow.toLocaleString()} tokens` : `${contextEstimate} tokens · model limit unknown`}</strong></div> : null}
                  </>;
                })()}
              </> : null}
              {decision.fallback_events.map((event, index) => <div className="inspector-event-item" key={`${event.event_type}-${index}`}><strong>{event.event_type}</strong><small>{event.payload.reason ?? event.payload.fallback_policy ?? ''}</small></div>)}
            </section>) : effectiveRouting ? <InspectorGroup title="Effective policy" rows={[
              ['Privacy', effectiveRouting.profile.global_privacy_policy],
              ['Fallback', effectiveRouting.profile.global_fallback_policy],
              ['Cost / latency', `${effectiveRouting.profile.cost_preference} / ${effectiveRouting.profile.latency_preference}`],
            ]} /> : <div style={{ color: '#68808e', fontSize: 11 }}>Effective routing profile is unavailable.</div>}
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
                                {isExpanded ? '▾ Hide details' : '▸ View operational details'}
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
              <strong>{contextManifestEntries.length ? `${contextManifestEntries.length} compiled manifest${contextManifestEntries.length === 1 ? '' : 's'}` : 'Not recorded'}</strong>
              <small>{contextObjectCount} compiled object{contextObjectCount === 1 ? '' : 's'} across the run tree</small>
            </div>
            {contextManifestEntries.length ? contextManifestEntries.map(({ runId, role, manifest }) => {
              const objects = Array.isArray(manifest.objects)
                ? manifest.objects.filter((item) => typeof item.object_id === 'string' && typeof item.object_type === 'string')
                : [];
              const requirements = [
                ...(Array.isArray(manifest.required_capabilities) ? manifest.required_capabilities : []),
                ...Object.entries(manifest.capability_requirements ?? {})
                  .filter(([, required]) => required === true)
                  .map(([key]) => key.replace(/^requires_/, '').replace(/_/g, ' ')),
              ];
              return <section className="inspector-group" key={runId}>
                <h4>{role} · {runId.slice(0, 12)}</h4>
                <div className="inspector-row"><span>Estimated tokens</span><strong>{typeof manifest.estimated_tokens === 'number' ? manifest.estimated_tokens.toLocaleString() : 'Unknown'}</strong></div>
                <div className="inspector-row"><span>Privacy</span><strong>{manifest.privacy_requirement ?? 'Unclassified'}</strong></div>
                {manifest.privacy_sources?.length ? <div className="inspector-row"><span>Privacy sources</span><strong>{manifest.privacy_sources.map((source) => `${source.object_id} · ${source.privacy_policy}`).join(' | ')}</strong></div> : null}
                {typeof manifest.character_count === 'number' ? <div className="inspector-row"><span>Compiled size</span><strong>{manifest.character_count.toLocaleString()} characters</strong></div> : null}
                {requirements.length ? <div className="inspector-row"><span>Requirements</span><strong>{[...new Set(requirements)].join(' · ')}</strong></div> : null}
                <div className="context-blocks">
                  <div className="context-blocks__head">
                    <span>Persisted context manifest</span>
                    <small>{onContextSelect ? 'click to focus' : 'object IDs'}</small>
                  </div>
                  {objects.map((item) => <button
                    className="context-block"
                    type="button"
                    key={item.object_id}
                    disabled={!onContextSelect}
                    onClick={() => onContextSelect?.(item.object_id)}
                  >
                    <span className="context-block__icon"><NotebookPen size={14} /></span>
                    <span className="context-block__copy">
                      <span className="context-block__meta">
                        <small>{item.object_type.replace(/_/g, ' ')}</small>
                        <em>{item.selected_by_user ? 'selected' : 'linked'}</em>
                      </span>
                      <strong>{item.object_id}</strong>
                      {item.source_object_ids?.length ? <small>Provenance links: {item.source_object_ids.join(', ')}</small> : null}
                      {item.selected_sections ? <small>Bridge sections: {Object.entries(item.selected_sections).filter(([, selected]) => selected === true).map(([section]) => section).join(', ') || 'none selected'}</small> : null}
                    </span>
                  </button>)}
                  {!objects.length ? <div className="inspector-empty">No workspace objects were compiled for this run.</div> : null}
                </div>
              </section>;
            }) : <div className="inspector-empty">No compiled context manifest is recorded for this run.</div>}
          </>
        ) : null}

        {tab === 'capabilities' ? (
          <div data-testid="inspector-capabilities">
            <div className="inspector-kpi">
              <span>Capability providers</span>
              <strong>{capabilityProviders.length} registered</strong>
              <small>Sanitized runtime inventory · no provider invocation</small>
            </div>
            {capabilityState === 'loading' ? <div className="inspector-empty">Loading provider inventory…</div> : null}
            {capabilityError ? <div className="inspector-empty" role="alert">{capabilityError}<button type="button" onClick={() => void loadCapabilityProviders()}>Retry</button></div> : null}
            {capabilityState === 'loaded' && capabilityProviders.length === 0 ? <div className="inspector-empty">No capability providers are registered.</div> : null}
            {capabilityProviders.map((provider) => (
              <section className="inspector-group" key={provider.provider_id}>
                <h4>{provider.name}</h4>
                <div className="inspector-row"><span>Provider ID</span><strong>{provider.provider_id}</strong></div>
                <div className="inspector-row"><span>Version</span><strong>{provider.version ?? 'Unknown'}</strong></div>
                <div className="inspector-row"><span>Health</span><strong>{provider.health === 'unknown' ? 'Unknown' : formatProviderValue(provider.health)}</strong></div>
                <div className="inspector-row"><span>Enabled</span><strong>{provider.enabled ? 'Yes' : 'No'}</strong></div>
                <div className="inspector-row"><span>Privacy boundary</span><strong>{formatProviderValue(provider.privacy_boundary)}</strong></div>
                <div className="inspector-row"><span>Network</span><strong>{formatProviderValue(provider.network_requirement)}</strong></div>
                <div className="inspector-row"><span>Data touched</span><strong>{formatProviderList(provider.data_touched)}</strong></div>
                <div className="inspector-row"><span>Permissions</span><strong>{formatProviderList(provider.permissions)}</strong></div>
                <div className="inspector-row"><span>Approval</span><strong>{formatProviderValue(provider.approval_requirement)}</strong></div>
                <div className="inspector-row"><span>Health checked</span><strong>{provider.health_checked_at ?? 'Not checked'}</strong></div>
                <div className="inspector-row"><span>Capabilities</span><strong>{formatProviderList(provider.capabilities)}</strong></div>
                <div className="inspector-capability-bindings" aria-label="Configured capability to AURA tool mappings">
                  <strong>Configured capability → AURA tools</strong>
                  {Object.entries(provider.declared_capability_tools ?? {}).length ? Object.entries(provider.declared_capability_tools).map(([capability, tools]) => (
                    <div className="inspector-capability-binding" key={capability}><span>{capability}</span><strong>{tools.length ? tools.join(' · ') : 'No tools declared'}</strong></div>
                  )) : <span>No capability mappings declared</span>}
                </div>
                <div className="inspector-capability-bindings" aria-label="Verified available capability to AURA tool bindings">
                  <strong>Verified available capability → AURA tools</strong>
                  {Object.entries(provider.capability_tools ?? {}).length ? Object.entries(provider.capability_tools).map(([capability, tools]) => (
                    <div className="inspector-capability-binding" key={capability}><span>{capability}</span><strong>{tools.length ? tools.join(' · ') : 'No tools available'}</strong></div>
                  )) : <span>No tools verified available</span>}
                </div>
              </section>
            ))}
          </div>
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


function formatProviderValue(value: string | null | undefined): string {
  if (!value || value === 'unknown') return 'Unknown';
  return value.split('_').map((part) => part[0]?.toUpperCase() + part.slice(1)).join(' ');
}

function formatProviderList(values: string[] | null | undefined): string {
  if (values == null) return 'Unknown';
  return values.length ? values.join(' · ') : 'None declared';
}
