import { useCallback, useEffect, useMemo, useState } from 'react';
import { BoardCanvas } from './components/board/BoardCanvas';
import { AuraCommandPalette } from './components/chat/AuraCommandPalette';
import { ProjectChatWorkspace } from './components/chat/ProjectChatWorkspace';
import { AutomationsView } from './components/global/AutomationsView';
import { GlobalHome } from './components/global/GlobalHome';
import { LibraryView } from './components/global/LibraryView';
import { ConnectedFolderView } from './components/global/ConnectedFolderView';
import { FilePreviewView, type FilePreviewRecord } from './components/global/FilePreviewView';
import { NotesView } from './components/global/NotesView';
import { ProjectsView } from './components/global/ProjectsView';
import { StudyView } from './components/global/StudyView';
import { ProjectFilesView } from './components/home/ProjectFilesView';
import { ProjectHome } from './components/home/ProjectHome';
import { InspectorPanel } from './components/layout/InspectorPanel';
import { Sidebar, type SidebarDestination } from './components/layout/Sidebar';
import { Topbar } from './components/layout/Topbar';
import { WorkspaceChrome, type AuraTab } from './components/layout/WorkspaceChrome';
import { ToastStack } from './components/ui/ToastStack';
import { initialNodes } from './data/mockData';
import { makeProjectBoard } from './data/projectBoards';
import {
  initialAutomations,
  initialChatThreads,
  initialLibraryItems,
  initialNotes,
  projectArtifacts,
  projects,
  type AutomationRecord,
  type ChatThreadRecord,
  type LibraryItem,
  type LibraryKind,
  type WorkspaceNote,
} from './data/workspaceData';
import { deleteLocalFile, getLocalFile, putLocalFile } from './lib/localFiles';
import {
  listDirectoryConnections,
  pickDirectoryConnection,
  removeDirectoryConnection,
  supportsDirectoryPicker,
  type DirectoryConnection,
} from './lib/folderConnections';
import { api } from './services/api';
import { mapRunEventsToExecutionSteps } from './lib/executionEvents';
import type {
  ApprovalDetail,
  AuraFlowNode,
  ChatMessage,
  ExecutionStep,
  MemoryItem,
  ModelCatalog,
  ResearchInspectorData,
  RunDetail,
  SessionSummary,
  ToastMessage,
  WorkspaceMode,
} from './types';

type WorkspaceSurface =
  | 'global-home'
  | 'library'
  | 'notes'
  | 'study'
  | 'automations'
  | 'projects'
  | 'project-overview'
  | 'project-files'
  | 'folder-viewer'
  | 'file-viewer'
  | 'workspace';

const STORAGE = {
  library: 'aura-v7-library',
  notes: 'aura-v7-notes',
  automations: 'aura-v7-automations',
  chats: 'aura-v7-chats',
};

function initialModeFromUrl(): WorkspaceMode {
  const value = new URLSearchParams(window.location.search).get('mode');
  return value === 'board' || value === 'split' || value === 'chat' ? value : 'chat';
}

function loadStored<T>(key: string, fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return value ? JSON.parse(value) as T : fallback;
  } catch {
    return fallback;
  }
}

function loadLibrary(): LibraryItem[] {
  const stored = loadStored<LibraryItem[]>(STORAGE.library, []);
  if (!stored.length) return initialLibraryItems.map((item) => ({ ...item, projectLinks: [...(item.projectLinks ?? [])] }));
  const storedById = new Map(stored.map((item) => [item.id, item]));
  const builtIns = initialLibraryItems.map((item) => ({ ...item, ...(storedById.get(item.id) ?? {}), href: item.href, source: 'bundled' as const }));
  const imported = stored.filter((item) => item.source === 'imported');
  return [...builtIns, ...imported];
}

function inferLibraryKind(file: File): LibraryKind {
  const ext = file.name.split('.').pop()?.toLowerCase();
  if (ext === 'html' || ext === 'htm' || file.type === 'text/html') return 'HTML';
  if (ext === 'pdf' || file.type === 'application/pdf') return 'PDF';
  if (ext === 'md' || ext === 'markdown') return 'MD';
  if (ext === 'csv') return 'CSV';
  if (ext === 'json' || file.type === 'application/json') return 'JSON';
  if (file.type.startsWith('image/')) return 'IMAGE';
  if (ext === 'txt' || file.type.startsWith('text/')) return 'TXT';
  return 'FILE';
}

function stripExtension(name: string) {
  return name.replace(/\.[^.]+$/, '');
}

interface AppTab extends AuraTab {
  surface: WorkspaceSurface;
  projectId?: string | null;
  connectionId?: string | null;
  previewId?: string | null;
  mode?: WorkspaceMode;
}

const AURA_TAB: AppTab = { id: 'aura', title: 'AURA', subtitle: 'Personal workspace', kind: 'home', surface: 'global-home', closable: false, projectId: null, connectionId: null, previewId: null };

function tabStateKey(tab: AppTab) {
  return [tab.id, tab.surface, tab.projectId ?? '', tab.connectionId ?? '', tab.previewId ?? '', tab.mode ?? ''].join('|');
}

