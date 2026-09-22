import {
  BookOpenText,
  ChevronDown,
  ChevronRight,
  CircleUserRound,
  FileText,
  FolderKanban,
  Home,
  Library,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Sparkles,
  Workflow,
} from 'lucide-react';
import { useState } from 'react';
import { projects } from '../../data/workspaceData';

export type SidebarDestination = 'home' | 'library' | 'notes' | 'study' | 'projects' | 'automations';

const globalNav: { label: string; id: SidebarDestination; icon: typeof Home }[] = [
  { label: 'Home', id: 'home', icon: Home },
  { label: 'Library', id: 'library', icon: Library },
  { label: 'Notes', id: 'notes', icon: NotebookPen },
  { label: 'Study', id: 'study', icon: FileText },
  { label: 'Automations', id: 'automations', icon: Workflow },
];

interface SidebarProps {
  collapsed: boolean;
  active: SidebarDestination | null;
  activeProjectId: string | null;
  libraryCount: number;
  onCollapsedChange: (collapsed: boolean) => void;
  onNavigate: (destination: SidebarDestination) => void;
  onProjectOpen: (projectId: string) => void;
  onNewProject: () => void;
}

export function Sidebar({
  collapsed,
  active,
  activeProjectId,
  libraryCount,
  onCollapsedChange,
  onNavigate,
  onProjectOpen,
  onNewProject,
}: SidebarProps) {
  const [hovered, setHovered] = useState(false);
  const [projectsOpen, setProjectsOpen] = useState(true);
  const visuallyExpanded = !collapsed || hovered;

  return (
    <aside
      className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''} ${visuallyExpanded ? 'sidebar--peek-open' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="brand-row">
        <div className="aura-mark" aria-hidden="true"><Sparkles size={15} strokeWidth={2.1} /></div>
        {visuallyExpanded ? <span className="brand-word">AURA</span> : null}
        {visuallyExpanded ? (
          <button
            className="sidebar-collapse"
            type="button"
            onClick={() => onCollapsedChange(!collapsed)}
            title={collapsed ? 'Pin sidebar open' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Pin sidebar open' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </button>
        ) : null}
      </div>

      <nav className="sidebar-nav sidebar-nav--global" aria-label="Personal workspace navigation">
        {globalNav.map(({ label, id, icon: Icon }) => (
          <button
            className={`sidebar-nav__item ${active === id ? 'is-active' : ''}`}
            type="button"
            key={id}
            title={label}
            onClick={() => onNavigate(id)}
          >
            <Icon size={17} strokeWidth={1.8} />
            {visuallyExpanded ? <span>{label}</span> : null}
          </button>
        ))}
      </nav>

      <div className="sidebar-section-head sidebar-section-head--projects">
        {visuallyExpanded ? <span>WORKSPACE</span> : <span className="sidebar-section-dot" />}
      </div>

      <nav className="sidebar-project-tree" aria-label="Projects">
        <div className="sidebar-project-parent-row">
          <button
            type="button"
            className={`sidebar-project-parent ${active === 'projects' ? 'is-active' : ''}`}
            onClick={() => {
              if (visuallyExpanded) onNavigate('projects');
              else setProjectsOpen(true);
            }}
            title="All projects"
          >
            {visuallyExpanded ? (
              <span className="project-tree-chevron" onClick={(event) => { event.stopPropagation(); setProjectsOpen((value) => !value); }}>{projectsOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</span>
            ) : null}
            <FolderKanban size={16} />
            {visuallyExpanded ? <span className="sidebar-project-parent__copy"><strong>Projects</strong><small>{projects.length} projects</small></span> : null}
          </button>
          {visuallyExpanded ? <button className="project-add-inline" type="button" title="New project" onClick={onNewProject}><Plus size={12} /></button> : null}
        </div>

        {projectsOpen ? (
          <div className="sidebar-project-children">
            {projects.map((project) => (
              <button
                key={project.id}
                type="button"
                className={`sidebar-project-child ${activeProjectId === project.id ? 'is-active' : ''}`}
                onClick={() => onProjectOpen(project.id)}
                title={project.name}
              >
                <span className="project-tree-line" />
                <span className={`project-dot project-dot--${project.accent}`} />
                {visuallyExpanded ? (
                  <span className="sidebar-project__copy">
                    <strong>{project.name}</strong>
                    <small>{project.updated}</small>
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        ) : null}
      </nav>

      <div className="sidebar-spacer" />

      <div className="sidebar-hint">
        <BookOpenText size={16} />
        {visuallyExpanded ? <div><strong>Personal library</strong><span>{libraryCount} local artifacts</span></div> : null}
      </div>

      <button className="profile-row" type="button">
        <CircleUserRound size={21} />
        {visuallyExpanded ? <span><strong>Minh</strong><small>Local workspace</small></span> : null}
      </button>
    </aside>
  );
}
