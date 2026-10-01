import { BellRing, Check, Clock3, Pause, Play, Plus, Workflow, X } from 'lucide-react';
import { useState } from 'react';
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
}

const intervalUnits = { minutes: 60, hours: 3600, days: 86400 } as const;
type IntervalUnit = keyof typeof intervalUnits;

export function AutomationsView({ projects, automations, onCreate, onToggle, onRunNow }: AutomationsViewProps) {
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
                {live ? <div className="automation-steps">{automation.actions.map((action) => <span key={action}><Check size={10} /> {action}</span>)}</div> : null}
                <div className="automation-card__footer"><span>Last: {automation.lastRun}</span><span>Next: {live && automation.enabled ? automation.nextRun : live ? 'Paused' : 'Example data'}</span></div>
              </div>
              <button className="automation-run" type="button" onClick={() => onRunNow(automation)} disabled={!live || !automation.enabled} title={live ? 'Queue a run through AURA' : 'Examples do not run'}>{automation.enabled ? <Play size={13} /> : <Pause size={13} />} Run now</button>
            </article>
          );
        })}
      </div>

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