export default function App() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const [mode, setMode] = useState<WorkspaceMode>(initialModeFromUrl);
  const [surface, setSurface] = useState<WorkspaceSurface>('global-home');
  const [activeNav, setActiveNav] = useState<SidebarDestination | null>('home');
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [routingOpen, setRoutingOpen] = useState(params.get('routing') === '1');
  const [auraOpen, setAuraOpen] = useState(false);
  const [locked, setLocked] = useState(params.get('locked') !== '0');
  const [inspectorOpen, setInspectorOpen] = useState(params.get('inspector') === '1');
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(params.get('focus'));
  const [selectedNode, setSelectedNode] = useState<AuraFlowNode | undefined>(() => initialNodes.find((node) => node.id === params.get('focus')));
  const [branchRequest, setBranchRequest] = useState<{ nodeId: string; nonce: number } | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const [libraryItems, setLibraryItems] = useState<LibraryItem[]>(loadLibrary);
  const [directoryConnections, setDirectoryConnections] = useState<DirectoryConnection[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(null);
  const [filePreviews, setFilePreviews] = useState<Record<string, FilePreviewRecord>>({});
  const [tabs, setTabs] = useState<AppTab[]>([AURA_TAB]);
  const [activeTabId, setActiveTabId] = useState(AURA_TAB.id);
  const [tabHistory, setTabHistory] = useState<AppTab[]>([AURA_TAB]);
  const [tabHistoryIndex, setTabHistoryIndex] = useState(0);
  const [notes, setNotes] = useState<WorkspaceNote[]>(() => loadStored(STORAGE.notes, initialNotes));
  const [automations, setAutomations] = useState<AutomationRecord[]>(() => loadStored(STORAGE.automations, initialAutomations));
  const [chatThreads, setChatThreads] = useState<ChatThreadRecord[]>(() => loadStored(STORAGE.chats, initialChatThreads));
  const [activeThreadByProject, setActiveThreadByProject] = useState<Record<string, string>>(() => {
    const map: Record<string, string> = {};
    projects.forEach((project) => {
      const first = initialChatThreads.find((thread) => thread.projectId === project.id);
      if (first) map[project.id] = first.id;
    });
    return map;
  });

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? AURA_TAB;
  const activeFilePreview = activeTab.previewId ? filePreviews[activeTab.previewId] ?? null : null;
  const projectThreads = useMemo(() => chatThreads.filter((thread) => thread.projectId === activeProjectId), [activeProjectId, chatThreads]);
  const activeThreadId = activeProjectId ? activeThreadByProject[activeProjectId] ?? projectThreads[0]?.id ?? null : null;
  const projectSection = surface === 'project-overview' ? 'overview' : surface === 'project-files' ? 'files' : surface === 'workspace' ? 'workspace' : null;
  const genericBoard = useMemo(() => activeProject && activeProject.id !== 'stateful' ? makeProjectBoard(activeProject) : null, [activeProject]);

  useEffect(() => window.localStorage.setItem(STORAGE.library, JSON.stringify(libraryItems)), [libraryItems]);
  useEffect(() => window.localStorage.setItem(STORAGE.notes, JSON.stringify(notes)), [notes]);
  useEffect(() => window.localStorage.setItem(STORAGE.automations, JSON.stringify(automations)), [automations]);
  useEffect(() => window.localStorage.setItem(STORAGE.chats, JSON.stringify(chatThreads)), [chatThreads]);
  useEffect(() => {
    let cancelled = false;
    void listDirectoryConnections().then((items) => { if (!cancelled) setDirectoryConnections(items); });
    return () => { cancelled = true; };
  }, []);

  // ── Per-thread live execution state ──────────────────────────────────────
  // Each live-execution key is scoped to the thread that originated it.
  // This prevents run/approval/research state from leaking across threads.
  interface ThreadLiveState {
    runId: string | null;
    runStatus: string | null;
    approval: ApprovalDetail | null;
    runDetail: RunDetail | null;
    researchData: ResearchInspectorData | null;
  }

  // Live Backend State
  const [catalog, setCatalog] = useState<ModelCatalog>({ providers: [] });
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [selectedModelOverride] = useState<string | null>(null);
  const [threadLiveStates, setThreadLiveStates] = useState<Record<string, ThreadLiveState>>({});
  /**
   * approvalOrigins — typed binding: approval.id → originatingThreadId.
   * Replaces the `_originatingThreadId as any` hack on the DTO.
   */
  const [approvalOrigins, setApprovalOrigins] = useState<Record<string, string>>({});

  /** Convenience accessor — live state for the currently active thread only */
  const activeThreadLive: ThreadLiveState = activeThreadId
    ? (threadLiveStates[activeThreadId] ?? { runId: null, runStatus: null, approval: null, runDetail: null, researchData: null })
    : { runId: null, runStatus: null, approval: null, runDetail: null, researchData: null };

  function patchThreadLive(threadId: string, patch: Partial<ThreadLiveState>) {
    setThreadLiveStates((prev) => ({
      ...prev,
      [threadId]: { ...{ runId: null, runStatus: null, approval: null, runDetail: null, researchData: null }, ...(prev[threadId] ?? {}), ...patch },
    }));
  }

  useEffect(() => {
    api.fetchModels().then(setCatalog).catch(() => ({ providers: [] }));
    api.fetchSessions().then(setSessions).catch(() => []);
  }, []);

  useEffect(() => {
    if (activeProject?.name) {
      api.fetchMemories(activeProject.name).then(setMemories).catch(() => setMemories([]));
    }
  }, [activeProject?.name]);

  const refreshInspectorData = useCallback(async (originatingThreadId: string, runId: string) => {
    try {
      const [rDetail, rResearch] = await Promise.all([
        api.fetchRunDetails(runId).catch(() => null),
        api.fetchRunResearch(runId).catch(() => null),
      ]);
      setThreadLiveStates((prev) => ({
        ...prev,
        [originatingThreadId]: {
          ...{ runId: null, runStatus: null, approval: null, runDetail: null, researchData: null },
          ...(prev[originatingThreadId] ?? {}),
          ...(rDetail ? { runDetail: rDetail } : {}),
          ...(rResearch ? { researchData: rResearch } : {}),
        },
      }));
    } catch (e) {
      console.error('Failed to load inspector data', e);
    }
  }, []);

  // Ensure app-level live states are marked as accessed
  void catalog;
  void sessions;
  void activeThreadLive;

  const pushToast = useCallback((title: string, detail?: string) => {
    const id = Date.now() + Math.floor(Math.random() * 999);
    setToasts((current) => [...current, { id, title, detail }]);
    window.setTimeout(() => setToasts((current) => current.filter((toast) => toast.id !== id)), 3200);
  }, []);

  const applyTab = useCallback((tab: AppTab) => {
    setActiveTabId(tab.id);
    setSurface(tab.surface);
    setActiveProjectId(tab.projectId ?? null);
    setActiveConnectionId(tab.connectionId ?? null);
    if (tab.mode) setMode(tab.mode);
    if (tab.surface === 'global-home') setActiveNav('home');
    else if (tab.surface === 'library' || tab.surface === 'folder-viewer' || tab.surface === 'file-viewer') setActiveNav('library');
    else if (tab.surface === 'notes') setActiveNav('notes');
    else if (tab.surface === 'study') setActiveNav('study');
    else if (tab.surface === 'automations') setActiveNav('automations');
    else if (tab.surface === 'projects') setActiveNav('projects');
    else setActiveNav(null);
  }, []);

  const openOrActivateTab = useCallback((tab: AppTab, recordHistory = true) => {
    setTabs((current) => current.some((item) => item.id === tab.id) ? current.map((item) => item.id === tab.id ? { ...item, ...tab } : item) : [...current, tab]);
    applyTab(tab);
    if (recordHistory) {
      const currentSnapshot = tabHistory[tabHistoryIndex];
      if (!currentSnapshot || tabStateKey(currentSnapshot) !== tabStateKey(tab)) {
        const nextIndex = tabHistoryIndex + 1;
        setTabHistory((current) => [...current.slice(0, nextIndex), { ...tab }]);
        setTabHistoryIndex(nextIndex);
      }
    }
  }, [applyTab, tabHistory, tabHistoryIndex]);

  const selectTab = useCallback((tabId: string, recordHistory = true) => {
    const tab = tabs.find((item) => item.id === tabId);
    if (!tab) return;
    applyTab(tab);
    if (recordHistory) {
      const currentSnapshot = tabHistory[tabHistoryIndex];
      if (!currentSnapshot || tabStateKey(currentSnapshot) !== tabStateKey(tab)) {
        const nextIndex = tabHistoryIndex + 1;
        setTabHistory((current) => [...current.slice(0, nextIndex), { ...tab }]);
        setTabHistoryIndex(nextIndex);
      }
    }
  }, [applyTab, tabHistory, tabHistoryIndex, tabs]);

  const closeTab = useCallback((tabId: string) => {
    if (tabId === AURA_TAB.id) return;
    const closing = tabs.find((tab) => tab.id === tabId);
    if (closing?.previewId) {
      const preview = filePreviews[closing.previewId];
      if (preview?.url.startsWith('blob:')) URL.revokeObjectURL(preview.url);
      setFilePreviews((current) => { const next = { ...current }; delete next[closing.previewId!]; return next; });
    }
    setTabs((current) => {
      if (current.length <= 1) return current;
      const index = current.findIndex((item) => item.id === tabId);
      const next = current.filter((item) => item.id !== tabId);
      if (tabId === activeTabId) {
        const fallback = next[Math.max(0, Math.min(index - 1, next.length - 1))] ?? AURA_TAB;
        window.setTimeout(() => applyTab(fallback), 0);
      }
      return next;
    });
  }, [activeTabId, applyTab, filePreviews, tabs]);

  const goTabHistory = useCallback((direction: -1 | 1) => {
    let nextIndex = tabHistoryIndex + direction;
    while (nextIndex >= 0 && nextIndex < tabHistory.length) {
      const snapshot = tabHistory[nextIndex];
      if (tabs.some((tab) => tab.id === snapshot.id)) {
        setTabHistoryIndex(nextIndex);
        setTabs((current) => current.map((tab) => tab.id === snapshot.id ? { ...tab, ...snapshot } : tab));
        applyTab(snapshot);
        return;
      }
      nextIndex += direction;
    }
  }, [applyTab, tabHistory, tabHistoryIndex, tabs]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setAuraOpen((value) => !value);
        return;
      }
      if (event.key !== 'Escape') return;
      setRoutingOpen(false);
      setAuraOpen(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const openProject = useCallback((projectId: string) => {
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    setInspectorOpen(false);
    setRoutingOpen(false);
    openOrActivateTab({ id: `project-${projectId}`, title: project.name, subtitle: 'Project Overview', kind: 'project', surface: 'project-overview', projectId });
  }, [openOrActivateTab]);

  const openProjectChats = useCallback(() => {
    if (!activeProjectId || !activeProject) return;
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Chat', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'chat' });
  }, [activeProject, activeProjectId, openOrActivateTab]);

  const openProjectFiles = useCallback(() => {
    if (!activeProjectId || !activeProject) return;
    setInspectorOpen(false);
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Files', kind: 'project', surface: 'project-files', projectId: activeProjectId });
  }, [activeProject, activeProjectId, openOrActivateTab]);

  const openProjectOverview = useCallback(() => {
    if (!activeProjectId || !activeProject) return;
    setInspectorOpen(false);
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Project Overview', kind: 'project', surface: 'project-overview', projectId: activeProjectId });
  }, [activeProject, activeProjectId, openOrActivateTab]);

  const openBoardNode = useCallback((nodeId: string) => {
    const projectId = activeProjectId ?? 'stateful';
    const project = projects.find((item) => item.id === projectId);
    if (!project) return;
    openOrActivateTab({ id: `project-${projectId}`, title: project.name, subtitle: 'Board', kind: 'project', surface: 'workspace', projectId, mode: 'board' });
    setFocusNodeId(nodeId);
    const node = initialNodes.find((item) => item.id === nodeId);
    if (node) setSelectedNode(node);
  }, [activeProjectId, openOrActivateTab]);

  const projectRootNodeId = useCallback(() => activeProjectId === 'stateful' ? 'root-answer' : activeProjectId ? `${activeProjectId}-root-answer` : 'root-answer', [activeProjectId]);

  const handleChatMessageFocus = useCallback((message: ChatMessage) => {
    setFocusedMessageId(message.id ?? null);
    setFocusNodeId(activeProjectId === 'stateful' && message.nodeId && !message.nodeId.startsWith('runtime-') ? message.nodeId : projectRootNodeId());
  }, [activeProjectId, projectRootNodeId]);

  const handleBoardNodeFocus = useCallback((messageId: string | null, node: AuraFlowNode) => {
    setSelectedNode(node);
    setFocusNodeId(node.id);
    if (messageId) setFocusedMessageId(messageId);
  }, []);

  const handleChatContextObjectFocus = useCallback((nodeId: string) => {
    if (!activeProjectId || !activeProject) return;
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Board', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'board' });
    const target = activeProjectId === 'stateful' ? nodeId : projectRootNodeId();
    setFocusNodeId(target);
    const node = initialNodes.find((item) => item.id === target);
    if (node) setSelectedNode(node);
  }, [activeProject, activeProjectId, openOrActivateTab, projectRootNodeId]);

  const handleBranchFromChat = useCallback((message: ChatMessage) => {
    if (!activeProjectId || !activeProject) return;
    const sourceNodeId = activeProjectId === 'stateful' && message.nodeId && !message.nodeId.startsWith('runtime-') ? message.nodeId : projectRootNodeId();
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Board', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'board' });
    setFocusNodeId(sourceNodeId);
    setBranchRequest({ nodeId: sourceNodeId, nonce: Date.now() });
    pushToast('Branch created from chat', 'The Board opened at the nearest persisted project turn.');
  }, [activeProject, activeProjectId, openOrActivateTab, projectRootNodeId, pushToast]);

  const handleSidebarNavigate = useCallback((destination: SidebarDestination) => {
    setInspectorOpen(false);
    setRoutingOpen(false);
    const map: Record<SidebarDestination, AppTab> = {
      home: { ...AURA_TAB, subtitle: 'Home', surface: 'global-home' },
      library: { ...AURA_TAB, subtitle: 'Library', surface: 'library' },
      notes: { ...AURA_TAB, subtitle: 'Notes', surface: 'notes' },
      study: { ...AURA_TAB, subtitle: 'Study', surface: 'study' },
      projects: { ...AURA_TAB, subtitle: 'Projects', surface: 'projects' },
      automations: { ...AURA_TAB, subtitle: 'Automations', surface: 'automations' },
    };
    openOrActivateTab(map[destination]);
  }, [openOrActivateTab]);

  const handleModeChange = useCallback((nextMode: WorkspaceMode) => {
    if (!activeProjectId || !activeProject) return;
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: nextMode[0].toUpperCase() + nextMode.slice(1), kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: nextMode });
  }, [activeProject, activeProjectId, openOrActivateTab]);

  const openFilePreview = useCallback((preview: FilePreviewRecord) => {
    setFilePreviews((current) => {
      const previous = current[preview.id];
      if (previous?.url?.startsWith('blob:') && previous.url !== preview.url) URL.revokeObjectURL(previous.url);
      return { ...current, [preview.id]: preview };
    });
    openOrActivateTab({ id: `file-${preview.id}`, title: preview.name, subtitle: preview.virtualPath, kind: 'file', surface: 'file-viewer', previewId: preview.id });
  }, [openOrActivateTab]);

  const handleLibraryItem = useCallback(async (item: LibraryItem) => {
    if (item.blobKey) {
      try {
        const blob = await getLocalFile(item.blobKey);
        if (!blob) throw new Error('Local file blob was not found');
        const url = URL.createObjectURL(blob);
        openFilePreview({ id: item.id, name: item.name, url, mimeType: item.mimeType || blob.type || 'application/octet-stream', virtualPath: `Library / ${item.collection} / ${item.name}` });
        return;
      } catch {
        pushToast('Could not open local file', 'The metadata exists, but the browser-local blob is unavailable. Re-import the file.');
        return;
      }
    }
    if (item.href) {
      openFilePreview({ id: item.id, name: item.name, url: item.href, mimeType: item.mimeType || (item.kind === 'HTML' ? 'text/html' : 'application/octet-stream'), virtualPath: `Library / ${item.collection} / ${item.name}` });
      return;
    }
    pushToast(`${item.kind} preview is mocked`, 'This bundled placeholder has metadata only. Your own imported files and connected-folder files open inside AURA tabs.');
  }, [openFilePreview, pushToast]);

  const handleConnectedFile = useCallback((file: File, virtualPath: string) => {
    const url = URL.createObjectURL(file);
    openFilePreview({ id: `fs-${crypto.randomUUID()}`, name: file.name, url, mimeType: file.type || 'application/octet-stream', virtualPath });
  }, [openFilePreview]);

  const connectFolder = useCallback(async () => {
    if (!supportsDirectoryPicker()) {
      pushToast('Folder picker unavailable', 'Use Chrome or Edge on localhost/HTTPS for connected folders. Individual file imports still work.');
      return;
    }
    try {
      const connection = await pickDirectoryConnection();
      if (!connection) return;
      const next = await listDirectoryConnections();
      setDirectoryConnections(next);
      openOrActivateTab({ ...AURA_TAB, subtitle: connection.name, surface: 'folder-viewer', connectionId: connection.id });
      pushToast('Folder connected', `${connection.name} stays in its original location. AURA stores only a browser permission handle.`);
    } catch (error) {
      if ((error as DOMException)?.name !== 'AbortError') pushToast('Could not connect folder', 'The folder picker was cancelled or the browser denied access.');
    }
  }, [openOrActivateTab, pushToast]);

  const openConnection = useCallback((connection: DirectoryConnection) => {
    openOrActivateTab({ ...AURA_TAB, subtitle: connection.name, surface: 'folder-viewer', connectionId: connection.id });
  }, [openOrActivateTab]);

  const disconnectConnection = useCallback(async (connection: DirectoryConnection) => {
    await removeDirectoryConnection(connection.id);
    setDirectoryConnections((current) => current.filter((item) => item.id !== connection.id));
    if (activeConnectionId === connection.id) openOrActivateTab({ ...AURA_TAB, subtitle: 'Library', surface: 'library' });
    pushToast('Disconnected from AURA', `${connection.name} was not deleted from disk.`);
  }, [activeConnectionId, openOrActivateTab, pushToast]);

  const removeLibraryItem = useCallback(async (item: LibraryItem) => {
    if (item.source === 'imported' && item.blobKey) {
      try { await deleteLocalFile(item.blobKey); } catch { /* metadata can still be removed */ }
    }
    setLibraryItems((current) => current.filter((entry) => entry.id !== item.id));
    pushToast('Removed from Library', item.source === 'imported' ? 'The browser-local indexed copy was removed. Connected filesystem folders are untouched.' : 'The Library reference was removed from this prototype.');
  }, [pushToast]);

  const importFiles = useCallback(async (files: File[], projectId?: string) => {
    if (!files.length) return;
    const imported: LibraryItem[] = [];
    for (const file of files) {
      const id = `local-${crypto.randomUUID()}`;
      const blobKey = id;
      try {
        await putLocalFile(blobKey, file);
        imported.push({
          id,
          name: stripExtension(file.name),
          kind: inferLibraryKind(file),
          collection: projectId ? 'Research' : 'Reference',
          detail: `Imported local file · ${file.name}`,
          updated: 'just now',
          tags: ['local', 'imported'],
          projectLinks: projectId ? [projectId] : [],
          source: 'imported',
          size: file.size,
          mimeType: file.type || undefined,
          blobKey,
        });
      } catch {
        pushToast('Import failed', `Could not store ${file.name} in browser-local storage.`);
      }
    }
    if (imported.length) {
      setLibraryItems((current) => [...imported, ...current]);
      pushToast(`${imported.length} file${imported.length === 1 ? '' : 's'} added`, projectId ? 'Imported into Library and linked to this project.' : 'Stored in Personal Library on this browser.');
    }
  }, [pushToast]);

  const toggleProjectLink = useCallback((itemId: string, projectId: string) => {
    setLibraryItems((current) => current.map((item) => {
      if (item.id !== itemId) return item;
      const links = item.projectLinks ?? [];
      return { ...item, projectLinks: links.includes(projectId) ? links.filter((id) => id !== projectId) : [...links, projectId], updated: 'just now' };
    }));
  }, []);

  const selectThread = useCallback((threadId: string) => {
    if (!activeProjectId) return;
    setActiveThreadByProject((current) => ({ ...current, [activeProjectId]: threadId }));
    setFocusedMessageId(null);

    // Session hydration: when switching to a live thread that has a backend
    // sessionId, fetch /v1/sessions/{sessionId} and reconcile messages.
    // This is fail-safe: hydration failure never destroys local state.
    const thread = chatThreads.find((t) => t.id === threadId);
    if (thread?.source === 'live' && thread.sessionId) {
      void api.fetchSession(thread.sessionId).then((detail) => {
        if (!detail?.messages?.length) return;
        setChatThreads((current) => current.map((t) => {
          if (t.id !== threadId) return t;

          // ── Role+content occurrence reconciliation ──────────────────────────
          // Backend canonical IDs are UUIDs; local optimistic IDs are synthetic
          // ("live-user-…", "live-assistant-…").  We CANNOT dedup by ID alone.
          //
          // Algorithm:
          //   1. Build an occurrence counter over local (role, content) pairs.
          //   2. For each backend message, check if occurrence N of that pair
          //      already exists locally.  If yes: adopt the backend canonical ID
          //      (so the backend wins on identity) and preserve all local UI
          //      metadata (executionLabel, execution, provenance, etc.).
          //      If no: it is a genuinely new backend-only message → append.

          type OccKey = `${string}::${string}`;
          const occurrenceCounter = new Map<OccKey, number>();

          // Index local messages by occurrence of (role, content)
          const localByOccurrence = new Map<string, ChatMessage & { _localIdx: number }>();
          t.messages.forEach((m, idx) => {
            const key: OccKey = `${m.role}::${m.content}`;
            const n = (occurrenceCounter.get(key) ?? 0) + 1;
            occurrenceCounter.set(key, n);
            localByOccurrence.set(`${key}::${n}`, { ...m, _localIdx: idx });
          });

          // Reset counter for backend pass
          occurrenceCounter.clear();

          const merged: ChatMessage[] = [...t.messages];
          let appended = false;

          for (const bm of detail.messages) {
            const key: OccKey = `${bm.role}::${bm.content}`;
            const n = (occurrenceCounter.get(key) ?? 0) + 1;
            occurrenceCounter.set(key, n);

            const localMatch = localByOccurrence.get(`${key}::${n}`);
            if (localMatch) {
              // Adopt the backend canonical ID on the existing local message
              if (localMatch.id !== bm.id && bm.id) {
                merged[localMatch._localIdx] = { ...merged[localMatch._localIdx], id: bm.id };
              }
            } else {
              // Genuinely new message from backend — append
              merged.push(bm);
              appended = true;
            }
          }

          // Only update thread if something actually changed
          const idChanged = detail.messages.some((bm, i) => bm.id && t.messages[i]?.id !== bm.id);
          if (!appended && !idChanged) return t;
          return { ...t, messages: merged };
        }));
      }).catch(() => { /* hydration failure is silently ignored */ });
    }
  }, [activeProjectId, chatThreads]);

  const newThread = useCallback(() => {
    if (!activeProjectId) return;
    const id = `${activeProjectId}-chat-${Date.now()}`;
    const sessionId = `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    const count = chatThreads.filter((thread) => thread.projectId === activeProjectId).length + 1;
    const thread: ChatThreadRecord = {
      id,
      projectId: activeProjectId,
      title: `New chat ${count}`,
      summary: 'Clean conversation · project context available explicitly',
      updated: 'just now',
      messages: [],
      sessionId,
      source: 'live',
    };
    setChatThreads((current) => [thread, ...current]);
    setActiveThreadByProject((current) => ({ ...current, [activeProjectId]: id }));
    if (activeProject) openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Chat', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'chat' });
    pushToast('New project chat', 'This thread starts clean and connects to live backend.');
  }, [activeProject, activeProjectId, chatThreads, openOrActivateTab, pushToast]);

  const updateThreadMessages = useCallback((threadId: string, updater: (messages: ChatMessage[]) => ChatMessage[]) => {
    setChatThreads((current) => current.map((thread) => {
      if (thread.id !== threadId) return thread;
      const nextMessages = updater(thread.messages);
      const firstUser = nextMessages.find((message) => message.role === 'user');
      const wasEmpty = thread.messages.length === 0;
      return {
        ...thread,
        messages: nextMessages,
        updated: 'just now',
        title: wasEmpty && firstUser ? firstUser.content.slice(0, 42) + (firstUser.content.length > 42 ? '…' : '') : thread.title,
        summary: wasEmpty && firstUser ? 'New conversation in this project' : thread.summary,
      };
    }));
  }, []);

  const handleSendMessage = useCallback(
    async (text: string) => {
      if (!activeProjectId || !activeThreadId) return;

      const currentThread = chatThreads.find((t) => t.id === activeThreadId);

      // ── Truthfulness invariant ─────────────────────────────────────────────
      // Demo threads MUST NOT silently call POST /v1/chat.
      // The caller (ChatPane) shows a CTA instead; this is a hard guard in case
      // it is bypassed.
      if (currentThread?.source === 'demo') {
        pushToast('Demo thread', 'Start a live chat to use the AURA backend with this project.');
        return;
      }

      const sessionId = currentThread?.sessionId || `sess-${activeProjectId}-${activeThreadId}`;

      // Capture originating thread at the time of send so approval decisions
      // are bound even if the user switches threads before the run completes.
      const originatingThreadId = activeThreadId;

      const nonce = Date.now();
      const userMsg: ChatMessage = {
        id: `live-user-${nonce}`,
        role: 'user',
        branch: 'Root',
        nodeId: `live-user-node-${nonce}`,
        content: text,
        timestamp: 'just now',
        created_at: new Date().toISOString(),
        status: 'Sent',
      };

      updateThreadMessages(originatingThreadId, (prev) => [...prev, userMsg]);
      patchThreadLive(originatingThreadId, { runStatus: 'running' });

      try {
        const resp = await api.sendChat(
          sessionId,
          text,
          activeProject?.name || undefined,
          selectedModelOverride
        );

        patchThreadLive(originatingThreadId, { runId: resp.run_id, runStatus: resp.status });

        if (resp.status === 'waiting_for_approval' && resp.approval_id) {
          const appDetail = await api.fetchApproval(resp.approval_id);
          // Typed binding: register originating thread in the approvalOrigins map
          setApprovalOrigins((prev) => ({ ...prev, [appDetail.id]: originatingThreadId }));
          patchThreadLive(originatingThreadId, { approval: appDetail });
        } else {
          patchThreadLive(originatingThreadId, { approval: null });
          if (resp.response) {
            let steps: ExecutionStep[] = [];
            if (resp.run_id) {
              try {
                const rDetail = await api.fetchRunDetails(resp.run_id);
                steps = mapRunEventsToExecutionSteps(rDetail.events);
                patchThreadLive(originatingThreadId, { runDetail: rDetail });
              } catch (e) {
                console.warn('Failed to fetch run details for execution steps', e);
              }
            }

            const assistantMsg: ChatMessage = {
              id: `live-assistant-${nonce}`,
              role: 'assistant',
              branch: 'Root',
              nodeId: `live-assistant-node-${nonce}`,
              content: resp.response,
              timestamp: 'just now',
              created_at: new Date().toISOString(),
              status: 'Completed',
              executionLabel: steps.length > 0 ? `AURA · ${steps.length} steps` : undefined,
              execution: steps.length > 0 ? steps : undefined,
            };
            updateThreadMessages(originatingThreadId, (prev) => [...prev, assistantMsg]);
          }
        }

        if (resp.run_id) {
          void refreshInspectorData(originatingThreadId, resp.run_id);
        }

        api.fetchSessions().then(setSessions).catch(() => {});
        if (activeProject?.name) {
          api.fetchMemories(activeProject.name).then(setMemories).catch(() => {});
        }
      } catch (err: any) {
        patchThreadLive(originatingThreadId, { runStatus: 'failed' });
        const errorMsg: ChatMessage = {
          id: `live-err-${nonce}`,
          role: 'assistant',
          branch: 'Root',
          nodeId: `live-err-node-${nonce}`,
          content: `Error: ${(err as Error).message || 'Execution failed'}`,
          timestamp: 'just now',
          status: 'Failed',
        };
        updateThreadMessages(originatingThreadId, (prev) => [...prev, errorMsg]);
      }
    },
    [
      activeProjectId,
      activeThreadId,
      chatThreads,
      activeProject?.name,
      selectedModelOverride,
      updateThreadMessages,
      refreshInspectorData,
      pushToast,
    ]
  );

  /**
   * handleStartLiveChat — creates a fresh live thread for the active project
   * then immediately sends `text` to the backend.
   *
   * This is the explicit user action that transitions from demo-only viewing to
   * an actual backend session.  Demo threads are never promoted; a new thread is
   * always created so the demo transcript is preserved exactly as-is.
   */
  const handleStartLiveChat = useCallback(
    async (text: string) => {
      if (!activeProjectId || !activeProject) return;
      const promptText = text.trim();
      const id = `${activeProjectId}-live-${Date.now()}`;
      const sessionId = `sess-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
      const count = chatThreads.filter((t) => t.projectId === activeProjectId).length + 1;
      // Title: use draft text if provided, otherwise a generic label
      const title = promptText
        ? promptText.slice(0, 42) + (promptText.length > 42 ? '…' : '')
        : `Live chat ${count}`;
      const thread: ChatThreadRecord = {
        id,
        projectId: activeProjectId,
        title,
        summary: 'Live backend session',
        updated: 'just now',
        messages: [],
        sessionId,
        source: 'live',
      };
      setChatThreads((current) => [thread, ...current]);
      setActiveThreadByProject((current) => ({ ...current, [activeProjectId]: id }));
      openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Chat', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'chat' });
      pushToast('Live chat started', 'A new thread is connected to the AURA backend.');

      // If there is no prompt text, we only create the thread — no backend call.
      if (!promptText) return;

      // Small yield so state settles before we send
      await new Promise((resolve) => window.setTimeout(resolve, 0));
      void (async () => {
        const originatingThreadId = id;
        const nonce = Date.now();
        const userMsg: ChatMessage = { id: `live-user-${nonce}`, role: 'user', branch: 'Root', nodeId: `live-user-node-${nonce}`, content: promptText, timestamp: 'just now', created_at: new Date().toISOString(), status: 'Sent' };
        updateThreadMessages(originatingThreadId, (prev) => [...prev, userMsg]);
        patchThreadLive(originatingThreadId, { runStatus: 'running' });
        try {
          const resp = await api.sendChat(sessionId, promptText, activeProject.name, selectedModelOverride);
          patchThreadLive(originatingThreadId, { runId: resp.run_id, runStatus: resp.status });
          if (resp.status === 'waiting_for_approval' && resp.approval_id) {
            const appDetail = await api.fetchApproval(resp.approval_id);
            // Typed binding: record which thread owns this approval
            setApprovalOrigins((prev) => ({ ...prev, [appDetail.id]: originatingThreadId }));
            patchThreadLive(originatingThreadId, { approval: appDetail });
          } else {
            patchThreadLive(originatingThreadId, { approval: null });
            if (resp.response) {
              let steps: ExecutionStep[] = [];
              if (resp.run_id) {
                try { const rDetail = await api.fetchRunDetails(resp.run_id); steps = mapRunEventsToExecutionSteps(rDetail.events); patchThreadLive(originatingThreadId, { runDetail: rDetail }); } catch {}
              }
              const assistantMsg: ChatMessage = { id: `live-assistant-${nonce}`, role: 'assistant', branch: 'Root', nodeId: `live-assistant-node-${nonce}`, content: resp.response, timestamp: 'just now', created_at: new Date().toISOString(), status: 'Completed', executionLabel: steps.length > 0 ? `AURA · ${steps.length} steps` : undefined, execution: steps.length > 0 ? steps : undefined };
              updateThreadMessages(originatingThreadId, (prev) => [...prev, assistantMsg]);
            }
          }
          if (resp.run_id) void refreshInspectorData(originatingThreadId, resp.run_id);
        } catch (err: any) {
          patchThreadLive(originatingThreadId, { runStatus: 'failed' });
          updateThreadMessages(originatingThreadId, (prev) => [...prev, { id: `live-err-${nonce}`, role: 'assistant', branch: 'Root', nodeId: `live-err-node-${nonce}`, content: `Error: ${(err as Error).message || 'Execution failed'}`, timestamp: 'just now', status: 'Failed' }]);
        }
      })();
      void count; // suppress lint — count used for UI naming above
    },
    [activeProject, activeProjectId, chatThreads, openOrActivateTab, pushToast, refreshInspectorData, selectedModelOverride, updateThreadMessages]
  );

  const handleApprovalDecision = useCallback(
    async (
      decision: 'approved' | 'rejected' | 'edited',
      notes?: string,
      editedInput?: Record<string, any>
    ) => {
      const approval = activeThreadLive.approval;
      if (!approval) return;

      // ── Typed approval thread binding ──────────────────────────────────────
      // `approvalOrigins` maps approval.id → originatingThreadId, set at the
      // moment the approval was raised.  This replaces the `as any` hack and
      // survives the user navigating to a different thread before deciding.
      const originatingThreadId: string =
        approvalOrigins[approval.id] ?? activeThreadId ?? '';
      if (!originatingThreadId) return;

      patchThreadLive(originatingThreadId, { runStatus: 'running' });
      try {
        const decisionResp = await api.submitApproval(
          approval.id,
          decision,
          notes,
          editedInput
        );

        patchThreadLive(originatingThreadId, { runStatus: decisionResp.execution_status });

        if (decisionResp.execution_status === 'waiting_for_approval' && decisionResp.approval_id) {
          const nextApp = await api.fetchApproval(decisionResp.approval_id);
          // Register the next approval in the typed map
          setApprovalOrigins((prev) => ({ ...prev, [nextApp.id]: originatingThreadId }));
          patchThreadLive(originatingThreadId, { approval: nextApp });
        } else {
          patchThreadLive(originatingThreadId, { approval: null });
          if (decisionResp.final_response) {
            let steps: ExecutionStep[] = [];
            if (decisionResp.run_id) {
              try {
                const rDetail = await api.fetchRunDetails(decisionResp.run_id);
                patchThreadLive(originatingThreadId, { runDetail: rDetail });
                steps = mapRunEventsToExecutionSteps(rDetail.events);
              } catch (e) {
                console.warn('Failed to fetch run details after approval', e);
              }
            }

            const nonce = Date.now();
            const assistantMsg: ChatMessage = {
              id: `live-approval-assistant-${nonce}`,
              role: 'assistant',
              branch: 'Root',
              nodeId: `live-approval-assistant-node-${nonce}`,
              content: decisionResp.final_response,
              timestamp: 'just now',
              created_at: new Date().toISOString(),
              status: 'Completed',
              executionLabel: steps.length > 0 ? `AURA · ${steps.length} steps` : undefined,
              execution: steps.length > 0 ? steps : undefined,
            };
            // Append to ORIGINATING thread, not the currently active one
            updateThreadMessages(originatingThreadId, (prev) => [...prev, assistantMsg]);
          }
        }

        // Fix 5: use decisionResp.run_id as the authoritative ID for this refresh;
        // fall back to the thread's stored runId only if the response omits it.
        const runId = decisionResp.run_id ?? threadLiveStates[originatingThreadId]?.runId;
        if (runId) {
          void refreshInspectorData(originatingThreadId, runId);
        }
        if (activeProject?.name) {
          api.fetchMemories(activeProject.name).then(setMemories).catch(() => {});
        }
      } catch (err: any) {
        patchThreadLive(originatingThreadId, { runStatus: 'failed' });
        console.error('Approval decision error:', err);
      }
    },
    [
      activeThreadLive.approval,
      activeThreadId,
      approvalOrigins,
      threadLiveStates,
      updateThreadMessages,
      refreshInspectorData,
      activeProject?.name,
    ]
  );

  const runAutomation = useCallback((automation: AutomationRecord) => {
    setAutomations((current) => current.map((item) => item.id === automation.id ? { ...item, status: 'running', lastRun: 'Running now…' } : item));
    pushToast(`Running · ${automation.name}`, 'Prototype run only — no external actions are executed.');
    window.setTimeout(() => {
      setAutomations((current) => current.map((item) => item.id === automation.id ? { ...item, status: 'ready', lastRun: 'Completed just now' } : item));
    }, 1600);
  }, [pushToast]);

  const activeConnection = directoryConnections.find((item) => item.id === activeConnectionId) ?? null;
  const title = surface === 'global-home' ? 'Home'
    : surface === 'library' ? 'Library'
    : surface === 'notes' ? 'Notes'
    : surface === 'study' ? 'Study'
    : surface === 'automations' ? 'Automations'
    : surface === 'projects' ? 'Projects'
    : surface === 'folder-viewer' ? activeConnection?.name ?? 'Connected folder'
    : surface === 'file-viewer' ? activeFilePreview?.name ?? 'File'
    : 'Home';

  const locationValue = surface === 'global-home' ? 'aura://home'
    : surface === 'library' ? 'aura://library'
    : surface === 'folder-viewer' ? `folder://${activeConnection?.name ?? 'connected'}`
    : surface === 'file-viewer' ? activeFilePreview?.virtualPath ?? 'aura://file'
    : activeProject ? `aura://projects/${activeProject.name.replace(/\s+/g, '-').toLowerCase()}/${surface === 'workspace' ? mode : surface.replace('project-', '')}`
    : `aura://${surface}`;

  const handleLocationSubmit = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    if (/^https?:\/\//i.test(trimmed)) {
      window.open(trimmed, '_blank', 'noopener,noreferrer');
      pushToast('Opened URL', trimmed);
      return;
    }
    const normalized = trimmed.toLowerCase();
    if (normalized.includes('library')) { handleSidebarNavigate('library'); return; }
    if (normalized.includes('home')) { handleSidebarNavigate('home'); return; }
    const matchingProject = projects.find((project) => project.name.toLowerCase().includes(normalized) || normalized.includes(project.name.toLowerCase()));
    if (matchingProject) { openProject(matchingProject.id); return; }
    const matchingConnection = directoryConnections.find((connection) => connection.name.toLowerCase().includes(normalized));
    if (matchingConnection) { openConnection(matchingConnection); return; }
    pushToast('Workspace search', `Searching AURA for “${trimmed}” is mocked in v8; Ctrl/⌘ K still opens Ask AURA.`);
  };

  const projectFileCount = activeProjectId ? libraryItems.filter((item) => item.projectLinks?.includes(activeProjectId)).length + projectArtifacts.filter((item) => item.projectId === activeProjectId).length : 0;
  const projectNoteCount = activeProjectId ? notes.filter((note) => note.projectIds.includes(activeProjectId)).length : 0;

  return (
    <div className={`app-shell ${inspectorOpen && surface === 'workspace' ? 'with-inspector' : ''} ${sidebarCollapsed ? 'sidebar-is-collapsed' : ''}`}>
      <Sidebar
        collapsed={sidebarCollapsed}
        active={activeNav}
        activeProjectId={activeProjectId}
        libraryCount={libraryItems.length}
        onCollapsedChange={setSidebarCollapsed}
        onNavigate={handleSidebarNavigate}
        onProjectOpen={openProject}
        onNewProject={() => pushToast('New project', 'Project creation UI is the one remaining mocked shell action in v7.')}
      />

      <Topbar
        projectName={activeProject?.name ?? null}
        projectSection={projectSection}
        globalTitle={title}
        mode={mode}
        onModeChange={handleModeChange}
        onOpenProjectOverview={openProjectOverview}
        onOpenProjectFiles={openProjectFiles}
        routingOpen={routingOpen}
        onRoutingOpenChange={setRoutingOpen}
        locked={locked}
        onToggleLock={() => {
          setLocked((value) => !value);
          pushToast(locked ? 'Agent lock released' : 'All agents locked', locked ? 'Routing follows the active profile again.' : 'Model C is pinned for this mock session.');
        }}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((value) => !value)}
        onOpenAura={() => setAuraOpen(true)}
      />

      <WorkspaceChrome
        tabs={tabs}
        activeTabId={activeTabId}
        locationValue={locationValue}
        canGoBack={tabHistoryIndex > 0}
        canGoForward={tabHistoryIndex < tabHistory.length - 1}
        onGoBack={() => goTabHistory(-1)}
        onGoForward={() => goTabHistory(1)}
        onSelectTab={selectTab}
        onCloseTab={closeTab}
        onSubmitLocation={handleLocationSubmit}
      />

      <main className={`workspace workspace--${surface === 'workspace' ? mode : surface}`}>
        {surface === 'global-home' ? (
          <GlobalHome
            libraryItems={libraryItems}
            automations={automations}
            noteCount={notes.length}
            onOpenProject={openProject}
            onOpenProjects={() => handleSidebarNavigate('projects')}
            onOpenLibrary={() => handleSidebarNavigate('library')}
            onOpenFile={(id) => {
              const item = libraryItems.find((entry) => entry.id === id);
              if (item) void handleLibraryItem(item);
            }}
          />
        ) : null}

        {surface === 'library' ? (
          <LibraryView
            items={libraryItems}
            connections={directoryConnections}
            directoryPickerSupported={supportsDirectoryPicker()}
            onOpenItem={(item) => void handleLibraryItem(item)}
            onImportFiles={(files) => void importFiles(files)}
            onToggleProjectLink={toggleProjectLink}
            onRemoveItem={(item) => void removeLibraryItem(item)}
            onConnectFolder={() => void connectFolder()}
            onOpenConnection={openConnection}
            onDisconnectConnection={(connection) => void disconnectConnection(connection)}
          />
        ) : null}
        {surface === 'folder-viewer' && activeConnection ? (
          <ConnectedFolderView
            connection={activeConnection}
            onBackToLibrary={() => handleSidebarNavigate('library')}
            onDisconnect={(connection) => void disconnectConnection(connection)}
            onOpenFile={handleConnectedFile}
          />
        ) : null}
        {surface === 'file-viewer' && activeFilePreview ? (
          <FilePreviewView preview={activeFilePreview} onOpenExternal={() => window.open(activeFilePreview.url, '_blank', 'noopener,noreferrer')} />
        ) : null}
        {surface === 'notes' ? <NotesView notes={notes} onNotesChange={setNotes} onOpenProject={openProject} /> : null}
        {surface === 'study' ? <StudyView libraryItems={libraryItems} onOpenItem={(item) => void handleLibraryItem(item)} onStartSession={(trackId) => pushToast('Study session started', `${trackId} · prototype timer/activity is mocked.`)} /> : null}
        {surface === 'automations' ? <AutomationsView automations={automations} onAutomationsChange={setAutomations} onRunNow={runAutomation} /> : null}
        {surface === 'projects' ? <ProjectsView onOpenProject={openProject} onMockCreate={() => pushToast('New project', 'Project creation is still mocked in this UI prototype.')} /> : null}

        {surface === 'project-overview' && activeProject ? (
          <ProjectHome
            projectId={activeProject.id}
            chatCount={projectThreads.length}
            fileCount={projectFileCount}
            noteCount={projectNoteCount}
            onBack={() => handleSidebarNavigate('projects')}
            onOpenNode={openBoardNode}
            onOpenChats={openProjectChats}
            onOpenFiles={openProjectFiles}
            onMockObject={(label) => pushToast(label, 'Open Chats, Files or Board to continue working with this object.')}
          />
        ) : null}

        {surface === 'project-files' && activeProject ? (
          <ProjectFilesView
            project={activeProject}
            libraryItems={libraryItems}
            onBack={openProjectOverview}
            onOpenItem={(item) => void handleLibraryItem(item)}
            onImportFiles={(files, projectId) => void importFiles(files, projectId)}
            onToggleProjectLink={toggleProjectLink}
          />
        ) : null}

        {surface === 'workspace' && mode === 'chat' && activeProject ? (
          <ProjectChatWorkspace
            project={activeProject}
            threads={projectThreads}
            activeThreadId={activeThreadId}
            libraryItems={libraryItems}
            notes={notes}
            focusedMessageId={focusedMessageId}
            onSelectThread={selectThread}
            onNewThread={newThread}
            onUpdateMessages={updateThreadMessages}
            onMessageFocus={handleChatMessageFocus}
            onBranchFromMessage={handleBranchFromChat}
            onContextObjectFocus={handleChatContextObjectFocus}
            onAttachRequest={openProjectFiles}
            onSendMessage={handleSendMessage}
            onStartLiveChat={handleStartLiveChat}
            currentApproval={activeThreadLive.approval}
            onApprovalDecision={handleApprovalDecision}
          />
        ) : null}

        {surface === 'workspace' && mode === 'board' && activeProject ? (
          <BoardCanvas
            key={activeProject.id}
            boardKey={activeProject.id}
            seedNodes={genericBoard?.nodes}
            seedEdges={genericBoard?.edges}
            showBranchLabels={activeProject.id === 'stateful'}
            focusNodeId={focusNodeId}
            onNodeFocus={handleBoardNodeFocus}
            onToast={pushToast}
            branchRequest={branchRequest}
            executionExpanded={params.get('execution') === '1'}
          />
        ) : null}

        {surface === 'workspace' && mode === 'split' && activeProject ? (
          <div className="split-workspace">
            <div className="split-workspace__chat">
              <ProjectChatWorkspace
                compact
                project={activeProject}
                threads={projectThreads}
                activeThreadId={activeThreadId}
                libraryItems={libraryItems}
                notes={notes}
                focusedMessageId={focusedMessageId}
                onSelectThread={selectThread}
                onNewThread={newThread}
                onUpdateMessages={updateThreadMessages}
                onMessageFocus={handleChatMessageFocus}
                onBranchFromMessage={handleBranchFromChat}
                onContextObjectFocus={handleChatContextObjectFocus}
                onAttachRequest={openProjectFiles}
                onSendMessage={handleSendMessage}
                onStartLiveChat={handleStartLiveChat}
                currentApproval={activeThreadLive.approval}
                onApprovalDecision={handleApprovalDecision}
              />
            </div>
            <div className="split-workspace__board">
              <BoardCanvas key={`split-${activeProject.id}`} compact boardKey={activeProject.id} seedNodes={genericBoard?.nodes} seedEdges={genericBoard?.edges} showBranchLabels={activeProject.id === 'stateful'} focusNodeId={focusNodeId} onNodeFocus={handleBoardNodeFocus} onToast={pushToast} branchRequest={branchRequest} executionExpanded={params.get('execution') === '1'} />
            </div>
          </div>
        ) : null}
      </main>

      {inspectorOpen ? (
        <InspectorPanel
          selectedNode={selectedNode}
          runDetail={activeThreadLive.runDetail}
          researchData={activeThreadLive.researchData}
          memories={memories}
          onClose={() => setInspectorOpen(false)}
          onContextSelect={openBoardNode}
        />
      ) : null}
      {auraOpen ? (
        <AuraCommandPalette
          projectName={activeProject?.name ?? null}
          libraryItems={libraryItems}
          notes={notes}
          automations={automations}
          onClose={() => setAuraOpen(false)}
          onOpenLibrary={() => { setAuraOpen(false); handleSidebarNavigate('library'); }}
          onOpenNotes={() => { setAuraOpen(false); handleSidebarNavigate('notes'); }}
          onOpenAutomations={() => { setAuraOpen(false); handleSidebarNavigate('automations'); }}
          onOpenProject={(projectId) => { setAuraOpen(false); openProject(projectId); }}
        />
      ) : null}
      <ToastStack toasts={toasts} />
    </div>
  );
}
