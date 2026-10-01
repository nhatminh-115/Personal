import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ConnectedFolderView } from '../components/global/ConnectedFolderView';
import * as folderConnections from '../lib/folderConnections';

const connection: folderConnections.DirectoryConnection = { id: 'directory-1', name: 'Research', createdAt: 1, updatedAt: 1 };

describe('ConnectedFolderView', () => {
  it('lets the user explicitly index file names for unified search', async () => {
    const root: folderConnections.AuraFileSystemDirectoryHandle = {
      kind: 'directory', name: 'Research',
      async *values() {},
      getDirectoryHandle: vi.fn(async () => { throw new Error('Not used'); }),
      getFileHandle: vi.fn(async () => { throw new Error('Not used'); }),
    };
    vi.spyOn(folderConnections, 'getDirectoryConnectionHandle').mockResolvedValue(root);
    vi.spyOn(folderConnections, 'ensureReadPermission').mockResolvedValue(true);
    vi.spyOn(folderConnections, 'getDirectoryIndexSnapshot').mockResolvedValue(null);
    const index = vi.spyOn(folderConnections, 'indexDirectoryConnection').mockResolvedValue({ indexedAt: 100, fileCount: 3, truncated: false });

    render(<ConnectedFolderView connection={connection} onBackToLibrary={() => {}} onDisconnect={() => {}} onOpenFile={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'Index filenames' }));

    await waitFor(() => expect(index).toHaveBeenCalledWith(connection, expect.any(Function)));
    expect(await screen.findByText(/3 file names indexed for workspace search/)).toBeInTheDocument();
    expect(screen.getByText(/File contents stay in the original folder/)).toBeInTheDocument();
  });
});
