import { MessageSquarePlus, Pin, Search, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { projectArtifacts, type ChatThreadRecord, type LibraryItem, type ProjectRecord, type WorkspaceNote } from '../../data/workspaceData';
import type { AIContextItem, ApprovalDetail, ChatMessage } from '../../types';
import { ChatPane } from './ChatPane';

export interface ProjectChatWorkspaceProps {
  compact?: boolean;
  project: ProjectRecord;
  threads: ChatThreadRecord[];
  activeThreadId: string | null;
  libraryItems: LibraryItem[];
  notes: WorkspaceNote[];
  focusedMessageId?: string | null;
  onSelectThread: (id: string) => void;
  onNewThread: () => void;
  onUpdateMessages: (threadId: string, updater: (messages: ChatMessage[]) => ChatMessage[]) => void;
  onMessageFocus?: (message: ChatMessage) => void;
  onBranchFromMessage?: (message: ChatMessage) => void;
  onContextObjectFocus?: (nodeId: string) => void;
  onAttachRequest?: () => void;
  onSendMessage?: (text: string) => Promise<void>;
  currentApproval?: ApprovalDetail | null;
  onApprovalDecision?: (
    decision: 'approved' | 'rejected' | 'edited',
    notes?: string,
    editedInput?: Record<string, any>
  ) => Promise<void>;
}

export function ProjectChatWorkspace({
  compact = false,
  project,
  threads,
  activeThreadId,
  libraryItems,
  notes,
  focusedMessageId,
  onSelectThread,
  onNewThread,
  onUpdateMessages,
  onMessageFocus,
  onBranchFromMessage,
  onContextObjectFocus,
  onAttachRequest,
  onSendMessage,
  currentApproval,
  onApprovalDecision,
}: ProjectChatWorkspaceProps) {
  const [query, setQuery] = useState('');
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return threads.filter((thread) => !q || `${thread.title} ${thread.summary}`.toLowerCase().includes(q));
  }, [query, threads]);
  const activeThread = threads.find((thread) => thread.id === activeThreadId) ?? threads[0] ?? null;

  const contextItems = useMemo<AIContextItem[]>(() => {
    const files = libraryItems.filter((item) => item.projectLinks?.includes(project.id)).slice(0, 4).map((item, index) => ({
      id: `file-${item.id}`,
      kind: 'file' as const,
      title: item.name,
      detail: `project file · ${item.kind}`,
      tokens: 500 + index * 240,
      included: index < 2,
    }));
    const projectNotes = notes.filter((note) => note.projectIds.includes(project.id)).slice(0, 2).map((note) => ({
      id: `note-${note.id}`,
      kind: 'note' as const,
      title: note.title,
      detail: 'linked workspace note',
      tokens: Math.max(80, Math.round(note.body.length * 0.7)),
      included: true,
    }));
    const artifacts = projectArtifacts.filter((item) => item.projectId === project.id).slice(0, 2).map((item) => ({
      id: `artifact-${item.id}`,
      kind: 'code' as const,
      title: item.name,
      detail: `project-local · ${item.kind}`,
      tokens: 640,
      included: false,
    }));
    return [
      { id: `thread-${activeThread?.id ?? 'new'}`, kind: 'turn' as const, title: activeThread?.title ?? 'Current chat', detail: 'current conversation thread', tokens: 1900, included: true, nodeId: project.id === 'stateful' ? 'root-answer' : undefined },
      ...projectNotes,
      ...files,
      ...artifacts,
    ];
  }, [activeThread?.id, activeThread?.title, libraryItems, notes, project.id]);

  return (
    <div className={`project-chat-workspace ${compact ? 'project-chat-workspace--compact' : ''}`}>
      <aside className="chat-thread-rail">
        <div className="chat-thread-rail__head">
          <div>
            <span className="eyebrow">PROJECT CHATS</span>
            <strong>{threads.length} threads</strong>
          </div>
          <button className="icon-button" type="button" title="New chat" onClick={onNewThread}><MessageSquarePlus size={15} /></button>
        </div>
        <label className="chat-thread-search">
          <Search size={13} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chats" />
        </label>
        <div className="chat-thread-list">
          {filtered.map((thread) => (
            <button
              key={thread.id}
              type="button"
              className={`chat-thread-item ${activeThread?.id === thread.id ? 'is-active' : ''}`}
              onClick={() => onSelectThread(thread.id)}
            >
              <span className="chat-thread-item__top">
                <strong>{thread.title}</strong>
                {thread.pinned ? <Pin size={11} /> : null}
              </span>
              <small>{thread.summary}</small>
              <span>{thread.updated}</span>
            </button>
          ))}
        </div>
        <button className="new-chat-card" type="button" onClick={onNewThread}>
          <Sparkles size={14} />
          <span><strong>New chat</strong><small>Starts clean, keeps project context explicit</small></span>
        </button>
      </aside>

      <div className="project-chat-workspace__main">
        {activeThread ? (
          <ChatPane
            compact={compact}
            projectName={project.name}
            threadTitle={activeThread.title}
            messages={activeThread.messages}
            onMessagesChange={(updater) => onUpdateMessages(activeThread.id, updater)}
            contextItems={contextItems}
            focusedMessageId={focusedMessageId}
            onMessageFocus={onMessageFocus}
            onBranchFromMessage={onBranchFromMessage}
            onContextObjectFocus={onContextObjectFocus}
            onAttachRequest={onAttachRequest}
            onSendMessage={onSendMessage}
            currentApproval={currentApproval}
            onApprovalDecision={onApprovalDecision}
            isLiveThread={activeThread.source === 'live' || Boolean(activeThread.sessionId)}
          />
        ) : (
          <div className="empty-project-chat"><MessageSquarePlus size={22} /><strong>No chats yet</strong><span>Create the first thread for this project.</span></div>
        )}
      </div>
    </div>
  );
}
