import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AuraCommandPalette } from '../components/chat/AuraCommandPalette';
import { api } from '../services/api';
import * as folderConnections from '../lib/folderConnections';

describe('AuraCommandPalette', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows backend search matches with their actual excerpts and opens the selected object', async () => {
    const result = {
      object_id: 'note-1', object_type: 'manual_note', title: 'Memory constraints',
      excerpt: 'Keep the project notes explicit.', project_name: null, created_by: 'user', updated_at: '2026-10-05T10:00:00Z',
    };
    const search = vi.spyOn(api, 'searchWorkspace').mockResolvedValue({ items: [result], nextCursor: null });
    const onOpenResult = vi.fn();
    render(<AuraCommandPalette projectName="AURA" onClose={() => {}} onOpenResult={onOpenResult} onOpenFile={() => {}} />);

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
    render(<AuraCommandPalette onClose={() => {}} onOpenResult={() => {}} onOpenFile={() => {}} />);
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
    render(<AuraCommandPalette onClose={() => {}} onOpenResult={() => {}} onOpenFile={() => {}} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved workspace content' }), { target: { value: 'evidence' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    expect(await screen.findByText('First match')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Load more results' }));
    expect(await screen.findByText('Second match')).toBeInTheDocument();
    expect(search).toHaveBeenNthCalledWith(2, 'evidence', undefined, 'next-page');
  });

  it('searches connected-folder names locally and opens them only through an explicit result action', async () => {
    vi.spyOn(api, 'searchWorkspace').mockResolvedValue({ items: [], nextCursor: null });
    const localSearch = vi.spyOn(folderConnections, 'searchDirectoryIndexes').mockResolvedValue([{
      connectionId: 'folder-1', connectionName: 'Research', relativePath: 'papers/architecture.pdf',
      name: 'architecture.pdf', size: 8192, lastModified: Date.parse('2026-10-04T10:00:00Z'), mimeType: 'application/pdf',
    }]);
    const onOpenFile = vi.fn();
    render(<AuraCommandPalette onClose={() => {}} onOpenResult={() => {}} onOpenFile={onOpenFile} />);
    fireEvent.change(screen.getByRole('textbox', { name: 'Search saved workspace content' }), { target: { value: 'architecture' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));

    const resultButton = await screen.findByRole('button', { name: /architecture\.pdf/ });
    expect(localSearch).toHaveBeenCalledWith('architecture');
    expect(screen.getByText(/browser-local connected-folder names/)).toBeInTheDocument();
    fireEvent.click(resultButton);
    expect(onOpenFile).toHaveBeenCalledWith(expect.objectContaining({
      source: 'connected-folder', connection_id: 'folder-1', relative_path: 'papers/architecture.pdf',
    }));
  });
});
