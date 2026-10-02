import { BellRing, Check, Clock3, Pause, Play, Plus, Workflow, X } from 'lucide-react';
import { useRef, useState } from 'react';
import type { ApprovalDetail, RunDetail, RunRoutingDecision, RunEvent } from '../../types';
import { api } from '../../services/api';
import type { AutomationRecord, ProjectRecord } from '../../data/workspaceData';

interface AutomationInput {
  name: string;
  description: string;
  instruction: string;
  scope: 'global' | 'project';
  project_name?: string;
  interval_seconds: number;
}

interface AutomationsViewProps {
  projects: ProjectRecord[];
  automations: AutomationRecord[];
  onCreate: (input: AutomationInput) => Promise<AutomationRecord>;
  onToggle: (automation: AutomationRecord, enabled: boolean) => void;
  onRunNow: (automation: AutomationRecord) => void;
  onApprovalResolved: (automationId: string) => void;
}

const intervalUnits = { minutes: 60, hours: 3600, days: 86400 } as const;
type IntervalUnit = keyof typeof intervalUnits;

function safeRunEventSummary(event: RunEvent): string | null {
  const payload = event.payload;
  const value = (key: string) => typeof payload[key] === 'string' ? payload[key] as string : '';
  if (event.event_type === 'model_selected') return [value('provider'), value('model')].filter(Boolean).join(' · ') || 'Model selected';
  if (event.event_type === 'reasoning_effort_selected') return value('selected_effort') || 'Reasoning selected';
  if (event.event_type === 'tool_requested' || event.event_type === 'tool_executed') {
    const tool = value('tool_name');
    if (!tool) return null;
    return event.event_type === 'tool_executed' ? `${tool} · ${payload.success === true ? 'succeeded' : payload.success === false ? 'failed' : 'finished'}` : `${tool} · requested`;
  }
  if (event.event_type.startsWith('delegation_')) return [value('specialist'), value('status')].filter(Boolean).join(' · ') || 'Specialist delegation';
  if (event.event_type.startsWith('approval_')) return [value('tool_name'), value('risk_level')].filter(Boolean).join(' · ') || event.event_type.replace(/_/g, ' ');
  if (event.event_type === 'fallback_blocked' || event.event_type === 'fallback_considered') return event.event_type.replace(/_/g, ' ');
  if (['response_generated', 'run_completed', 'run_failed', 'run_cancelled'].includes(event.event_type)) return event.event_type.replace(/_/g, ' ');
  return null;
}

