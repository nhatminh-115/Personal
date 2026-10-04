import { MessageSquarePlus, Pin, Search, Sparkles } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { projectArtifacts, type ChatThreadRecord, type LibraryItem, type ProjectRecord, type WorkspaceNote } from '../../data/workspaceData';
import type { AIContextItem, ApprovalDetail, ChatMessage, WorkspaceObject } from '../../types';
import { api } from '../../services/api';
import { getLocalFile } from '../../lib/localFiles';
import { MAX_LOCAL_DOCX_BYTES } from '../../lib/docxText';
import { MAX_LOCAL_XLSX_BYTES } from '../../lib/xlsxText';
import { MAX_LOCAL_PDF_BYTES } from '../../lib/pdfText';
import { ChatPane } from './ChatPane';

function mapWorkspaceContextObjects(objects: WorkspaceObject[], selectedIds: Set<string>, libraryItems: LibraryItem[], fileContentIds: Set<string>, localContextFileIds: Set<string>): AIContextItem[] {
  return objects.map((object) => {
    const metadataOnlyFile = object.object_type === 'file_reference' && !object.content;
    const localFile = metadataOnlyFile ? libraryItems.find((item) => item.id === object.id) : undefined;
    const localFileKindSupported = Boolean(localFile && (
      ['TXT', 'MD', 'CSV', 'JSON', 'HTML'].includes(localFile.kind)
        ? (localFile.size ?? 0) <= 80_000
        : localFile.kind === 'PDF'
          ? (localFile.size ?? 0) <= MAX_LOCAL_PDF_BYTES
          : localFile.kind === 'DOCX'
            ? (localFile.size ?? 0) <= MAX_LOCAL_DOCX_BYTES
            : localFile.kind === 'XLSX' && (localFile.size ?? 0) <= MAX_LOCAL_XLSX_BYTES
    ));
    const fileContentAvailable = Boolean(localContextFileIds.has(object.id)
      && localFile?.source === 'imported' && localFile.blobKey
      && localFileKindSupported);
    const kind: AIContextItem['kind'] = object.object_type === 'file_reference' ? 'file'
      : object.object_type === 'manual_note' ? 'note'
      : object.object_type === 'research_source' || object.object_type === 'research_evidence' ? 'paper'
        : object.object_type === 'research_claim' ? 'claim' : 'turn';
    const verification = object.metadata_json.verification_status;
    const tokenSource = metadataOnlyFile ? object.title || object.object_type : object.content;
    const detail = metadataOnlyFile
      ? fileContentAvailable
        ? localFile?.kind === 'PDF'
          ? 'browser-local PDF · text is extracted here only after you explicitly send it with a message'
          : localFile?.kind === 'DOCX'
            ? 'browser-local Word document · text is extracted here only after you explicitly send it with a message'
            : localFile?.kind === 'XLSX'
              ? 'browser-local spreadsheet · visible sheet text is extracted here only after you explicitly send it with a message'
            : 'browser-local text · stays here until you explicitly send it with a message'
        : 'file reference · metadata only · this browser has no supported local text, PDF, Word document, or spreadsheet copy available'
      : object.object_type === 'research_claim' && typeof verification === 'string'
        ? `research claim · ${verification} · saved in this project`
        : `${object.object_type.split('_').join(' ')} · saved in this project`;
    return {
      id: `workspace-${object.id}`,
      nodeId: object.id,
      kind,
      title: object.title || object.object_type.split('_').join(' '),
      detail,
      tokens: Math.max(1, Math.ceil(tokenSource.length / 4)),
      included: selectedIds.has(object.id),
      fileContentAvailable,
      fileContentIncluded: fileContentIds.has(object.id),
    };
  });
}

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
  onSendMessage?: (text: string, contextObjectIds?: string[], taskType?: 'research' | 'coding' | 'writing', contextFileContentIds?: string[]) => Promise<void>;
  onStartLiveChat?: (text: string, contextObjectIds?: string[], taskType?: 'research' | 'coding' | 'writing', contextFileContentIds?: string[]) => Promise<void>;
  onContextObjectIdsChange?: (threadId: string, objectIds: string[]) => void;
  onContextFileContentIdsChange?: (threadId: string, objectIds: string[]) => void;
  onLoadOlderMessages?: (threadId: string) => Promise<void>;
  onLoadOlderSessions?: () => Promise<void>;
  onRetryLoadSessions?: () => Promise<void>;
  hasOlderSessions?: boolean;
  loadingOlderSessions?: boolean;
  sessionLoadError?: string | null;
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
  onStartLiveChat,
  onContextObjectIdsChange,
  onContextFileContentIdsChange,
  onLoadOlderMessages,
  onLoadOlderSessions,
  onRetryLoadSessions,
  hasOlderSessions = false,
  loadingOlderSessions = false,
  sessionLoadError,
  currentApproval,
  onApprovalDecision,
}: ProjectChatWorkspaceProps) {
  const [query, setQuery] = useState('');
  const [liveWorkspaceContext, setLiveWorkspaceContext] = useState<AIContextItem[]>([]);
  const [localContextFileIds, setLocalContextFileIds] = useState<Set<string>>(new Set());
  const [contextPanelOpen, setContextPanelOpen] = useState(false);
  const [contextObjectsNextCursor, setContextObjectsNextCursor] = useState<string | null>(null);
  const [contextObjectsLoading, setContextObjectsLoading] = useState(false);
  const [contextObjectsError, setContextObjectsError] = useState<string | null>(null);
  const [contextObjectsReloadKey, setContextObjectsReloadKey] = useState(0);
  const contextObjectsRequest = useRef(0);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return threads.filter((thread) => !q || `${thread.title} ${thread.summary}`.toLowerCase().includes(q));
  }, [query, threads]);
  const activeThread = threads.find((thread) => thread.id === activeThreadId) ?? threads[0] ?? null;
  const selectedContextIds = useMemo(() => new Set(activeThread?.initialContextObjectIds ?? []), [activeThread?.initialContextObjectIds]);
  const selectedFileContentIds = useMemo(() => new Set(activeThread?.initialContextFileContentIds ?? []), [activeThread?.initialContextFileContentIds]);

  useEffect(() => {
    let active = true;
    const candidates = liveWorkspaceContext.flatMap((item) => {
      if (!item.nodeId || item.kind !== 'file') return [];
      const local = libraryItems.find((entry) => entry.id === item.nodeId);
      const supportedText = Boolean(local && ['TXT', 'MD', 'CSV', 'JSON', 'HTML'].includes(local.kind) && (local.size ?? 0) <= 80_000);
      const supportedPdf = Boolean(local?.kind === 'PDF' && (local.size ?? 0) <= MAX_LOCAL_PDF_BYTES);
      const supportedDocx = Boolean(local?.kind === 'DOCX' && (local.size ?? 0) <= MAX_LOCAL_DOCX_BYTES);
      const supportedXlsx = Boolean(local?.kind === 'XLSX' && (local.size ?? 0) <= MAX_LOCAL_XLSX_BYTES);
      if (!local?.blobKey || (!supportedText && !supportedPdf && !supportedDocx && !supportedXlsx)) return [];
      return [{ objectId: item.nodeId, blobKey: local.blobKey }];
    });
    void Promise.all(candidates.map(async ({ objectId, blobKey }) => {
      try { return await getLocalFile(blobKey) ? objectId : null; }
      catch { return null; }
    })).then((available) => {
      if (!active) return;
      const next = new Set(available.filter((id): id is string => Boolean(id)));
      setLocalContextFileIds((current) => current.size === next.size && [...current].every((id) => next.has(id)) ? current : next);
    });
    return () => { active = false; };
  }, [libraryItems, liveWorkspaceContext]);

  const isLiveThread = activeThread?.source === 'live' || Boolean(activeThread?.sessionId);

  useEffect(() => {
    if (!isLiveThread) {
      setLiveWorkspaceContext([]);
      setContextObjectsNextCursor(null);
      return;
    }
    if (!contextPanelOpen) return;
    let active = true;
    const requestId = ++contextObjectsRequest.current;
    setLiveWorkspaceContext([]);
    setContextObjectsNextCursor(null);
    setContextObjectsError(null);
    setContextObjectsLoading(true);
    void (async () => {
      try {
        let cursor: string | null = null;
        let objects: WorkspaceObject[] = [];
        let nextCursor: string | null = null;
        do {
          const page = await api.fetchWorkspaceObjectPage(project.name, cursor);
          if (!active) return;
          objects = [...objects, ...page.objects];
          nextCursor = page.nextCursor;
          setLiveWorkspaceContext(mapWorkspaceContextObjects(objects, selectedContextIds, libraryItems, selectedFileContentIds, localContextFileIds));
          cursor = nextCursor;
        } while (cursor && [...selectedContextIds].some((id) => !objects.some((object) => object.id === id)));
        if (active && contextObjectsRequest.current === requestId) setContextObjectsNextCursor(nextCursor);
      } catch {
        if (active && contextObjectsRequest.current === requestId) {
          setContextObjectsError('Saved project objects could not be loaded. Retry to continue.');
        }
      } finally {
        if (active && contextObjectsRequest.current === requestId) setContextObjectsLoading(false);
      }
    })();
    return () => { active = false; };
  // Selection is rendered from the active thread below; it must not reload the
  // object page every time a user toggles a context item.
  }, [activeThread?.id, activeThread?.messages.length, contextObjectsReloadKey, contextPanelOpen, isLiveThread, libraryItems, localContextFileIds, project.name]);

  const loadOlderContextObjects = useCallback(async () => {
    if (!contextObjectsNextCursor || contextObjectsLoading || !isLiveThread) return;
    setContextObjectsLoading(true);
    setContextObjectsError(null);
    try {
      const page = await api.fetchWorkspaceObjectPage(project.name, contextObjectsNextCursor);
      setLiveWorkspaceContext((current) => {
        const existing = new Set(current.map((item) => item.nodeId));
        const older = mapWorkspaceContextObjects(page.objects, selectedContextIds, libraryItems, selectedFileContentIds, localContextFileIds).filter((item) => !existing.has(item.nodeId));
        return [...current, ...older];
      });
      setContextObjectsNextCursor(page.nextCursor);
    } catch {
      setContextObjectsError('Older project objects could not be loaded. Retry to continue.');
    } finally {
      setContextObjectsLoading(false);
    }
  }, [contextObjectsLoading, contextObjectsNextCursor, isLiveThread, libraryItems, localContextFileIds, project.name, selectedContextIds, selectedFileContentIds]);

  const demoContextItems = useMemo<AIContextItem[]>(() => {
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
  const contextItems = useMemo(() => isLiveThread
    ? liveWorkspaceContext.map((item) => ({
      ...item,
      included: Boolean(item.nodeId && selectedContextIds.has(item.nodeId)),
      fileContentIncluded: Boolean(item.nodeId && selectedFileContentIds.has(item.nodeId)),
    }))
    : demoContextItems, [demoContextItems, isLiveThread, liveWorkspaceContext, selectedContextIds, selectedFileContentIds]);

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
        {loadingOlderSessions && !hasOlderSessions ? <div className="chat-thread-load-status" role="status">Loading saved chats…</div> : null}
        {sessionLoadError ? (
          <div className="chat-thread-load-error" role="alert">
            <span>{sessionLoadError}</span>
            <button type="button" disabled={loadingOlderSessions} onClick={() => void onRetryLoadSessions?.()}>Retry</button>
          </div>
        ) : null}
        {hasOlderSessions ? (
          <button className="chat-thread-load-more" type="button" disabled={loadingOlderSessions} onClick={() => void onLoadOlderSessions?.()}>
            {loadingOlderSessions ? 'Loading saved chats…' : 'Load older chats'}
          </button>
        ) : null}
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
            messagesNextCursor={activeThread.messagesNextCursor}
            loadingOlderMessages={activeThread.loadingOlderMessages}
            onLoadOlderMessages={onLoadOlderMessages ? () => onLoadOlderMessages(activeThread.id) : undefined}
            onMessagesChange={(updater) => onUpdateMessages(activeThread.id, updater)}
            contextItems={contextItems}
            contextIsLive={isLiveThread}
            contextHasMore={Boolean(contextObjectsNextCursor)}
            loadingOlderContext={contextObjectsLoading}
            contextLoadError={contextObjectsError}
            contextLoading={isLiveThread && contextPanelOpen && contextObjectsLoading && liveWorkspaceContext.length === 0}
            onLoadOlderContext={loadOlderContextObjects}
            onRetryContext={() => setContextObjectsReloadKey((key) => key + 1)}
            focusedMessageId={focusedMessageId}
            onMessageFocus={onMessageFocus}
            onBranchFromMessage={onBranchFromMessage}
            onContextObjectFocus={onContextObjectFocus}
            onAttachRequest={onAttachRequest}
            onSendMessage={onSendMessage}
            onStartLiveChat={onStartLiveChat}
            onContextObjectIdsChange={onContextObjectIdsChange ? (ids) => onContextObjectIdsChange(activeThread.id, ids) : undefined}
            onContextFileContentIdsChange={onContextFileContentIdsChange ? (ids) => onContextFileContentIdsChange(activeThread.id, ids) : undefined}
            onContextPanelOpenChange={setContextPanelOpen}
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
