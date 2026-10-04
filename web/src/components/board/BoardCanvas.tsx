import {
  Background,
  BackgroundVariant,
  MarkerType,
  MiniMap,
  ReactFlow,
  SelectionMode,
  addEdge,
  useEdgesState,
  useNodesState,
  type ReactFlowInstance,
} from '@xyflow/react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { initialEdges, initialNodes } from '../../data/mockData';
import { useBoardHistory } from '../../hooks/useBoardHistory';
import type { AuraFlowEdge, AuraFlowNode, LayerKey, NodeDensity, RoutingPrivacy, WorkspaceContextPreview, WorkspaceExecutionTrace } from '../../types';
import { AuraNodeCard } from './AuraNodeCard';
import { BoardToolbar } from './BoardToolbar';
import { ContextLensBar } from './ContextLensBar';
import { buildMergedContinuation } from './contextActions';
import { SmartEdge } from './SmartEdge';
import { ApiError, api } from '../../services/api';
import { projectExecutionGraph } from './executionProjection';
import type { BoardSnapshot } from '../../hooks/useBoardHistory';

const nodeTypes = { aura: AuraNodeCard };
const edgeTypes = { smart: SmartEdge };
const EMPTY_SESSION_IDS: string[] = [];

function nodeCenter(node: AuraFlowNode) {
  const width = node.measured?.width ?? 296;
  const height = node.measured?.height ?? 132;
  return { x: node.position.x + width / 2, y: node.position.y + height / 2 };
}

function smartHandles(source: AuraFlowNode | undefined, target: AuraFlowNode | undefined) {
  if (!source || !target) return { sourceHandle: 'source-right', targetHandle: 'target-left' };
  const a = nodeCenter(source);
  const b = nodeCenter(target);
  const dx = b.x - a.x;
  const dy = b.y - a.y;

  if (Math.abs(dx) >= Math.abs(dy) * 0.9) {
    return dx >= 0
      ? { sourceHandle: 'source-right', targetHandle: 'target-left' }
      : { sourceHandle: 'source-left', targetHandle: 'target-right' };
  }

  return dy >= 0
    ? { sourceHandle: 'source-bottom', targetHandle: 'target-top' }
    : { sourceHandle: 'source-top', targetHandle: 'target-bottom' };
}

function mapWorkspaceGraph(graph: Awaited<ReturnType<typeof api.fetchWorkspaceGraph>>) {
  const positions = graph.layout.layout?.positions ?? {};
  const nodes: AuraFlowNode[] = graph.objects.map((object, index) => {
    const role = object.metadata_json.role;
    const researchObject = object.object_type.startsWith('research_');
    const studyCard = object.object_type === 'study_card';
    const kind = object.object_type === 'manual_note' ? 'note'
      : object.object_type === 'study_session' ? 'paper'
      : studyCard ? 'answer'
      : object.object_type === 'file_reference' ? 'file'
      : object.object_type === 'context_bridge' ? 'bridge'
        : object.object_type === 'context_set' ? 'merge'
          : object.object_type === 'research_source' || object.object_type === 'research_evidence' ? 'paper'
            : object.object_type === 'research_claim' ? 'answer'
          : object.object_type === 'conversation_branch' || role === 'user' ? 'user' : 'answer';
    const verification = String(object.metadata_json.verification_status ?? '');
    const mergeItems = Array.isArray(object.metadata_json.source_titles)
      ? object.metadata_json.source_titles.filter((item): item is string => typeof item === 'string')
      : [];
    const rawBridgeOptions = object.metadata_json.bridge_options as Record<string, unknown> | undefined;
    const rawBridgeSections = object.metadata_json.bridge_sections as Record<string, unknown> | undefined;
    return {
      id: object.id,
      type: 'aura',
      position: positions[object.id] ?? { x: 120 + (index % 3) * 390, y: 100 + Math.floor(index / 3) * 210 },
      data: {
        kind,
        eyebrow: studyCard ? 'STUDY CARD' : researchObject ? object.object_type.replace(/_/g, ' ').toUpperCase() : object.object_type === 'conversation_branch' ? 'NEW BRANCH' : object.object_type === 'study_session' ? 'STUDY SESSION' : kind === 'user' ? 'USER' : kind === 'answer' ? 'AURA' : kind === 'note' ? 'MANUAL NOTE' : kind === 'bridge' ? 'CONTEXT BRIDGE' : 'SAVED CONTEXT SET',
        title: object.title || (kind === 'user' ? 'User turn' : 'AURA response'),
        body: object.content || (kind === 'merge' ? 'Selected objects remain individually inspectable. No summary was generated.' : object.object_type === 'conversation_branch' ? 'Saved branch point. Add a user-authored prompt to start this conversation.' : object.object_type === 'study_session' ? 'Learning session linked to verified research.' : ''),
        summary: object.content ? object.content.slice(0, 160) : object.object_type === 'study_session' ? 'Learning session linked to verified research.' : undefined,
        density: graph.layout.layout?.densities?.[object.id] ?? 'compact',
        manual: object.created_by === 'user' && kind === 'note' && !studyCard,
        accent: studyCard ? 'cyan' : kind === 'note' ? 'amber' : kind === 'bridge' || kind === 'merge' ? 'cyan' : kind === 'user' ? 'slate' : researchObject && verification === 'verified' ? 'green' : researchObject ? 'cyan' : 'purple',
        layer: studyCard || kind === 'note' || kind === 'file' || kind === 'bridge' || kind === 'merge' || researchObject ? 'knowledge' : 'conversation',
        messageId: object.source_message_id ?? undefined,
        workspaceObjectType: object.object_type,
        workspaceCreatedBy: object.created_by,
        workspaceMetadata: object.metadata_json,
        sourceCount: typeof object.metadata_json.source_count === 'number' ? object.metadata_json.source_count : mergeItems.length,
        mergeItems,
        bridgeOptions: kind === 'bridge' ? {
          conclusions: typeof rawBridgeOptions?.conclusions === 'boolean' ? rawBridgeOptions.conclusions : true,
          observations: typeof rawBridgeOptions?.observations === 'boolean' ? rawBridgeOptions.observations : true,
          failed: typeof rawBridgeOptions?.failed === 'boolean' ? rawBridgeOptions.failed : false,
          artifacts: typeof rawBridgeOptions?.artifacts === 'boolean' ? rawBridgeOptions.artifacts : false,
          constraints: typeof rawBridgeOptions?.constraints === 'boolean' ? rawBridgeOptions.constraints : false,
          decisions: typeof rawBridgeOptions?.decisions === 'boolean' ? rawBridgeOptions.decisions : false,
        } : undefined,
        bridgeSections: kind === 'bridge' ? {
          conclusions: typeof rawBridgeSections?.conclusions === 'string' ? rawBridgeSections.conclusions : '',
          observations: typeof rawBridgeSections?.observations === 'string' ? rawBridgeSections.observations : '',
          failed: typeof rawBridgeSections?.failed === 'string' ? rawBridgeSections.failed : '',
          artifacts: typeof rawBridgeSections?.artifacts === 'string' ? rawBridgeSections.artifacts : '',
          constraints: typeof rawBridgeSections?.constraints === 'string' ? rawBridgeSections.constraints : '',
          decisions: typeof rawBridgeSections?.decisions === 'string' ? rawBridgeSections.decisions : '',
        } : undefined,
        bridgeNote: object.content,
      },
    } as AuraFlowNode;
  });
  const edges: AuraFlowEdge[] = graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source_object_id,
    target: edge.target_object_id,
    type: 'smoothstep',
    data: {
      edgeKind: edge.relation_type === 'reply' ? 'reply' : edge.edge_family === 'context' ? 'context' : edge.edge_family === 'execution' ? 'execution' : 'semantic',
      workspaceCreatedBy: edge.created_by,
      relationType: edge.relation_type,
      edgeFamily: edge.edge_family,
      workspaceMetadata: edge.metadata_json,
    },
  }));
  const execution = projectExecutionGraph(graph.execution_traces ?? [], nodes);
  return { nodes, edges, executionNodes: execution.nodes, executionEdges: execution.edges, executionHistoryTruncated: graph.execution_history_truncated ?? false, executionTraces: graph.execution_traces ?? [], executionNextCursor: graph.execution_next_cursor ?? null };
}

function layoutSnapshotFor(nodes: AuraFlowNode[], viewport: { x: number; y: number; zoom: number } | null) {
  return JSON.stringify({
    positions: Object.fromEntries(nodes.map((node) => [node.id, node.position])),
    densities: Object.fromEntries(nodes.map((node) => [node.id, node.data.density])),
    viewport,
  });
}