export function AutomationsView({ projects, automations, onCreate, onToggle, onRunNow, onApprovalResolved }: AutomationsViewProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instruction, setInstruction] = useState('');
  const [scope, setScope] = useState<'global' | 'project'>('global');
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '');
  const [interval, setInterval] = useState(1);
  const [unit, setUnit] = useState<IntervalUnit>('days');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [approvalReview, setApprovalReview] = useState<{ automation: AutomationRecord; approval: ApprovalDetail } | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [approvalError, setApprovalError] = useState('');
  const [approvalNotes, setApprovalNotes] = useState('');
  const [approvalEditing, setApprovalEditing] = useState(false);
  const [approvalEditedJson, setApprovalEditedJson] = useState('');
  const [historyAutomationId, setHistoryAutomationId] = useState<string | null>(null);
  const [historyByAutomation, setHistoryByAutomation] = useState<Record<string, Awaited<ReturnType<typeof api.fetchAutomationRuns>>>>({});
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [runReview, setRunReview] = useState<{ automation: AutomationRecord; detail: RunDetail; routing: RunRoutingDecision[] } | null>(null);
  const [runLoadingId, setRunLoadingId] = useState<string | null>(null);
  const [runError, setRunError] = useState('');
  const historyRequest = useRef(0);

  const loadRunHistory = async (automationId: string) => {
    const requestId = ++historyRequest.current;
    setHistoryError('');
    setHistoryLoadingId(automationId);
    try {
      const records = await api.fetchAutomationRuns(automationId, 10);
      if (historyRequest.current !== requestId) return;
      setHistoryByAutomation((current) => ({ ...current, [automationId]: records }));
    } catch (cause) {
      if (historyRequest.current !== requestId) return;
      setHistoryError(cause instanceof Error ? cause.message : 'Could not load run history.');
    } finally {
      if (historyRequest.current === requestId) setHistoryLoadingId(null);
    }
  };

  const toggleRunHistory = (automation: AutomationRecord) => {
    if (automation.source !== 'live') return;
    if (historyAutomationId === automation.id) {
      historyRequest.current += 1;
      setHistoryAutomationId(null);
      setHistoryLoadingId(null);
      setHistoryError('');
      return;
    }
    setHistoryAutomationId(automation.id);
    void loadRunHistory(automation.id);
  };

  const inspectRun = async (automation: AutomationRecord, runId: string) => {
    if (runLoadingId) return;
    setRunLoadingId(runId);
    setRunError('');
    try {
      const [detail, routing] = await Promise.all([api.fetchRunDetails(runId), api.fetchRunRouting(runId)]);
      setRunReview({ automation, detail, routing: routing.decisions });
    } catch (cause) {
      setRunError(cause instanceof Error ? cause.message : 'Could not load the automation run.');
    } finally {
      setRunLoadingId(null);
    }
  };
  const openApprovalReview = async (automation: AutomationRecord) => {
    const runId = automation.latestExecution?.runId;
    if (!runId || automation.latestExecution?.status !== 'waiting_for_approval' || approvalLoading) return;
    setApprovalLoading(true);
    setApprovalError('');
    setApprovalNotes('');
    setApprovalEditing(false);
    try {
      const run = await api.fetchRunDetails(runId);
      const requests = run.events.filter((event) => event.event_type === 'approval_requested').reverse();
      for (const event of requests) {
        const approvalId = event.payload.approval_id;
        if (typeof approvalId !== 'string') continue;
        const approval = await api.fetchApproval(approvalId);
        if (approval.status === 'pending') {
          setApprovalReview({ automation, approval });
          setApprovalEditedJson(JSON.stringify(approval.tool_input, null, 2));
          return;
        }
      }
      setApprovalError('This automation run no longer has a pending approval.');
    } catch (cause) {
      setApprovalError(cause instanceof Error ? cause.message : 'Could not load the pending approval.');
    } finally {
      setApprovalLoading(false);
    }
  };

  const decideApproval = async (decision: 'approved' | 'rejected' | 'edited') => {
    if (!approvalReview || approvalLoading) return;
    let editedInput: Record<string, unknown> | undefined;
    if (decision === 'edited') {
      try {
        const parsed: unknown = JSON.parse(approvalEditedJson);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Expected a JSON object for tool arguments.');
        editedInput = parsed as Record<string, unknown>;
      } catch (cause) {
        setApprovalError(cause instanceof Error ? cause.message : 'Edited input must be a valid JSON object.');
        return;
      }
    }
    setApprovalLoading(true);
    setApprovalError('');
    try {
      const result = await api.submitApproval(approvalReview.approval.id, decision, approvalNotes.trim() || undefined, editedInput);
      if (result.execution_status === 'waiting_for_approval' && result.approval_id) {
        const nextApproval = await api.fetchApproval(result.approval_id);
        setApprovalReview({ ...approvalReview, approval: nextApproval });
        setApprovalEditedJson(JSON.stringify(nextApproval.tool_input, null, 2));
        setApprovalEditing(false);
        setApprovalNotes('');
        return;
      }
      setApprovalReview(null);
      onApprovalResolved(approvalReview.automation.id);
    } catch (cause) {
      setApprovalError(cause instanceof Error ? cause.message : 'Could not submit the approval decision.');
    } finally {
      setApprovalLoading(false);
    }
  };

  const create = async () => {
    if (saving || !name.trim() || !instruction.trim() || (scope === 'project' && !projectId)) return;
    setSaving(true);
    setError('');
    try {
      const project = projects.find((item) => item.id === projectId);
      await onCreate({
        name: name.trim(), description: description.trim(), instruction: instruction.trim(), scope,
        project_name: scope === 'project' ? project?.name : undefined,
        interval_seconds: interval * intervalUnits[unit],
      });
      setName(''); setDescription(''); setInstruction(''); setCreating(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not create automation.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="automations-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">AUTOMATIONS</span>
          <h1>Background routines without turning AURA into Zapier.</h1>
          <p>Scheduled instructions run through AURA and remain scoped to your workspace or one project.</p>
        </div>
        <button className="primary-soft-button" type="button" onClick={() => setCreating(true)}><Plus size={15} /> New automation</button>
      </div>

      <div className="automation-summary-row">
        <div><Workflow size={15} /><span><strong>{automations.filter((item) => item.source === 'live' && item.enabled).length} active</strong><small>{automations.filter((item) => item.source === 'live').length} scheduled routines</small></span></div>
        <div><BellRing size={15} /><span><strong>Persistent scheduler</strong><small>Runs are queued through AURA</small></span></div>
      </div>

      {approvalError && !approvalReview ? <p className="automation-form-error" role="alert">{approvalError}</p> : null}
      <div className="automation-list">
        {automations.map((automation) => {
          const project = automation.projectId ? projects.find((item) => item.id === automation.projectId) : null;
          const live = automation.source === 'live';
          return (
            <article key={automation.id} className={`automation-card ${automation.enabled ? '' : 'is-paused'}`}>
              <button aria-label={`${automation.enabled ? 'Pause' : 'Resume'} ${automation.name}`} className={`automation-toggle ${automation.enabled ? 'is-on' : ''}`} type="button" onClick={() => onToggle(automation, !automation.enabled)} disabled={!live}><span /></button>
              <div className="automation-card__body">
                <div className="automation-card__title"><strong>{automation.name}</strong><span>{live ? (automation.scope === 'global' ? 'Global' : project?.name ?? automation.projectName ?? 'Project') : 'Example'}</span></div>
                <p>{automation.description}</p>
                {live ? <details className="automation-instruction"><summary>Instruction</summary><p>{automation.instruction}</p></details> : null}
                <div className="automation-trigger"><Clock3 size={12} /><strong>{automation.trigger}</strong></div>
                {live && automation.latestExecution ? <div className={`automation-execution-status is-${automation.latestExecution.status}`}><span>Latest run</span><strong>{automation.latestExecution.status.replace(/_/g, ' ')}</strong>{automation.latestExecution.retryCount > 0 ? <small>{automation.latestExecution.retryCount} retries</small> : null}{automation.latestExecution.status === 'waiting_for_approval' ? <button type="button" onClick={() => void openApprovalReview(automation)} disabled={approvalLoading}>{approvalLoading ? 'Loading approval…' : 'Review approval'}</button> : null}</div> : null}
                {live ? (
                  <div className="automation-history">
                    <button
                      type="button"
                      className="secondary-button automation-history__toggle"
                      aria-expanded={historyAutomationId === automation.id}
                      aria-controls={`automation-history-${automation.id}`}
                      onClick={() => toggleRunHistory(automation)}
                    >
                      {historyAutomationId === automation.id ? 'Hide run history' : 'Run history'}
                    </button>
                    {historyAutomationId === automation.id ? (
                      <div id={`automation-history-${automation.id}`} className="automation-history__panel" aria-live="polite">
                        <button type="button" className="secondary-button" onClick={() => void loadRunHistory(automation.id)} disabled={historyLoadingId === automation.id}>{historyLoadingId === automation.id ? 'Refreshing…' : 'Refresh history'}</button>
                        {historyLoadingId === automation.id ? <p>Loading run history…</p> : null}
                        {historyError ? <p className="automation-form-error" role="alert">{historyError}</p> : null}
                        {runError ? <p className="automation-form-error" role="alert">{runError}</p> : null}
                        {historyByAutomation[automation.id]?.length === 0 ? <p>No runs yet.</p> : null}
                        {historyByAutomation[automation.id]?.length ? (
                          <ol>
                            {historyByAutomation[automation.id].map((run) => (
                              <li key={run.event_id} className={`automation-execution-status is-${run.status}`}>
                                <time dateTime={run.queued_at}>{run.queued_at}</time>
                                <strong>{run.status.replace(/_/g, ' ')}</strong>
                                {run.retry_count > 0 ? <small>{run.retry_count} retries</small> : null}
                                <button type="button" onClick={() => void inspectRun(automation, run.run_id)} disabled={runLoadingId !== null}>{runLoadingId === run.run_id ? 'Loading run…' : 'Inspect run'}</button>
                              </li>
                            ))}
                          </ol>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {live ? <div className="automation-steps">{automation.actions.map((action) => <span key={action}><Check size={10} /> {action}</span>)}</div> : null}
                <div className="automation-card__footer"><span>Last: {automation.lastRun}</span><span>Next: {live && automation.enabled ? automation.nextRun : live ? 'Paused' : 'Example data'}</span></div>
              </div>
              <button className="automation-run" type="button" onClick={() => onRunNow(automation)} disabled={!live || !automation.enabled} title={live ? 'Queue a run through AURA' : 'Examples do not run'}>{automation.enabled ? <Play size={13} /> : <Pause size={13} />} Run now</button>
            </article>
          );
        })}
      </div>

      {runReview ? (
        <div className="modal-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !runLoadingId) setRunReview(null); }}>
          <div className="automation-create-modal automation-run-review" role="dialog" aria-modal="true" aria-labelledby="automation-run-review-title">
            <div className="modal-head"><div><span className="eyebrow">AUTOMATION RUN</span><strong id="automation-run-review-title">{runReview.automation.name}</strong></div><button className="icon-button" type="button" onClick={() => setRunReview(null)} aria-label="Close run inspector"><X size={15} /></button></div>
            <div className="automation-run-review__summary"><span>Status</span><strong>{runReview.detail.status.replace(/_/g, ' ')}</strong><span>Run</span><code>{runReview.detail.id}</code><span>Started</span><time dateTime={runReview.detail.created_at}>{runReview.detail.created_at}</time></div>
            {runReview.detail.final_response ? <section><h3>Result</h3><p className="automation-run-review__result">{runReview.detail.final_response}</p></section> : null}
            <section><h3>Routing decisions</h3>
              {runReview.routing.length ? runReview.routing.map((decision) => {
                const model = decision.model_selection ?? {};
                const snapshot = decision.snapshot ?? {};
                const provider = typeof model.provider === 'string' ? model.provider : '';
                const modelName = typeof model.model === 'string' ? model.model : '';
                const role = typeof model.agent_role === 'string' ? model.agent_role : typeof snapshot.role === 'string' ? snapshot.role : 'Run';
                const scope = typeof model.winning_scope === 'string' ? model.winning_scope : typeof snapshot.winning_scope === 'string' ? snapshot.winning_scope : '';
                return <div key={decision.run_id} className="automation-run-review__decision"><strong>{role}</strong><span>{[provider, modelName].filter(Boolean).join(' · ') || 'No model selection recorded'}</span>{scope ? <small>Scope: {scope}</small> : null}</div>;
              }) : <p>No routing decisions were recorded.</p>}
            </section>
            <section><h3>Execution timeline</h3>
              {runReview.detail.events.map((event) => {
                const summary = safeRunEventSummary(event);
                return summary ? <div key={event.id} className="automation-run-review__event"><time dateTime={event.created_at}>{event.created_at}</time><strong>{event.event_type.replace(/_/g, ' ')}</strong><span>{summary}</span></div> : null;
              })}
            </section>
            <p className="modal-note">Timeline shows filtered operational events. User instructions and raw tool payloads are not included.</p>
          </div>
        </div>
      ) : null}
      {approvalReview ? (
        <div className="modal-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !approvalLoading) setApprovalReview(null); }}>
          <div className="automation-create-modal automation-approval-modal" role="dialog" aria-modal="true" aria-labelledby="automation-approval-title">
            <div className="modal-head"><div><span className="eyebrow">TOOL APPROVAL</span><strong id="automation-approval-title">{approvalReview.automation.name}</strong></div><button className="icon-button" type="button" onClick={() => { setApprovalReview(null); setApprovalError(''); }} disabled={approvalLoading} aria-label="Close"><X size={15} /></button></div>
            <p>This automation run is paused until you decide whether AURA may continue.</p>
            <div className="automation-approval-detail"><span>Tool</span><strong>{approvalReview.approval.tool_name}</strong></div>
            <div className="automation-approval-detail"><span>Risk</span><strong>{approvalReview.approval.risk_level}</strong></div>
            <label>
              <span>Requested input</span>
              {approvalEditing ? (
                <textarea
                  aria-label="Edit automation tool input JSON"
                  className="automation-approval-json"
                  value={approvalEditedJson}
                  onChange={(event) => { setApprovalEditedJson(event.target.value); setApprovalError(''); }}
                  spellCheck={false}
                />
              ) : <pre>{JSON.stringify(approvalReview.approval.tool_input, null, 2)}</pre>}
            </label>
            <label><span>Decision note (optional)</span><input value={approvalNotes} onChange={(event) => setApprovalNotes(event.target.value)} maxLength={1000} /></label>
            {approvalError ? <p className="automation-form-error" role="alert">{approvalError}</p> : null}
            <div className="automation-approval-actions">
              {approvalEditing ? (
                <>
                  <button type="button" className="secondary-button" disabled={approvalLoading} onClick={() => { setApprovalEditing(false); setApprovalError(''); }}>Cancel edit</button>
                  <button type="button" className="primary-soft-button" disabled={approvalLoading} onClick={() => void decideApproval('edited')}>{approvalLoading ? 'Submitting…' : 'Approve edited input'}</button>
                </>
              ) : (
                <>
                  <button type="button" className="secondary-button" disabled={approvalLoading} onClick={() => void decideApproval('rejected')}>Reject</button>
                  <button type="button" className="secondary-button" disabled={approvalLoading} onClick={() => { setApprovalEditedJson(JSON.stringify(approvalReview.approval.tool_input, null, 2)); setApprovalError(''); setApprovalEditing(true); }}>Edit input</button>
                  <button type="button" className="primary-soft-button" disabled={approvalLoading} onClick={() => void decideApproval('approved')}>{approvalLoading ? 'Submitting…' : 'Approve and continue'}</button>
                </>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {creating ? (
        <div className="modal-scrim" role="presentation" onMouseDown={() => !saving && setCreating(false)}>
          <div className="automation-create-modal" role="dialog" aria-modal="true" aria-labelledby="automation-create-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head"><div><span className="eyebrow">NEW AUTOMATION</span><strong id="automation-create-title">Create a routine</strong></div><button className="icon-button" type="button" onClick={() => setCreating(false)} disabled={saving} aria-label="Close"><X size={15} /></button></div>
            <label><span>Name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Weekly literature scan" /></label>
            <label><span>Description</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What this routine is for" /></label>
            <label><span>Instruction for AURA</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Describe what AURA should do each time it runs" rows={4} /></label>
            <div className="automation-scope-switch"><button type="button" className={scope === 'global' ? 'is-active' : ''} onClick={() => setScope('global')}>Global</button><button type="button" className={scope === 'project' ? 'is-active' : ''} onClick={() => setScope('project')}>Project</button></div>
            {scope === 'project' ? <label><span>Project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label> : null}
            <label className="automation-interval"><span>Run every</span><input type="number" min={1} max={31536000 / intervalUnits[unit]} value={interval} onChange={(event) => setInterval(Math.max(1, Number(event.target.value) || 1))} /><select value={unit} onChange={(event) => setUnit(event.target.value as IntervalUnit)}><option value="minutes">minutes</option><option value="hours">hours</option><option value="days">days</option></select></label>
            {error ? <p className="automation-form-error" role="alert">{error}</p> : null}
            <div className="modal-note">AURA queues scheduled runs through its durable event system. Tool actions still follow their normal approval rules.</div>
            <button className="primary-soft-button" type="button" onClick={() => void create()} disabled={saving || !name.trim() || !instruction.trim() || (scope === 'project' && !projectId)}>{saving ? 'Creating…' : 'Create automation'}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
