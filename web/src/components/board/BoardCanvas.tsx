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
import type { AuraFlowEdge, AuraFlowNode, LayerKey, NodeDensity } from '../../types';
import { AuraNodeCard } from './AuraNodeCard';
import { BoardToolbar } from './BoardToolbar';
import { ContextLensBar } from './ContextLensBar';
import { SmartEdge } from './SmartEdge';
import { ApiError, api } from '../../services/api';
import { projectExecutionGraph } from './executionProjection';
import { isWorkspaceEdgeDeletable } from './workspaceEdgePolicy';

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
    const kind = object.object_type === 'manual_note' ? 'note'
      : object.object_type === 'context_bridge' ? 'bridge'
        : object.object_type === 'context_set' ? 'merge'
          : object.object_type === 'conversation_branch' || role === 'user' ? 'user' : 'answer';
    const mergeItems = Array.isArray(object.metadata_json.source_titles)
      ? object.metadata_json.source_titles.filter((item): item is string => typeof item === 'string')
      : [];
    const rawBridgeOptions = object.metadata_json.bridge_options as Record<string, unknown> | undefined;
    return {
      id: object.id,
      type: 'aura',
      position: positions[object.id] ?? { x: 120 + (index % 3) * 390, y: 100 + Math.floor(index / 3) * 210 },
      data: {
        kind,
        eyebrow: object.object_type === 'conversation_branch' ? 'NEW BRANCH' : kind === 'user' ? 'USER' : kind === 'answer' ? 'AURA' : kind === 'note' ? 'MANUAL NOTE' : kind === 'bridge' ? 'CONTEXT BRIDGE' : 'SAVED CONTEXT SET',
        title: object.title || (kind === 'user' ? 'User turn' : 'AURA response'),
        body: object.content || (kind === 'merge' ? 'Selected objects remain individually inspectable. No summary was generated.' : object.object_type === 'conversation_branch' ? 'Saved branch point. Add a user-authored prompt to start this conversation.' : ''),
        summary: object.content.slice(0, 160),
        density: 'compact',
        manual: object.created_by === 'user' && kind === 'note',
        accent: kind === 'note' ? 'amber' : kind === 'bridge' || kind === 'merge' ? 'cyan' : kind === 'user' ? 'slate' : 'purple',
        layer: kind === 'note' || kind === 'bridge' || kind === 'merge' ? 'knowledge' : 'conversation',
        messageId: object.source_message_id ?? undefined,
        sourceCount: typeof object.metadata_json.source_count === 'number' ? object.metadata_json.source_count : mergeItems.length,
        mergeItems,
        bridgeOptions: kind === 'bridge' ? {
          conclusions: typeof rawBridgeOptions?.conclusions === 'boolean' ? rawBridgeOptions.conclusions : true,
          observations: typeof rawBridgeOptions?.observations === 'boolean' ? rawBridgeOptions.observations : true,
          failed: typeof rawBridgeOptions?.failed === 'boolean' ? rawBridgeOptions.failed : false,
          artifacts: typeof rawBridgeOptions?.artifacts === 'boolean' ? rawBridgeOptions.artifacts : false,
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
      createdBy: edge.created_by,
    },
  }));
  const execution = projectExecutionGraph(graph.execution_traces ?? [], nodes);
  return { nodes, edges, executionNodes: execution.nodes, executionEdges: execution.edges };
}

function layoutSnapshotFor(nodes: AuraFlowNode[], viewport: { x: number; y: number; zoom: number } | null) {
  return JSON.stringify({ positions: Object.fromEntries(nodes.map((node) => [node.id, node.position])), viewport });
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
  onAskWithContext?: (prompt: string, objectIds: string[]) => void | Promise<void>;
}

const densityOrder: NodeDensity[] = ['collapsed', 'compact', 'full'];

