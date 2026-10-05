import { BellRing, Check, Clock3, Copy, Pause, Pencil, Play, Plus, Workflow, X } from 'lucide-react';
import { useRef, useState } from 'react';
import type { ApprovalDetail, AutomationExecutionRecord, RunDetail, RunRoutingDecision, RunEvent } from '../../types';
import { api } from '../../services/api';
import type { AutomationRecord, ProjectRecord } from '../../data/workspaceData';

interface AutomationInput {
  name: string;
  description: string;
  instruction: string;
  scope: 'global' | 'project';
  project_name?: string;
  interval_seconds: number;
  schedule: { mode: 'interval' | 'daily' | 'weekly'; local_time: string | null; weekdays: number[]; timezone: string };
  webhook_enabled?: boolean;
}

interface AutomationsViewProps {
  projects: ProjectRecord[];
  automations: AutomationRecord[];
  totalCount?: number;
  enabledCount?: number;
  hasMore?: boolean;
  loadingPage?: boolean;
  pageError?: string | null;
  onLoadMore?: () => void;
  onCreate: (input: AutomationInput) => Promise<AutomationRecord>;
  onUpdate?: (id: string, input: Pick<AutomationInput, 'name' | 'description' | 'instruction' | 'interval_seconds' | 'schedule' | 'webhook_enabled'>, expectedRevision: number) => Promise<AutomationRecord>;
  onDuplicate?: (automation: AutomationRecord) => void;
  onSetArchived?: (automation: AutomationRecord, archived: boolean) => void;
  includeArchived?: boolean;
  onToggleArchived?: () => void;
  onToggle: (automation: AutomationRecord, enabled: boolean) => void;
  onRunNow: (automation: AutomationRecord) => void;
  onCancelRun?: (automationId: string, eventId: string) => Promise<AutomationExecutionRecord>;
  onRetryRun?: (automationId: string, eventId: string) => Promise<AutomationExecutionRecord>;
  onApprovalResolved: (automationId: string) => void;
}

const intervalUnits = { seconds: 1, minutes: 60, hours: 3600, days: 86400 } as const;
type IntervalUnit = keyof typeof intervalUnits;
const weekdays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

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

function triggerSourceLabel(triggerType?: 'schedule' | 'manual' | 'webhook' | 'retry'): string {
  if (triggerType === 'webhook') return 'webhook';
  if (triggerType === 'schedule') return 'schedule';
  if (triggerType === 'retry') return 'retry';
  return 'manual run';
}

