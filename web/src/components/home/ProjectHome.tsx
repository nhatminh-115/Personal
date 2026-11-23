import { ArrowRight, FileText, Layers3, MessageSquareText, Plus, Sparkles, StickyNote, Workflow } from 'lucide-react';
import type { ChatThreadRecord, ProjectRecord } from '../../data/workspaceData';
import './ProjectHome.css';

interface ProjectHomeProps {
  projects: ProjectRecord[];
  projectId: string;
  threads: ChatThreadRecord[];
  chatCount: number;
  fileCount: number;
  noteCount: number;
  onOpenChats: () => void;
  onOpenThread: (threadId: string) => void;
  onNewThread: () => void;
  onOpenBoard: () => void;
  onOpenFiles: () => void;
  onOpenNotes: () => void;
}

function threadSourceLabel(thread: ChatThreadRecord): string {
  if (thread.source === 'live') return 'Live';
  if (thread.source === 'demo') return 'Demo';
  return 'Local';
}

export function ProjectHome({
  projects,
  projectId,
  threads,
  chatCount,
  fileCount,
  noteCount,
  onOpenChats,
  onNewThread,
  onOpenBoard,
  onOpenThread,
  onOpenFiles,
  onOpenNotes,
}: ProjectHomeProps) {
  const project = projects.find((item) => item.id === projectId);
  if (!project) return null;

  const isUserProject = project.source === 'user';
  const recentThreads = threads.slice(0, 4);

  return (
    <section className="project-home-redesign" aria-labelledby="project-home-title">
      <header className="project-home-redesign__header">
        <div className="project-home-redesign__heading">
          <div className="project-home-redesign__eyebrow">
            <span>PROJECT WORKSPACE</span>
            <span className={`project-home-redesign__source ${isUserProject ? 'is-live' : 'is-demo'}`}>
              {isUserProject ? 'YOUR PROJECT' : 'DEMO PROJECT'}
            </span>
          </div>
          <h1 id="project-home-title">{project.name}</h1>
          <p>{project.subtitle || 'A project space for conversations, files, notes, and working context.'}</p>
        </div>
        <div className="project-home-redesign__actions">
          <button className="project-home-redesign__button project-home-redesign__button--quiet" type="button" onClick={onOpenChats}>
            <MessageSquareText size={15} />
            <span>Conversations</span>
          </button>
          <button className="project-home-redesign__button project-home-redesign__button--primary" type="button" onClick={onNewThread}>
            <Plus size={16} />
            <span>New conversation</span>
          </button>
        </div>
      </header>

      <div className="project-home-redesign__grid">
        <div className="project-home-redesign__main-column">
          <section className="project-home-redesign__card project-home-redesign__brief">
            <div className="project-home-redesign__card-heading">
              <span className="project-home-redesign__label">PROJECT BRIEF</span>
              <span className="project-home-redesign__brief-mark"><Sparkles size={13} /> {isUserProject ? 'IN PROGRESS' : 'EXAMPLE CONTEXT'}</span>
            </div>
            <h2>{isUserProject ? 'Build context as you work.' : project.thesis}</h2>
            <div className="project-home-redesign__direction">
              <span>{isUserProject ? 'GET STARTED' : 'CURRENT DIRECTION'}</span>
              <p>{isUserProject ? 'Start a conversation or add a file. Project context will grow from the work you choose to keep.' : project.next}</p>
            </div>
            <div className="project-home-redesign__brief-footer">
              <span><Layers3 size={13} /> One project · multiple views</span>
              <span>{project.updated}</span>
            </div>
          </section>

          <section className="project-home-redesign__card project-home-redesign__conversations" aria-labelledby="project-conversations-title">
            <div className="project-home-redesign__section-heading">
              <div>
                <span className="project-home-redesign__label">RECENT CONVERSATIONS</span>
                <h2 id="project-conversations-title">Continue where you left off</h2>
              </div>
              <button className="project-home-redesign__text-action" type="button" onClick={onOpenChats}>
                All conversations <ArrowRight size={14} />
              </button>
            </div>

            {recentThreads.length ? (
              <div className="project-home-redesign__thread-list">
                {recentThreads.map((thread) => (
                  <button
                    className="project-home-redesign__thread"
                    key={thread.id}
                    type="button"
                    onClick={() => onOpenThread(thread.id)}
                    aria-label={`${thread.title}. ${thread.summary || 'Project conversation'}. ${threadSourceLabel(thread)} thread`}
                  >
                    <span className="project-home-redesign__thread-icon"><MessageSquareText size={16} /></span>
                    <span className="project-home-redesign__thread-copy">
                      <strong>{thread.title}</strong>
                      <small>{thread.summary || 'Project conversation'} <span>·</span> {threadSourceLabel(thread)}</small>
                    </span>
                    <span className="project-home-redesign__thread-time">{thread.updated}</span>
                    <ArrowRight className="project-home-redesign__thread-arrow" size={14} />
                  </button>
                ))}
              </div>
            ) : (
              <div className="project-home-redesign__empty">
                <span className="project-home-redesign__empty-icon"><MessageSquareText size={17} /></span>
                <div>
                  <strong>No conversations yet</strong>
                  <p>Start a project conversation. It will stay in this project alongside its files and Board.</p>
                </div>
                <button className="project-home-redesign__button project-home-redesign__button--quiet" type="button" onClick={onNewThread}>
                  <Plus size={14} /> New conversation
                </button>
              </div>
            )}
          </section>
        </div>

        <aside className="project-home-redesign__side-column">
          <section className="project-home-redesign__card" aria-label="Project at a glance">
            <div className="project-home-redesign__section-heading project-home-redesign__section-heading--compact">
              <div>
                <span className="project-home-redesign__label">AT A GLANCE</span>
                <h2>Workspace objects</h2>
              </div>
            </div>
            <div className="project-home-redesign__stats">
              <button type="button" onClick={onOpenChats} aria-label={`Chats ${chatCount} Conversation threads`}>
                <span className="project-home-redesign__stat-icon"><MessageSquareText size={15} /></span>
                <span className="project-home-redesign__stat-copy"><strong>{chatCount}</strong><span>Chats</span><small>Conversation threads</small></span>
                <ArrowRight size={13} />
              </button>
              <button type="button" onClick={onOpenFiles} aria-label={`Files ${fileCount} Project and linked Library files`}>
                <span className="project-home-redesign__stat-icon"><FileText size={15} /></span>
                <span className="project-home-redesign__stat-copy"><strong>{fileCount}</strong><span>Files</span><small>Project + linked Library</small></span>
                <ArrowRight size={13} />
              </button>
              <button type="button" onClick={onOpenNotes} aria-label={`Notes ${noteCount} Linked workspace notes`}>
                <span className="project-home-redesign__stat-icon"><StickyNote size={15} /></span>
                <span className="project-home-redesign__stat-copy"><strong>{noteCount}</strong><span>Notes</span><small>Linked workspace notes</small></span>
                <ArrowRight size={13} />
              </button>
            </div>
          </section>

          <section className="project-home-redesign__card project-home-redesign__board-card">
            <div className="project-home-redesign__section-heading project-home-redesign__section-heading--compact">
              <div>
                <span className="project-home-redesign__label">PROJECT MAP</span>
                <h2>Board view</h2>
              </div>
              <span className="project-home-redesign__board-icon"><Workflow size={17} /></span>
            </div>
            <p>Explore conversations and workspace objects together on the project Board.</p>
            <button className="project-home-redesign__text-action" type="button" onClick={onOpenBoard}>
              Open Board <ArrowRight size={14} />
            </button>
          </section>
        </aside>
      </div>
    </section>
  );
}
