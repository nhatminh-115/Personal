import {
  FolderKanban,
  Home,
  Library,
  LockKeyhole,
  MessageSquareText,
  NotebookPen,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
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
  onCollapsedChange: (collapsed: boolean) => void;
  onNavigate: (destination: SidebarDestination) => void;
  onProjectOpen: (projectId: string) => void;
  onNewProject: () => void;
}

function PrototypeMark({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 64 64" fill="none" stroke="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="32" cy="32" r="14" strokeWidth="1.45" strokeDasharray="2.5 3.5" opacity="0.34" />
      <ellipse cx="32" cy="32" rx="23.5" ry="8.5" transform="rotate(-30 32 32)" strokeWidth="2.15" opacity="0.86" />
      <ellipse cx="32" cy="32" rx="23.5" ry="8.5" transform="rotate(30 32 32)" strokeWidth="1.65" opacity="0.38" />
      <path d="M32 23L39.8 27.5L32 32L24.2 27.5L32 23Z" fill="currentColor" stroke="none" />
      <path d="M24.2 27.5L32 32V41L24.2 36.5V27.5Z" fill="currentColor" stroke="none" opacity="0.68" />
      <path d="M39.8 27.5L32 32V41L39.8 36.5V27.5Z" fill="currentColor" stroke="none" opacity="0.36" />
      <circle cx="32" cy="11" r="3.1" fill="currentColor" stroke="none" />
      <circle cx="50.2" cy="42.5" r="2.9" fill="currentColor" stroke="none" opacity="0.82" />
      <circle cx="13.8" cy="42.5" r="2.9" fill="currentColor" stroke="none" opacity="0.82" />
    </svg>
  );
}

function projectMonogram(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  return words.length > 1
    ? words.slice(0, 2).map((word) => word[0]).join('').toUpperCase()
    : (words[0] ?? 'P').slice(0, 2).toUpperCase();
}

export function Sidebar({ projects, collapsed, active, activeProjectId, onCollapsedChange, onNavigate, onProjectOpen, onNewProject }: SidebarProps) {
  const [hovered, setHovered] = useState(false);
  const visuallyExpanded = !collapsed || hovered;

  return (
    <aside
      className={`sidebar sidebar--prototype ${collapsed ? 'sidebar--collapsed' : ''} ${visuallyExpanded ? 'sidebar--peek-open' : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="sidebar-brand" role="img" aria-label="Kuractus">
        <div className="sidebar-brand__mark"><PrototypeMark /></div>
        {visuallyExpanded ? <strong className="sidebar-brand__name">KURACTUS</strong> : null}
      </div>

      <div className="sidebar-nav-label">YOUR SPACE</div>
      <nav className="sidebar-nav sidebar-nav--global" aria-label="Personal workspace navigation">
        {globalNav.map(({ label, id, icon: Icon }) => {
          const isActive = active === id || (id === 'library' && active === 'study');
          return (
            <button
              key={id}
              className={`sidebar-nav__item ${isActive ? 'is-active' : ''}`}
              type="button"
              title={label}
              aria-label={label}
              aria-current={isActive ? 'page' : undefined}
              onClick={() => onNavigate(id)}
            >
              <Icon size={17} strokeWidth={1.8} />
              {visuallyExpanded ? <span>{label}</span> : null}
              {id === 'projects' && visuallyExpanded ? <span className="sidebar-nav__count">{String(projects.length).padStart(2, '0')}</span> : null}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-section-head sidebar-section-head--projects">
        {visuallyExpanded ? <span>PINNED PROJECTS</span> : <span className="sidebar-section-dot" />}
        {visuallyExpanded ? <button className="sidebar-projects-add" type="button" onClick={onNewProject} title="New project" aria-label="New project"><Plus size={15} /></button> : null}
      </div>

      <nav className="sidebar-project-list" aria-label="Projects">
        {projects.map((project) => (
          <button
            key={project.id}
            type="button"
            className={`sidebar-project-row ${activeProjectId === project.id ? 'is-active' : ''}`}
            onClick={() => onProjectOpen(project.id)}
            title={project.name}
            aria-label={project.name}
            aria-current={activeProjectId === project.id ? 'page' : undefined}
          >
            <span className={`sidebar-project-mark sidebar-project-mark--${project.accent}`}>{projectMonogram(project.name)}</span>
            {visuallyExpanded ? <span className="sidebar-project-name">{project.name}</span> : null}
            <span className={`sidebar-project-status sidebar-project-status--${project.status}`} aria-hidden="true" />
          </button>
        ))}
      </nav>

      <div className="sidebar-spacer" />

      <div className="sidebar-footer sidebar-footer--prototype">
        <button
          className="sidebar-collapse"
          type="button"
          onClick={() => onCollapsedChange(!collapsed)}
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          aria-expanded={!collapsed}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
          {visuallyExpanded ? <span>{collapsed ? 'Expand sidebar' : 'Collapse sidebar'}</span> : null}
        </button>
      </div>
    </aside>
  );
}
