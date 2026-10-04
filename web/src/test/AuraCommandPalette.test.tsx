import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuraCommandPalette } from '../components/chat/AuraCommandPalette';
import { api } from '../services/api';

describe('AuraCommandPalette', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows backend search matches with their actual excerpts and opens the selected object', async () => {
    const result = {
      object_id: 'note-1', object_type: 'manual_note', title: 'Memory constraints',
      excerpt: 'Keep the project notes explicit.', project_name: null, created_by: 'user', updated_at: '2026-10-05T10:00:00Z',
    };
    const search = vi.spyOn(api, 'searchWorkspace').mockResolvedValue({ items: [result], nextCursor: null });
    const onOpenResult = vi.fn();
    render(<AuraCommandPalette projectName="AURA" onClose={() => {}} onOpenResult={onOpenResult} />);

    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved workspace content' }), { target: { value: 'memory' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    await waitFor(() => expect(screen.getByText('Memory constraints')).toBeInTheDocument());
    expect(search).toHaveBeenCalledWith('memory', 'AURA');
    expect(screen.getByRole('button', { name: /Memory constraints/ })).toHaveTextContent('Keep the project notes explicit.');
    expect(screen.queryByText(/The workspace has .* saved Library references/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Memory constraints/ }));
    expect(onOpenResult).toHaveBeenCalledWith(result);
  });

  it('reports an empty result set without inventing an answer or sources', async () => {
    vi.spyOn(api, 'searchWorkspace').mockResolvedValue({ items: [], nextCursor: null });
    render(<AuraCommandPalette onClose={() => {}} onOpenResult={() => {}} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved workspace content' }), { target: { value: 'unmatched phrase' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('No saved workspace objects matched “unmatched phrase”.')).toBeInTheDocument();
    expect(screen.queryByText('Stateful Architecture')).not.toBeInTheDocument();
  });

  it('loads another backend page for the submitted query', async () => {
    const first = {
      object_id: 'note-1', object_type: 'manual_note', title: 'First match', excerpt: 'First excerpt',
      project_name: null, created_by: 'user', updated_at: '2026-10-05T10:00:00Z',
    };
    const second = {
      ...first, object_id: 'note-2', title: 'Second match', excerpt: 'Second excerpt',
    };
    const search = vi.spyOn(api, 'searchWorkspace')
      .mockResolvedValueOnce({ items: [first], nextCursor: 'next-page' })
      .mockResolvedValueOnce({ items: [second], nextCursor: null });
    render(<AuraCommandPalette onClose={() => {}} onOpenResult={() => {}} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved workspace content' }), { target: { value: 'evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('First match')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more results' }));
    expect(await screen.findByText('Second match')).toBeInTheDocument();
    expect(search).toHaveBeenNthCalledWith(2, 'evidence', undefined, 'next-page');
  });
});
