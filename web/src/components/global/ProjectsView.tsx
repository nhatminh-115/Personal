import { Archive, ArchiveRestore, ArrowRight, FolderKanban, Plus, X } from 'lucide-react';
import { useEffect, useState, type FormEvent } from 'react';
import type { ProjectRecord } from '../../data/workspaceData';

interface ProjectsViewProps {
  projects: ProjectRecord[];
  createRequest: number;
  onOpenProject: (projectId: string) => void;
  onCreateProject: (input: { name: string; subtitle: string }) => Promise<void>;
  onSetArchived: (project: ProjectRecord, archived: boolean) => Promise<void>;
}

export function ProjectsView({ projects, createRequest, onOpenProject, onCreateProject, onSetArchived }: ProjectsViewProps) {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [subtitle, setSubtitle] = useState('');
  const [saving, setSaving] = useState(false);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [archivePendingId, setArchivePendingId] = useState<string | null>(null);
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

  const visibleProjects = projects.filter((project) => Boolean(project.archived) === includeArchived);
  const archivedCount = projects.filter((project) => project.archived && project.source === 'user').length;
  const setProjectArchived = async (project: ProjectRecord, archived: boolean) => {
    if (archivePendingId) return;
    setArchivePendingId(project.id);
    try {
      await onSetArchived(project, archived);
    } finally {
      setArchivePendingId(null);
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
        <div className="projects-view__actions">
          <button className="soft-action-button" type="button" aria-pressed={includeArchived} onClick={() => setIncludeArchived((value) => !value)}>
            {includeArchived ? 'Hide archived' : `Show archived${archivedCount ? ` (${archivedCount})` : ''}`}
          </button>
          <button className="primary-soft-button" type="button" onClick={() => { setCreating((value) => !value); setError(null); }}><Plus size={15} /> New project</button>
        </div>
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
        {visibleProjects.map((project) => (
          <div key={project.id} className="project-overview-card-wrap">
            <button className={`project-overview-card project-overview-card--${project.accent}`} type="button" onClick={() => onOpenProject(project.id)}>
              <span className="project-overview-card__icon"><FolderKanban size={18} /></span>
              <span className="project-overview-card__copy">
                <strong>{project.name}</strong>
                <small>{project.subtitle}</small>
                <span>{project.meta}</span>
                {project.archived ? <span className="project-overview-card__status">Archived</span> : null}
              </span>
              <span className="project-overview-card__updated">{project.updated}</span>
              <ArrowRight size={15} />
            </button>
            {project.source === 'user' ? (
              <button
                className="project-overview-card__archive"
                type="button"
                aria-label={`${project.archived ? 'Restore' : 'Archive'} ${project.name}`}
                title={project.archived ? 'Restore project' : 'Archive project'}
                disabled={archivePendingId === project.id}
                onClick={() => { void setProjectArchived(project, !project.archived); }}
              >
                {project.archived ? <ArchiveRestore size={14} /> : <Archive size={14} />}
              </button>
            ) : null}
          </div>
        ))}
        {visibleProjects.length === 0 ? (
          <p className="projects-view__empty">
            {includeArchived ? 'No archived projects yet. Archiving keeps project data and history available for later restore.' : 'No projects yet. Create a project to give related chats and files a shared home.'}
          </p>
        ) : null}
      </div>
    </section>
  );
}
