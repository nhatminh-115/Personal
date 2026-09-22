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

const nodeTypes = { aura: AuraNodeCard };
const edgeTypes = { smart: SmartEdge };

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
}

const densityOrder: NodeDensity[] = ['collapsed', 'compact', 'full'];

export function BoardCanvas({ compact = false, boardKey = 'stateful', seedNodes, seedEdges, showBranchLabels = true, focusNodeId, onNodeFocus, onToast, executionExpanded, branchRequest }: BoardCanvasProps) {
  const [nodes, setNodes, onNodesChange] = useNodesState<AuraFlowNode>(seedNodes ?? initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<AuraFlowEdge>(seedEdges ?? initialEdges);
  const [activeTool, setActiveTool] = useState<'select' | 'note' | 'link'>('select');
  const [layers, setLayers] = useState<Record<LayerKey, boolean>>({
    conversation: true,
    knowledge: true,
    execution: executionExpanded ?? false,
  });
  const [linkSource, setLinkSource] = useState<string | null>(null);
  const instanceRef = useRef<ReactFlowInstance<AuraFlowNode, AuraFlowEdge> | null>(null);
  const idRef = useRef(100);
  const processedBranchNonce = useRef<number | null>(null);
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  nodesRef.current = nodes;
  edgesRef.current = edges;

  const { record: recordHistory, undo, redo, canUndo, canRedo } = useBoardHistory({
    nodesRef,
    edgesRef,
    setNodes,
    setEdges,
  });

  useEffect(() => {
    const nextNodes = (seedNodes ?? initialNodes).map((node) => ({ ...node, data: { ...node.data }, selected: false }));
    const nextEdges = (seedEdges ?? initialEdges).map((edge) => ({ ...edge, data: edge.data ? { ...edge.data } : edge.data, selected: false }));
    setNodes(nextNodes);
    setEdges(nextEdges);
    nodesRef.current = nextNodes;
    edgesRef.current = nextEdges;
  }, [boardKey, seedEdges, seedNodes, setEdges, setNodes]);

  useEffect(() => {
    if (typeof executionExpanded === 'boolean') {
      setLayers((current) => ({ ...current, execution: executionExpanded }));
    }
  }, [executionExpanded]);

  const toast = useCallback((title: string, detail?: string) => onToast?.(title, detail), [onToast]);

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
      setNodes((current) => current.map((node) => (node.id === id ? { ...node, data: { ...node.data, body } } : node)));
    },
    [setNodes],
  );

  const updateBridgeOption = useCallback(
    (id: string, key: 'conclusions' | 'observations' | 'failed' | 'artifacts', value: boolean) => {
      recordHistory();
      setNodes((current) =>
        current.map((node) => {
          if (node.id !== id) return node;
          const bridgeOptions = node.data.bridgeOptions ?? {
            conclusions: true,
            observations: true,
            failed: false,
            artifacts: false,
          };
          return {
            ...node,
            data: { ...node.data, bridgeOptions: { ...bridgeOptions, [key]: value } },
          };
        }),
      );
    },
    [recordHistory, setNodes],
  );

  const addBranch = useCallback(
    (sourceId: string) => {
      const source = nodesRef.current.find((node) => node.id === sourceId);
      if (!source) return;
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
    [recordHistory, setEdges, setNodes, toast],
  );

  useEffect(() => {
    if (!branchRequest || processedBranchNonce.current === branchRequest.nonce) return;
    processedBranchNonce.current = branchRequest.nonce;
    addBranch(branchRequest.nodeId);
  }, [addBranch, branchRequest]);

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
      nodes.map((node) => ({
        ...node,
        hidden: !layers[node.data.layer],
        data: {
          ...node.data,
          onCycleDensity: cycleDensity,
          onBranch: addBranch,
          onChangeBody: changeBody,
          onBridgeApply: applyBridge,
          onBridgeOption: updateBridgeOption,
          onContinueMerge: continueMerge,
        },
      })),
    [addBranch, applyBridge, changeBody, continueMerge, cycleDensity, layers, nodes, updateBridgeOption],
  );

  const deleteEdges = useCallback(
    (edgeIds: string[]) => {
      const ids = new Set(edgeIds);
      if (ids.size === 0) return;
      recordHistory();
      setEdges((current) => current.filter((edge) => !ids.has(edge.id)));
      toast(ids.size === 1 ? 'Link deleted' : `${ids.size} links deleted`, 'Ctrl+Z restores the removed relation.');
    },
    [recordHistory, setEdges, toast],
  );

  const styledEdges = useMemo(() => {
    const nodeMap = new Map(nodes.map((node) => [node.id, node]));
    return edges.map((edge) => {
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
          onDelete: (id: string) => deleteEdges([id]),
        },
      };
    });
  }, [deleteEdges, edges, layers.execution, nodes]);

  const selectedNodes = useMemo(() => nodes.filter((node) => node.selected), [nodes]);
  const selectedEdges = useMemo(() => edges.filter((edge) => edge.selected), [edges]);

  const createNoteAt = useCallback(
    (position: { x: number; y: number }, body = 'New manual note. Double-click the density control until Full to edit inline.') => {
      recordHistory();
      const id = `note-${idRef.current++}`;
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
    [recordHistory, setNodes, toast],
  );

  const getSelectionAnchor = useCallback(() => {
    if (selectedNodes.length === 0) return { x: 850, y: 350 };
    const x = selectedNodes.reduce((sum, node) => sum + node.position.x, 0) / selectedNodes.length;
    const y = selectedNodes.reduce((sum, node) => sum + node.position.y, 0) / selectedNodes.length;
    return { x: x + 390, y };
  }, [selectedNodes]);

  const mergeSelected = useCallback(() => {
    if (selectedNodes.length < 2) return;
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
  }, [getSelectionAnchor, recordHistory, selectedNodes, setEdges, setNodes, toast]);

  const askSelected = useCallback(
    (prompt: string) => {
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
    [getSelectionAnchor, recordHistory, selectedNodes, setEdges, setNodes, toast],
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
        onNodeDragStart={() => recordHistory()}
        onConnect={(connection) => {
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
          window.setTimeout(() => instance.fitView({ padding: compact ? 0.2 : 0.12, duration: 300 }), 80);
        }}
        onNodeClick={(_, node) => {
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
                deleteEdges([existing.id]);
                toast('Semantic link removed', 'Linking the same pair again toggles the manual relation off.');
              } else {
                recordHistory();
                setEdges((current) => [
                  ...current,
                  {
                    id: `semantic-${idRef.current++}`,
                    source: linkSource,
                    target: node.id,
                    type: 'smart',
                    data: { edgeKind: 'semantic' },
                  },
                ]);
                toast('Semantic link created', 'Click the link to delete it, or link the same pair again to toggle it off.');
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
        onLayerToggle={(layer) => setLayers((current) => ({ ...current, [layer]: !current[layer] }))}
      />

      {selectedNodes.length > 1 ? (
        <ContextLensBar
          nodes={selectedNodes}
          onAsk={askSelected}
          onCreateNote={() => createNoteAt(getSelectionAnchor(), 'Manual note derived from the current Context Lens selection.')}
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
