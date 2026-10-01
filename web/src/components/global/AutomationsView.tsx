import { BellRing, Clock3, Pause, Play, Plus, Trash2, Workflow, X } from 'lucide-react';
import { useState } from 'react';
import { projects, type AutomationRecord } from '../../data/workspaceData';

interface AutomationDraft {
  name: string;
  description: string;
  prompt: string;
  scope: 'global' | 'project';
  projectId: string;
  intervalSeconds: number;
}

interface AutomationsViewProps {
  automations: AutomationRecord[];
  loading?: boolean;
  error?: string | null;
  onCreate: (draft: AutomationDraft) => Promise<void>;
  onToggle: (automation: AutomationRecord) => void;
  onDelete: (automation: AutomationRecord) => void;
  onRunNow: (automation: AutomationRecord) => void;
}

const blankDraft = (): AutomationDraft => ({
  name: '', description: '', prompt: '', scope: 'global', projectId: projects[0]?.id ?? '', intervalSeconds: 86_400,
});

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function AutomationsView({ automations, loading = false, error, onCreate, onToggle, onDelete, onRunNow }: AutomationsViewProps) {
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<AutomationDraft>(blankDraft);
  const [saving, setSaving] = useState(false);

  const create = async () => {
    if (!draft.name.trim() || !draft.prompt.trim()) return;
    setSaving(true);
    try {
      await onCreate(draft);
      setDraft(blankDraft());
      setCreating(false);
    } catch {
      // The parent renders the structured API error notice.
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
          <p>Scheduled runs use local-only model routing. Tools that change external state still require their normal approval.</p>
        </div>
        <button className="primary-soft-button" type="button" onClick={() => setCreating(true)}><Plus size={15} /> New automation</button>
      </div>

      <div className="automation-summary-row">
        <div><Workflow size={15} /><span><strong>{automations.filter((item) => item.enabled).length} active</strong><small>{automations.length} saved routines</small></span></div>
        <div><BellRing size={15} /><span><strong>Durable scheduler</strong><small>Runs are queued and traced by AURA</small></span></div>
      </div>

      {error ? <div className="routing-error-notice" role="alert">{error}</div> : null}
      {loading ? <div className="automation-empty">Loading saved automations…</div> : null}
      {!loading && automations.length === 0 ? <div className="automation-empty">No automations yet. Create a routine with a prompt and a schedule.</div> : null}
      <div className="automation-list">
        {automations.map((automation) => {
          const project = automation.projectId ? projects.find((item) => item.id === automation.projectId) : null;
          const schedule = automation.intervalSeconds === 604_800 ? 'Every week' : automation.intervalSeconds === 86_400 ? 'Every day' : `Every ${Math.round((automation.intervalSeconds ?? 0) / 3600)} hours`;
          return (
            <article key={automation.id} className={`automation-card ${automation.enabled ? '' : 'is-paused'}`}>
              <button className={`automation-toggle ${automation.enabled ? 'is-on' : ''}`} type="button" onClick={() => onToggle(automation)} aria-label={`${automation.enabled ? 'Pause' : 'Resume'} ${automation.name}`}><span /></button>
              <div className="automation-card__body">
                <div className="automation-card__title"><strong>{automation.name}</strong><span>{automation.scope === 'global' ? 'Global' : project?.name ?? 'Project'}</span></div>
                <p>{automation.description || automation.prompt}</p>
                <div className="automation-trigger"><Clock3 size={12} /><strong>{schedule} · next {automation.enabled ? formatDate(automation.nextRun) : 'Paused'}</strong></div>
                <div className="automation-steps"><span>Prompt-backed root agent run</span><span>Local-only routing</span></div>
                <div className="automation-card__footer"><span>Last: {automation.lastRun}</span><span>Status: {automation.status}</span></div>
              </div>
              <button className="automation-run" type="button" onClick={() => onRunNow(automation)} disabled={!automation.enabled}>{automation.enabled ? <Play size={13} /> : <Pause size={13} />} Run now</button>
              <button className="icon-button" type="button" onClick={() => onDelete(automation)} title={`Delete ${automation.name}`} aria-label={`Delete ${automation.name}`}><Trash2 size={14} /></button>
            </article>
          );
        })}
      </div>

      {creating ? (
        <div className="modal-scrim" role="presentation" onMouseDown={() => !saving && setCreating(false)}>
          <div className="automation-create-modal" role="dialog" aria-modal="true" aria-labelledby="automation-create-title" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head"><div><span className="eyebrow">NEW AUTOMATION</span><strong id="automation-create-title">Create a routine</strong></div><button className="icon-button" type="button" onClick={() => setCreating(false)} disabled={saving}><X size={15} /></button></div>
            <label><span>Name</span><input autoFocus value={draft.name} onChange={(event) => setDraft((value) => ({ ...value, name: event.target.value }))} placeholder="e.g. Weekly literature scan" /></label>
            <label><span>What should AURA do?</span><textarea value={draft.prompt} onChange={(event) => setDraft((value) => ({ ...value, prompt: event.target.value }))} placeholder="Describe the task AURA should run on each schedule…" rows={5} /></label>
            <label><span>Description (optional)</span><input value={draft.description} onChange={(event) => setDraft((value) => ({ ...value, description: event.target.value }))} placeholder="A short label for this routine" /></label>
            <label><span>Schedule</span><select value={draft.intervalSeconds} onChange={(event) => setDraft((value) => ({ ...value, intervalSeconds: Number(event.target.value) }))}><option value={86_400}>Every day</option><option value={604_800}>Every week</option></select></label>
            <div className="automation-scope-switch"><button type="button" className={draft.scope === 'global' ? 'is-active' : ''} onClick={() => setDraft((value) => ({ ...value, scope: 'global' }))}>Global</button><button type="button" className={draft.scope === 'project' ? 'is-active' : ''} onClick={() => setDraft((value) => ({ ...value, scope: 'project' }))}>Project</button></div>
            {draft.scope === 'project' ? <label><span>Project</span><select value={draft.projectId} onChange={(event) => setDraft((value) => ({ ...value, projectId: event.target.value }))}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label> : null}
            <div className="modal-note">Scheduled runs use local-only model routing and cannot continue automatically if a tool needs approval.</div>
            <button className="primary-soft-button" type="button" onClick={() => void create()} disabled={saving || !draft.name.trim() || !draft.prompt.trim()}>{saving ? 'Saving…' : 'Create automation'}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