interface BoardCanvasProps {
  compact?: boolean;
  boardKey?: string;
  seedNodes?: AuraFlowNode[];
  seedEdges?: AuraFlowEdge[];
  showBranchLabels?: boolean;
  focusNodeId?: string | null;
  onNodeFocus?: (messageId: string | null, node: AuraFlowNode) => void;
  onToast?: (title: string, detail?: string) => void;
  executionExpanded?: boolean;
  branchRequest?: { nodeId: string; nonce: number } | null;
  workspaceProjectName?: string | null;
  workspaceSessionIds?: string[];
  workspaceGraphRevision?: number;
  onAskWithContext?: (prompt: string, objectIds: string[]) => void | Promise<void>;
  onUseWorkspaceContext?: (objectId: string) => void;
}

const densityOrder: NodeDensity[] = ['collapsed', 'compact', 'full'];

function isUserWorkspaceObject(node: AuraFlowNode) {
  return node.data.workspaceCreatedBy === 'user'
    && ['manual_note', 'context_bridge', 'context_set', 'conversation_branch'].includes(node.data.workspaceObjectType ?? '');
}

function workspaceObjectWrite(node: AuraFlowNode) {
  const bridge = node.data.workspaceObjectType === 'context_bridge';
  const metadata = {
    ...(node.data.workspaceMetadata ?? {}),
    ...(bridge ? {
      bridge_options: node.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false, constraints: false, decisions: false },
      bridge_sections: node.data.bridgeSections ?? { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
    } : {}),
  };
  return {
    title: node.data.title,
    content: bridge ? (node.data.bridgeNote ?? node.data.body) : node.data.body,
    metadata_json: metadata,
  };
}