export function AutomationsView({ projects, automations, totalCount = automations.filter((item) => item.source === 'live').length, enabledCount = automations.filter((item) => item.source === 'live' && item.enabled).length, hasMore = false, loadingPage = false, pageError = null, onLoadMore = () => {}, onCreate, onUpdate, onDuplicate, onSetArchived, includeArchived = false, onToggleArchived, onToggle, onRunNow, onCancelRun, onRetryRun, onApprovalResolved }: AutomationsViewProps) {
  const [creating, setCreating] = useState(false);
  const [editingAutomation, setEditingAutomation] = useState<AutomationRecord | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [instruction, setInstruction] = useState('');
  const [scope, setScope] = useState<'global' | 'project'>('global');
  const [projectId, setProjectId] = useState(projects[0]?.id ?? '');
  const [interval, setInterval] = useState(1);
  const [unit, setUnit] = useState<IntervalUnit>('days');
  const [scheduleMode, setScheduleMode] = useState<'interval' | 'daily' | 'weekly'>('interval');
  const [scheduleTime, setScheduleTime] = useState('09:00');
  const [scheduleWeekdays, setScheduleWeekdays] = useState<number[]>([0, 1, 2, 3, 4]);
  const [scheduleTimezone, setScheduleTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [webhookSetup, setWebhookSetup] = useState<{ path: string; secret: string } | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [approvalReview, setApprovalReview] = useState<{ automation: AutomationRecord; approval: ApprovalDetail } | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(false);
  const [approvalError, setApprovalError] = useState('');
  const [approvalNotes, setApprovalNotes] = useState('');
  const [approvalEditing, setApprovalEditing] = useState(false);
  const [approvalEditedJson, setApprovalEditedJson] = useState('');
  const [historyAutomationId, setHistoryAutomationId] = useState<string | null>(null);
  const [historyByAutomation, setHistoryByAutomation] = useState<Record<string, AutomationExecutionRecord[]>>({});
  const [historyCursorByAutomation, setHistoryCursorByAutomation] = useState<Record<string, string | null>>({});
  const [historyLoadingId, setHistoryLoadingId] = useState<string | null>(null);
  const [cancellingEventId, setCancellingEventId] = useState<string | null>(null);
  const [retryingEventId, setRetryingEventId] = useState<string | null>(null);
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
      const page = await api.fetchAutomationRuns(automationId, 10);
      if (historyRequest.current !== requestId) return;
      setHistoryByAutomation((current) => ({ ...current, [automationId]: page.runs }));
      setHistoryCursorByAutomation((current) => ({ ...current, [automationId]: page.nextCursor }));
    } catch (cause) {
      if (historyRequest.current !== requestId) return;
      setHistoryError(cause instanceof Error ? cause.message : 'Could not load run history.');
    } finally {
      if (historyRequest.current === requestId) setHistoryLoadingId(null);
    }
  };

  const loadOlderRunHistory = async (automationId: string) => {
    const cursor = historyCursorByAutomation[automationId];
    if (!cursor || historyLoadingId === automationId) return;
    const requestId = ++historyRequest.current;
    setHistoryError('');
    setHistoryLoadingId(automationId);
    try {
      const page = await api.fetchAutomationRuns(automationId, 10, cursor);
      if (historyRequest.current !== requestId) return;
      setHistoryByAutomation((current) => ({
        ...current,
        [automationId]: [...(current[automationId] ?? []), ...page.runs],
      }));
      setHistoryCursorByAutomation((current) => ({ ...current, [automationId]: page.nextCursor }));
    } catch (cause) {
      if (historyRequest.current !== requestId) return;
      setHistoryError(cause instanceof Error ? cause.message : 'Could not load older runs.');
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

  const cancelAutomationRun = async (automation: AutomationRecord, run: AutomationExecutionRecord) => {
    if (!onCancelRun || !['queued', 'running'].includes(run.status) || cancellingEventId) return;
    setCancellingEventId(run.event_id);
    setHistoryError('');
    try {
      const cancelled = await onCancelRun(automation.id, run.event_id);
      setHistoryByAutomation((current) => ({
        ...current,
        [automation.id]: (current[automation.id] ?? []).map((item) => item.event_id === run.event_id ? cancelled : item),
      }));
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : 'Could not request run cancellation.');
    } finally {
      setCancellingEventId(null);
    }
  };

  const retryFailedRun = async (automation: AutomationRecord, run: AutomationExecutionRecord) => {
    if (!onRetryRun || !['failed', 'dead_letter'].includes(run.status) || retryingEventId) return;
    setRetryingEventId(run.event_id);
    setHistoryError('');
    try {
      const retry = await onRetryRun(automation.id, run.event_id);
      setHistoryByAutomation((current) => ({
        ...current,
        [automation.id]: [retry, ...(current[automation.id] ?? []).filter((item) => item.event_id !== retry.event_id)],
      }));
    } catch (cause) {
      setHistoryError(cause instanceof Error ? cause.message : 'Could not retry this run.');
    } finally {
      setRetryingEventId(null);
    }
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

  const openEditor = (automation: AutomationRecord) => {
    setEditingAutomation(automation);
    setName(automation.name);
    setDescription(automation.description);
    setInstruction(automation.instruction ?? '');
    setScope(automation.scope);
    setProjectId(automation.projectId ?? projects.find((project) => project.name === automation.projectName)?.id ?? '');
    const seconds = Math.max(1, automation.intervalSeconds ?? 86400);
    const unit = (Object.entries(intervalUnits).reverse().find(([, size]) => seconds % size === 0)?.[0] ?? 'seconds') as IntervalUnit;
    setUnit(unit);
    setInterval(seconds / intervalUnits[unit]);
    const schedule = automation.schedule ?? { mode: 'interval' as const, local_time: null, weekdays: [], timezone: 'UTC' };
    setScheduleMode(schedule.mode);
    setScheduleTime(schedule.local_time ?? '09:00');
    setScheduleWeekdays(schedule.weekdays.length ? schedule.weekdays : [0, 1, 2, 3, 4]);
    setScheduleTimezone(schedule.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC');
    setWebhookEnabled(automation.webhookEnabled ?? false);
    setError('');
    setCreating(true);
  };

  const closeEditor = () => {
    if (saving) return;
    setCreating(false);
    setEditingAutomation(null);
    setError('');
  };

  const save = async () => {
    if (saving || !name.trim() || !instruction.trim() || (!editingAutomation && scope === 'project' && !projectId)) return;
    setSaving(true);
    setError('');
    try {
      const common = {
        name: name.trim(), description: description.trim(), instruction: instruction.trim(),
        interval_seconds: interval * intervalUnits[unit],
        schedule: {
          mode: scheduleMode,
          local_time: scheduleMode === 'interval' ? null : scheduleTime,
          weekdays: scheduleMode === 'weekly' ? scheduleWeekdays : [],
          timezone: scheduleTimezone,
        },
        webhook_enabled: webhookEnabled,
      };
      let saved: AutomationRecord;
      if (editingAutomation) {
        if (!onUpdate) throw new Error('Editing automations is unavailable.');
        if (editingAutomation.revision === undefined) throw new Error('Reload this automation before editing it.');
        saved = await onUpdate(editingAutomation.id, common, editingAutomation.revision);
      } else {
        const project = projects.find((item) => item.id === projectId);
        saved = await onCreate({ ...common, scope, project_name: scope === 'project' ? project?.name : undefined });
      }
      if (saved.webhookSecret && saved.webhookPath) setWebhookSetup({ path: saved.webhookPath, secret: saved.webhookSecret });
      setName(''); setDescription(''); setInstruction(''); setCreating(false); setEditingAutomation(null); setScheduleMode('interval');
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save automation.');
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
          <p>Scheduled instructions and secret-authenticated webhook signals run through AURA, scoped to your workspace or one project.</p>
        </div>
        <div className="automations-view__header-actions">
          {onToggleArchived ? <button className="secondary-button" type="button" onClick={onToggleArchived} disabled={loadingPage}>{includeArchived ? 'Hide archived' : 'Include archived'}</button> : null}
          <button className="primary-soft-button" type="button" onClick={() => { setEditingAutomation(null); setName(''); setDescription(''); setInstruction(''); setScheduleMode('interval'); setWebhookEnabled(false); setScheduleTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'); setCreating(true); }}><Plus size={15} /> New automation</button>
        </div>
      </div>

      <div className="automation-summary-row">
        <div><Workflow size={15} /><span><strong>{enabledCount} active</strong><small>{totalCount} scheduled routines</small></span></div>
        <div><BellRing size={15} /><span><strong>Persistent scheduler</strong><small>Runs are queued through AURA</small></span></div>
      </div>

      {webhookSetup ? (
        <div className="modal-scrim" role="presentation">
          <div className="automation-create-modal automation-webhook-secret" role="dialog" aria-modal="true" aria-labelledby="automation-webhook-title">
            <div className="modal-head"><div><span className="eyebrow">WEBHOOK SECRET</span><strong id="automation-webhook-title">Save this secret now</strong></div><button className="icon-button" type="button" onClick={() => setWebhookSetup(null)} aria-label="Close"><X size={15} /></button></div>
            <p>This secret is shown once. Send a POST request with <code>Authorization: Bearer &lt;secret&gt;</code> and a unique <code>X-Aura-Event-Id</code>. The request body is ignored; AURA runs only the saved instruction.</p>
            <label><span>Webhook path</span><code>{webhookSetup.path}</code></label>
            <label><span>Secret</span><code>{webhookSetup.secret}</code></label>
            <div className="automation-approval-actions"><button type="button" className="secondary-button" onClick={() => void navigator.clipboard?.writeText(webhookSetup.secret)}>Copy secret</button><button type="button" className="primary-soft-button" onClick={() => setWebhookSetup(null)}>Done</button></div>
          </div>
        </div>
      ) : null}

      {approvalError && !approvalReview ? <p className="automation-form-error" role="alert">{approvalError}</p> : null}
      <div className="automation-list">
        {automations.map((automation) => {
          const project = automation.projectId ? projects.find((item) => item.id === automation.projectId) : null;
          const live = automation.source === 'live';
          const runInProgress = ['queued', 'running', 'cancellation_requested', 'waiting_for_approval', 'waiting_for_routing_confirmation']
            .includes(automation.latestExecution?.status ?? '');
          return (
            <article key={automation.id} className={`automation-card ${automation.archived ? 'is-archived' : automation.enabled ? '' : 'is-paused'}`}>
              <button aria-label={`${automation.enabled ? 'Pause' : 'Resume'} ${automation.name}`} className={`automation-toggle ${automation.enabled ? 'is-on' : ''}`} type="button" onClick={() => onToggle(automation, !automation.enabled)} disabled={!live || automation.archived}><span /></button>
              <div className="automation-card__body">
                <div className="automation-card__title"><strong>{automation.name}</strong><span>{automation.archived ? 'Archived' : live ? (automation.scope === 'global' ? 'Global' : project?.name ?? automation.projectName ?? 'Project') : 'Example'}</span></div>
                <p>{automation.description}</p>
                {live ? <details className="automation-instruction"><summary>Instruction</summary><p>{automation.instruction}</p></details> : null}
                <div className="automation-trigger"><Clock3 size={12} /><strong>{automation.trigger}</strong></div>
                {live && automation.webhookEnabled && automation.webhookPath ? <details className="automation-instruction"><summary>Webhook endpoint</summary><code>{automation.webhookPath}</code><p>The secret is never shown again. Disable then re-enable this trigger to rotate it.</p></details> : null}
                {live && automation.latestExecution ? <div className={`automation-execution-status is-${automation.latestExecution.status}`}><span>Latest run</span><small>Started by {triggerSourceLabel(automation.latestExecution.triggerType)}</small><strong>{automation.latestExecution.status.replace(/_/g, ' ')}</strong>{automation.latestExecution.retryCount > 0 ? <small>{automation.latestExecution.retryCount} retries</small> : null}{automation.latestExecution.status === 'waiting_for_approval' ? <button type="button" onClick={() => void openApprovalReview(automation)} disabled={approvalLoading}>{approvalLoading ? 'Loading approval…' : 'Review approval'}</button> : null}</div> : null}
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
                                <small className="automation-trigger-origin">via {triggerSourceLabel(run.trigger_type)}</small>
                                <strong>{run.status.replace(/_/g, ' ')}</strong>
                                {run.retry_count > 0 ? <small>{run.retry_count} retries</small> : null}
                                {run.retry_of_event_id ? <small>Retry of {run.retry_of_event_id.slice(0, 8)}</small> : null}
                                {['failed', 'dead_letter'].includes(run.status) && onRetryRun && automation.enabled && !automation.archived ? <button type="button" onClick={() => void retryFailedRun(automation, run)} disabled={retryingEventId !== null || runInProgress} title={runInProgress ? 'Wait for the current Automation run to finish' : "Queue a fresh run using the Automation's saved instruction"}>{retryingEventId === run.event_id ? 'Queueing retry…' : 'Retry run'}</button> : ['queued', 'running'].includes(run.status) && onCancelRun ? <button type="button" onClick={() => void cancelAutomationRun(automation, run)} disabled={cancellingEventId !== null} title={run.status === 'queued' ? 'Cancel before execution starts' : 'Request cooperative cancellation at the next safe execution boundary'}>{cancellingEventId === run.event_id ? 'Sending request…' : run.status === 'queued' ? 'Cancel queued run' : 'Stop active run'}</button> : run.status === 'cancellation_requested' ? <span title="An operation already in progress may finish before AURA observes the request.">Stop requested · waiting for a safe boundary</span> : run.status === 'cancelled' ? <span title="An operation already in progress may have completed before cancellation took effect.">Run cancelled</span> : <button type="button" onClick={() => void inspectRun(automation, run.run_id)} disabled={runLoadingId !== null || run.status === 'queued'} title="Inspect persisted run result and operational provenance">{runLoadingId === run.run_id ? 'Loading run…' : 'Inspect run'}</button>}
                              </li>
                            ))}
                          </ol>
                        ) : null}
                        {historyCursorByAutomation[automation.id] ? <button type="button" className="secondary-button" onClick={() => void loadOlderRunHistory(automation.id)} disabled={historyLoadingId === automation.id}>{historyLoadingId === automation.id ? 'Loading older runs…' : 'Load older runs'}</button> : null}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {live ? <div className="automation-steps">{automation.actions.map((action) => <span key={action}><Check size={10} /> {action}</span>)}</div> : null}
                <div className="automation-card__footer"><span>Last: {automation.lastRun}</span><span>Next: {automation.archived ? 'Archived' : live && automation.enabled ? automation.nextRun : live ? 'Paused' : 'Example data'}</span></div>
              </div>
              <div className="automation-card__actions">
                {live ? <button className="secondary-button" type="button" aria-label={`Edit ${automation.name}`} onClick={() => openEditor(automation)} disabled={!onUpdate || automation.archived}><Pencil size={13} /> Edit</button> : null}
                {live && onDuplicate ? <button className="secondary-button" type="button" onClick={() => onDuplicate(automation)} title="Create a paused copy with independent run history"><Copy size={13} /> Duplicate</button> : null}
                {live && onSetArchived ? <button className="secondary-button" type="button" onClick={() => onSetArchived(automation, !automation.archived)} title={automation.archived ? 'Restore this paused routine; its history is preserved' : 'Stop future schedules and keep run history; already queued runs can still finish'}>{automation.archived ? 'Restore' : 'Archive'}</button> : null}
                <button className="automation-run" type="button" onClick={() => onRunNow(automation)} disabled={!live || !automation.enabled || automation.archived || runInProgress} title={automation.archived ? 'Archived routines cannot run' : runInProgress ? 'A run is already active' : live ? 'Queue a run through AURA' : 'Examples do not run'}>{automation.enabled && !automation.archived ? <Play size={13} /> : <Pause size={13} />} Run now</button>
              </div>
            </article>
          );
        })}
      </div>

      {pageError ? <div className="notes-list-pagination" role="status"><span>Could not load automations: {pageError}</span><button type="button" disabled={loadingPage} onClick={onLoadMore}>Retry</button></div> : null}
      {loadingPage && !pageError ? <div className="notes-list-pagination" role="status">Loading automations…</div> : null}
      {!pageError && hasMore ? <button className="notes-load-more" type="button" disabled={loadingPage} onClick={onLoadMore}>{loadingPage ? 'Loading automations…' : 'Load more automations'}</button> : null}

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
        <div className="modal-scrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeEditor(); }}>
          <div className="automation-create-modal" role="dialog" aria-modal="true" aria-labelledby="automation-create-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head"><div><span className="eyebrow">{editingAutomation ? 'EDIT AUTOMATION' : 'NEW AUTOMATION'}</span><strong id="automation-create-title">{editingAutomation ? 'Update this routine' : 'Create a routine'}</strong></div><button className="icon-button" type="button" onClick={closeEditor} disabled={saving} aria-label="Close"><X size={15} /></button></div>
            <label><span>Name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Weekly literature scan" /></label>
            <label><span>Description</span><input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What this routine is for" /></label>
            <label><span>Instruction for AURA</span><textarea value={instruction} onChange={(event) => setInstruction(event.target.value)} placeholder="Describe what AURA should do each time it runs" rows={4} /></label>
            <label className="automation-webhook-option"><input type="checkbox" checked={webhookEnabled} onChange={(event) => setWebhookEnabled(event.target.checked)} /><span><strong>Allow secret-authenticated webhook triggers</strong><small>External services can queue this saved instruction. Request bodies are ignored.</small></span></label>
            {editingAutomation ? <p className="modal-note">Scope stays {editingAutomation.scope === 'global' ? 'global' : `in ${editingAutomation.projectName ?? 'its current project'}`} so this routine keeps its existing session and history.</p> : <><div className="automation-scope-switch"><button type="button" className={scope === 'global' ? 'is-active' : ''} onClick={() => setScope('global')}>Global</button><button type="button" className={scope === 'project' ? 'is-active' : ''} onClick={() => setScope('project')}>Project</button></div>{scope === 'project' ? <label><span>Project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label> : null}</>}
            <label><span>Schedule</span><select aria-label="Schedule" value={scheduleMode} onChange={(event) => setScheduleMode(event.target.value as typeof scheduleMode)}><option value="interval">Repeat after an interval</option><option value="daily">Every day at a local time</option><option value="weekly">Selected weekdays at a local time</option></select></label>
            {scheduleMode === 'interval' ? <label className="automation-interval"><span>Run every</span><input type="number" min={unit === 'seconds' ? 60 : 1} max={31536000 / intervalUnits[unit]} value={interval} onChange={(event) => setInterval(Math.max(unit === 'seconds' ? 60 : 1, Number(event.target.value) || 1))} /><select value={unit} onChange={(event) => { const nextUnit = event.target.value as IntervalUnit; setUnit(nextUnit); setInterval((current) => Math.max(nextUnit === 'seconds' ? 60 : 1, current)); }}><option value="seconds">seconds</option><option value="minutes">minutes</option><option value="hours">hours</option><option value="days">days</option></select></label> : <>
              <label><span>Local time</span><input aria-label="Local time" type="time" value={scheduleTime} onChange={(event) => setScheduleTime(event.target.value)} /></label>
              {scheduleMode === 'weekly' ? <fieldset className="automation-weekdays"><legend>Run on</legend>{weekdays.map((day, index) => <label key={day}><input type="checkbox" checked={scheduleWeekdays.includes(index)} onChange={(event) => setScheduleWeekdays((current) => event.target.checked ? [...current, index].sort() : current.filter((value) => value !== index))} />{day}</label>)}</fieldset> : null}
              <label><span>Timezone</span><input aria-label="Timezone" value={scheduleTimezone} onChange={(event) => setScheduleTimezone(event.target.value)} placeholder="Asia/Saigon" /></label>
              {scheduleMode === 'weekly' && scheduleWeekdays.length === 0 ? <p className="automation-form-error" role="alert">Choose at least one weekday.</p> : null}
            </>}
            {error ? <p className="automation-form-error" role="alert">{error}</p> : null}
            <div className="modal-note">AURA queues scheduled runs through its durable event system. Tool actions still follow their normal approval rules.{editingAutomation ? ' Changing the interval starts a new countdown from save time. Already queued runs keep the instruction snapshot they started with.' : ''}</div>
            <button className="primary-soft-button" type="button" onClick={() => void save()} disabled={saving || !name.trim() || !instruction.trim() || (!editingAutomation && scope === 'project' && !projectId) || (scheduleMode === 'weekly' && scheduleWeekdays.length === 0) || !scheduleTimezone.trim()}>{saving ? 'Saving…' : editingAutomation ? 'Save changes' : 'Create automation'}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
