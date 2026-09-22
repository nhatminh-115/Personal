import { BellRing, Check, Clock3, Pause, Play, Plus, Workflow, X } from 'lucide-react';
import { useState } from 'react';
import { projects, type AutomationRecord } from '../../data/workspaceData';

interface AutomationsViewProps {
  automations: AutomationRecord[];
  onAutomationsChange: (items: AutomationRecord[]) => void;
  onRunNow: (automation: AutomationRecord) => void;
}

export function AutomationsView({ automations, onAutomationsChange, onRunNow }: AutomationsViewProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [scope, setScope] = useState<'global' | 'project'>('global');
  const [projectId, setProjectId] = useState(projects[0].id);

  const toggle = (id: string) => {
    onAutomationsChange(automations.map((item) => item.id === id ? { ...item, enabled: !item.enabled, status: item.enabled ? 'paused' : 'ready', nextRun: item.enabled ? 'Paused' : item.nextRun === 'Paused' ? 'Next scheduled run' : item.nextRun } : item));
  };

  const create = () => {
    if (!name.trim()) return;
    const item: AutomationRecord = {
      id: `auto-${Date.now()}`,
      name: name.trim(),
      description: 'New local prototype automation. Trigger and actions can be refined later.',
      enabled: true,
      scope,
      projectId: scope === 'project' ? projectId : undefined,
      trigger: 'Manual / schedule not configured',
      actions: ['Ask AURA', 'Create workspace object'],
      lastRun: 'Never',
      nextRun: 'Not scheduled',
      status: 'ready',
    };
    onAutomationsChange([item, ...automations]);
    setName('');
    setCreating(false);
  };

  return (
    <section className="automations-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">AUTOMATIONS</span>
          <h1>Background routines without turning AURA into Zapier.</h1>
          <p>Global routines can use your personal workspace; project routines stay scoped to one project.</p>
        </div>
        <button className="primary-soft-button" type="button" onClick={() => setCreating(true)}><Plus size={15} /> New automation</button>
      </div>

      <div className="automation-summary-row">
        <div><Workflow size={15} /><span><strong>{automations.filter((item) => item.enabled).length} active</strong><small>{automations.length} total routines</small></span></div>
        <div><BellRing size={15} /><span><strong>Local prototype</strong><small>No real scheduler/backend yet</small></span></div>
      </div>

      <div className="automation-list">
        {automations.map((automation) => {
          const project = automation.projectId ? projects.find((item) => item.id === automation.projectId) : null;
          return (
            <article key={automation.id} className={`automation-card ${automation.enabled ? '' : 'is-paused'}`}>
              <button className={`automation-toggle ${automation.enabled ? 'is-on' : ''}`} type="button" onClick={() => toggle(automation.id)}><span /></button>
              <div className="automation-card__body">
                <div className="automation-card__title"><strong>{automation.name}</strong><span>{automation.scope === 'global' ? 'Global' : project?.name ?? 'Project'}</span></div>
                <p>{automation.description}</p>
                <div className="automation-trigger"><Clock3 size={12} /><strong>{automation.trigger}</strong></div>
                <div className="automation-steps">{automation.actions.map((action) => <span key={action}><Check size={10} /> {action}</span>)}</div>
                <div className="automation-card__footer"><span>Last: {automation.lastRun}</span><span>Next: {automation.enabled ? automation.nextRun : 'Paused'}</span></div>
              </div>
              <button className="automation-run" type="button" onClick={() => onRunNow(automation)} disabled={!automation.enabled}>{automation.enabled ? <Play size={13} /> : <Pause size={13} />} Run now</button>
            </article>
          );
        })}
      </div>

      {creating ? (
        <div className="modal-scrim" role="presentation" onMouseDown={() => setCreating(false)}>
          <div className="automation-create-modal" role="dialog" aria-modal="true" onMouseDown={(event) => event.stopPropagation()}>
            <div className="modal-head"><div><span className="eyebrow">NEW AUTOMATION</span><strong>Create a routine</strong></div><button className="icon-button" type="button" onClick={() => setCreating(false)}><X size={15} /></button></div>
            <label><span>Name</span><input autoFocus value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Weekly literature scan" /></label>
            <div className="automation-scope-switch"><button type="button" className={scope === 'global' ? 'is-active' : ''} onClick={() => setScope('global')}>Global</button><button type="button" className={scope === 'project' ? 'is-active' : ''} onClick={() => setScope('project')}>Project</button></div>
            {scope === 'project' ? <label><span>Project</span><select value={projectId} onChange={(event) => setProjectId(event.target.value)}>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label> : null}
            <div className="modal-note">This prototype stores the routine locally. Scheduling and external actions remain mocked.</div>
            <button className="primary-soft-button" type="button" onClick={create} disabled={!name.trim()}>Create automation</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
