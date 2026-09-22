import { ArrowRight, FolderKanban, Plus } from 'lucide-react';
import { projects } from '../../data/workspaceData';

interface ProjectsViewProps {
  onOpenProject: (projectId: string) => void;
  onMockCreate: () => void;
}

export function ProjectsView({ onOpenProject, onMockCreate }: ProjectsViewProps) {
  return (
    <section className="projects-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">PROJECTS</span>
          <h1>Separate contexts, one personal workspace.</h1>
          <p>Each project gets its own overview, conversation graph, research context and artifacts.</p>
        </div>
        <button className="primary-soft-button" type="button" onClick={onMockCreate}><Plus size={15} /> New project</button>
      </div>

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
