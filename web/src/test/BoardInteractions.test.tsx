import { render, screen, fireEvent } from '@testing-library/react';
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ReactFlowProvider } from '@xyflow/react';
import { AuraNodeCard } from '../components/board/AuraNodeCard';
import { useBoardHistory } from '../hooks/useBoardHistory';
import type { AuraFlowNode, AuraFlowEdge, AuraNodeData } from '../types';

describe('Board Prototype Interactions', () => {
  it('renders answer node card and triggers Branch interaction', () => {
    const onBranchMock = vi.fn();
    const data: AuraNodeData = {
      kind: 'answer',
      title: 'Root synthesis',
      body: 'Stateful synthesis across TTT and recurrent memory',
      density: 'compact',
      layer: 'conversation',
      onBranch: onBranchMock,
    };

    render(
      <ReactFlowProvider>
        <AuraNodeCard
          id="node-test-1"
          data={data}
          selected={false}
          type="auraNode"
          zIndex={1}
          isConnectable={true}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
          dragging={false}
          selectable={false}
          deletable={false}
          draggable={false}
        />
      </ReactFlowProvider>
    );

    expect(screen.getByText('Root synthesis')).toBeInTheDocument();
    const branchBtn = screen.getByRole('button', { name: /Branch from here/i });
    expect(branchBtn).toBeInTheDocument();

    fireEvent.click(branchBtn);
    expect(onBranchMock).toHaveBeenCalledWith('node-test-1');
  });

  it('renders Context Bridge and triggers bridge options and apply', () => {
    const onBridgeApplyMock = vi.fn();
    const onBridgeOptionMock = vi.fn();
    const data: AuraNodeData = {
      kind: 'bridge',
      title: 'Bridge A → C',
      body: 'Bridge summary',
      density: 'full',
      layer: 'knowledge',
      bridgeOptions: {
        conclusions: true,
        observations: true,
        failed: false,
        artifacts: false,
      },
      bridgeNote: 'Keep novelty hypothesis conservative',
      onBridgeApply: onBridgeApplyMock,
      onBridgeOption: onBridgeOptionMock,
    };

    render(
      <ReactFlowProvider>
        <AuraNodeCard
          id="bridge-node-1"
          data={data}
          selected={false}
          type="auraNode"
          zIndex={1}
          isConnectable={true}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
          dragging={false}
          selectable={false}
          deletable={false}
          draggable={false}
        />
      </ReactFlowProvider>
    );

    expect(screen.getByText('Bridge A → C')).toBeInTheDocument();
    expect(screen.getByText(/Keep novelty hypothesis conservative/i)).toBeInTheDocument();

    // Toggle option
    const failedCheckbox = screen.getByLabelText(/Failed attempts/i);
    fireEvent.click(failedCheckbox);
    expect(onBridgeOptionMock).toHaveBeenCalledWith('bridge-node-1', 'failed', true);

    // Apply button
    const applyBtn = screen.getByRole('button', { name: /Apply to Branch C/i });
    fireEvent.click(applyBtn);
    expect(onBridgeApplyMock).toHaveBeenCalledWith('bridge-node-1');
  });

  it('renders Merge node and triggers continue merge', () => {
    const onContinueMergeMock = vi.fn();
    const data: AuraNodeData = {
      kind: 'merge',
      title: 'Cross-branch synthesis',
      body: 'Synthesize A and B',
      density: 'full',
      layer: 'conversation',
      mergeItems: ['Branch A: TTT bounds', 'Branch B: Constant memory'],
      onContinueMerge: onContinueMergeMock,
    };

    render(
      <ReactFlowProvider>
        <AuraNodeCard
          id="merge-node-1"
          data={data}
          selected={false}
          type="auraNode"
          zIndex={1}
          isConnectable={true}
          positionAbsoluteX={0}
          positionAbsoluteY={0}
          dragging={false}
          selectable={false}
          deletable={false}
          draggable={false}
        />
      </ReactFlowProvider>
    );

    expect(screen.getByText('Cross-branch synthesis')).toBeInTheDocument();
    expect(screen.getByText('Branch A: TTT bounds')).toBeInTheDocument();
    expect(screen.getByText('Branch B: Constant memory')).toBeInTheDocument();

    const continueBtn = screen.getByRole('button', { name: /Continue from merged context/i });
    fireEvent.click(continueBtn);
    expect(onContinueMergeMock).toHaveBeenCalledWith('merge-node-1');
  });

  it('verifies undo and redo operations via useBoardHistory hook', () => {
    let currentNodes: AuraFlowNode[] = [
      { id: 'node-1', position: { x: 0, y: 0 }, data: { kind: 'user', title: 'Start', body: '', density: 'compact', layer: 'conversation' } },
    ];
    let currentEdges: AuraFlowEdge[] = [];

    const nodesRef = { current: currentNodes };
    const edgesRef = { current: currentEdges };

    const setNodes = (updater: any) => {
      currentNodes = typeof updater === 'function' ? updater(currentNodes) : updater;
      nodesRef.current = currentNodes;
    };
    const setEdges = (updater: any) => {
      currentEdges = typeof updater === 'function' ? updater(currentEdges) : updater;
      edgesRef.current = currentEdges;
    };

    const { result } = renderHook(() =>
      useBoardHistory({
        nodesRef,
        edgesRef,
        setNodes,
        setEdges,
      })
    );

    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);

    // Record state before mutation
    act(() => {
      result.current.record();
    });

    // Add a node
    act(() => {
      currentNodes = [
        ...currentNodes,
        { id: 'node-2', position: { x: 100, y: 100 }, data: { kind: 'answer', title: 'Answer', body: '', density: 'compact', layer: 'conversation' } },
      ];
      nodesRef.current = currentNodes;
    });

    expect(result.current.canUndo).toBe(true);

    // Perform undo
    act(() => {
      result.current.undo();
    });

    // Reverted back to 1 node
    expect(currentNodes.length).toBe(1);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(true);

    // Perform redo
    act(() => {
      result.current.redo();
    });

    // Restored to 2 nodes
    expect(currentNodes.length).toBe(2);
    expect(result.current.canUndo).toBe(true);
    expect(result.current.canRedo).toBe(false);
  });
});
