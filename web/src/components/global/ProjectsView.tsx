import { ArrowRight, FolderKanban, Plus, X } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import type { ProjectRecord } from '../../data/workspaceData';

interface ProjectsViewProps {
  projects: ProjectRecord[];
  createRequest: number;
  onOpenProject: (projectId: string) => void;
  onCreateProject: (input: { name: string; subtitle: string }) => Promise<void>;
}

export function ProjectsView({ projects, createRequest, onOpenProject, onCreateProject }: ProjectsViewProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (createRequest > 0) setCreating(true);
  }, [createRequest]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      await onCreateProject({ name: name.trim(), subtitle: subtitle.trim() });
      setName('');
      setSubtitle('');
      setCreating(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not create project.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <section className="projects-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">PROJECTS</span>
          <h1>Separate contexts, one personal workspace.</h1>
          <p>Each project gets its own overview, conversation graph, research context and artifacts.</p>
        </div>
        <button className="primary-soft-button" type="button" onClick={() => { setCreating((value) => !value); setError(null); }}><Plus size={15} /> New project</button>
      </div>

      {creating ? (
        <form className="project-create-form" onSubmit={(event) => { void submit(event); }}>
          <div className="project-create-form__head"><strong>Create a project</strong><button className="icon-button" type="button" aria-label="Close project form" onClick={() => setCreating(false)}><X size={14} /></button></div>
          <label><span>Project name</span><input autoFocus maxLength={128} required value={name} onChange={(event) => setName(event.target.value)} placeholder="For example, Thesis research" /></label>
          <label><span>Description <small>Optional</small></span><input maxLength={255} value={subtitle} onChange={(event) => setSubtitle(event.target.value)} placeholder="What is this project about?" /></label>
          {error ? <p role="alert" className="project-create-form__error">{error}</p> : null}
          <div className="project-create-form__actions"><button className="soft-action-button" type="button" onClick={() => setCreating(false)}>Cancel</button><button className="primary-soft-button" type="submit" disabled={saving || !name.trim()}>{saving ? 'Creating…' : 'Create project'}</button></div>
        </form>
      ) : null}

      <div className="projects-list-grid">
        {projects.map((project) => (
          <button key={project.id} className={`project-overview-card project-overview-card--${project.accent}`} type="button" onClick={() => onOpenProject(project.id)}>
            <span className="project-overview-card__icon"><FolderKanban size={18} /></span>
            <span className="project-overview-card__copy">
              <strong>{project.name}</strong>
              <small>{project.subtitle}</small>
              <span>{project.meta}</span>
            </span>
            <span className="project-overview-card__updated">{project.updated}</span>
            <ArrowRight size={15} />
          </button>
        ))}
      </div>
    </section>
  );
}