export function BoardCanvas({ compact = false, boardKey = 'stateful', seedNodes, seedEdges, showBranchLabels = true, focusNodeId, onNodeFocus, onToast, executionExpanded, branchRequest, workspaceProjectName = null, workspaceSessionIds = EMPTY_SESSION_IDS, onAskWithContext }: BoardCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<AuraFlowNode>(seedNodes ?? initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AuraFlowEdge>(seedEdges ?? initialEdges);
  const [executionNodes, setExecutionNodes] = useState<AuraFlowNode[]>([]);
  const [executionEdges, setExecutionEdges] = useState<AuraFlowEdge[]>([]);
  const [activeTool, setActiveTool] = useState<'select' | 'note' | 'link'>('select');
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    conversation: true,
    knowledge: true,
    execution: executionExpanded ?? false,
  });
  const [linkSource, setLinkSource] = useState<string | null>(null);
  const [viewport, setViewport] = useState<{ x: number; y: number; zoom: number } | null>(null);
  const [historyApplying, setHistoryApplying] = useState(false);
  const instanceRef = useRef<ReactFlowInstance<AuraFlowNode, AuraFlowEdge> | null>(null);
  const idRef = useRef(100);
  const processedBranchNonce = useRef<number | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const workspaceReady = useRef(false);
  const layoutRevision = useRef(0);
  const layoutSnapshot = useRef('');
  const layoutTimer = useRef<number | null>(null);
  const layoutConflict = useRef(false);
  const historyBusy = useRef(false);
  const viewportRef = useRef(viewport);
  const noteSaveTimers = useRef<Map<string, number>>(new Map());
  const noteRestorePayloads = useRef<Map<string, { object_type: 'manual_note'; title: string; content: string }>>(new Map());
  nodesRef.current = nodes;
  edgesRef.current = edges;
  viewportRef.current = viewport;

  const { record: recordHistory, undo, redo, getUndoEffect, getRedoEffect, canUndo, canRedo } = useBoardHistory({
    nodesRef,
    edgesRef,
    setNodes,
    setEdges,
  });

  const toast = useCallback((title: string, detail?: string) => onToast?.(title, detail), [onToast]);

  const applyHistory = useCallback(async (direction: 'undo' | 'redo') => {
    if (historyBusy.current) return;
    const effect = direction === 'undo' ? getUndoEffect() : getRedoEffect();
    historyBusy.current = true;
    setHistoryApplying(true);
    try {
      if (effect) await effect[direction]();
      const changed = direction === 'undo' ? undo() : redo();
      if (changed) toast(direction === 'undo' ? 'Undone' : 'Redone');
    } catch {
      toast(direction === 'undo' ? 'Undo was not saved' : 'Redo was not saved', 'The saved graph changed or could not be reached. Reload the Board before retrying.');
    } finally {
      historyBusy.current = false;
      setHistoryApplying(false);
    }
  }, [getRedoEffect, getUndoEffect, redo, toast, undo]);

  useEffect(() => {
    const nextNodes = (seedNodes ?? initialNodes).map((node) => ({ ...node, data: { ...node.data }, selected: false }));
    const nextEdges = (seedEdges ?? initialEdges).map((edge) => ({ ...edge, data: edge.data ? { ...edge.data } : edge.data, selected: false }));
    setNodes(nextNodes);
    setEdges(nextEdges);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
  }, [boardKey, seedEdges, seedNodes, setEdges, setNodes]);

  useEffect(() => {
    workspaceReady.current = false;
    layoutConflict.current = false;
    setExecutionNodes([]);
    setExecutionEdges([]);
    if (!workspaceProjectName) return;
    let cancelled = false;
    void Promise.all(workspaceSessionIds.map((sessionId) => api.attachWorkspaceSession(workspaceProjectName, sessionId).catch((error) => {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }))).then(() => api.fetchWorkspaceGraph(workspaceProjectName)).then(async (graph) => {
      if (cancelled) return;
      const { nodes: nextNodes, edges: nextEdges, executionNodes: nextExecutionNodes, executionEdges: nextExecutionEdges } = mapWorkspaceGraph(graph);
      const savedViewport = graph.layout.layout?.viewport ?? null;
      let revision = graph.layout.revision;
      const persistedPositions = graph.layout.layout?.positions ?? {};
      const missingPositions = nextNodes.some((node) => !persistedPositions[node.id]);
      if (missingPositions) {
        try {
          const savedLayout = await api.putWorkspaceLayout(workspaceProjectName, {
            positions: Object.fromEntries(nextNodes.map((node) => [node.id, node.position])),
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
      nodesRef.current = nextNodes;
      edgesRef.current = nextEdges;
      if (savedViewport) {
        requestAnimationFrame(() => instanceRef.current?.setViewport(savedViewport, { duration: 0 }));
      }
      workspaceReady.current = true;
    }).catch(() => {
      if (!cancelled) toast('Could not load saved Board', 'The workspace graph could not be loaded from AURA.');
    });
    return () => { cancelled = true; };
  }, [workspaceProjectName, workspaceSessionIds, setEdges, setNodes, toast]);

  useEffect(() => () => {
    if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
    noteSaveTimers.current.forEach((timer) => window.clearTimeout(timer));
  }, []);

  useEffect(() => {
    if (!workspaceProjectName || !workspaceReady.current || layoutConflict.current) return;
    const positions = Object.fromEntries(nodes.filter((node) => !node.id.startsWith('branch-') && !node.id.startsWith('note-') && !node.id.startsWith('merge-') && !node.id.startsWith('lens-answer-') && !node.id.startsWith('bridge-')).map((node) => [node.id, node.position]));
    const layout = { positions, viewport };
    const snapshot = JSON.stringify(layout);
    if (snapshot === layoutSnapshot.current) return;
    if (layoutTimer.current !== null) window.clearTimeout(layoutTimer.current);
    layoutTimer.current = window.setTimeout(() => {
      void api.putWorkspaceLayout(workspaceProjectName, layout, layoutRevision.current).then((result) => {
        layoutRevision.current = result.revision;
        layoutSnapshot.current = snapshot;
      }).catch((error) => {
        if (error instanceof ApiError && error.status === 409) {
          layoutConflict.current = true;
          toast('Board layout changed elsewhere', 'Reload the project Board before saving more layout changes.');
        } else {
          toast('Board layout was not saved', 'Check the connection and retry after reopening the Board.');
        }
      });
    }, 450);
  }, [nodes, viewport, workspaceProjectName, toast]);

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
      setNodes((current) => current.map((node) => (node.id === id ? {
        ...node,
        data: { ...node.data, body, ...(node.data.kind === 'bridge' ? { bridgeNote: body } : {}) },
      } : node)));
      if (workspaceProjectName) {
        const node = nodesRef.current.find((item) => item.id === id);
        if (node?.data.manual || node?.data.kind === 'bridge') {
          if (node.data.manual) {
            const restorePayload = noteRestorePayloads.current.get(id);
            if (restorePayload) restorePayload.content = body;
          }
          const previous = noteSaveTimers.current.get(id);
          if (previous !== undefined) window.clearTimeout(previous);
          const timer = window.setTimeout(() => {
            void api.updateWorkspaceObject(workspaceProjectName, id, {
              title: node.data.title,
              content: body,
              metadata_json: node.data.kind === 'bridge' ? {
                bridge_options: node.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false },
              } : {},
            }).catch(() => toast(node.data.kind === 'bridge' ? 'Context Bridge was not saved' : 'Manual note was not saved', 'Your text is still visible here. Reopen the Board to retry.'));
            noteSaveTimers.current.delete(id);
          }, 500);
          noteSaveTimers.current.set(id, timer);
        }
      }
    },
    [setNodes, toast, workspaceProjectName],
  );

  const updateBridgeOption = useCallback(
    (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts', value: boolean) => {
      recordHistory();
      const node = nodesRef.current.find((item) => item.id === id);
      const bridgeOptions = {
        ...(node?.data.bridgeOptions ?? { conclusions: true, observations: true, failed: false, artifacts: false }),
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
        void api.updateWorkspaceObject(workspaceProjectName, id, {
          title: node.data.title,
          content: node.data.bridgeNote ?? node.data.body,
          metadata_json: { bridge_options: bridgeOptions },
        }).catch(() => toast('Bridge options were not saved', 'The selection remains visible until you reload the Board.'));
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
          const graph = await api.fetchWorkspaceGraph(workspaceProjectName);
          const projected = mapWorkspaceGraph(graph);
          layoutRevision.current = graph.layout.revision;
          nodesRef.current = projected.nodes;
          edgesRef.current = projected.edges;
          setNodes(projected.nodes);
          setEdges(projected.edges);
          setExecutionNodes(projected.executionNodes);
          setExecutionEdges(projected.executionEdges);
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
          onBridgeApply: workspaceProjectName ? undefined : applyBridge,
          onBridgeOption: updateBridgeOption,
          onContinueMerge: continueMerge,
        },
      })),
    [addBranch, applyBridge, changeBody, continueMerge, cycleDensity, executionNodes, layers, nodes, updateBridgeOption, workspaceProjectName],
  );

  const deleteEdges = useCallback(
    async (edgeIds: string[]) => {
      const ids = new Set(edgeIds);
      if (ids.size === 0) return;
      const systemEdgeIds = new Set(edgesRef.current
        .filter((edge) => ids.has(edge.id) && !isWorkspaceEdgeDeletable(edge))
        .map((edge) => edge.id));
      const deletableIds = new Set([...ids].filter((id) => !systemEdgeIds.has(id)));
      if (deletableIds.size === 0) {
        toast('System relation protected', 'AURA keeps conversation and execution provenance links intact.');
        return;
      }
      if (workspaceProjectName) {
        const persisted = edgesRef.current.filter((edge) => deletableIds.has(edge.id) && !edge.id.startsWith('edge-') && !edge.id.startsWith('semantic-'));
        try {
          if (persisted.length > 0) {
            const deleted = await api.deleteWorkspaceEdges(workspaceProjectName, persisted.map((edge) => edge.id));
            recordHistory({
              undo: async () => { await api.restoreWorkspaceEdges(workspaceProjectName, deleted); },
              redo: async () => { await api.deleteWorkspaceEdges(workspaceProjectName, deleted.map((edge) => edge.id)); },
            });
          } else {
            recordHistory();
          }
        } catch {
          toast('Link was not deleted', 'AURA could not update the saved workspace graph.');
          return;
        }
      } else {
        recordHistory();
      }
      setEdges((current) => current.filter((edge) => !deletableIds.has(edge.id)));
      const deletedCount = [...deletableIds].filter((id) => edgesRef.current.some((edge) => edge.id === id)).length;
      const keptMessage = systemEdgeIds.size > 0 ? ' System-owned conversation links were kept.' : '';
      toast(deletedCount === 1 ? 'Link deleted' : `${deletedCount} links deleted`, `Ctrl+Z restores the removed relation.${keptMessage}`);
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
          onDelete: isExecution || !isWorkspaceEdgeDeletable(edge) ? undefined : (id: string) => deleteEdges([id]),
        },
        deletable: !isExecution && isWorkspaceEdgeDeletable(edge),
      };
    });
  }, [deleteEdges, edges, executionEdges, executionNodes, layers.execution, nodes]);

  const selectedNodes = useMemo(() => nodes.filter((node) => node.selected), [nodes]);
  const selectedEdges = useMemo(() => edges.filter((edge) => edge.selected), [edges]);

  const createNoteAt = useCallback(
    async (position: { x: number; y: number }, body = 'New manual note. Double-click the density control until Full to edit inline.') => {
      let id = `note-${idRef.current++}`;
      const noteInput = { object_type: 'manual_note' as const, title: 'Untitled note', content: body };
      if (workspaceProjectName) {
        try {
          const created = await api.createWorkspaceObject(workspaceProjectName, noteInput);
          id = created.id;
          const objectId = id;
          const restorePayload = { ...noteInput };
          noteRestorePayloads.current.set(objectId, restorePayload);
          recordHistory({
            undo: async () => {
              const timer = noteSaveTimers.current.get(objectId);
              if (timer !== undefined) window.clearTimeout(timer);
              noteSaveTimers.current.delete(objectId);
              await api.deleteWorkspaceObject(workspaceProjectName, objectId);
            },
            redo: async () => {
              await api.createWorkspaceObject(workspaceProjectName, { ...restorePayload, id: objectId });
            },
          });
        } catch {
          toast('Manual note was not saved', 'AURA could not create this note in the project graph.');
          return null;
        }
      } else {
        recordHistory();
      }
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
        },
      };
      setNodes((current) => [...current, note]);
      toast('Manual note created', 'It lives on the Knowledge layer and is explicitly marked Manual.');
      return id;
    },
    [recordHistory, setNodes, toast, workspaceProjectName],
  );

  const getSelectionAnchor = useCallback(() => {
    if (selectedNodes.length === 0) return { x: 850, y: 350 };
    const x = selectedNodes.reduce((sum, node) => sum + node.position.x, 0) / selectedNodes.length;
    const y = selectedNodes.reduce((sum, node) => sum + node.position.y, 0) / selectedNodes.length;
    return { x: x + 390, y };
  }, [selectedNodes]);

  const createContextBridge = useCallback(async () => {
    if (selectedNodes.length < 2) return;
    const bridgeOptions = { conclusions: true, observations: true, failed: false, artifacts: false };
    if (workspaceProjectName) {
      try {
        await api.createWorkspaceObject(workspaceProjectName, {
          object_type: 'context_bridge',
          title: 'Context Bridge',
          content: '',
          metadata_json: { bridge_options: bridgeOptions },
          source_object_ids: selectedNodes.map((node) => node.id),
        });
        const graph = await api.fetchWorkspaceGraph(workspaceProjectName);
        const projected = mapWorkspaceGraph(graph);
        layoutRevision.current = graph.layout.revision;
        nodesRef.current = projected.nodes;
        edgesRef.current = projected.edges;
        setNodes(projected.nodes);
        setEdges(projected.edges);
        setExecutionNodes(projected.executionNodes);
        setExecutionEdges(projected.executionEdges);
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
  }, [getSelectionAnchor, recordHistory, selectedNodes, setEdges, setNodes, toast, workspaceProjectName]);

  const mergeSelected = useCallback(async () => {
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
        const graph = await api.fetchWorkspaceGraph(workspaceProjectName);
        const projected = mapWorkspaceGraph(graph);
        layoutRevision.current = graph.layout.revision;
        nodesRef.current = projected.nodes;
        edgesRef.current = projected.edges;
        setNodes(projected.nodes);
        setEdges(projected.edges);
        setExecutionNodes(projected.executionNodes);
        setExecutionEdges(projected.executionEdges);
        toast('Context selection saved', 'Source objects are linked without changing their content or generating a summary.');
      } catch (error) {
        toast('Context selection was not saved', error instanceof ApiError && error.status === 409
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
        eyebrow: 'MERGE CONTEXT',
        title: 'Merged working context',
        body: 'Selected objects are combined into a continuation context.',
        summary: `${selectedNodes.length} sources merged`,
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
    toast('Merge node created', `${selectedNodes.length} selected objects feed a new merged context.`);
  }, [getSelectionAnchor, recordHistory, selectedNodes, setEdges, setNodes, toast, workspaceProjectName]);

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
      if (historyBusy.current) {
        if (modifier && ['z', 'y'].includes(event.key.toLowerCase())) event.preventDefault();
        return;
      }
      if (modifier && event.key.toLowerCase() === 'z') {
        event.preventDefault();
        void applyHistory(event.shiftKey ? 'redo' : 'undo');
        return;
      }
      if (modifier && event.key.toLowerCase() === 'y') {
        event.preventDefault();
        void applyHistory('redo');
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
  }, [applyHistory, clearSelection, deleteEdges, selectedEdges]);

  useEffect(() => {
    if (!focusNodeId || !instanceRef.current) return;
    const node = instanceRef.current.getNode(focusNodeId);
    if (!node) return;
    const width = node.measured?.width ?? 300;
    const height = node.measured?.height ?? 130;
    instanceRef.current.setCenter(node.position.x + width / 2, node.position.y + height / 2, {
      zoom: compact ? 0.85 : 1,
      duration: 450,
    });
    setNodes((current) => current.map((item) => ({ ...item, selected: item.id === focusNodeId })));
  }, [compact, focusNodeId, setNodes]);

  return (
    <div className={`board-canvas ${compact ? 'board-canvas--compact' : ''}`}>
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
        nodesDraggable={!historyApplying}
        nodesConnectable={!historyApplying}
        elementsSelectable={!historyApplying}
        onNodeDragStart={() => recordHistory()}
        onConnect={async (connection) => {
          if (workspaceProjectName && connection.source && connection.target) {
            try {
              const persisted = await api.createWorkspaceEdge(workspaceProjectName, {
                source_object_id: connection.source,
                target_object_id: connection.target,
                relation_type: 'related_to',
                edge_family: 'semantic',
              });
              const restore = [{
                id: persisted.id,
                source_object_id: persisted.source_object_id,
                target_object_id: persisted.target_object_id,
                relation_type: persisted.relation_type,
                edge_family: persisted.edge_family,
                metadata_json: persisted.metadata_json,
              }];
              recordHistory({
                undo: async () => { await api.deleteWorkspaceEdges(workspaceProjectName, restore.map((edge) => edge.id)); },
                redo: async () => { await api.restoreWorkspaceEdges(workspaceProjectName, restore); },
              });
              setEdges((current) => [...current, {
                id: persisted.id,
                source: persisted.source_object_id,
                target: persisted.target_object_id,
                type: 'smoothstep',
                data: { edgeKind: 'semantic', createdBy: persisted.created_by },
              }]);
              return;
            } catch {
              toast('Link was not saved', 'Semantic links require two objects in this project graph.');
              return;
            }
          }
          recordHistory();
          setEdges((current) => addEdge({ ...connection, type: 'smart', data: { edgeKind: 'semantic' } }, current));
        }}
        onEdgeClick={(event, edge) => {
          event.stopPropagation();
          setNodes((current) => current.map((node) => ({ ...node, selected: false })));
          setEdges((current) => current.map((item) => ({ ...item, selected: item.id === edge.id })));
        }}
        onInit={(instance) => {
          instanceRef.current = instance;
          if (!workspaceProjectName || !viewportRef.current) {
            window.setTimeout(() => instance.fitView({ padding: compact ? 0.2 : 0.12, duration: 300 }), 80);
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
                if (workspaceProjectName) {
                  try {
                    const persisted = await api.createWorkspaceEdge(workspaceProjectName, {
                      source_object_id: linkSource,
                      target_object_id: node.id,
                      relation_type: 'related_to',
                      edge_family: 'semantic',
                    });
                    const restore = [{
                      id: persisted.id,
                      source_object_id: persisted.source_object_id,
                      target_object_id: persisted.target_object_id,
                      relation_type: persisted.relation_type,
                      edge_family: persisted.edge_family,
                      metadata_json: persisted.metadata_json,
                    }];
                    recordHistory({
                      undo: async () => { await api.deleteWorkspaceEdges(workspaceProjectName, restore.map((edge) => edge.id)); },
                      redo: async () => { await api.restoreWorkspaceEdges(workspaceProjectName, restore); },
                    });
                    setEdges((current) => [...current, {
                      id: persisted.id,
                      source: persisted.source_object_id,
                      target: persisted.target_object_id,
                      type: 'smart',
                      data: { edgeKind: 'semantic', createdBy: persisted.created_by },
                    }]);
                    toast('Semantic link created', 'The relationship is saved in this project graph.');
                  } catch {
                    toast('Link was not saved', 'AURA could not create that semantic relationship.');
                  }
                } else {
                  recordHistory();
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
        onUndo={() => { void applyHistory('undo'); }}
        onRedo={() => { void applyHistory('redo'); }}
        canUndo={canUndo}
        canRedo={canRedo}
        layers={layers}
        onLayerToggle={(layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}
      />

      {selectedNodes.length > 1 ? (
        <ContextLensBar
          nodes={selectedNodes}
          onAsk={askSelected}
          onCreateNote={() => createNoteAt(getSelectionAnchor(), 'Manual note derived from the current Context Lens selection.')}
          onCreateBridge={createContextBridge}
          onCreateBranch={() => addBranch(selectedNodes[0].id)}
          onMerge={mergeSelected}
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
