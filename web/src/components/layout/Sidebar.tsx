import {
  BookOpenText,
  ChevronDown,
  ChevronRight,
  CircleUserRound,
  FolderKanban,
  Home,
  Library,
  LockKeyhole,
  MessageSquareText,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Sparkles,
  Workflow,
} from 'lucide-react';
import { useState } from 'react';
import type { ProjectRecord } from '../../data/workspaceData';

export type SidebarDestination = 'home' | 'conversation' | 'projects' | 'notes' | 'library' | 'study' | 'automations' | 'preferences';

const globalNav: { label: string; id: SidebarDestination; icon: typeof Home }[] = [
  { label: 'Home', id: 'home', icon: Home },
  { label: 'Conversation', id: 'conversation', icon: MessageSquareText },
  { label: 'Projects', id: 'projects', icon: FolderKanban },
  { label: 'Notes', id: 'notes', icon: NotebookPen },
  { label: 'Library', id: 'library', icon: Library },
  { label: 'Automations', id: 'automations', icon: Workflow },
  { label: 'Preferences', id: 'preferences', icon: LockKeyhole },
];

interface SidebarProps {
  projects: ProjectRecord[];
  collapsed: boolean;
  active: SidebarDestination | null;
  activeProjectId: string | null;
  libraryCount: number;
  onCollapsedChange: (collapsed: boolean) => void;
  onNavigate: (destination: SidebarDestination) => void;
  onProjectOpen: (projectId: string) => void;
  onNewProject: () => void;
}

export function Sidebar({ projects, collapsed, active, activeProjectId, libraryCount, onCollapsedChange, onNavigate, onProjectOpen, onNewProject }: SidebarProps) {
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
      </div>

      <nav className="sidebar-nav sidebar-nav--global" aria-label="Personal workspace navigation">
        {globalNav.map(({ label, id, icon: Icon }) => (
          <div className="sidebar-nav__group" key={id}>
            <div className="sidebar-nav__row">
              <button
                className={`sidebar-nav__item ${active === id ? 'is-active' : ''}`}
                type="button"
                title={label}
                aria-current={active === id ? 'page' : undefined}
                onClick={() => onNavigate(id)}
              >
                <Icon size={17} strokeWidth={1.8} />
                {visuallyExpanded ? <span>{label}</span> : null}
              </button>
              {id === 'projects' && visuallyExpanded ? <button className="sidebar-nav__add" type="button" onClick={onNewProject} title="New project" aria-label="New project"><Plus size={14} /></button> : null}
            </div>
            {id === 'library' && visuallyExpanded ? (
              <button className={`sidebar-nav__subitem ${active === 'study' ? 'is-active' : ''}`} type="button" onClick={() => onNavigate('study')}>
                <BookOpenText size={14} /> <span>Study</span>
              </button>
            ) : null}
          </div>
        ))}
      </nav>

      <div className="sidebar-section-head sidebar-section-head--projects">
        {visuallyExpanded ? <span>PROJECTS</span> : <span className="sidebar-section-dot" />}
        {visuallyExpanded ? <button className="sidebar-projects-toggle" type="button" onClick={() => setProjectsOpen((value) => !value)} aria-label={projectsOpen ? 'Collapse projects' : 'Expand projects'}>{projectsOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}</button> : null}
      </div>

      {projectsOpen ? (
        <nav className="sidebar-project-tree" aria-label="Projects">
          {projects.map((project) => (
            <button
              key={project.id}
              type="button"
              className={`sidebar-project-child ${activeProjectId === project.id ? 'is-active' : ''}`}
              onClick={() => onProjectOpen(project.id)}
              title={project.name}
              aria-current={activeProjectId === project.id ? 'page' : undefined}
            >
              <span className={`project-dot project-dot--${project.accent}`} />
              {visuallyExpanded ? <span className="sidebar-project__copy"><strong>{project.name}</strong><small>{project.updated}</small></span> : null}
            </button>
          ))}
        </nav>
      ) : null}

      <div className="sidebar-spacer" />

      {visuallyExpanded ? <div className="sidebar-hint"><BookOpenText size={15} /><div><strong>Personal library</strong><span>{libraryCount} local artifacts</span></div></div> : null}
      <div className="sidebar-footer">
        <button className="sidebar-collapse" type="button" onClick={() => onCollapsedChange(!collapsed)} title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          {collapsed ? <PanelLeftOpen size={15} /> : <PanelLeftClose size={15} />}
          {visuallyExpanded ? <span>{collapsed ? 'Expand' : 'Collapse'}</span> : null}
        </button>
        <button className="sidebar-profile" type="button" onClick={() => onNavigate('preferences')} title="Local workspace">
          <CircleUserRound size={15} /> {visuallyExpanded ? <span>Local workspace</span> : null}
        </button>
      </div>
    </aside>
  );
}