export function BoardCanvas({ compact = false, boardKey = 'stateful', seedNodes, seedEdges, showBranchLabels = true, focusNodeId, onNodeFocus, onToast, executionExpanded, branchRequest, workspaceProjectName = null, workspaceSessionIds = EMPTY_SESSION_IDS, workspaceGraphRevision = 0, onAskWithContext, onUseWorkspaceContext }: BoardCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<AuraFlowNode>(seedNodes ?? initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AuraFlowEdge>(seedEdges ?? initialEdges);
  const [executionNodes, setExecutionNodes] = useState<AuraFlowNode[]>([]);
  const [executionEdges, setExecutionEdges] = useState<AuraFlowEdge[]>([]);
  const [executionHistoryTruncated, setExecutionHistoryTruncated] = useState(false);
  const [executionTraces, setExecutionTraces] = useState<WorkspaceExecutionTrace[]>([]);
  const executionTracesRef = useRef(executionTraces);
  const [executionNextCursor, setExecutionNextCursor] = useState<string | null>(null);
  const hasLoadedOlderExecutionPage = useRef(false);
  const [loadingOlderExecution, setLoadingOlderExecution] = useState(false);
  const [graphObjectCursor, setGraphObjectCursor] = useState<string | null>(null);
  const [graphEdgeCursor, setGraphEdgeCursor] = useState<string | null>(null);
  const [loadingOlderGraph, setLoadingOlderGraph] = useState(false);
  const [activeTool, setActiveTool] = useState<'select' | 'note' | 'link'>('select');
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    conversation: true,
    knowledge: true,
    execution: executionExpanded ?? false,
  });
  const [linkSource, setLinkSource] = useState<string | null>(null);
  const [viewport, setViewport] = useState<{ x: number; y: number; zoom: number } | null>(null);
  const [flowReady, setFlowReady] = useState(false);
  const [canvasSizeReady, setCanvasSizeReady] = useState(false);
  const [contextPreview, setContextPreview] = useState<WorkspaceContextPreview | null>(null);
  const [contextPreviewLoading, setContextPreviewLoading] = useState(false);
  const [contextPreviewError, setContextPreviewError] = useState<string | null>(null);
  const instanceRef = useRef<ReactFlowInstance<AuraFlowNode, AuraFlowEdge> | null>(null);
  const pendingInitialFit = useRef<ReactFlowInstance<AuraFlowNode, AuraFlowEdge> | null>(null);
  const focusNodeIdRef = useRef(focusNodeId);
  const initialFitTimer = useRef<number | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const idRef = useRef(100);
  const processedBranchNonce = useRef<number | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const workspaceReady = useRef(false);
  const workspaceSessionAttachments = useRef(new Map<string, Promise<void>>());
  const workspaceGraphRevisionRef = useRef(workspaceGraphRevision);
  const lastRefreshedGraphRevision = useRef(workspaceGraphRevision);
  const workspaceSessionKeyRef = useRef('');
  const [workspaceLoadVersion, setWorkspaceLoadVersion] = useState(0);
  const layoutRevision = useRef(0);
  const layoutSnapshot = useRef('');
  const layoutTimer = useRef<number | null>(null);
  const layoutConflict = useRef(false);
  const layoutSync = useRef<Promise<void>>(Promise.resolve());
  const layoutWritesPending = useRef(0);
  const viewportRef = useRef(viewport);
  const noteSaveTimers = useRef<Map<string, number>>(new Map());
  const bridgeSectionSaveTimers = useRef<Map<string, number>>(new Map());
  const historySync = useRef<Promise<void>>(Promise.resolve());
  nodesRef.current = nodes;
  edgesRef.current = edges;
  viewportRef.current = viewport;
  focusNodeIdRef.current = focusNodeId;
  executionTracesRef.current = executionTraces;
  workspaceGraphRevisionRef.current = workspaceGraphRevision;

  const workspaceSessionKey = useMemo(() => [...new Set(workspaceSessionIds)].sort().join('\u0000'), [workspaceSessionIds]);
  workspaceSessionKeyRef.current = workspaceSessionKey;

  const toast = useCallback((title: string, detail?: string) => onToast?.(title, detail), [onToast]);

  const saveWorkspaceLayout = useCallback((layout: Record<string, any>, snapshot: string) => {
    if (!workspaceProjectName) return Promise.resolve();
    layoutWritesPending.current += 1;
    const save = layoutSync.current.catch(() => undefined).then(async () => {
      try {
        const result = await api.putWorkspaceLayout(workspaceProjectName, layout, layoutRevision.current);
        layoutRevision.current = result.revision;
        layoutSnapshot.current = snapshot;
      } finally {
        layoutWritesPending.current -= 1;
      }
    });
    layoutSync.current = save;
    return save;
  }, [workspaceProjectName]);

  const attachWorkspaceSessions = useCallback((projectName: string, sessionIds: string[]) => {
    let scheduledNewAttachment = false;
    const attachments = sessionIds.map((sessionId) => {
      const key = `${projectName}\u0000${sessionId}`;
      const existing = workspaceSessionAttachments.current.get(key);
      if (existing) return existing;
      scheduledNewAttachment = true;
      const attachment = api.attachWorkspaceSession(projectName, sessionId).then(() => undefined).catch((error) => {
        workspaceSessionAttachments.current.delete(key);
        if (error instanceof ApiError && error.status === 404) return;
        throw error;
      });
      workspaceSessionAttachments.current.set(key, attachment);
      return attachment;
    });
    return Promise.all(attachments).then(() => scheduledNewAttachment);
  }, []);

  const fitInitialViewWhenReady = useCallback(() => {
    const bounds = canvasRef.current?.getBoundingClientRect();
    const hasSize = Boolean(bounds && bounds.width > 0 && bounds.height > 0);
    setCanvasSizeReady(hasSize);
    if (!hasSize) return;
    const instance = pendingInitialFit.current;
    if (!instance) return;
    if (workspaceProjectName && viewportRef.current) {
      pendingInitialFit.current = null;
      return;
    }
    pendingInitialFit.current = null;
    void instance.fitView({ padding: compact ? 0.2 : 0.12, duration: 300 });
  }, [compact, workspaceProjectName]);

  useEffect(() => {
    const element = canvasRef.current;
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(fitInitialViewWhenReady);
    observer.observe(element);
    fitInitialViewWhenReady();
    return () => observer.disconnect();
  }, [fitInitialViewWhenReady]);

  const refreshRecentWorkspacePage = useCallback(async (fitView = true) => {
    if (!workspaceProjectName) return;
    const graph = await api.fetchWorkspaceGraphPage(workspaceProjectName);
    if (graph.layout.revision !== layoutRevision.current && layoutWritesPending.current === 0) {
      layoutConflict.current = true;
      toast('Board layout changed elsewhere', 'Reload the project Board before saving more layout changes.');
    }
    const projected = mapWorkspaceGraph(graph);
    const savedPositions = graph.layout.layout?.positions ?? {};
    const maxLoadedY = Math.max(0, ...nodesRef.current.map((node) => node.position.y + 190));
    const nodesById = new Map(nodesRef.current.map((node) => [node.id, node]));
    projected.nodes.forEach((node, index) => {
      if (nodesById.has(node.id)) return;
      nodesById.set(node.id, savedPositions[node.id] ? { ...node, selected: false } : {
        ...node,
        selected: false,
        position: { x: 120 + (index % 3) * 390, y: maxLoadedY + 100 + Math.floor(index / 3) * 210 },
      });
    });
    const mergedNodes = [...nodesById.values()];
    nodesRef.current = mergedNodes;
    setNodes(mergedNodes);
    const edgesById = new Map(edgesRef.current.map((edge) => [edge.id, edge]));
    for (const edge of projected.edges) if (!edgesById.has(edge.id)) edgesById.set(edge.id, edge);
    const mergedEdges = [...edgesById.values()];
    edgesRef.current = mergedEdges;
    setEdges(mergedEdges);
    const tracesByRun = new Map(executionTracesRef.current.map((trace) => [trace.run_id, trace]));
    for (const trace of projected.executionTraces) {
      const existing = tracesByRun.get(trace.run_id);
      const eventsById = new Map((existing?.events ?? []).map((event) => [event.id, event]));
      for (const event of trace.events) eventsById.set(event.id, event);
      tracesByRun.set(trace.run_id, { ...existing, ...trace, events: [...eventsById.values()] });
    }
    const mergedTraces = [...tracesByRun.values()];
    executionTracesRef.current = mergedTraces;
    setExecutionTraces(mergedTraces);
    const execution = projectExecutionGraph(mergedTraces, mergedNodes);
    setExecutionNodes(execution.nodes);
    setExecutionEdges(execution.edges);
    setExecutionHistoryTruncated((current) => current || projected.executionHistoryTruncated);
    if (!hasLoadedOlderExecutionPage.current) {
      setExecutionNextCursor((current) => current ?? projected.executionNextCursor);
    }
    if (fitView) requestAnimationFrame(() => instanceRef.current?.fitView({ padding: compact ? 0.2 : 0.12, duration: 350 }));
  }, [compact, setEdges, setNodes, toast, workspaceProjectName]);

  useEffect(() => {
    if (!workspaceProjectName || !workspaceReady.current || lastRefreshedGraphRevision.current === workspaceGraphRevision) return;
    lastRefreshedGraphRevision.current = workspaceGraphRevision;
    void refreshRecentWorkspacePage(false).catch(() => {
      toast('Could not refresh saved Board', 'The latest chat turn could not be added to the project graph.');
    });
  }, [refreshRecentWorkspacePage, toast, workspaceGraphRevision, workspaceLoadVersion, workspaceProjectName]);

  const persistHistoryChange = useCallback((current: BoardSnapshot, target: BoardSnapshot) => {
    if (!workspaceProjectName || !workspaceReady.current) return;
    historySync.current = historySync.current.then(async () => {
      for (const timer of noteSaveTimers.current.values()) window.clearTimeout(timer);
      for (const timer of bridgeSectionSaveTimers.current.values()) window.clearTimeout(timer);
      noteSaveTimers.current.clear();
      bridgeSectionSaveTimers.current.clear();

      const currentObjects = new Map(current.nodes.filter(isUserWorkspaceObject).map((node) => [node.id, node]));
      const targetObjects = new Map(target.nodes.filter(isUserWorkspaceObject).map((node) => [node.id, node]));
      const deletedObjectIds = new Set([...currentObjects.keys()].filter((id) => !targetObjects.has(id)));
      const currentKeys = new Set(current.edges.map((edge) => edge.id));
      const targetKeys = new Set(target.edges.map((edge) => edge.id));

      const removedUserEdges = current.edges.filter((edge) =>
        edge.data?.workspaceCreatedBy === 'user'
        && !targetKeys.has(edge.id)
        && !deletedObjectIds.has(edge.source)
        && !deletedObjectIds.has(edge.target),
      );
      if (removedUserEdges.length > 0) {
        await api.deleteWorkspaceEdges(workspaceProjectName, removedUserEdges.map((edge) => edge.id));
      }
      for (const id of deletedObjectIds) await api.deleteWorkspaceObject(workspaceProjectName, id);

      for (const [id, node] of targetObjects) {
        const before = currentObjects.get(id);
        if (!before) {
          const sourceIds = target.edges.filter((edge) => edge.target === id && edge.data?.edgeFamily === 'context').map((edge) => edge.source);
          await api.createWorkspaceObject(workspaceProjectName, {
            id,
            object_type: node.data.workspaceObjectType as 'manual_note' | 'context_bridge' | 'context_set' | 'conversation_branch',
            ...workspaceObjectWrite(node),
            source_object_ids: sourceIds,
          });
          continue;
        }
        if (['manual_note', 'context_bridge'].includes(node.data.workspaceObjectType ?? '')
          && JSON.stringify(workspaceObjectWrite(before)) !== JSON.stringify(workspaceObjectWrite(node))) {
          await api.updateWorkspaceObject(workspaceProjectName, id, workspaceObjectWrite(node));
        }
      }

      const newObjectIds = new Set([...targetObjects.keys()].filter((id) => !currentObjects.has(id)));
      const restoredEdges = target.edges.filter((edge) => {
        if (edge.data?.workspaceCreatedBy !== 'user' || currentKeys.has(edge.id)) return false;
        const targetNode = targetObjects.get(edge.target);
        const autoCreatedContextRelation = newObjectIds.has(edge.target)
          && edge.data.edgeFamily === 'context'
          && ['context_bridge', 'context_set', 'conversation_branch'].includes(targetNode?.data.workspaceObjectType ?? '');
        return !autoCreatedContextRelation;
      });
      if (restoredEdges.length > 0) {
        await api.restoreWorkspaceEdges(workspaceProjectName, restoredEdges.map((edge) => ({
          id: edge.id,
          source_object_id: edge.source,
          target_object_id: edge.target,
          relation_type: edge.data?.relationType ?? (edge.data?.edgeKind === 'context' ? 'bridges_to' : 'related_to'),
          edge_family: edge.data?.edgeFamily ?? (edge.data?.edgeKind === 'context' ? 'context' : 'semantic'),
          metadata_json: edge.data?.workspaceMetadata ?? {},
        })));
      }

      if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
      const targetLayout = {
        positions: Object.fromEntries(target.nodes.map((node) => [node.id, node.position])),
        densities: Object.fromEntries(target.nodes.map((node) => [node.id, node.data.density])),
        viewport: viewportRef.current,
      };
      await saveWorkspaceLayout(targetLayout, JSON.stringify(targetLayout));
    }).catch(async () => {
      toast('Undo/redo could not be saved', 'The Board will reload the latest project graph before further edits.');
      try {
        const graph = await api.fetchWorkspaceGraph(workspaceProjectName);
        const projected = mapWorkspaceGraph(graph);
        setGraphObjectCursor(graph.objects_next_cursor ?? null);
        setGraphEdgeCursor(graph.edges_next_cursor ?? null);
        setExecutionHistoryTruncated(projected.executionHistoryTruncated);
        setExecutionTraces(projected.executionTraces);
        executionTracesRef.current = projected.executionTraces;
        setExecutionNextCursor(projected.executionNextCursor);
        hasLoadedOlderExecutionPage.current = false;
        layoutRevision.current = graph.layout.revision;
        nodesRef.current = projected.nodes;
        edgesRef.current = projected.edges;
        setNodes(projected.nodes);
        setEdges(projected.edges);
        setExecutionNodes(projected.executionNodes);
        setExecutionEdges(projected.executionEdges);
      } catch {
        toast('Board reload failed', 'Reopen the Board to reconcile it with the saved project graph.');
      }
    });
  }, [saveWorkspaceLayout, setEdges, setNodes, toast, workspaceProjectName]);

  const { record: recordHistory, undo, redo, canUndo, canRedo } = useBoardHistory({
    nodesRef,
    edgesRef,
    setNodes,
    setEdges,
    onHistoryChange: persistHistoryChange,
  });

  useEffect(() => {
    if (workspaceProjectName) return;
    const nextNodes = (seedNodes ?? initialNodes).map((node) => ({ ...node, data: { ...node.data }, selected: false }));
    const nextEdges = (seedEdges ?? initialEdges).map((edge) => ({ ...edge, data: edge.data ? { ...edge.data } : edge.data, selected: false }));
    setNodes(nextNodes);
    setEdges(nextEdges);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
  }, [boardKey, seedEdges, seedNodes, setEdges, setNodes, workspaceProjectName]);

  useEffect(() => {
    workspaceReady.current = false;
    layoutConflict.current = false;
    setExecutionNodes([]);
    setExecutionEdges([]);
    setExecutionHistoryTruncated(false);
    setExecutionTraces([]);
    executionTracesRef.current = [];
    setExecutionNextCursor(null);
    hasLoadedOlderExecutionPage.current = false;
    setGraphObjectCursor(null);
    setGraphEdgeCursor(null);
    if (!workspaceProjectName) return;
    const revisionAtLoadStart = workspaceGraphRevisionRef.current;
    let cancelled = false;
    const sessionIds = workspaceSessionKeyRef.current ? workspaceSessionKeyRef.current.split('\u0000') : [];
    void attachWorkspaceSessions(workspaceProjectName, sessionIds).then(() => api.fetchWorkspaceGraphPage(workspaceProjectName)).then(async (graph) => {
      if (cancelled) return;
      let loadedGraph = graph;
      const requestedFocusId = focusNodeIdRef.current;
      let objects = [...graph.objects];
      let edges = [...graph.edges];
      let objectCursor = graph.objects_next_cursor ?? null;
      let edgeCursor = graph.edges_next_cursor ?? null;
      while (requestedFocusId && objectCursor && !objects.some((object) => object.id === requestedFocusId)) {
        const page = await api.fetchWorkspaceGraphPage(workspaceProjectName, { object: objectCursor, edge: edgeCursor });
        if (cancelled) return;
        objects = [...objects, ...page.objects];
        edges = [...edges, ...page.edges];
        objectCursor = page.objects_next_cursor ?? null;
        edgeCursor = page.edges_next_cursor ?? null;
        loadedGraph = { ...loadedGraph, layout: page.layout };
      }
      loadedGraph = { ...loadedGraph, objects, edges, objects_next_cursor: objectCursor, edges_next_cursor: edgeCursor };
      const { nodes: nextNodes, edges: nextEdges, executionNodes: nextExecutionNodes, executionEdges: nextExecutionEdges, executionHistoryTruncated: nextExecutionHistoryTruncated, executionTraces: nextExecutionTraces, executionNextCursor: nextExecutionNextCursor } = mapWorkspaceGraph(loadedGraph);
      const savedViewport = loadedGraph.layout.layout?.viewport ?? null;
      let revision = loadedGraph.layout.revision;
      const persistedPositions = loadedGraph.layout.layout?.positions ?? {};
      const persistedDensities = loadedGraph.layout.layout?.densities ?? {};
      const missingLayout = nextNodes.some((node) => !persistedPositions[node.id] || !persistedDensities[node.id]);
      if (missingLayout) {
        try {
          const savedLayout = await api.putWorkspaceLayout(workspaceProjectName, {
            positions: Object.fromEntries(nextNodes.map((node) => [node.id, node.position])),
            densities: Object.fromEntries(nextNodes.map((node) => [node.id, node.data.density])),
            viewport: savedViewport,
          }, revision);
          revision = savedLayout.revision;
        } catch (error) {
          if (error instanceof ApiError && error.status === 409) layoutConflict.current = true;
          toast('Some Board positions were not saved', 'AURA could not initialize the missing positions in the saved layout.');
        }
      }
      if (cancelled) return;
      layoutRevision.current = revision;
      viewportRef.current = savedViewport;
      setViewport(savedViewport);
      layoutSnapshot.current = layoutSnapshotFor(nextNodes, savedViewport);
      setNodes(nextNodes);
      setEdges(nextEdges);
      setExecutionNodes(nextExecutionNodes);
      setExecutionEdges(nextExecutionEdges);
      setExecutionHistoryTruncated(nextExecutionHistoryTruncated);
      setExecutionTraces(nextExecutionTraces);
      executionTracesRef.current = nextExecutionTraces;
      setExecutionNextCursor(nextExecutionNextCursor);
      hasLoadedOlderExecutionPage.current = false;
      setGraphObjectCursor(loadedGraph.objects_next_cursor ?? null);
      setGraphEdgeCursor(loadedGraph.edges_next_cursor ?? null);
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      if (savedViewport) {
        requestAnimationFrame(() => instanceRef.current?.setViewport(savedViewport, { duration: 0 }));
      }
      workspaceReady.current = true;
      lastRefreshedGraphRevision.current = revisionAtLoadStart;
      setWorkspaceLoadVersion((current) => current + 1);
    }).catch(() => {
      if (!cancelled) toast('Could not load saved Board', 'The workspace graph could not be loaded from AURA.');
    });
    return () => { cancelled = true; };
  }, [attachWorkspaceSessions, workspaceProjectName, setEdges, setNodes, toast]);

  useEffect(() => {
    if (!workspaceProjectName || !workspaceSessionKey) return;
    const sessionIds = workspaceSessionKey.split('\u0000');
    void attachWorkspaceSessions(workspaceProjectName, sessionIds).then((scheduledNewAttachment) => {
      if (scheduledNewAttachment && workspaceReady.current) return refreshRecentWorkspacePage(false);
      return undefined;
    }).catch(() => {
      toast('Could not connect live chat to Board', 'The project graph could not attach this live session.');
    });
  }, [attachWorkspaceSessions, refreshRecentWorkspacePage, toast, workspaceProjectName, workspaceSessionKey]);

  const loadOlderGraphPage = useCallback(async () => {
    if (!workspaceProjectName || loadingOlderGraph || (!graphObjectCursor && !graphEdgeCursor)) return;
    setLoadingOlderGraph(true);
    try {
      const graph = await api.fetchWorkspaceGraphPage(workspaceProjectName, {
        object: graphObjectCursor,
        edge: graphEdgeCursor,
      });
      if (graph.layout.revision !== layoutRevision.current && layoutWritesPending.current === 0) {
        layoutConflict.current = true;
        toast('Board layout changed elsewhere', 'Reload the project Board before saving more layout changes.');
      }
      const projected = mapWorkspaceGraph(graph);
      const maxLoadedY = Math.max(0, ...nodesRef.current.map((node) => node.position.y + 190));
      const persistedPositions = graph.layout.layout?.positions ?? {};
      const pageNodes = projected.nodes.map((node, index) => persistedPositions[node.id] ? node : {
        ...node,
        position: {
          x: 120 + (index % 3) * 390,
          y: maxLoadedY + 100 + Math.floor(index / 3) * 210,
        },
      });
      setNodes((current) => {
        const byId = new Map(current.map((node) => [node.id, node]));
        for (const node of pageNodes) if (!byId.has(node.id)) byId.set(node.id, node);
        const next = [...byId.values()];
        nodesRef.current = next;
        return next;
      });
      setEdges((current) => {
        const byId = new Map(current.map((edge) => [edge.id, edge]));
        for (const edge of projected.edges) if (!byId.has(edge.id)) byId.set(edge.id, edge);
        const next = [...byId.values()];
        edgesRef.current = next;
        return next;
      });
      setGraphObjectCursor(graph.objects_next_cursor ?? null);
      setGraphEdgeCursor(graph.edges_next_cursor ?? null);
      requestAnimationFrame(() => instanceRef.current?.fitView({ padding: compact ? 0.2 : 0.12, duration: 350 }));
    } catch {
      toast('Older Board objects could not be loaded', 'Retry to continue browsing this project graph.');
    } finally {
      setLoadingOlderGraph(false);
    }
  }, [compact, graphEdgeCursor, graphObjectCursor, loadingOlderGraph, setEdges, setNodes, toast, workspaceProjectName]);

  useEffect(() => () => {
    if (initialFitTimer.current !== null) window.clearTimeout(initialFitTimer.current);
    if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
    noteSaveTimers.current.forEach((timer) => window.clearTimeout(timer));
    bridgeSectionSaveTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    if (!workspaceProjectName || !workspaceReady.current || layoutConflict.current) return;
    const persistentNodes = nodes.filter((node) => !node.id.startsWith('branch-') && !node.id.startsWith('note-') && !node.id.startsWith('merge-') && !node.id.startsWith('lens-answer-') && !node.id.startsWith('bridge-'));
    const layout = {
      positions: Object.fromEntries(persistentNodes.map((node) => [node.id, node.position])),
      densities: Object.fromEntries(persistentNodes.map((node) => [node.id, node.data.density])),
      viewport,
    };
    const snapshot = JSON.stringify(layout);
    if (snapshot === layoutSnapshot.current) return;
    if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
    layoutTimer.current = window.setTimeout(() => {
      void saveWorkspaceLayout(layout, snapshot).catch((error) => {
        if (error instanceof ApiError && error.status === 409) {
          layoutConflict.current = true;
          toast('Board layout changed elsewhere', 'Reload the project Board before saving more layout changes.');
        } else {
          toast('Board layout was not saved', 'Check the connection and retry after reopening the Board.');
        }
      });
    }, 450);
  }, [nodes, viewport, saveWorkspaceLayout, workspaceProjectName, toast]);

  useEffect(() => {
    if (typeof executionExpanded === 'boolean') {
      setLayers((current) => ({ ...current, execution: executionExpanded }));
    }
  }, [executionExpanded]);

  const cycleDensity = useCallback(
    (id: string) => {
      recordHistory();
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== id) return node;
          const next = densityOrder[(densityOrder.indexOf(node.data.density) + 1) % densityOrder.length];
          return { ...node, data: { ...node.data, density: next } };
        }),
      );
    },
    [recordHistory, setNodes],
  );

  const changeBody = useCallback(
    (id: string, body: string) => {
      const existingNode = nodesRef.current.find((item) => item.id === id);
      const timers = existingNode?.data.kind === 'bridge' ? bridgeSectionSaveTimers.current : noteSaveTimers.current;
      if (workspaceProjectName && (existingNode?.data.manual || existingNode?.data.kind === 'bridge') && !timers.has(id)) recordHistory();
      setNodes((current) => current.map((node) => (node.id === id ? {
        ...node,
        data: { ...node.data, body, ...(node.data.kind === 'bridge' ? { bridgeNote: body } : {}) },
      } : node)));
      if (workspaceProjectName) {
        const node = nodesRef.current.find((item) => item.id === id);
        if (node?.data.manual || node?.data.kind === 'bridge') {
          const timers = node.data.kind === 'bridge' ? bridgeSectionSaveTimers.current : noteSaveTimers.current;
          const previous = timers.get(id);
          if (previous !== undefined) window.clearTimeout(previous);
          const timer = window.setTimeout(() => {
            const latestNode = nodesRef.current.find((item) => item.id === id);
            if (!latestNode) return;
            void api.updateWorkspaceObject(workspaceProjectName, id, {
              title: latestNode.data.title,
              content: latestNode.data.kind === 'bridge' ? (latestNode.data.bridgeNote ?? body) : body,
              metadata_json: latestNode.data.kind === 'bridge' ? {
                ...(latestNode.data.workspaceMetadata ?? {}),
                bridge_options: latestNode.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false, constraints: false, decisions: false },
                bridge_sections: latestNode.data.bridgeSections ?? { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
              } : latestNode.data.workspaceMetadata ?? {},
            }).catch(() => toast(latestNode.data.kind === 'bridge' ? 'Context Bridge was not saved' : 'Manual note was not saved', 'Your text is still visible here. Reopen the Board to retry.'));
            timers.delete(id);
          }, 500);
          timers.set(id, timer);
        }
      }
    },
    [recordHistory, setNodes, toast, workspaceProjectName],
  );

  const setPrivacyPolicy = useCallback(
    (id: string, policy: RoutingPrivacy | null) => {
      const node = nodesRef.current.find((item) => item.id === id);
      if (!node || !['manual_note', 'context_bridge'].includes(node.data.workspaceObjectType ?? '')) return;
      recordHistory();
      const metadata = { ...(node.data.workspaceMetadata ?? {}) };
      if (policy) metadata.privacy_policy = policy;
      else delete metadata.privacy_policy;
      const updatedNode = { ...node, data: { ...node.data, workspaceMetadata: metadata } };
      setNodes((current) => current.map((item) => item.id === id ? updatedNode : item));
      if (workspaceProjectName) {
        void api.updateWorkspaceObject(workspaceProjectName, id, workspaceObjectWrite(updatedNode))
          .catch(() => toast('Privacy setting was not saved', 'The previous saved classification remains active.'));
      }
    },
    [recordHistory, setNodes, toast, workspaceProjectName],
  );

  const updateBridgeOption = useCallback(
    (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts' | 'constraints' | 'decisions', value: boolean) => {
      if (!bridgeSectionSaveTimers.current.has(id)) recordHistory();
      const node = nodesRef.current.find((item) => item.id === id);
      const bridgeOptions = {
        ...(node?.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false, constraints: false, decisions: false }),
        [key]: value,
      };
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== id) return node;
          return {
            ...node,
            data: { ...node.data, bridgeOptions: { ...bridgeOptions, [key]: value } },
          };
        }),
      );
      if (workspaceProjectName && node?.data.kind === 'bridge') {
        const previous = bridgeSectionSaveTimers.current.get(id);
        if (previous !== undefined) window.clearTimeout(previous);
        const timer = window.setTimeout(() => {
          const latestNode = nodesRef.current.find((item) => item.id === id);
          if (!latestNode || latestNode.data.kind !== 'bridge') return;
          void api.updateWorkspaceObject(workspaceProjectName, id, {
            title: latestNode.data.title,
            content: latestNode.data.bridgeNote ?? latestNode.data.body,
            metadata_json: {
              ...(latestNode.data.workspaceMetadata ?? {}),
              bridge_options: latestNode.data.bridgeOptions ?? bridgeOptions,
              bridge_sections: latestNode.data.bridgeSections ?? { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
            },
          }).catch(() => toast('Bridge options were not saved', 'The selection remains visible until you reload the Board.'));
          bridgeSectionSaveTimers.current.delete(id);
        }, 500);
        bridgeSectionSaveTimers.current.set(id, timer);
      }
    },
    [recordHistory, setNodes, toast, workspaceProjectName],
  );

  const updateBridgeSection = useCallback(
    (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts' | 'constraints' | 'decisions', value: string) => {
      if (!bridgeSectionSaveTimers.current.has(id)) recordHistory();
      setNodes((current) => current.map((node) => node.id === id ? {
        ...node,
        data: { ...node.data, bridgeSections: { ...(node.data.bridgeSections ?? { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' }), [key]: value } },
      } : node));
      if (workspaceProjectName) {
        const previous = bridgeSectionSaveTimers.current.get(id);
        if (previous !== undefined) window.clearTimeout(previous);
        const timer = window.setTimeout(() => {
          const node = nodesRef.current.find((item) => item.id === id);
          if (!node || node.data.kind !== 'bridge') return;
          void api.updateWorkspaceObject(workspaceProjectName, id, {
            title: node.data.title,
            content: node.data.bridgeNote ?? node.data.body,
            metadata_json: {
              ...(node.data.workspaceMetadata ?? {}),
              bridge_options: node.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false, constraints: false, decisions: false },
              bridge_sections: node.data.bridgeSections ?? { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' },
            },
          }).catch(() => toast('Context Bridge section was not saved', 'Your text is still visible here. Reopen the Board to retry.'));
          bridgeSectionSaveTimers.current.delete(id);
        }, 500);
        bridgeSectionSaveTimers.current.set(id, timer);
      }
    },
    [recordHistory, setNodes, toast, workspaceProjectName],
  );

  const addBranch = useCallback(
    (sourceId: string) => {
      const source = nodesRef.current.find((node) => node.id === sourceId || node.data.messageId === sourceId);
      if (!source) return;
      if (workspaceProjectName) {
        void api.createWorkspaceObject(workspaceProjectName, {
          object_type: 'conversation_branch',
          title: 'Continue from this point…',
          content: '',
          metadata_json: { branch_source_title: source.data.title },
          source_object_ids: [source.id],
        }).then(async () => {
          recordHistory();
          await refreshRecentWorkspacePage();
          toast('Branch point saved', 'The source turn is linked. Add a prompt before treating it as a live chat.');
        }).catch(() => toast('Branch was not saved', 'AURA could not link the selected turn in this project graph.'));
        return;
      }
      recordHistory();
      const id = `branch-${idRef.current++}`;
      const newNode: AuraFlowNode = {
        id,
        type: 'aura',
        position: { x: source.position.x + 390, y: source.position.y + 145 },
        data: {
          kind: 'user',
          branch: source.data.branch ?? 'Root',
          eyebrow: 'NEW BRANCH',
          title: 'Continue from this point…',
          body: 'Type a new branch prompt here. This is a mock conversation placeholder.',
          summary: 'New branch prompt…',
          density: 'compact',
          accent: 'slate',
          layer: 'conversation',
        },
      };
      const newEdge: AuraFlowEdge = {
        id: `edge-${idRef.current++}`,
        source: sourceId,
        target: id,
        type: 'smoothstep',
        data: { edgeKind: 'reply' },
      };
      setNodes((current) => [...current, newNode]);
      setEdges((current) => [...current, newEdge]);
      toast('Branch created', 'A user placeholder was added from the selected AURA turn.');
    },
    [recordHistory, setEdges, setNodes, toast, workspaceProjectName],
  );

  useEffect(() => {
    if (!branchRequest || processedBranchNonce.current === branchRequest.nonce) return;
    if (workspaceProjectName && !workspaceReady.current) return;
    processedBranchNonce.current = branchRequest.nonce;
    addBranch(branchRequest.nodeId);
  }, [addBranch, branchRequest, nodes, workspaceProjectName]);

  const applyBridge = useCallback(
    (id: string) => {
      recordHistory();
      toast('Context applied', 'Selected Branch A context is now mocked as available to Branch C.');
      setNodes((current) =>
        current.map((node) =>
          node.id === id ? { ...node, data: { ...node.data, eyebrow: 'CONTEXT BRIDGE · APPLIED' } } : node,
        ),
      );
    },
    [recordHistory, setNodes, toast],
  );

  const continueMerge = useCallback(
    (id: string) => {
      addBranch(id);
      toast('Merged continuation ready', 'A continuation node was created from the merged context.');
    },
    [addBranch, toast],
  );

  const actionNodes = useMemo(
    () =>
      [...nodes, ...(layers.execution ? executionNodes : [])].map((node) => ({
        ...node,
        hidden: !layers[node.data.layer],
        data: {
          ...node.data,
          onCycleDensity: cycleDensity,
          onBranch: addBranch,
          onChangeBody: changeBody,
          onSetPrivacyPolicy: setPrivacyPolicy,
          onBridgeApply: workspaceProjectName ? undefined : applyBridge,
          onBridgeOption: updateBridgeOption,
          onBridgeSection: updateBridgeSection,
          onContinueMerge: continueMerge,
          onUseWorkspaceContext: workspaceProjectName ? onUseWorkspaceContext : undefined,
        },
      })),
    [addBranch, applyBridge, changeBody, continueMerge, cycleDensity, executionNodes, layers, nodes, onUseWorkspaceContext, setPrivacyPolicy, updateBridgeOption, updateBridgeSection, workspaceProjectName],
  );

  const deleteEdges = useCallback(
    async (edgeIds: string[]) => {
      const ids = new Set(edgeIds);
      if (ids.size === 0) return;
      const selected = edgesRef.current.filter((edge) => ids.has(edge.id));
      const persisted = workspaceProjectName
        ? selected.filter((edge) => !edge.id.startsWith('edge-') && !edge.id.startsWith('semantic-'))
        : [];
      const protectedIds = new Set(
        persisted.filter((edge) => edge.data?.workspaceCreatedBy !== 'user').map((edge) => edge.id),
      );
      const deletableIds = new Set([...ids].filter((id) => !protectedIds.has(id)));
      if (deletableIds.size === 0) {
        toast('System link protected', 'AURA-owned graph links cannot be deleted.');
        return;
      }
      if (workspaceProjectName) {
        const persistedUserEdges = persisted.filter((edge) => deletableIds.has(edge.id));
        try {
          if (persistedUserEdges.length > 0) {
            await api.deleteWorkspaceEdges(workspaceProjectName, persistedUserEdges.map((edge) => edge.id));
          }
        } catch {
          toast('Link was not deleted', 'AURA could not update the saved workspace graph.');
          return;
        }
      }
      recordHistory();
      setEdges((current) => current.filter((edge) => !deletableIds.has(edge.id)));
      const protectedCount = protectedIds.size;
      if (protectedCount > 0) {
        toast(
          'User links deleted',
          `${protectedCount} AURA-owned ${protectedCount === 1 ? 'link was' : 'links were'} kept in the graph.`,
        );
      } else {
        toast(deletableIds.size === 1 ? 'Link deleted' : `${deletableIds.size} links deleted`, 'Ctrl+Z restores the removed relation.');
      }
    },
    [recordHistory, setEdges, toast, workspaceProjectName],
  );

  const styledEdges = useMemo(() => {
    const nodeMap = new Map([...nodes, ...executionNodes].map((node) => [node.id, node]));
    return [...edges, ...(layers.execution ? executionEdges : [])].map((edge) => {
      const kind = edge.data?.edgeKind ?? 'reply';
      const isContext = kind === 'context';
      const isExecution = kind === 'execution';
      const handles = smartHandles(nodeMap.get(edge.source), nodeMap.get(edge.target));
      return {
        ...edge,
        ...handles,
        type: 'smart',
        hidden: isExecution && !layers.execution,
        animated: isContext || isExecution,
        markerEnd: isContext ? { type: MarkerType.ArrowClosed, color: '#61c8db' } : undefined,
        data: {
          ...edge.data,
          edgeKind: kind,
          onDelete: isExecution || (workspaceProjectName && !edge.id.startsWith('edge-') && !edge.id.startsWith('semantic-') && edge.data?.workspaceCreatedBy !== 'user') ? undefined : (id: string) => deleteEdges([id]),
        },
      };
    });
  }, [deleteEdges, edges, executionEdges, executionNodes, layers.execution, nodes]);

  const loadOlderExecution = useCallback(async () => {
    if (!workspaceProjectName || !executionNextCursor || loadingOlderExecution) return;
    setLoadingOlderExecution(true);
    try {
      const page = await api.fetchWorkspaceExecutionHistory(workspaceProjectName, executionNextCursor);
      const byRun = new Map([...executionTraces, ...(page.execution_traces ?? [])].map((trace) => [trace.run_id, trace]));
      const combinedTraces = [...byRun.values()].sort((left, right) => {
        const leftTime = left.events[0]?.created_at ?? '';
        const rightTime = right.events[0]?.created_at ?? '';
        return leftTime.localeCompare(rightTime) || left.run_id.localeCompare(right.run_id);
      });
      const projected = projectExecutionGraph(combinedTraces, nodesRef.current);
      setExecutionTraces(combinedTraces);
      executionTracesRef.current = combinedTraces;
      setExecutionNodes(projected.nodes);
      setExecutionEdges(projected.edges);
      setExecutionNextCursor(page.execution_next_cursor ?? null);
      setExecutionHistoryTruncated((current) => current || (page.execution_history_truncated ?? false));
      hasLoadedOlderExecutionPage.current = true;
    } catch {
      toast('Older execution history could not be loaded', 'The current Board trace is still available. Try again.');
    } finally {
      setLoadingOlderExecution(false);
    }
  }, [executionNextCursor, executionTraces, loadingOlderExecution, toast, workspaceProjectName]);

  const selectedNodes = useMemo(() => nodes.filter((node) => node.selected), [nodes]);
  const previewSelectedContext = useCallback(async () => {
    if (!workspaceProjectName) return;
    setContextPreviewLoading(true);
    setContextPreviewError(null);
    setContextPreview(null);
    try {
      setContextPreview(await api.previewWorkspaceContext(workspaceProjectName, selectedNodes.map((node) => node.id)));
    } catch (error) {
      setContextPreviewError(error instanceof Error ? error.message : 'Could not preview selected context.');
    } finally {
      setContextPreviewLoading(false);
    }
  }, [selectedNodes, workspaceProjectName]);

  const selectedEdges = useMemo(() => edges.filter((edge) => edge.selected), [edges]);
  const mergeTargets = useMemo(() => nodes
    .filter((node) => workspaceProjectName
      ? node.data.workspaceObjectType === 'conversation_branch'
      : node.data.layer === 'conversation')
    .map((node) => ({ id: node.id, title: node.data.title })), [nodes, workspaceProjectName]);

  const createNoteAt = useCallback(
    async (position: { x: number; y: number }, body = 'New manual note. Double-click the density control until Full to edit inline.') => {
      let id = `note-${idRef.current++}`;
      if (workspaceProjectName) {
        try {
          const created = await api.createWorkspaceObject(workspaceProjectName, {
            object_type: 'manual_note', title: 'Untitled note', content: body,
          });
          id = created.id;
        } catch {
          toast('Manual note was not saved', 'AURA could not create this note in the project graph.');
          return null;
        }
      }
      recordHistory();
      const note: AuraFlowNode = {
        id,
        type: 'aura',
        position,
      data: {
        kind: 'note',
        eyebrow: 'MANUAL NOTE',
        title: 'Untitled note',
          body,
          summary: body,
          density: 'compact',
        manual: true,
        accent: 'amber',
        layer: 'knowledge',
        ...(workspaceProjectName ? { workspaceObjectType: 'manual_note', workspaceCreatedBy: 'user', workspaceMetadata: {} } : {}),
      },
      };
      setNodes((current) => [...current, note]);
      toast('Manual note created', 'It lives on the Knowledge layer and is explicitly marked Manual.');
      return id;
    },
    [recordHistory, toast, workspaceProjectName],
  );

  const getSelectionAnchor = useCallback(() => {
    if (selectedNodes.length === 0) return { x: 850, y: 350 };
    const x = selectedNodes.reduce((sum, node) => sum + node.position.x, 0) / selectedNodes.length;
    const y = selectedNodes.reduce((sum, node) => sum + node.position.y, 0) / selectedNodes.length;
    return { x: x + 390, y };
  }, [selectedNodes]);

  const createContextBridge = useCallback(async () => {
    if (selectedNodes.length < 2) return;
    const bridgeOptions = { conclusions: true, observations: true, failed: false, artifacts: false, constraints: false, decisions: false };
    if (workspaceProjectName) {
      try {
        await api.createWorkspaceObject(workspaceProjectName, {
          object_type: 'context_bridge',
          title: 'Context Bridge',
          content: '',
          metadata_json: { bridge_options: bridgeOptions, bridge_sections: { conclusions: '', observations: '', failed: '', artifacts: '', constraints: '', decisions: '' } },
          source_object_ids: selectedNodes.map((node) => node.id),
        });
        recordHistory();
        await refreshRecentWorkspacePage();
        toast('Context Bridge saved', 'Selected source objects are linked. The bridge does not copy their full content.');
      } catch (error) {
        toast('Context Bridge was not saved', error instanceof ApiError && error.status === 409
          ? 'This bridge would create a cycle in the context-flow graph.'
          : 'AURA could not link all selected objects in the project graph.');
      }
      return;
    }
    const anchor = getSelectionAnchor();
    const id = `bridge-${idRef.current++}`;
    recordHistory();
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), {
      id,
      type: 'aura',
      position: anchor,
      data: {
        kind: 'bridge', eyebrow: 'CONTEXT BRIDGE', title: 'Context Bridge',
        body: '', summary: 'Selected context handoff', density: 'full', accent: 'cyan',
        layer: 'knowledge', bridgeOptions,
        bridgeNote: 'User-authored handoff note goes here.',
      },
    }]);
    setEdges((current) => [...current, ...selectedNodes.map((node) => ({
      id: `edge-${idRef.current++}`, source: node.id, target: id, type: 'smoothstep' as const,
      data: { edgeKind: 'context' as const },
    }))]);
    toast('Context Bridge created', 'Selected objects are connected as sources for a future context handoff.');
  }, [getSelectionAnchor, recordHistory, refreshRecentWorkspacePage, selectedNodes, setEdges, setNodes, toast, workspaceProjectName]);

  const saveContextSet = useCallback(async () => {
    if (selectedNodes.length < 2) return;
    if (workspaceProjectName) {
      try {
        await api.createWorkspaceObject(workspaceProjectName, {
          object_type: 'context_set',
          title: 'Saved context selection',
          content: '',
          metadata_json: {
            source_count: selectedNodes.length,
            source_titles: selectedNodes.map((node) => node.data.title),
          },
          source_object_ids: selectedNodes.map((node) => node.id),
        });
        recordHistory();
        await refreshRecentWorkspacePage();
        toast('Context Set saved', 'Source objects are linked without changing their content or generating a summary.');
      } catch (error) {
        toast('Context Set was not saved', error instanceof ApiError && error.status === 409
          ? 'This selection would create a cycle in the context-flow graph.'
          : 'AURA could not link all selected objects in the project graph.');
      }
      return;
    }
    recordHistory();
    const anchor = getSelectionAnchor();
    const id = `merge-${idRef.current++}`;
    const mergeNode: AuraFlowNode = {
      id,
      type: 'aura',
      position: anchor,
      data: {
        kind: 'merge',
        eyebrow: 'SAVED CONTEXT SET',
        title: 'Saved context selection',
        body: 'Selected objects remain individually inspectable. No summary was generated.',
        summary: `${selectedNodes.length} linked sources`,
        density: 'full',
        accent: 'cyan',
        layer: 'knowledge',
        sourceCount: selectedNodes.length,
        mergeItems: selectedNodes.slice(0, 4).map((node) => node.data.title),
      },
    };
    const mergeEdges: AuraFlowEdge[] = selectedNodes.map((node) => ({
      id: `edge-${idRef.current++}`,
      source: node.id,
      target: id,
      type: 'smoothstep',
      animated: true,
      data: { edgeKind: 'context' },
    }));
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), mergeNode]);
    setEdges((current) => [...current, ...mergeEdges]);
    toast('Context Set saved', `${selectedNodes.length} selected objects are linked without changing their content.`);
  }, [getSelectionAnchor, recordHistory, refreshRecentWorkspacePage, selectedNodes, setEdges, setNodes, toast, workspaceProjectName]);

  const mergeIntoBranch = useCallback(async (targetId: string) => {
    const target = nodes.find((node) => node.id === targetId);
    if (!target || selectedNodes.length < 2) return;
    const mergeInput = buildMergedContinuation(
      { id: target.id, title: target.data.title },
      selectedNodes.map((node) => ({ id: node.id, title: node.data.title })),
    );
    const sourceIds = mergeInput.source_object_ids;
    const sourceTitles = mergeInput.metadata_json.source_titles;
    if (workspaceProjectName) {
      try {
        await api.createWorkspaceObject(workspaceProjectName, mergeInput);
        recordHistory();
        await refreshRecentWorkspacePage();
        toast('Merged continuation created', `A new branch now links ${sourceIds.length} context objects. “${target.data.title}” remains unchanged.`);
      } catch (error) {
        toast('Merge was not saved', error instanceof ApiError && error.status === 409
          ? 'This merge would create a cycle in the context-flow graph.'
          : 'AURA could not link the selected objects into a new branch.');
      }
      return;
    }
    recordHistory();
    const id = `merge-${idRef.current++}`;
    const anchor = getSelectionAnchor();
    const mergedNode: AuraFlowNode = {
      id, type: 'aura', position: anchor,
      data: {
        kind: 'merge', eyebrow: 'MERGED CONTINUATION', title: `Merged into ${target.data.title}`,
        body: 'A new continuation links the destination branch and selected context. The source branch remains unchanged.',
        summary: `${sourceIds.length} linked sources`, density: 'full', accent: 'cyan', layer: 'knowledge',
        sourceCount: sourceIds.length, mergeItems: sourceTitles,
      },
    };
    setNodes((current) => [...current.map((node) => ({ ...node, selected: false })), mergedNode]);
    setEdges((current) => [...current, ...sourceIds.map((sourceId) => ({
      id: `edge-${idRef.current++}`, source: sourceId, target: id, type: 'smoothstep' as const,
      data: { edgeKind: 'context' as const },
    }))]);
    toast('Merged continuation created', `A new node links ${sourceIds.length} context objects. “${target.data.title}” remains unchanged.`);
  }, [getSelectionAnchor, nodes, recordHistory, refreshRecentWorkspacePage, selectedNodes, setEdges, setNodes, toast, workspaceProjectName]);

  const askSelected = useCallback(
    (prompt: string) => {
      if (workspaceProjectName && onAskWithContext) {
        void onAskWithContext(prompt, selectedNodes.map((node) => node.id));
        return;
      }
      recordHistory();
      const anchor = getSelectionAnchor();
      const id = `lens-answer-${idRef.current++}`;
      const answerNode: AuraFlowNode = {
        id,
        type: 'aura',
        position: anchor,
        data: {
          kind: 'answer',
          eyebrow: 'AURA · CONTEXT LENS',
          title: prompt,
          body: 'Mock synthesis: selected research and coding evidence point toward the fixed-size state representation as the stronger novelty boundary; update dynamics alone overlap existing work.',
          summary: 'Lens synthesis across the selected context.',
          density: 'compact',
          accent: 'cyan',
          chip: `Context lens · ${selectedNodes.length} objects`,
          layer: 'conversation',
        },
      };
      const answerEdges: AuraFlowEdge[] = selectedNodes.map((node) => ({
        id: `edge-${idRef.current++}`,
        source: node.id,
        target: id,
        type: 'smoothstep',
        data: { edgeKind: 'semantic' },
      }));
      setNodes((current) => [...current, answerNode]);
      setEdges((current) => [...current, ...answerEdges]);
      toast('AURA answered from the lens', 'The generated node is mock content based on selected objects.');
    },
    [getSelectionAnchor, onAskWithContext, recordHistory, selectedNodes, setEdges, setNodes, toast, workspaceProjectName],
  );

  const autoLayout = useCallback(() => {
    recordHistory();
    const originals = new Map(initialNodes.map((node) => [node.id, node.position]));
    let extraIndex = 0;
    setNodes((current) =>
      current.map((node) => {
        const original = originals.get(node.id);
        if (original) return { ...node, position: { ...original } };
        const position = { x: 1900 + (extraIndex % 2) * 360, y: 150 + Math.floor(extraIndex / 2) * 190 };
        extraIndex += 1;
        return { ...node, position };
      }),
    );
    requestAnimationFrame(() => instanceRef.current?.fitView({ padding: 0.16, duration: 450 }));
    toast('Board re-laid out', 'Prototype layout reset to the curated branch arrangement.');
  }, [recordHistory, setNodes, toast]);

  const clearSelection = useCallback(() => {
    setNodes((current) => current.map((node) => ({ ...node, selected: false })));
    setEdges((current) => current.map((edge) => ({ ...edge, selected: false })));
  }, [setEdges, setNodes]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const editing = Boolean(target?.closest('input, textarea, [contenteditable="true"]'));
      if (editing) return;

      const modifier = event.metaKey || event.ctrlKey;
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        const changed = event.shiftKey ? redo() : undo();
        if (changed) toast(event.shiftKey ? 'Redone' : 'Undone');
        return;
      }
      if (modifier && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        if (redo()) toast('Redone');
        return;
      }
      if ((event.key === 'Delete' || event.key === 'Backspace') && selectedEdges.length > 0) {
        event.preventDefault();
        deleteEdges(selectedEdges.map((edge) => edge.id));
        return;
      }
      if (event.key === 'Escape') {
        setActiveTool('select');
        setLinkSource(null);
        clearSelection();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [clearSelection, deleteEdges, redo, selectedEdges, toast, undo]);

  useEffect(() => {
    if (!focusNodeId) return;
    const node = nodes.find((item) => item.id === focusNodeId);
    if (!node) return;
    if (flowReady && canvasSizeReady && instanceRef.current) {
      const width = node.measured?.width ?? 300;
      const height = node.measured?.height ?? 130;
      instanceRef.current.setCenter(node.position.x + width / 2, node.position.y + height / 2, {
        zoom: compact ? 0.85 : 1,
        duration: 450,
      });
    }
    if (!node.selected) {
      setNodes((current) => current.map((item) => ({ ...item, selected: item.id === focusNodeId })));
    }
  }, [canvasSizeReady, compact, focusNodeId, flowReady, nodes, setNodes]);

  return (
    <div ref={canvasRef} className={`board-canvas ${compact ? 'board-canvas--compact' : ''}`}>
      {showBranchLabels ? (
        <div className="board-branch-labels" aria-hidden="true">
          <span className="branch-label branch-label--a">A · TTT literature</span>
          <span className="branch-label branch-label--b">B · Recurrent memory</span>
          <span className="branch-label branch-label--c">C · Coding experiment</span>
        </div>
      ) : null}

      <ReactFlow<AuraFlowNode, AuraFlowEdge>
        nodes={actionNodes}
        edges={styledEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeDragStart={() => recordHistory()}
        onConnect={async (connection) => {
          recordHistory();
          if (workspaceProjectName && connection.source && connection.target) {
            try {
              const persisted = await api.createWorkspaceEdge(workspaceProjectName, {
                source_object_id: connection.source,
                target_object_id: connection.target,
                relation_type: 'related_to',
                edge_family: 'semantic',
              });
              setEdges((current) => [...current, {
                id: persisted.id,
                source: persisted.source_object_id,
                target: persisted.target_object_id,
                type: 'smoothstep',
                data: {
                  edgeKind: 'semantic',
                  workspaceCreatedBy: persisted.created_by,
                  relationType: persisted.relation_type,
                  edgeFamily: persisted.edge_family,
                  workspaceMetadata: persisted.metadata_json,
                },
              }]);
              return;
            } catch {
              toast('Link was not saved', 'Semantic links require two objects in this project graph.');
              return;
            }
          }
          setEdges((current) => addEdge({ ...connection, type: 'smart', data: { edgeKind: 'semantic' } }, current));
        }}
        onEdgeClick={(event, edge) => {
          event.stopPropagation();
          setNodes((current) => current.map((node) => ({ ...node, selected: false })));
          setEdges((current) => current.map((item) => ({ ...item, selected: item.id === edge.id })));
        }}
        onInit={(instance) => {
          instanceRef.current = instance;
          setFlowReady(true);
          if (!workspaceProjectName || !viewportRef.current) {
            if (initialFitTimer.current !== null) window.clearTimeout(initialFitTimer.current);
            initialFitTimer.current = window.setTimeout(() => {
              initialFitTimer.current = null;
              pendingInitialFit.current = instance;
              fitInitialViewWhenReady();
            }, 80);
          }
        }}
        defaultViewport={viewport ?? undefined}
        onMoveEnd={(_, nextViewport) => setViewport(nextViewport)}
        onNodeClick={async (_, node) => {
          if (activeTool === 'link') {
            if (!linkSource) {
              setLinkSource(node.id);
              toast('Link source selected', 'Click a second object to create a semantic link.');
              return;
            }
            if (linkSource !== node.id) {
              const existing = edgesRef.current.find((edge) =>
                edge.data?.edgeKind === 'semantic' &&
                ((edge.source === linkSource && edge.target === node.id) ||
                  (edge.source === node.id && edge.target === linkSource)),
              );
              if (existing) {
                await deleteEdges([existing.id]);
              } else {
                recordHistory();
                if (workspaceProjectName) {
                  try {
                    const persisted = await api.createWorkspaceEdge(workspaceProjectName, {
                      source_object_id: linkSource,
                      target_object_id: node.id,
                      relation_type: 'related_to',
                      edge_family: 'semantic',
                    });
                    setEdges((current) => [...current, {
                      id: persisted.id,
                      source: persisted.source_object_id,
                      target: persisted.target_object_id,
                      type: 'smart',
                      data: { edgeKind: 'semantic' },
                    }]);
                    toast('Semantic link created', 'The relationship is saved in this project graph.');
                  } catch {
                    toast('Link was not saved', 'AURA could not create that semantic relationship.');
                  }
                } else {
                  setEdges((current) => [...current, {
                    id: `semantic-${idRef.current++}`,
                    source: linkSource,
                    target: node.id,
                    type: 'smart',
                    data: { edgeKind: 'semantic' },
                  }]);
                  toast('Semantic link created', 'Click the link to delete it, or link the same pair again to toggle it off.');
                }
              }
            }
            setLinkSource(null);
            setActiveTool('select');
            return;
          }
          onNodeFocus?.(node.data.messageId ?? null, node);
        }}
        onPaneClick={(event) => {
          if (activeTool !== 'note' || !instanceRef.current) return;
          createNoteAt(instanceRef.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
          setActiveTool('select');
        }}
        onPaneContextMenu={(event) => {
          event.preventDefault();
          if (!instanceRef.current) return;
          createNoteAt(
            instanceRef.current.screenToFlowPosition({ x: event.clientX, y: event.clientY }),
            'Quick note created from the board context menu.',
          );
        }}
        selectionMode={SelectionMode.Partial}
        panOnDrag={[0, 1]}
        selectionOnDrag={activeTool === 'select'}
        multiSelectionKeyCode={['Meta', 'Control', 'Shift']}
        minZoom={0.22}
        maxZoom={1.6}
        defaultEdgeOptions={{ type: 'smart' }}
        proOptions={{ hideAttribution: true }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1} color="#26323d" />
        <MiniMap
          className="aura-minimap"
          pannable
          zoomable
          nodeColor={(node) => {
            const accent = (node.data as AuraFlowNode['data']).accent;
            if (accent === 'purple') return '#806dc5';
            if (accent === 'amber') return '#a98955';
            if (accent === 'green') return '#5b9f7d';
            if (accent === 'cyan') return '#4a96a6';
            return '#586370';
          }}
          maskColor="rgba(6, 10, 15, .72)"
        />
      </ReactFlow>

      <BoardToolbar
        activeTool={activeTool}
        onToolChange={(tool) => {
          setActiveTool(tool);
          setLinkSource(null);
        }}
        onAutoLayout={autoLayout}
        onFitView={() => instanceRef.current?.fitView({ padding: compact ? 0.2 : 0.12, duration: 450 })}
        onUndo={() => { if (undo()) toast('Undone'); }}
        onRedo={() => { if (redo()) toast('Redone'); }}
        canUndo={canUndo}
        canRedo={canRedo}
        layers={layers}
        executionHistoryTruncated={executionHistoryTruncated || Boolean(executionNextCursor)}
        onLoadOlderExecution={executionNextCursor ? () => void loadOlderExecution() : undefined}
        loadingOlderExecution={loadingOlderExecution}
        graphHasMore={Boolean(graphObjectCursor || graphEdgeCursor)}
        onLoadOlderGraph={graphObjectCursor || graphEdgeCursor ? () => void loadOlderGraphPage() : undefined}
        loadingOlderGraph={loadingOlderGraph}
        onLayerToggle={(layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}
      />

      {selectedNodes.length > 1 ? (
        <ContextLensBar
          key={selectedNodes.map((node) => node.id).join(':')}
          nodes={selectedNodes}
          onAsk={askSelected}
          onPreviewContext={workspaceProjectName ? previewSelectedContext : undefined}
          contextPreview={contextPreview}
          contextPreviewLoading={contextPreviewLoading}
          contextPreviewError={contextPreviewError}
          onCreateNote={() => createNoteAt(getSelectionAnchor(), 'Manual note derived from the current Context Lens selection.')}
          onCreateBridge={createContextBridge}
          onCreateBranch={() => addBranch(selectedNodes[0].id)}
          onSaveContextSet={saveContextSet}
          mergeTargets={mergeTargets}
          onMergeInto={(targetId) => void mergeIntoBranch(targetId)}
          onClear={clearSelection}
        />
      ) : null}

      {activeTool === 'note' ? <div className="board-mode-hint">Click the canvas to place a Manual Note · Esc to cancel</div> : null}
      {activeTool === 'link' ? (
        <div className="board-mode-hint">{linkSource ? 'Select a target object' : 'Select a source object'} · Esc to cancel</div>
      ) : null}
    </div>
  );
}
