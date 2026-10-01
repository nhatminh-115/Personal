import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AuraCommandPalette } from './components/chat/AuraCommandPalette';
import { ProjectChatWorkspace } from './components/chat/ProjectChatWorkspace';
import type { FilePreviewRecord } from './components/global/FilePreviewView';
import { Sidebar, type SidebarDestination } from './components/layout/Sidebar';
import { Topbar } from './components/layout/Topbar';
import { WorkspaceChrome, type AuraTab } from './components/layout/WorkspaceChrome';
import { ToastStack } from './components/ui/ToastStack';
import { RoutingConfirmationNotice } from './components/routing/RoutingConfirmationNotice';
import { initialNodes } from './data/mockData';
import { makeProjectBoard } from './data/projectBoards';
import {
  initialAutomations,
  initialChatThreads,
  initialLibraryItems,
  initialNotes,
  projectArtifacts,
  projects,
  studyTracks,
  type AutomationRecord,
  type ChatThreadRecord,
  type LibraryItem,
  type LibraryKind,
  type ProjectRecord,
  type WorkspaceNote,
} from './data/workspaceData';
import { deleteLocalFile, getLocalFile, putLocalFile } from './lib/localFiles';
import { executionErrorText } from './lib/executionError';
import {
  compiledContextTokenCount,
  compiledContextTokenCountFromManifest,
  contextProvenanceFromManifest,
  contextProvenanceFromRunEvents,
  routingSummaryFromProvenance,
  routingSummaryFromRunEvents,
} from './lib/contextProvenance';
import {
  listDirectoryConnections,
  pickDirectoryConnection,
  removeDirectoryConnection,
  supportsDirectoryPicker,
  type DirectoryConnection,
} from './lib/folderConnections';
import { api, ApiError } from './services/api';
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
  WorkspaceNoteRecord,
  StudySessionRecord,
  WorkspaceLibraryReferenceRecord,
  WorkspaceProjectRecord,
  WorkspaceMode,
  EffectiveRouting,
  ReasoningEffort,
  RunRoutingDecision,
} from './types';

const BoardCanvas = lazy(async () => {
  const module = await import('./components/board/BoardCanvas');
  return { default: module.BoardCanvas };
});
const AutomationsView = lazy(() => import('./components/global/AutomationsView').then((module) => ({ default: module.AutomationsView })));
const GlobalHome = lazy(() => import('./components/global/GlobalHome').then((module) => ({ default: module.GlobalHome })));
const LibraryView = lazy(() => import('./components/global/LibraryView').then((module) => ({ default: module.LibraryView })));
const ConnectedFolderView = lazy(() => import('./components/global/ConnectedFolderView').then((module) => ({ default: module.ConnectedFolderView })));
const FilePreviewView = lazy(() => import('./components/global/FilePreviewView').then((module) => ({ default: module.FilePreviewView })));
const NotesView = lazy(() => import('./components/global/NotesView').then((module) => ({ default: module.NotesView })));
const ProjectsView = lazy(() => import('./components/global/ProjectsView').then((module) => ({ default: module.ProjectsView })));
const StudyView = lazy(() => import('./components/global/StudyView').then((module) => ({ default: module.StudyView })));
const ProjectFilesView = lazy(() => import('./components/home/ProjectFilesView').then((module) => ({ default: module.ProjectFilesView })));
const ProjectHome = lazy(() => import('./components/home/ProjectHome').then((module) => ({ default: module.ProjectHome })));
const InspectorPanel = lazy(() => import('./components/layout/InspectorPanel').then((module) => ({ default: module.InspectorPanel })));
const RoutingStudio = lazy(() => import('./components/routing/RoutingStudio').then((module) => ({ default: module.RoutingStudio })));

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

function noteUpdatedLabel(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return 'today';
  const age = Math.max(0, Date.now() - timestamp);
  if (age < 60_000) return 'just now';
  if (age < 60 * 60_000) return `${Math.floor(age / 60_000)}m ago`;
  if (age < 24 * 60 * 60_000) return `${Math.floor(age / (60 * 60_000))}h ago`;
  if (age < 48 * 60 * 60_000) return 'yesterday';
  return new Date(timestamp).toLocaleDateString();
}

function workspaceNoteFromRecord(record: WorkspaceNoteRecord, projectCatalog: ProjectRecord[] = projects): WorkspaceNote {
  return {
    id: record.id,
    title: record.title,
    body: record.body,
    updated: noteUpdatedLabel(record.updated_at),
    tags: record.tags,
    projectIds: record.project_names.map((name) => projectCatalog.find((project) => project.name === name)?.id ?? name),
    pinned: record.pinned,
    source: 'live',
  };
}

function workspaceNotePayload(note: WorkspaceNote, projectCatalog: ProjectRecord[] = projects): Omit<WorkspaceNoteRecord, 'id' | 'created_at' | 'updated_at'> {
  return {
    title: note.title,
    body: note.body,
    tags: note.tags,
    project_names: note.projectIds.map((id) => projectCatalog.find((project) => project.id === id)?.name ?? id),
    pinned: note.pinned === true,
  };
}

function workspaceNoteFingerprint(note: WorkspaceNote): string {
  return JSON.stringify({
    title: note.title,
    body: note.body,
    tags: note.tags,
    projectIds: [...note.projectIds].sort(),
    pinned: note.pinned === true,
  });
}

