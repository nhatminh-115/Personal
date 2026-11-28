import { ArrowRight, MessageSquarePlus, MessageSquareText, PanelRightOpen } from 'lucide-react';
import type { ReactNode } from 'react';
import type { HomeConversation } from './GlobalHome';
import type { ProjectRecord } from '../../data/workspaceData';
import type { WorkspaceMode } from '../../types';

interface ConversationViewProps {
  projects: ProjectRecord[];
  conversations: HomeConversation[];
  projectId: string | null;
  activeProjectId: string | null;
  activeThreadId: string | null;
  mode: WorkspaceMode;
  onSelectProject: (projectId: string | null) => void;
  onChangeMode: (mode: WorkspaceMode) => void;
  onNewConversation: (projectId: string | null) => void;
  onOpenConversation: (projectId: string, threadId: string) => void;
  showInspectorToggle: boolean;
  inspectorOpen: boolean;
  onToggleInspector: () => void;
  onCreateProject: () => void;
  children?: ReactNode;
}

const modes: { id: WorkspaceMode; label: string }[] = [
  { id: 'chat', label: 'Conversation' },
  { id: 'board', label: 'Board' },
  { id: 'split', label: 'Split' },
];

export function ConversationView({
  projects,
  conversations,
  projectId,
  activeProjectId,
  activeThreadId,
  mode,
  onSelectProject,
  onChangeMode,
  onNewConversation,
  onOpenConversation,
  showInspectorToggle,
  inspectorOpen,
  onToggleInspector,
  onCreateProject,
  children,
}: ConversationViewProps) {
  const project = projectId ? projects.find((item) => item.id === projectId) ?? null : null;
  const availableConversations = project
    ? conversations.filter((item) => item.project.id === project.id)
    : conversations;

  return (
    <section className={`conversation-v16 ${project ? '' : 'conversation-v16--all'}`} aria-labelledby="conversation-v16-title">
      <header className="conversation-v16__header">
        <div className="conversation-v16__heading">
          <span className="eyebrow">WORKSPACE</span>
          <h1 id="conversation-v16-title">Conversation</h1>
        </div>
        <label className="conversation-v16__scope">
          <span>Project scope</span>
          <select aria-label="Conversation project scope" value={project?.id ?? ''} onChange={(event) => onSelectProject(event.target.value || null)} disabled={!projects.length}>
            {projects.length ? <><option value="">All projects</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</> : <option value="">No projects yet</option>}
          </select>
        </label>
        <div className="conversation-v16__views" role="tablist" aria-label="Conversation views">
          {modes.map((item) => (
            <button key={item.id} type="button" role="tab" aria-selected={mode === item.id} className={mode === item.id ? 'is-active' : ''} disabled={!activeProjectId} onClick={() => onChangeMode(item.id)}>{item.label}</button>
          ))}
        </div>
        {showInspectorToggle ? <button className={`conversation-v16__context ${inspectorOpen ? 'is-active' : ''}`} type="button" title="Toggle inspector" aria-pressed={inspectorOpen} onClick={onToggleInspector}><PanelRightOpen size={14} /> Context</button> : null}
        <button className="conversation-v16__new" type="button" disabled={!projects.length} onClick={() => onNewConversation(project?.id ?? activeProjectId)}><MessageSquarePlus size={15} /> New conversation</button>
      </header>
      {project ? children : (
        projects.length ? (
          <div className="conversation-v16__all-projects">
            <div className="conversation-v16__all-heading"><span className="eyebrow">YOUR SPACE</span><h2>Conversations</h2></div>
            <button className="conversation-v16__all-new" type="button" disabled={!projects.length} onClick={() => onNewConversation(activeProjectId)}><MessageSquarePlus size={14} /> New conversation</button>
            {availableConversations.length ? (
              <div className="conversation-v16__all-list">
                {availableConversations.map(({ thread, project: threadProject }) => (
                  <button type="button" className={`conversation-v16__thread ${activeProjectId === threadProject.id && activeThreadId === thread.id ? 'is-active' : ''}`} key={`${threadProject.id}:${thread.id}`} onClick={() => onOpenConversation(threadProject.id, thread.id)}>
                    <span className="conversation-v16__thread-icon"><MessageSquareText size={16} /></span>
                    <span className="conversation-v16__thread-copy"><strong>{thread.title}</strong><small>{threadProject.name}{thread.summary ? ` · ${thread.summary}` : ''}</small></span>
                    <span className="conversation-v16__thread-time">{thread.updated}</span><ArrowRight size={14} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="conversation-v16__all-empty">
                <MessageSquareText size={19} />
                <div><strong>No conversations yet</strong><p>Start one in a project. Its messages, saved context, and Board remain together.</p></div>
              </div>
            )}
          </div>
        ) : (
          <div className="conversation-v16__empty">
            <MessageSquarePlus size={22} />
            <div><strong>Choose a project to begin</strong><p>Conversations stay with their project, along with the context and Board built around them.</p></div>
            <button type="button" onClick={onCreateProject}>Create a project <ArrowRight size={14} /></button>
          </div>
        )
      )}
    </section>
  );
}
