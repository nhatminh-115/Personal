import { render, screen, fireEvent } from '@testing-library/react';
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ReactFlowProvider } from '@xyflow/react';
import { AuraNodeCard } from '../components/board/AuraNodeCard';
import { ContextLensBar } from '../components/board/ContextLensBar';
import { useBoardHistory } from '../hooks/useBoardHistory';
import type { AuraFlowNode, AuraFlowEdge, AuraNodeData, WorkspaceContextPreview } from '../types';

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
    const onBridgeSectionMock = vi.fn();
    const onChangeBodyMock = vi.fn();
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
      bridgeSections: {
        conclusions: 'The migration can be reversible.',
        observations: '',
        failed: '',
        artifacts: '',
      },
      onBridgeApply: onBridgeApplyMock,
      onBridgeOption: onBridgeOptionMock,
      onBridgeSection: onBridgeSectionMock,
      onChangeBody: onChangeBodyMock,
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
    const handoffNote = screen.getByRole('textbox', { name: /Edit context bridge handoff note/i });
    expect(handoffNote).toHaveValue('Keep novelty hypothesis conservative');
    const conclusions = screen.getByRole('textbox', { name: 'Context Bridge Conclusions' });
    expect(conclusions).toHaveValue('The migration can be reversible.');
    fireEvent.change(conclusions, { target: { value: 'Keep rollbacks available.' } });
    expect(onBridgeSectionMock).toHaveBeenCalledWith('bridge-node-1', 'conclusions', 'Keep rollbacks available.');
    fireEvent.change(handoffNote, { target: { value: 'Keep the claim narrow.' } });
    expect(onChangeBodyMock).toHaveBeenCalledWith('bridge-node-1', 'Keep the claim narrow.');

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


describe('Compiled Context Preview', () => {
  it('shows the included manifest and compiled text when requested', () => {
    const onPreviewContext = vi.fn();
    const node = {
      id: 'bridge-preview',
      position: { x: 0, y: 0 },
      data: {
        kind: 'bridge',
        title: 'Safe handoff',
        body: 'Selected bridge',
        density: 'compact',
        layer: 'knowledge',
        workspaceObjectType: 'context_bridge',
      },
    } as AuraFlowNode;
    const preview: WorkspaceContextPreview = {
      project_name: 'AURA Project',
      estimated_tokens: 22,
      prompt_text: 'The reviewed finding is ready.',
      privacy_requirement: 'internal',
      required_capabilities: ['code_graph.read'],
      available_capabilities: [],
      missing_capabilities: ['code_graph.read'],
      objects: [
        {
          object_id: 'bridge-preview',
          object_type: 'context_bridge',
          selected_by_user: true,
          source_object_ids: ['source-note'],
          selected_sections: { conclusions: true },
        },
        { object_id: 'source-note', object_type: 'manual_note', selected_by_user: false },
      ],
    };

    render(
      <ContextLensBar
        nodes={[node, { ...node, id: 'note-preview', data: { ...node.data, kind: 'note', workspaceObjectType: 'manual_note' } }]}
        onAsk={vi.fn()}
        onPreviewContext={onPreviewContext}
        contextPreview={preview}
        mergeTargets={[]}
        onCreateNote={vi.fn()}
        onCreateBridge={vi.fn()}
        onCreateBranch={vi.fn()}
        onSaveContextSet={vi.fn()}
        onMergeInto={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Preview Context/i }));
    expect(onPreviewContext).toHaveBeenCalledOnce();
    expect(screen.getByText('22 estimated tokens')).toBeInTheDocument();
    expect(screen.getByText(/1 selected · 2 included/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Unavailable required capabilities: code_graph.read');
    fireEvent.click(screen.getByText('Inspect compiled text'));
    expect(screen.getByText('The reviewed finding is ready.')).toBeInTheDocument();
  });
});

describe('Context Set save interaction', () => {
  it('saves the selected objects through the Context Lens action', () => {
    const onSaveContextSet = vi.fn();
    const selectedNodes = [
      {
        id: 'selected-bridge',
        position: { x: 0, y: 0 },
        data: {
          kind: 'bridge',
          title: 'Reviewed handoff',
          body: 'Selected conclusion',
          density: 'compact',
          layer: 'knowledge',
          workspaceObjectType: 'context_bridge',
        },
      },
      {
        id: 'selected-note',
        position: { x: 120, y: 0 },
        data: {
          kind: 'note',
          title: 'Source note',
          body: 'Supporting context',
          density: 'compact',
          layer: 'knowledge',
          workspaceObjectType: 'manual_note',
        },
      },
    ] as AuraFlowNode[];

    render(
      <ContextLensBar
        nodes={selectedNodes}
        onAsk={vi.fn()}
        onCreateNote={vi.fn()}
        onCreateBridge={vi.fn()}
        onCreateBranch={vi.fn()}
        onSaveContextSet={onSaveContextSet}
        mergeTargets={[]}
        onMergeInto={vi.fn()}
        onClear={vi.fn()}
      />,
    );

    expect(screen.getByText('2 objects selected')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Save Context Set/i }));
    expect(onSaveContextSet).toHaveBeenCalledOnce();
  });
});
