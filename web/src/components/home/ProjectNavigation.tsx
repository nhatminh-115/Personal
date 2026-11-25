import { ArrowRight, Files, LayoutDashboard, MessageSquareText, Plus, SplitSquareHorizontal, Workflow } from 'lucide-react';
import type { ProjectRecord } from '../../data/workspaceData';
import type { WorkspaceMode } from '../../types';

interface ProjectNavigationProps {
  project?: ProjectRecord;
  showProjectHeading?: boolean;
  active: 'overview' | 'conversations' | 'board' | 'split' | 'files';
  onOverview: () => void;
  onConversations: () => void;
  onModeChange: (mode: WorkspaceMode) => void;
  onFiles: () => void;
  onNewConversation?: () => void;
}

const items = [
  { id: 'overview', label: 'Overview', icon: LayoutDashboard },
  { id: 'conversations', label: 'Conversations', icon: MessageSquareText },
  { id: 'board', label: 'Board', icon: Workflow },
  { id: 'split', label: 'Split', icon: SplitSquareHorizontal },
  { id: 'files', label: 'Files', icon: Files },
] as const;

export function ProjectNavigation({ project, showProjectHeading = false, active, onOverview, onConversations, onModeChange, onFiles, onNewConversation }: ProjectNavigationProps) {
  const actions: Record<(typeof items)[number]['id'], () => void> = {
    overview: onOverview,
    conversations: onConversations,
    board: () => onModeChange('board'),
    split: () => onModeChange('split'),
    files: onFiles,
  };

  return (
    <div className={`project-navigation-shell-v16 ${showProjectHeading ? 'project-navigation-shell-v16--project' : 'project-navigation-shell-v16--inline'}`}>
      {showProjectHeading && project ? <header className="project-workspace-heading-v16">
        <div><span className="eyebrow">PROJECT WORKSPACE</span><h1>{project.name}</h1><p>{project.subtitle || 'A project space for conversations, files, notes, and working context.'}</p></div>
        <div className="project-workspace-heading-v16__actions">
          <button type="button" className="project-workspace-heading-v16__quiet" onClick={onConversations}><MessageSquareText size={14} /> Open in Conversation <ArrowRight size={13} /></button>
          {onNewConversation ? <button type="button" className="project-workspace-heading-v16__primary" onClick={onNewConversation}><Plus size={15} /> New conversation</button> : null}
        </div>
      </header> : null}
      <nav className="project-navigation-v16" aria-label="Project navigation">
        {items.map(({ id, label, icon: Icon }) => (
          <button key={id} type="button" className={active === id ? 'is-active' : ''} aria-current={active === id ? 'page' : undefined} onClick={actions[id]}>
            <Icon size={14} /> {label}
          </button>
        ))}
      </nav>
    </div>
  );
}