function workspaceLibraryFromRecord(record: WorkspaceLibraryReferenceRecord, projectCatalog: ProjectRecord[] = projects): LibraryItem {
  return {
    id: record.id,
    name: record.name,
    kind: record.kind,
    collection: record.collection,
    detail: record.detail,
    updated: noteUpdatedLabel(record.updated_at),
    tags: record.tags,
    projectLinks: record.project_names.map((name) => projectCatalog.find((project) => project.name === name)?.id ?? name),
    source: 'imported',
    syncState: 'synced',
    size: record.size ?? undefined,
    mimeType: record.mime_type ?? undefined,
    blobKey: `local-${record.id}`,
  };
}

function workspaceLibraryPayload(item: LibraryItem, projectCatalog: ProjectRecord[] = projects) {
  return {
    name: item.name,
    kind: item.kind,
    collection: item.collection,
    detail: item.detail,
    tags: item.tags,
    project_names: (item.projectLinks ?? []).map((id) => projectCatalog.find((project) => project.id === id)?.name ?? id),
    size: item.size,
    mime_type: item.mimeType,
  };
}

function projectFromRecord(record: WorkspaceProjectRecord, index: number): ProjectRecord {
  const accents: ProjectRecord['accent'][] = ['cyan', 'purple', 'amber', 'green'];
  return {
    id: record.id,
    name: record.name,
    subtitle: record.subtitle || 'Personal project workspace',
    status: 'active',
    accent: accents[index % accents.length],
    updated: noteUpdatedLabel(record.updated_at),
    meta: 'New project · 0 chats',
    thesis: 'No project thesis added yet.',
    next: 'Start a chat or add a file to build project context.',
    source: 'user',
  };
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
  const [projectCreateRequest, setProjectCreateRequest] = useState(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [routingOpen, setRoutingOpen] = useState(params.get('routing') === '1');
  const [routingStudioOpen, setRoutingStudioOpen] = useState(false);
  const [routingStudioLoaded, setRoutingStudioLoaded] = useState(false);
  const [routingConfirmation, setRoutingConfirmation] = useState<{ provider?: string; model?: string } | null>(null);
  const [auraOpen, setAuraOpen] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(params.get('inspector') === '1');
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null);
  const [focusNodeId, setFocusNodeId] = useState<string | null>(params.get('focus'));
  const [selectedNode, setSelectedNode] = useState<AuraFlowNode | undefined>(() => initialNodes.find((node) => node.id === params.get('focus')));
  const [branchRequest, setBranchRequest] = useState<{ nodeId: string; nonce: number } | null>(null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);

  const [libraryItems, setLibraryItems] = useState<LibraryItem[]>(loadLibrary);
  const libraryLoaded = useRef(false);
  const [userProjects, setUserProjects] = useState<ProjectRecord[]>([]);
  const [directoryConnections, setDirectoryConnections] = useState<DirectoryConnection[]>([]);
  const [activeConnectionId, setActiveConnectionId] = useState<string | null>(null);
  const [filePreviews, setFilePreviews] = useState<Record<string, FilePreviewRecord>>({});
  const [tabs, setTabs] = useState<AppTab[]>([AURA_TAB]);
  const [activeTabId, setActiveTabId] = useState(AURA_TAB.id);
  const [tabHistory, setTabHistory] = useState<AppTab[]>([AURA_TAB]);
  const [tabHistoryIndex, setTabHistoryIndex] = useState(0);
  const [notes, setNotes] = useState<WorkspaceNote[]>(() => loadStored(STORAGE.notes, initialNotes));
  const [studySessions, setStudySessions] = useState<StudySessionRecord[]>([]);
  const studySessionsLoaded = useRef(false);
  const notesRef = useRef(notes);
  notesRef.current = notes;
  const notesLoaded = useRef(false);
  const noteSyncTimers = useRef(new Map<string, number>());
  const noteCreateInFlight = useRef(new Set<string>());
  const noteUpdateInFlight = useRef(new Set<string>());
  const savedNoteFingerprints = useRef(new Map<string, string>());
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

  const projectCatalog = useMemo(() => [...userProjects, ...projects], [userProjects]);
  const activeProject = projectCatalog.find((project) => project.id === activeProjectId) ?? null;

  useEffect(() => {
    if (!userProjects.length) return;
    const idByName = new Map(userProjects.map((project) => [project.name, project.id]));
    setLibraryItems((current) => current.map((item) => ({
      ...item,
      projectLinks: item.projectLinks?.map((id) => idByName.get(id) ?? id),
    })));
    const normalizedNotes = notesRef.current.map((note) => ({
      ...note,
      projectIds: note.projectIds.map((id) => idByName.get(id) ?? id),
    }));
    notesRef.current = normalizedNotes;
    setNotes(normalizedNotes);
  }, [userProjects]);
  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? AURA_TAB;
  const activeFilePreview = activeTab.previewId ? filePreviews[activeTab.previewId] ?? null : null;
  const projectThreads = useMemo(() => chatThreads.filter((thread) => thread.projectId === activeProjectId), [activeProjectId, chatThreads]);
  const workspaceGraphProjectName = activeProject && projectThreads.some((thread) => thread.source === 'live') ? activeProject.name : null;
  const workspaceSessionIds = useMemo(() => projectThreads
    .filter((thread) => thread.source === 'live' && thread.sessionId)
    .map((thread) => thread.sessionId!), [projectThreads]);
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
    routingData: RunRoutingDecision[] | null;
  }

  // Live Backend State
  const [catalog, setCatalog] = useState<ModelCatalog>({ providers: [] });
  const [effectiveRouting, setEffectiveRouting] = useState<EffectiveRouting | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [threadRoutingOverrides, setThreadRoutingOverrides] = useState<Record<string, { model: string | null; reasoning: ReasoningEffort | null }>>({});

  const openRoutingStudio = () => {
    setRoutingOpen(false);
    setRoutingStudioLoaded(true);
    setRoutingStudioOpen(true);
  };
  const [threadLiveStates, setThreadLiveStates] = useState<Record<string, ThreadLiveState>>({});
  /**
   * approvalOrigins — typed binding: approval.id → originatingThreadId.
   * Replaces the `_originatingThreadId as any` hack on the DTO.
   */
  const [approvalOrigins, setApprovalOrigins] = useState<Record<string, string>>({});

  /** Convenience accessor — live state for the currently active thread only */
  const activeThreadLive: ThreadLiveState = activeThreadId
    ? (threadLiveStates[activeThreadId] ?? { runId: null, runStatus: null, approval: null, runDetail: null, researchData: null, routingData: null })
    : { runId: null, runStatus: null, approval: null, runDetail: null, researchData: null, routingData: null };
  const activeThread = chatThreads.find((thread) => thread.id === activeThreadId) ?? null;
  const activeThreadOverrides = activeThreadId ? threadRoutingOverrides[activeThreadId] : undefined;
  const sessionAvailable = Boolean(activeThread?.source === 'live' && (activeThread.messages.some((message) => message.role === 'assistant') || activeThreadLive.runId));

  const setActiveModelLock = useCallback((model: string | null) => {
    if (!activeThreadId) return;
    const [providerId, modelId] = model?.split(':') ?? [];
    const reasoningSupport = catalog.providers
      .find((provider) => provider.id === providerId)
      ?.models.find((item) => item.id === modelId)?.reasoning_support;
    const clearsReasoning = reasoningSupport === 'fixed_by_model' || reasoningSupport === 'unsupported';
    setThreadRoutingOverrides((current) => ({
      ...current,
      [activeThreadId]: {
        model,
        reasoning: clearsReasoning ? null : current[activeThreadId]?.reasoning ?? null,
      },
    }));
  }, [activeThreadId, catalog.providers]);
  const setActiveReasoningOverride = useCallback((reasoning: ReasoningEffort | null) => {
    if (!activeThreadId) return;
    setThreadRoutingOverrides((current) => ({ ...current, [activeThreadId]: { model: current[activeThreadId]?.model ?? null, reasoning } }));
  }, [activeThreadId]);

  function patchThreadLive(threadId: string, patch: Partial<ThreadLiveState>) {
    setThreadLiveStates((prev) => ({
      ...prev,
      [threadId]: { ...{ runId: null, runStatus: null, approval: null, runDetail: null, researchData: null, routingData: null }, ...(prev[threadId] ?? {}), ...patch },
    }));
  }

  useEffect(() => {
    api.fetchModels().then(setCatalog).catch(() => ({ providers: [] }));
    api.fetchSessions().then(setSessions).catch(() => []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (!activeProject?.name) { setEffectiveRouting(null); return; }
    const sessionId = sessionAvailable ? activeThread?.sessionId : undefined;
    void api.fetchEffectiveRouting(activeProject.name, sessionId).then((value) => {
      if (!cancelled) setEffectiveRouting(value);
    }).catch(() => { if (!cancelled) setEffectiveRouting(null); });
    return () => { cancelled = true; };
  }, [activeProject?.name, activeThread?.id, activeThread?.sessionId, sessionAvailable]);

  useEffect(() => {
    if (activeProject?.name) {
      api.fetchMemories(activeProject.name).then(setMemories).catch(() => setMemories([]));
    }
  }, [activeProject?.name]);

  const refreshInspectorData = useCallback(async (originatingThreadId: string, runId: string) => {
    try {
      const [rDetail, rResearch, rRouting] = await Promise.all([
        api.fetchRunDetails(runId).catch(() => null),
        api.fetchRunResearch(runId).catch(() => null),
        api.fetchRunRouting(runId).catch(() => null),
      ]);
      setThreadLiveStates((prev) => ({
        ...prev,
        [originatingThreadId]: {
          ...{ runId: null, runStatus: null, approval: null, runDetail: null, researchData: null, routingData: null },
          ...(prev[originatingThreadId] ?? {}),
          ...(rDetail ? { runDetail: rDetail } : {}),
          ...(rResearch ? { researchData: rResearch } : {}),
          ...(rRouting ? { routingData: rRouting.decisions } : {}),
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
    const project = projectCatalog.find((item) => item.id === projectId);
    if (!project) return;
    setInspectorOpen(false);
    setRoutingOpen(false);
    openOrActivateTab({ id: `project-${projectId}`, title: project.name, subtitle: 'Project Overview', kind: 'project', surface: 'project-overview', projectId });
  }, [openOrActivateTab, projectCatalog]);

  const createProject = useCallback(async (input: { name: string; subtitle: string }) => {
    if (projectCatalog.some((project) => project.name.toLowerCase() === input.name.toLowerCase())) {
      throw new Error('A project with this name already exists.');
    }
    const record = await api.createWorkspaceProject({ id: crypto.randomUUID(), ...input });
    const project = projectFromRecord(record, userProjects.length);
    setUserProjects((current) => [...current.filter((item) => item.id !== project.id), project]);
    setInspectorOpen(false);
    setRoutingOpen(false);
    openOrActivateTab({ id: `project-${project.id}`, title: project.name, subtitle: 'Project Overview', kind: 'project', surface: 'project-overview', projectId: project.id });
  }, [openOrActivateTab, projectCatalog, userProjects.length]);

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
    const project = projectCatalog.find((item) => item.id === projectId);
    if (!project) return;
    openOrActivateTab({ id: `project-${projectId}`, title: project.name, subtitle: 'Board', kind: 'project', surface: 'workspace', projectId, mode: 'board' });
    setFocusNodeId(nodeId);
    const node = initialNodes.find((item) => item.id === nodeId);
    if (node) setSelectedNode(node);
  }, [activeProjectId, openOrActivateTab, projectCatalog]);

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
    const target = (workspaceGraphProjectName || activeProjectId === 'stateful') ? nodeId : projectRootNodeId();
    setFocusNodeId(target);
    const node = initialNodes.find((item) => item.id === target);
    if (node) setSelectedNode(node);
  }, [activeProject, activeProjectId, openOrActivateTab, projectRootNodeId, workspaceGraphProjectName]);

  const handleBranchFromChat = useCallback((message: ChatMessage) => {
    if (!activeProjectId || !activeProject) return;
    const sourceNodeId = workspaceGraphProjectName && message.id
      ? message.id
      : activeProjectId === 'stateful' && message.nodeId && !message.nodeId.startsWith('runtime-')
        ? message.nodeId
        : projectRootNodeId();
    openOrActivateTab({ id: `project-${activeProjectId}`, title: activeProject.name, subtitle: 'Board', kind: 'project', surface: 'workspace', projectId: activeProjectId, mode: 'board' });
    setFocusNodeId(sourceNodeId);
    setBranchRequest({ nodeId: sourceNodeId, nonce: Date.now() });
    pushToast('Branch point requested', workspaceGraphProjectName ? 'The Board will save a link from this persisted conversation turn.' : 'The Board opened at the nearest project turn.');
  }, [activeProject, activeProjectId, openOrActivateTab, projectRootNodeId, pushToast, workspaceGraphProjectName]);

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
    try {
      if (item.source === 'imported' && item.syncState === 'synced') await api.deleteWorkspaceLibraryReference(item.id);
      if (item.source === 'imported' && item.blobKey) {
        try { await deleteLocalFile(item.blobKey); } catch { /* stale local blobs do not prevent reference removal */ }
      }
      setLibraryItems((current) => current.filter((entry) => entry.id !== item.id));
      pushToast('Removed from Library', item.source === 'imported' ? 'The saved reference and this browser’s indexed copy were removed. Original connected-folder files are untouched.' : 'The bundled Library reference was removed from this browser.');
    } catch (error) {
      pushToast('Could not remove Library reference', executionErrorText(error));
    }
  }, [pushToast]);

  const importFiles = useCallback(async (files: File[], projectId?: string) => {
    if (!files.length) return;
    const imported: LibraryItem[] = [];
    for (const file of files) {
      const id = crypto.randomUUID();
      const blobKey = `local-${id}`;
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
          syncState: 'pending',
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
      let savedCount = 0;
      for (const item of imported) {
        try {
          await api.createWorkspaceLibraryReference({ id: item.id, ...workspaceLibraryPayload(item, projectCatalog) });
          savedCount += 1;
          setLibraryItems((current) => current.map((entry) => entry.id === item.id ? { ...entry, syncState: 'synced' } : entry));
        } catch (error) {
          pushToast('File stays on this browser', `${item.name} could not sync its reference: ${executionErrorText(error)}`);
        }
      }
      pushToast(`${imported.length} file${imported.length === 1 ? '' : 's'} added`, `${savedCount} reference${savedCount === 1 ? '' : 's'} saved to the workspace graph; file contents remain in this browser.`);
    }
  }, [projectCatalog, pushToast]);

  const toggleProjectLink = useCallback(async (itemId: string, projectId: string) => {
    const item = libraryItems.find((entry) => entry.id === itemId);
    if (!item) return;
    const links = item.projectLinks ?? [];
    const next = { ...item, projectLinks: links.includes(projectId) ? links.filter((id) => id !== projectId) : [...links, projectId], updated: 'just now' };
    if (item.source === 'imported' && item.syncState === 'synced') {
      try {
        const saved = await api.updateWorkspaceLibraryReference(item.id, workspaceLibraryPayload(next, projectCatalog));
        setLibraryItems((current) => current.map((entry) => entry.id === item.id ? { ...workspaceLibraryFromRecord(saved, projectCatalog), blobKey: item.blobKey } : entry));
      } catch (error) {
        pushToast('Project link was not saved', executionErrorText(error));
      }
      return;
    }
    setLibraryItems((current) => current.map((entry) => entry.id === item.id ? next : entry));
  }, [libraryItems, projectCatalog, pushToast]);

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
        const hydratedMessages = detail.messages.map((message) => {
          const manifest = message.context_manifest;
          return {
            ...message,
            branch: message.branch ?? 'Root',
            provenance: contextProvenanceFromManifest(manifest),
            contextTokens: compiledContextTokenCountFromManifest(manifest),
            contextObjectIds: manifest?.objects?.filter((item) => item.selected_by_user).map((item) => item.object_id),
            ...routingSummaryFromProvenance(message.routing_provenance),
          };
        });
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

          for (const bm of hydratedMessages) {
            const key: OccKey = `${bm.role}::${bm.content}`;
            const n = (occurrenceCounter.get(key) ?? 0) + 1;
            occurrenceCounter.set(key, n);

            const localMatch = localByOccurrence.get(`${key}::${n}`);
            if (localMatch) {
              // Adopt the backend canonical ID on the existing local message
              const existing = merged[localMatch._localIdx];
              merged[localMatch._localIdx] = {
                ...existing,
                id: bm.id ?? existing.id,
                provenance: existing.provenance?.length ? existing.provenance : bm.provenance,
                contextTokens: existing.contextTokens ?? bm.contextTokens,
                contextObjectIds: existing.contextObjectIds?.length ? existing.contextObjectIds : bm.contextObjectIds,
                routeLabel: existing.routeLabel ?? bm.routeLabel,
                reasoningLabel: existing.reasoningLabel ?? bm.reasoningLabel,
              };
            } else {
              // Genuinely new message from backend — append
              merged.push(bm);
              appended = true;
            }
          }

          // Only update thread if something actually changed
          const idChanged = hydratedMessages.some((bm, i) => bm.id && t.messages[i]?.id !== bm.id);
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
    async (text: string, contextObjectIds: string[] = [], taskType?: 'research' | 'coding' | 'writing') => {
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
        contextObjectIds: contextObjectIds.length > 0 ? [...new Set(contextObjectIds)] : undefined,
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
          activeThreadOverrides?.model,
          activeThreadOverrides?.reasoning,
          contextObjectIds,
          taskType,
        );

        if (resp.user_message_id) {
          updateThreadMessages(originatingThreadId, (prev) => prev.map((message) =>
            message.id === userMsg.id ? { ...message, id: resp.user_message_id } : message,
          ));
        }

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
            let provenance = [] as ReturnType<typeof contextProvenanceFromRunEvents>;
            let contextTokens: number | undefined;
            let routingSummary = {} as ReturnType<typeof routingSummaryFromRunEvents>;
            if (resp.run_id) {
              try {
                const rDetail = await api.fetchRunDetails(resp.run_id);
                steps = mapRunEventsToExecutionSteps(rDetail.events);
                provenance = contextProvenanceFromRunEvents(rDetail.events);
                contextTokens = compiledContextTokenCount(rDetail.events);
                routingSummary = routingSummaryFromRunEvents(rDetail.events);
                patchThreadLive(originatingThreadId, { runDetail: rDetail });
              } catch (e) {
                console.warn('Failed to fetch run details for execution steps', e);
              }
            }

            const assistantMsg: ChatMessage = {
              id: resp.assistant_message_id || `live-assistant-${nonce}`,
              role: 'assistant',
              branch: 'Root',
              nodeId: `live-assistant-node-${nonce}`,
              content: resp.response,
              timestamp: 'just now',
              created_at: new Date().toISOString(),
              status: 'Completed',
              executionLabel: steps.length > 0 ? `AURA · ${steps.length} steps` : undefined,
              execution: steps.length > 0 ? steps : undefined,
              provenance,
              contextTokens,
              contextObjectIds,
              ...routingSummary,
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
        if (err instanceof ApiError && err.code === 'RoutingConfirmationRequired') {
          setRoutingConfirmation({ provider: err.details?.proposed_provider, model: err.details?.proposed_model });
        }
        const errorMsg: ChatMessage = {
          id: `live-err-${nonce}`,
          role: 'assistant',
          branch: 'Root',
          nodeId: `live-err-node-${nonce}`,
          content: `Error: ${executionErrorText(err)}`,
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
      activeThreadOverrides,
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
    async (text: string, contextObjectIds: string[] = [], taskType?: 'research' | 'coding' | 'writing') => {
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
        initialContextObjectIds: contextObjectIds.length > 0 ? [...new Set(contextObjectIds)] : undefined,
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
        const userMsg: ChatMessage = { id: `live-user-${nonce}`, role: 'user', branch: 'Root', nodeId: `live-user-node-${nonce}`, content: promptText, contextObjectIds: contextObjectIds.length > 0 ? [...new Set(contextObjectIds)] : undefined, timestamp: 'just now', created_at: new Date().toISOString(), status: 'Sent' };
        updateThreadMessages(originatingThreadId, (prev) => [...prev, userMsg]);
        patchThreadLive(originatingThreadId, { runStatus: 'running' });
        try {
          // A new live thread starts with profile routing; thread-local temporary
          // overrides from the previous conversation are deliberately not copied.
          const resp = await api.sendChat(sessionId, promptText, activeProject.name, null, null, contextObjectIds, taskType);
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
              let provenance = [] as ReturnType<typeof contextProvenanceFromRunEvents>;
              let contextTokens: number | undefined;
              let routingSummary = {} as ReturnType<typeof routingSummaryFromRunEvents>;
              if (resp.run_id) {
                try {
                  const rDetail = await api.fetchRunDetails(resp.run_id);
                  steps = mapRunEventsToExecutionSteps(rDetail.events);
                  provenance = contextProvenanceFromRunEvents(rDetail.events);
                  contextTokens = compiledContextTokenCount(rDetail.events);
                  routingSummary = routingSummaryFromRunEvents(rDetail.events);
                  patchThreadLive(originatingThreadId, { runDetail: rDetail });
                } catch {}
              }
              const assistantMsg: ChatMessage = { id: resp.assistant_message_id || `live-assistant-${nonce}`, role: 'assistant', branch: 'Root', nodeId: `live-assistant-node-${nonce}`, content: resp.response, timestamp: 'just now', created_at: new Date().toISOString(), status: 'Completed', executionLabel: steps.length > 0 ? `AURA · ${steps.length} steps` : undefined, execution: steps.length > 0 ? steps : undefined, provenance, contextTokens, contextObjectIds, ...routingSummary };
              updateThreadMessages(originatingThreadId, (prev) => [...prev, assistantMsg]);
            }
          }
          if (resp.run_id) void refreshInspectorData(originatingThreadId, resp.run_id);
        } catch (err: any) {
          patchThreadLive(originatingThreadId, { runStatus: 'failed' });
          if (err instanceof ApiError && err.code === 'RoutingConfirmationRequired') {
            setRoutingConfirmation({ provider: err.details?.proposed_provider, model: err.details?.proposed_model });
          }
          updateThreadMessages(originatingThreadId, (prev) => [...prev, { id: `live-err-${nonce}`, role: 'assistant', branch: 'Root', nodeId: `live-err-node-${nonce}`, content: `Error: ${executionErrorText(err)}`, timestamp: 'just now', status: 'Failed' }]);
        }
      })();
      void count; // suppress lint — count used for UI naming above
    },
    [activeProject, activeProjectId, chatThreads, openOrActivateTab, pushToast, refreshInspectorData, updateThreadMessages]
  );

  const handleBoardAskWithContext = useCallback(async (prompt: string, objectIds: string[]) => {
    const currentThread = chatThreads.find((thread) => thread.id === activeThreadId);
    openOrActivateTab({
      id: `project-${activeProjectId}`,
      title: activeProject?.name ?? 'Project',
      subtitle: 'Chat',
      kind: 'project',
      surface: 'workspace',
      projectId: activeProjectId,
      mode: 'chat',
    });
    if (currentThread?.source === 'demo' || !currentThread?.sessionId) {
      await handleStartLiveChat(prompt, objectIds);
      return;
    }
    await handleSendMessage(prompt, objectIds);
  }, [activeProject?.name, activeProjectId, activeThreadId, chatThreads, handleSendMessage, handleStartLiveChat, openOrActivateTab]);

  const handleContextObjectIdsChange = useCallback((threadId: string, objectIds: string[]) => {
    setChatThreads((current) => current.map((thread) => thread.id === threadId
      ? { ...thread, initialContextObjectIds: [...new Set(objectIds)] }
      : thread));
  }, []);

  useEffect(() => {
    let active = true;
    void api.fetchWorkspaceProjects().then((records) => {
      if (!active || !Array.isArray(records)) return;
      setUserProjects(records.map(projectFromRecord));
    }).catch((error: unknown) => {
      if (active) pushToast('Could not load projects', executionErrorText(error));
    });
    return () => { active = false; };
  }, [pushToast]);

  useEffect(() => {
    if (surface !== 'library' || libraryLoaded.current) return;
    let active = true;
    void api.fetchWorkspaceLibrary().then((records) => {
      if (!active || !Array.isArray(records)) return;
      setLibraryItems((current) => {
        const currentById = new Map(current.map((item) => [item.id, item]));
        const remoteItems = records.map((record) => {
          const remote = workspaceLibraryFromRecord(record, projectCatalog);
          const local = currentById.get(remote.id);
          return local ? { ...remote, blobKey: local.blobKey ?? remote.blobKey } : remote;
        });
        const remoteIds = new Set(remoteItems.map((item) => item.id));
        return [...remoteItems, ...current.filter((item) => item.source !== 'imported' || !remoteIds.has(item.id))];
      });
      libraryLoaded.current = true;
    }).catch((error: unknown) => {
      if (active) pushToast('Could not load Library references', executionErrorText(error));
    });
    return () => { active = false; };
  }, [projectCatalog, pushToast, surface]);

  const replaceWorkspaceNote = useCallback((previousId: string, nextNote: WorkspaceNote) => {
    const next = notesRef.current.map((item) => item.id === previousId ? nextNote : item);
    notesRef.current = next;
    setNotes(next);
  }, []);

  const queueWorkspaceNoteUpdate = useCallback((note: WorkspaceNote) => {
    if (note.source !== 'live') return;
    const previousTimer = noteSyncTimers.current.get(note.id);
    if (previousTimer !== undefined) window.clearTimeout(previousTimer);
    const timer = window.setTimeout(() => {
      noteSyncTimers.current.delete(note.id);
      const latest = notesRef.current.find((item) => item.id === note.id);
      if (!latest || latest.source !== 'live') return;
      if (workspaceNoteFingerprint(latest) === savedNoteFingerprints.current.get(latest.id)) return;
      if (noteUpdateInFlight.current.has(latest.id)) {
        queueWorkspaceNoteUpdate(latest);
        return;
      }
      noteUpdateInFlight.current.add(latest.id);
      const sentFingerprint = workspaceNoteFingerprint(latest);
      void api.updateWorkspaceNote(latest.id, workspaceNotePayload(latest, projectCatalog)).then((record) => {
        const saved = workspaceNoteFromRecord(record, projectCatalog);
        savedNoteFingerprints.current.set(saved.id, workspaceNoteFingerprint(saved));
        const current = notesRef.current.find((item) => item.id === saved.id);
        if (!current) return;
        const refreshed = { ...current, updated: saved.updated, source: 'live' as const };
        replaceWorkspaceNote(current.id, refreshed);
        if (workspaceNoteFingerprint(current) !== sentFingerprint) queueWorkspaceNoteUpdate(refreshed);
      }).catch((error: unknown) => {
        pushToast('Note was not saved', executionErrorText(error));
      }).finally(() => {
        noteUpdateInFlight.current.delete(latest.id);
      });
    }, 500);
    noteSyncTimers.current.set(note.id, timer);
  }, [projectCatalog, pushToast, replaceWorkspaceNote]);

  const persistLocalWorkspaceNote = useCallback((note: WorkspaceNote) => {
    if (note.source !== 'local' || noteCreateInFlight.current.has(note.id)) return;
    noteCreateInFlight.current.add(note.id);
    const submittedFingerprint = workspaceNoteFingerprint(note);
    void api.createWorkspaceNote(workspaceNotePayload(note, projectCatalog)).then((record) => {
      const saved = workspaceNoteFromRecord(record, projectCatalog);
      savedNoteFingerprints.current.set(saved.id, workspaceNoteFingerprint(saved));
      const latest = notesRef.current.find((item) => item.id === note.id);
      if (!latest) return;
      const liveNote: WorkspaceNote = {
        ...saved,
        title: latest.title,
        body: latest.body,
        tags: latest.tags,
        projectIds: latest.projectIds,
        pinned: latest.pinned,
        source: 'live',
      };
      replaceWorkspaceNote(note.id, liveNote);
      if (workspaceNoteFingerprint(latest) !== submittedFingerprint) queueWorkspaceNoteUpdate(liveNote);
    }).catch((error: unknown) => {
      pushToast('Note is still local', `AURA could not sync it to the workspace: ${executionErrorText(error)}`);
    }).finally(() => {
      noteCreateInFlight.current.delete(note.id);
    });
  }, [projectCatalog, pushToast, queueWorkspaceNoteUpdate, replaceWorkspaceNote]);

  const handleWorkspaceNotesChange = useCallback((next: WorkspaceNote[]) => {
    notesRef.current = next;
    setNotes(next);
    for (const note of next) {
      if (note.source === 'local') persistLocalWorkspaceNote(note);
      else if (note.source === 'live') queueWorkspaceNoteUpdate(note);
    }
  }, [persistLocalWorkspaceNote, queueWorkspaceNoteUpdate]);

  useEffect(() => {
    if (surface !== 'notes' || notesLoaded.current) return;
    let active = true;
    void api.fetchWorkspaceNotes().then((records) => {
      if (!active || !Array.isArray(records)) return;
      const liveNotes = records.map((record) => workspaceNoteFromRecord(record, projectCatalog));
      savedNoteFingerprints.current = new Map(liveNotes.map((note) => [note.id, workspaceNoteFingerprint(note)]));
      const localNotes = notesRef.current.filter((note) => note.source !== 'live');
      const next = [...liveNotes, ...localNotes];
      notesRef.current = next;
      setNotes(next);
      notesLoaded.current = true;
      localNotes.filter((note) => note.source === 'local').forEach(persistLocalWorkspaceNote);
    }).catch((error: unknown) => {
      if (!active) return;
      pushToast('Could not load saved Notes', executionErrorText(error));
    });
    return () => { active = false; };
  }, [persistLocalWorkspaceNote, projectCatalog, pushToast, surface]);

  useEffect(() => {
    if (surface !== 'study' || studySessionsLoaded.current) return;
    let active = true;
    void api.fetchStudySessions().then((sessions) => {
      if (!active) return;
      setStudySessions(sessions);
      studySessionsLoaded.current = true;
    }).catch((error: unknown) => {
      if (active) pushToast('Could not load Study sessions', executionErrorText(error));
    });
    return () => { active = false; };
  }, [pushToast, surface]);

  const startStudySession = useCallback(async (trackId: string) => {
    const track = studyTracks.find((item) => item.id === trackId);
    if (!track) return;
    try {
      const session = await api.startStudySession(track.id, track.title);
      setStudySessions((current) => [session, ...current]);
      pushToast('Study session started', `${track.title} · this session is saved in your workspace.`);
    } catch (error) {
      pushToast('Study session was not started', executionErrorText(error));
    }
  }, [pushToast]);

  const completeStudySession = useCallback(async (sessionId: string) => {
    try {
      const session = await api.completeStudySession(sessionId);
      setStudySessions((current) => current.map((item) => item.id === session.id ? session : item));
      pushToast('Study session completed', `${session.track_title} · saved to your workspace.`);
    } catch (error) {
      pushToast('Study session was not updated', executionErrorText(error));
    }
  }, [pushToast]);

  useEffect(() => () => {
    noteSyncTimers.current.forEach((timer) => window.clearTimeout(timer));
    noteSyncTimers.current.clear();
  }, []);

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
            let provenance = [] as ReturnType<typeof contextProvenanceFromRunEvents>;
            let contextTokens: number | undefined;
            let routingSummary = {} as ReturnType<typeof routingSummaryFromRunEvents>;
            if (decisionResp.run_id) {
              try {
                const rDetail = await api.fetchRunDetails(decisionResp.run_id);
                patchThreadLive(originatingThreadId, { runDetail: rDetail });
                steps = mapRunEventsToExecutionSteps(rDetail.events);
                provenance = contextProvenanceFromRunEvents(rDetail.events);
                contextTokens = compiledContextTokenCount(rDetail.events);
                routingSummary = routingSummaryFromRunEvents(rDetail.events);
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
              provenance,
              contextTokens,
              ...routingSummary,
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
    const matchingProject = projectCatalog.find((project) => project.name.toLowerCase().includes(normalized) || normalized.includes(project.name.toLowerCase()));
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
        projects={projectCatalog}
        collapsed={sidebarCollapsed}
        active={activeNav}
        activeProjectId={activeProjectId}
        libraryCount={libraryItems.length}
        onCollapsedChange={setSidebarCollapsed}
        onNavigate={handleSidebarNavigate}
        onProjectOpen={openProject}
        onNewProject={() => { handleSidebarNavigate('projects'); setProjectCreateRequest((current) => current + 1); }}
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
        effectiveRouting={effectiveRouting}
        catalog={catalog}
        sessionAvailable={sessionAvailable}
        demoThread={activeThread?.source === 'demo'}
        lockedModel={activeThreadOverrides?.model ?? null}
        reasoningOverride={activeThreadOverrides?.reasoning ?? null}
        onSetModelLock={setActiveModelLock}
        onSetReasoningOverride={setActiveReasoningOverride}
        onOpenRoutingStudio={openRoutingStudio}
        inspectorOpen={inspectorOpen}
        onToggleInspector={() => setInspectorOpen((value) => !value)}
        onOpenAura={() => setAuraOpen(true)}
      />
      {routingStudioLoaded ? <Suspense fallback={null}>
        <RoutingStudio
          open={routingStudioOpen}
          projectName={activeProject?.name ?? ''}
          sessionId={activeThread?.sessionId}
          sessionAvailable={sessionAvailable}
          demoThread={activeThread?.source === 'demo'}
          effective={effectiveRouting}
          catalog={catalog}
          onClose={() => setRoutingStudioOpen(false)}
          onSaved={() => {
            if (activeProject?.name) void api.fetchEffectiveRouting(activeProject.name, sessionAvailable ? activeThread?.sessionId : undefined).then(setEffectiveRouting).catch(() => {});
          }}
          onSetModelLock={setActiveModelLock}
          onRefreshModels={async () => { try { setCatalog(await api.refreshModels()); } catch (error) { pushToast('Model discovery failed', executionErrorText(error)); } }}
        />
      </Suspense> : null}
      {routingConfirmation ? <RoutingConfirmationNotice
        proposal={routingConfirmation}
        onCancel={() => setRoutingConfirmation(null)}
        onOpenStudio={() => { setRoutingConfirmation(null); openRoutingStudio(); }}
        onChangeRouting={() => { setRoutingConfirmation(null); setActiveModelLock(null); openRoutingStudio(); }}
      /> : null}

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
        <Suspense fallback={<div className="workspace-loading" role="status">Loading workspace…</div>}>
        {surface === 'global-home' ? (
          <GlobalHome
            projects={projectCatalog}
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
            projects={projectCatalog}
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
        {surface === 'notes' ? <NotesView projects={projectCatalog} notes={notes} onNotesChange={handleWorkspaceNotesChange} onOpenProject={openProject} /> : null}
        {surface === 'study' ? <StudyView libraryItems={libraryItems} sessions={studySessions} onOpenItem={(item) => void handleLibraryItem(item)} onStartSession={(trackId) => void startStudySession(trackId)} onCompleteSession={(sessionId) => void completeStudySession(sessionId)} /> : null}
        {surface === 'automations' ? <AutomationsView projects={projectCatalog} automations={automations} onAutomationsChange={setAutomations} onRunNow={runAutomation} /> : null}
        {surface === 'projects' ? <ProjectsView projects={projectCatalog} createRequest={projectCreateRequest} onOpenProject={openProject} onCreateProject={createProject} /> : null}

        {surface === 'project-overview' && activeProject ? (
          <ProjectHome
            projects={projectCatalog}
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
            onContextObjectIdsChange={handleContextObjectIdsChange}
            currentApproval={activeThreadLive.approval}
            onApprovalDecision={handleApprovalDecision}
          />
        ) : null}

        {surface === 'workspace' && mode === 'board' && activeProject ? (
          <Suspense fallback={<div className="board-canvas board-canvas--loading" role="status">Loading Board…</div>}>
            <BoardCanvas
              key={activeProject.id}
              boardKey={activeProject.id}
              seedNodes={workspaceGraphProjectName ? [] : genericBoard?.nodes}
              seedEdges={workspaceGraphProjectName ? [] : genericBoard?.edges}
              workspaceProjectName={workspaceGraphProjectName}
              workspaceSessionIds={workspaceSessionIds}
              showBranchLabels={!workspaceGraphProjectName && activeProject.id === 'stateful'}
              focusNodeId={focusNodeId}
              onNodeFocus={handleBoardNodeFocus}
              onToast={pushToast}
              branchRequest={branchRequest}
              executionExpanded={params.get('execution') === '1'}
              onAskWithContext={handleBoardAskWithContext}
              onUseWorkspaceContext={(objectId) => { void handleStartLiveChat('', [objectId]); }}
            />
          </Suspense>
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
                onContextObjectIdsChange={handleContextObjectIdsChange}
                currentApproval={activeThreadLive.approval}
                onApprovalDecision={handleApprovalDecision}
              />
            </div>
            <div className="split-workspace__board">
              <Suspense fallback={<div className="board-canvas board-canvas--loading" role="status">Loading Board…</div>}>
                <BoardCanvas key={`split-${activeProject.id}`} compact boardKey={activeProject.id} seedNodes={workspaceGraphProjectName ? [] : genericBoard?.nodes} seedEdges={workspaceGraphProjectName ? [] : genericBoard?.edges} workspaceProjectName={workspaceGraphProjectName} workspaceSessionIds={workspaceSessionIds} showBranchLabels={!workspaceGraphProjectName && activeProject.id === 'stateful'} focusNodeId={focusNodeId} onNodeFocus={handleBoardNodeFocus} onToast={pushToast} branchRequest={branchRequest} executionExpanded={params.get('execution') === '1'} onAskWithContext={handleBoardAskWithContext} onUseWorkspaceContext={(objectId) => { void handleStartLiveChat('', [objectId]); }} />
              </Suspense>
            </div>
          </div>
        ) : null}
        </Suspense>
      </main>

      {inspectorOpen ? (
        <Suspense fallback={<aside className="inspector-panel inspector-panel--loading" role="status">Loading Inspector…</aside>}>
          <InspectorPanel
            selectedNode={selectedNode}
            runDetail={activeThreadLive.runDetail}
            effectiveRouting={effectiveRouting}
            routingData={activeThreadLive.routingData}
            researchData={activeThreadLive.researchData}
            memories={memories}
            onClose={() => setInspectorOpen(false)}
            onContextSelect={openBoardNode}
          />
        </Suspense>
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
