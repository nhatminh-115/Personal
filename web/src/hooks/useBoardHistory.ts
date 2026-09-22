import { useCallback, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import type { AuraFlowEdge, AuraFlowNode } from '../types';

interface BoardSnapshot {
  nodes: AuraFlowNode[];
  edges: AuraFlowEdge[];
}

interface UseBoardHistoryOptions {
  nodesRef: MutableRefObject<AuraFlowNode[]>;
  edgesRef: MutableRefObject<AuraFlowEdge[]>;
  setNodes: Dispatch<SetStateAction<AuraFlowNode[]>>;
  setEdges: Dispatch<SetStateAction<AuraFlowEdge[]>>;
  limit?: number;
}

function cloneNode(node: AuraFlowNode): AuraFlowNode {
  return {
    ...node,
    selected: false,
    dragging: false,
    data: {
      ...node.data,
      bridgeOptions: node.data.bridgeOptions ? { ...node.data.bridgeOptions } : undefined,
      mergeItems: node.data.mergeItems ? [...node.data.mergeItems] : undefined,
      execution: node.data.execution ? node.data.execution.map((step) => ({ ...step })) : undefined,
    },
  };
}

function cloneEdge(edge: AuraFlowEdge): AuraFlowEdge {
  return {
    ...edge,
    selected: false,
    data: edge.data ? { ...edge.data, onDelete: undefined } : edge.data,
    style: edge.style ? { ...edge.style } : edge.style,
  };
}

function snapshot(nodes: AuraFlowNode[], edges: AuraFlowEdge[]): BoardSnapshot {
  return {
    nodes: nodes.map(cloneNode),
    edges: edges.map(cloneEdge),
  };
}

export function useBoardHistory({ nodesRef, edgesRef, setNodes, setEdges, limit = 80 }: UseBoardHistoryOptions) {
  const undoRef = useRef<BoardSnapshot[]>([]);
  const redoRef = useRef<BoardSnapshot[]>([]);
  const [availability, setAvailability] = useState({ canUndo: false, canRedo: false });

  const syncAvailability = useCallback(() => {
    setAvailability({ canUndo: undoRef.current.length > 0, canRedo: redoRef.current.length > 0 });
  }, []);

  const record = useCallback(() => {
    undoRef.current.push(snapshot(nodesRef.current, edgesRef.current));
    if (undoRef.current.length > limit) undoRef.current.shift();
    redoRef.current = [];
    syncAvailability();
  }, [edgesRef, limit, nodesRef, syncAvailability]);

  const undo = useCallback(() => {
    const previous = undoRef.current.pop();
    if (!previous) return false;
    redoRef.current.push(snapshot(nodesRef.current, edgesRef.current));
    nodesRef.current = previous.nodes;
    edgesRef.current = previous.edges;
    setNodes(previous.nodes);
    setEdges(previous.edges);
    syncAvailability();
    return true;
  }, [edgesRef, nodesRef, setEdges, setNodes, syncAvailability]);

  const redo = useCallback(() => {
    const next = redoRef.current.pop();
    if (!next) return false;
    undoRef.current.push(snapshot(nodesRef.current, edgesRef.current));
    nodesRef.current = next.nodes;
    edgesRef.current = next.edges;
    setNodes(next.nodes);
    setEdges(next.edges);
    syncAvailability();
    return true;
  }, [edgesRef, nodesRef, setEdges, setNodes, syncAvailability]);

  return {
    record,
    undo,
    redo,
    canUndo: availability.canUndo,
    canRedo: availability.canRedo,
  };
}
