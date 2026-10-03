import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AIContextPanel } from '../components/chat/AIContextPanel';

describe('AI context object pagination', () => {
  it('loads older saved objects on demand and exposes retry after an error', () => {
    const onLoadOlder = vi.fn(async () => {});
    const onRetry = vi.fn();
    const props = {
      items: [{ id: 'context-1', nodeId: 'object-1', kind: 'note' as const, title: 'Latest note', detail: 'manual note', tokens: 20, included: false }],
      contextIsLive: true,
      hasMore: true,
      onLoadOlder,
      onToggleItem: vi.fn(),
      onClose: vi.fn(),
    };
    const { rerender } = render(<AIContextPanel {...props} />);

    fireEvent.click(screen.getByRole('button', { name: 'Load older objects' }));
    expect(onLoadOlder).toHaveBeenCalledTimes(1);

    rerender(<AIContextPanel {...props} loadError="Older page unavailable" onRetry={onRetry} />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);

    rerender(<AIContextPanel {...props} loadingOlder />);
    expect(screen.getByRole('button', { name: 'Loading older objects…' })).toBeDisabled();
  });

  it('distinguishes loading from an empty live project', () => {
    render(<AIContextPanel items={[]} contextIsLive loading onToggleItem={() => {}} onClose={() => {}} />);
    expect(screen.getByText('Loading saved project objects…')).toBeInTheDocument();
  });
});
