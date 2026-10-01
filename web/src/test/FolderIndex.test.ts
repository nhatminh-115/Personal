import { describe, expect, it, vi } from 'vitest';
import { collectIndexedFolderFiles, filterIndexedFolderFiles, type AuraFileSystemDirectoryHandle, type AuraFileSystemFileHandle, type DirectoryConnection } from '../lib/folderConnections';

const connection: DirectoryConnection = { id: 'connected-1', name: 'Research', createdAt: 1, updatedAt: 1 };

function fileHandle(name: string, contents: string): AuraFileSystemFileHandle {
  return {
    kind: 'file',
    name,
    getFile: vi.fn(async () => new File([contents], name, { type: 'text/plain', lastModified: 1_760_000_000_000 })),
  };
}

function directoryHandle(name: string, children: Array<AuraFileSystemFileHandle | AuraFileSystemDirectoryHandle>): AuraFileSystemDirectoryHandle {
  return {
    kind: 'directory',
    name,
    async *values() { yield* children; },
    getDirectoryHandle: vi.fn(async () => { throw new Error('Not used by indexing'); }),
    getFileHandle: vi.fn(async () => { throw new Error('Not used by indexing'); }),
  };
}

describe('connected folder metadata index', () => {
  it('collects names and file metadata without indexing file contents', async () => {
    const readme = fileHandle('readme.txt', 'private document body');
    const nested = directoryHandle('papers', [fileHandle('study.pdf', 'private PDF bytes')]);
    const root = directoryHandle('Research', [readme, nested]);

    const result = await collectIndexedFolderFiles(connection, root);

    expect(result.truncated).toBe(false);
    expect(result.files.map((file) => file.relativePath).sort()).toEqual(['papers/study.pdf', 'readme.txt']);
    expect(result.files.find((file) => file.name === 'readme.txt')).toMatchObject({
      connectionId: 'connected-1', connectionName: 'Research', size: 21, mimeType: 'text/plain',
    });
    expect(Object.keys(result.files[0]).sort()).toEqual(['connectionId', 'connectionName', 'lastModified', 'mimeType', 'name', 'relativePath', 'size']);
    expect(readme.getFile).toHaveBeenCalledOnce();
  });

  it('matches names and relative paths case-insensitively with a bounded result count', () => {
    const files = ['book.pdf', 'notes.txt', 'book-backup.md'].map((name) => ({
      connectionId: 'connected-1', connectionName: 'Research', relativePath: `library/${name}`,
      name, size: 10, lastModified: 1, mimeType: 'text/plain',
    }));

    expect(filterIndexedFolderFiles(files, 'BOOK', 1).map((file) => file.name)).toEqual(['book.pdf']);
    expect(filterIndexedFolderFiles(files, 'library/notes').map((file) => file.name)).toEqual(['notes.txt']);
    expect(filterIndexedFolderFiles(files, '   ')).toEqual([]);
  });
});
