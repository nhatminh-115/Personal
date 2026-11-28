import { beforeEach, describe, expect, it, vi } from 'vitest';

const bridge = vi.hoisted(() => ({
  invoke: vi.fn(),
  isDesktop: vi.fn(() => true),
}));

vi.mock('@tauri-apps/api/core', () => ({
  invoke: (...args: unknown[]) => bridge.invoke(...args),
  isTauri: () => bridge.isDesktop(),
}));

import {
  getFileAccessProvider,
  getDirectoryIndexSnapshot,
  indexDirectoryConnection,
  listDirectoryConnections,
  listDirectoryEntries,
  openIndexedFolderFile,
  pickDirectoryConnection,
  removeDirectoryConnection,
  searchDirectoryIndexes,
  supportsDirectoryPicker,
  type DirectoryConnection,
  type IndexedFolderFile,
} from '../lib/folderConnections';

const connection: DirectoryConnection = { id: 'native-opaque-id', name: 'Research', createdAt: 1, updatedAt: 2 };

describe('Tauri desktop folder access provider', () => {
  beforeEach(() => bridge.invoke.mockReset());

  it('uses a native folder picker and returns an opaque connection reference', async () => {
    bridge.invoke.mockResolvedValue(connection);

    await expect(pickDirectoryConnection()).resolves.toEqual(connection);
    expect(bridge.invoke).toHaveBeenCalledWith('desktop_pick_folder');
    expect(supportsDirectoryPicker()).toBe(true);
  });

  it('browses native folders using relative paths and metadata only', async () => {
    const snapshot = {
      relativePath: 'papers',
      entries: [{ name: 'report.pdf', kind: 'file', relativePath: 'papers/report.pdf', size: 12, mimeType: 'application/pdf' }],
      truncated: false,
    };
    bridge.invoke.mockResolvedValue(snapshot);

    await expect(listDirectoryEntries(connection.id, 'papers')).resolves.toEqual(snapshot);
    expect(getFileAccessProvider().kind).toBe('desktop');
    expect(bridge.invoke).toHaveBeenCalledWith('desktop_list_folder_entries', {
      connectionId: connection.id,
      relativePath: 'papers',
    });
  });

  it('lists and removes native folder references by opaque ID', async () => {
    bridge.invoke.mockResolvedValueOnce([connection]).mockResolvedValueOnce(undefined);

    await expect(listDirectoryConnections()).resolves.toEqual([connection]);
    await expect(removeDirectoryConnection(connection.id)).resolves.toBeUndefined();
    expect(bridge.invoke).toHaveBeenNthCalledWith(2, 'desktop_remove_folder', { connectionId: connection.id });
  });

  it('indexes metadata and reports progress without reading file content', async () => {
    const progress = vi.fn();
    bridge.invoke.mockResolvedValue({ indexedAt: 100, fileCount: 12, truncated: false });

    await expect(indexDirectoryConnection(connection, progress)).resolves.toEqual({ indexedAt: 100, fileCount: 12, truncated: false });
    expect(progress).toHaveBeenCalledWith(12);
    expect(bridge.invoke).toHaveBeenCalledWith('desktop_index_folder', { connectionId: connection.id });
  });

  it('loads the persisted native folder index snapshot', async () => {
    const snapshot = { indexedAt: 100, fileCount: 12, truncated: false };
    bridge.invoke.mockResolvedValue(snapshot);

    await expect(getDirectoryIndexSnapshot(connection.id)).resolves.toEqual(snapshot);
    expect(bridge.invoke).toHaveBeenCalledWith('desktop_get_folder_index_snapshot', { connectionId: connection.id });
  });

  it('searches the metadata index and reads bytes only for an explicit file open', async () => {
    const file: IndexedFolderFile = {
      connectionId: connection.id,
      connectionName: connection.name,
      relativePath: 'papers/report.txt',
      name: 'report.txt',
      size: 6,
      lastModified: 3,
      mimeType: 'text/plain',
    };
    bridge.invoke.mockResolvedValueOnce([file]).mockResolvedValueOnce({
      name: 'report.txt',
      mimeType: 'text/plain',
      bytesBase64: 'c2VjcmV0',
    });

    await expect(searchDirectoryIndexes('report')).resolves.toEqual([file]);
    const opened = await openIndexedFolderFile(file);
    const openedText = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(reader.error);
      reader.readAsText(opened);
    });
    expect(openedText).toBe('secret');
    expect(bridge.invoke).toHaveBeenNthCalledWith(1, 'desktop_search_folder_indexes', { query: 'report', limit: 25 });
    expect(bridge.invoke).toHaveBeenNthCalledWith(2, 'desktop_read_folder_file', {
      connectionId: connection.id,
      relativePath: file.relativePath,
    });
  });
});
