import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { BoardObjectInspector } from '../components/board/BoardObjectInspector';
import type { AuraFlowNode } from '../types';

function makeNode(id: string, title: string): AuraFlowNode {
  return {
    id,
    position: { x: 0, y: 0 },
    data: {
      kind: 'answer',
      eyebrow: 'Kuractus RESPONSE',
      title,
      body: `${title} description`,
      density: 'compact',
      accent: 'purple',
      layer: 'conversation',
      workspaceObjectType: 'conversation_branch',
      workspaceCreatedBy: 'assistant',
      workspaceRevision: 2,
    },
  } as AuraFlowNode;
}

describe('BoardObjectInspector', () => {
  it('shows object provenance and follows linked objects', () => {
    const node = makeNode('object-1', 'Root response');
    const related = makeNode('object-2', 'Follow-up branch');
    const onSelectRelationship = vi.fn();
    render(
      <BoardObjectInspector
        node={node}
        relationships={[{ id: 'edge-1', node: related, direction: 'Outgoing', label: 'reply' }]}
        onClose={vi.fn()}
        onSelectRelationship={onSelectRelationship}
      />,
    );

    expect(screen.getByText('Root response')).toBeInTheDocument();
    expect(screen.getByText('Kuractus-generated')).toBeInTheDocument();
    expect(screen.getByText('conversation branch')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open related object Follow-up branch' }));
    expect(onSelectRelationship).toHaveBeenCalledWith(related);
  });

  it('sends the selected object to Kuractus and can be dismissed', () => {
    const node = makeNode('object-1', 'Root response');
    const onAskWithContext = vi.fn();
    const onClose = vi.fn();
    render(
      <BoardObjectInspector
        node={node}
        relationships={[]}
        onClose={onClose}
        onSelectRelationship={vi.fn()}
        onAskWithContext={onAskWithContext}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: /Ask Kuractus with this object/ }));
    expect(onAskWithContext).toHaveBeenCalledWith(
      'Review “Root response” and explain its relationship to the surrounding project context.',
      ['object-1'],
    );
    fireEvent.click(screen.getByRole('button', { name: 'Close object inspector' }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
