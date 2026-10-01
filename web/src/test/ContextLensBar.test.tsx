import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ContextLensBar } from '../components/board/ContextLensBar';
import { buildMergedContinuation } from '../components/board/contextActions';
import type { AuraFlowNode } from '../types';

const selectedNodes = [
  { id: 'turn-a', data: { kind: 'user', title: 'Source A', layer: 'conversation' } },
  { id: 'turn-b', data: { kind: 'answer', title: 'Source B', layer: 'conversation' } },
] as AuraFlowNode[];

describe('Context Lens actions', () => {
  it('builds a new merged continuation from the destination branch and selected objects without duplicates', () => {
    expect(buildMergedContinuation(
      { id: 'branch-a', title: 'Branch A' },
      [{ id: 'branch-a', title: 'Branch A' }, { id: 'source-b', title: 'Source B' }],
    )).toEqual({
      object_type: 'conversation_branch',
      title: 'Merged continuation from Branch A',
      content: '',
      metadata_json: {
        branch_source_title: 'Branch A',
        merged_into_branch_id: 'branch-a',
        source_count: 2,
        source_titles: ['Branch A', 'Source B'],
      },
      source_object_ids: ['branch-a', 'source-b'],
    });
  });

  it('keeps Save Context Set separate from merging into a destination branch', () => {
    const onSaveContextSet = vi.fn();
    const onMergeInto = vi.fn();
    render(<ContextLensBar
      nodes={selectedNodes}
      onAsk={vi.fn()}
      onCreateNote={vi.fn()}
      onCreateBridge={vi.fn()}
      onCreateBranch={vi.fn()}
      onSaveContextSet={onSaveContextSet}
      mergeTargets={[{ id: 'branch-a', title: 'Branch A' }]}
      onMergeInto={onMergeInto}
      onClear={vi.fn()}
    />);

    fireEvent.click(screen.getByRole('button', { name: /Save Context Set/i }));
    expect(onSaveContextSet).toHaveBeenCalledOnce();
    expect(onMergeInto).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: /Merge Into/i }));
    fireEvent.change(screen.getByLabelText('Destination branch'), { target: { value: 'branch-a' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create merged continuation' }));
    expect(onMergeInto).toHaveBeenCalledWith('branch-a');
    expect(onSaveContextSet).toHaveBeenCalledOnce();
  });

  it('does not offer a merge action when no saved destination branch exists', () => {
    render(<ContextLensBar
      nodes={selectedNodes}
      onAsk={vi.fn()}
      onCreateNote={vi.fn()}
      onCreateBridge={vi.fn()}
      onCreateBranch={vi.fn()}
      onSaveContextSet={vi.fn()}
      mergeTargets={[]}
      onMergeInto={vi.fn()}
      onClear={vi.fn()}
    />);

    fireEvent.click(screen.getByRole('button', { name: /Merge Into/i }));
    expect(screen.getByRole('status')).toHaveTextContent('Create a branch before merging selected context into it.');
    expect(screen.queryByRole('button', { name: 'Create merged continuation' })).not.toBeInTheDocument();
  });
});
