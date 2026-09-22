import { ArrowRight, BookOpenText, Clock3, FolderKanban, Sparkles } from 'lucide-react';
import { projects, type AutomationRecord, type LibraryItem } from '../../data/workspaceData';

interface GlobalHomeProps {
  libraryItems: LibraryItem[];
  automations: AutomationRecord[];
  noteCount: number;
  onOpenProject: (projectId: string) => void;
  onOpenProjects: () => void;
  onOpenLibrary: () => void;
  onOpenFile: (id: string) => void;
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function GlobalHome({ libraryItems, automations, noteCount, onOpenProject, onOpenProjects, onOpenLibrary, onOpenFile }: GlobalHomeProps) {
  const recent = projects.slice(0, 3);
  const recentFiles = libraryItems.slice(0, 4);
  const activeAutomations = automations.filter((item) => item.enabled).length;

  return (
    <section className="global-home">
      <div className="global-home__hero">
        <span className="eyebrow">PERSONAL WORKSPACE</span>
        <h1>{greeting()}.</h1>
        <p>Pick up a project, open a personal file, continue studying, or ask AURA across the workspace.</p>
      </div>

      <div className="global-home__section global-home__section--continue">
        <div className="section-heading">
          <div><span className="eyebrow">CONTINUE</span><h2>Recent projects</h2></div>
          <button className="text-button" type="button" onClick={onOpenProjects}>All projects <ArrowRight size={14} /></button>
        </div>

        <div className="project-card-grid">
          {recent.map((project) => (
            <button type="button" key={project.id} className={`project-card project-card--${project.accent}`} onClick={() => onOpenProject(project.id)}>
              <span className="project-card__icon"><FolderKanban size={17} /></span>
              <span className="project-card__body"><strong>{project.name}</strong><small>{project.subtitle}</small><span>{project.meta}</span></span>
              <span className="project-card__time"><Clock3 size={12} /> {project.updated}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="global-home__columns">
        <section className="home-panel">
          <div className="section-heading section-heading--compact">
            <div><span className="eyebrow">RECENT FILES</span><h2>Your library</h2></div>
            <button className="icon-button" type="button" onClick={onOpenLibrary} title="Open library"><ArrowRight size={15} /></button>
          </div>
          <div className="recent-file-list">
            {recentFiles.map((item) => (
              <button className="recent-file" type="button" key={item.id} onClick={() => onOpenFile(item.id)}>
                <span className={`file-kind file-kind--${item.kind.toLowerCase()}`}>{item.kind}</span>
                <span className="recent-file__copy"><strong>{item.name}</strong><small>{item.collection} · {item.updated}</small></span>
                <ArrowRight size={13} />
              </button>
            ))}
          </div>
        </section>

        <section className="home-panel home-panel--ambient">
          <span className="eyebrow">WORKSPACE PULSE</span>
          <div className="ambient-stat"><Sparkles size={16} /><div><strong>{activeAutomations} active automations</strong><span>Across personal + project scopes</span></div></div>
          <div className="ambient-stat"><BookOpenText size={16} /><div><strong>{libraryItems.length} library artifacts</strong><span>Reusable across {projects.length} projects</span></div></div>
          <div className="ambient-note"><span>Linked knowledge</span><strong>{noteCount} notes · {libraryItems.filter((item) => item.projectLinks?.length).length} linked files</strong></div>
        </section>
      </div>
    </section>
  );
}
