export type AuraFileSystemHandleKind = 'file' | 'directory';

export interface AuraFileSystemHandle {
  kind: AuraFileSystemHandleKind;
  name: string;
  isSameEntry?: (other: AuraFileSystemHandle) => Promise<boolean>;
  queryPermission?: (descriptor?: { mode?: 'read' | 'readwrite' }) => Promise<PermissionState>;
  requestPermission?: (descriptor?: { mode?: 'read' | 'readwrite' }) => Promise<PermissionState>;
}

export interface AuraFileSystemFileHandle extends AuraFileSystemHandle {
  kind: 'file';
  getFile: () => Promise<File>;
}

export interface AuraFileSystemDirectoryHandle extends AuraFileSystemHandle {
  kind: 'directory';
  values: () => AsyncIterableIterator<AuraFileSystemHandle>;
  getDirectoryHandle: (name: string, options?: { create?: boolean }) => Promise<AuraFileSystemDirectoryHandle>;
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<AuraFileSystemFileHandle>;
}

export interface DirectoryConnection {
  id: string;
  name: string;
  createdAt: number;
  updatedAt: number;
}

interface StoredConnection extends DirectoryConnection {
  handle: AuraFileSystemDirectoryHandle;
}

const DB_NAME = 'aura-folder-connections';
const STORE_NAME = 'connections';
const INDEX_STORE_NAME = 'file-indexes';
const DB_VERSION = 2;

export interface IndexedFolderFile {
  connectionId: string;
  connectionName: string;
  relativePath: string;
  name: string;
  size: number;
  lastModified: number;
  mimeType: string;
}

export interface DirectoryIndexSnapshot {
  indexedAt: number;
  fileCount: number;
  truncated: boolean;
}

interface StoredDirectoryIndex {
  connectionId: string;
  indexedAt: number;
  truncated: boolean;
  files: IndexedFolderFile[];
}

function openDb(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('IndexedDB is not supported in this environment'));
  }
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      if (!db.objectStoreNames.contains(INDEX_STORE_NAME)) db.createObjectStore(INDEX_STORE_NAME, { keyPath: 'connectionId' });
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Failed to open folder connection database'));
  });
}

function txRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

export async function saveDirectoryConnection(handle: AuraFileSystemDirectoryHandle): Promise<DirectoryConnection> {
  const db = await openDb();
  const now = Date.now();
  const existing = await listStoredConnections(db);
  const same = await findSameHandle(existing, handle);
  const record: StoredConnection = same
    ? { ...same, name: handle.name, updatedAt: now, handle }
    : { id: `dir-${crypto.randomUUID()}`, name: handle.name, createdAt: now, updatedAt: now, handle };

  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).put(record);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Failed to save folder connection'));
  });
  db.close();
  return stripHandle(record);
}

async function listStoredConnections(db?: IDBDatabase): Promise<StoredConnection[]> {
  const ownDb = db ?? await openDb();
  const tx = ownDb.transaction(STORE_NAME, 'readonly');
  const result = await txRequest(tx.objectStore(STORE_NAME).getAll()) as StoredConnection[];
  if (!db) ownDb.close();
  return result;
}

async function findSameHandle(records: StoredConnection[], handle: AuraFileSystemDirectoryHandle) {
  for (const record of records) {
    try {
      if (record.handle?.isSameEntry && await record.handle.isSameEntry(handle)) return record;
    } catch {
      // Ignore stale handles and fall through to creating a new connection.
    }
  }
  return undefined;
}

function stripHandle(record: StoredConnection): DirectoryConnection {
  const { id, name, createdAt, updatedAt } = record;
  return { id, name, createdAt, updatedAt };
}

export async function listDirectoryConnections(): Promise<DirectoryConnection[]> {
  try {
    const records = await listStoredConnections();
    return records
      .map(stripHandle)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  } catch {
    return [];
  }
}

export async function getDirectoryConnectionHandle(id: string): Promise<AuraFileSystemDirectoryHandle | null> {
  const db = await openDb();
  const tx = db.transaction(STORE_NAME, 'readonly');
  const record = await txRequest(tx.objectStore(STORE_NAME).get(id)) as StoredConnection | undefined;
  db.close();
  return record?.handle ?? null;
}

export async function indexDirectoryConnection(
  connection: DirectoryConnection,
  onProgress?: (fileCount: number) => void,
): Promise<DirectoryIndexSnapshot> {
  const root = await getDirectoryConnectionHandle(connection.id);
  if (!root) throw new Error('Connected folder is unavailable. Reconnect it from Library.');
  if (!await ensureReadPermission(root)) throw new Error('Read access is required to index this folder.');

  const { files, truncated } = await collectIndexedFolderFiles(connection, root, onProgress);
  const snapshot: StoredDirectoryIndex = { connectionId: connection.id, indexedAt: Date.now(), truncated, files };
  const db = await openDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(INDEX_STORE_NAME, 'readwrite');
      tx.objectStore(INDEX_STORE_NAME).put(snapshot);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('Failed to save folder file index'));
    });
  } finally { db.close(); }
  return { indexedAt: snapshot.indexedAt, fileCount: files.length, truncated };
}

export async function collectIndexedFolderFiles(
  connection: DirectoryConnection,
  root: AuraFileSystemDirectoryHandle,
  onProgress?: (fileCount: number) => void,
): Promise<{ files: IndexedFolderFile[]; truncated: boolean }> {
  const maxFiles = 5_000;
  const maxEntries = 10_000;
  const maxDepth = 24;
  const directories: Array<{ handle: AuraFileSystemDirectoryHandle; path: string; depth: number }> = [{ handle: root, path: '', depth: 0 }];
  const files: IndexedFolderFile[] = [];
  let truncated = false;
  let visitedEntries = 0;
  while (directories.length) {
    const current = directories.pop()!;
    for await (const handle of current.handle.values()) {
      visitedEntries += 1;
      if (visitedEntries > maxEntries) { truncated = true; break; }
      if (handle.kind === 'directory') {
        if (current.depth < maxDepth) directories.push({ handle: handle as AuraFileSystemDirectoryHandle, path: current.path ? `${current.path}/${handle.name}` : handle.name, depth: current.depth + 1 });
        else truncated = true;
        continue;
      }
      if (files.length >= maxFiles) { truncated = true; break; }
      const file = await (handle as AuraFileSystemFileHandle).getFile();
      const relativePath = current.path ? `${current.path}/${handle.name}` : handle.name;
      files.push({
        connectionId: connection.id,
        connectionName: connection.name,
        relativePath,
        name: handle.name,
        size: file.size,
        lastModified: file.lastModified,
        mimeType: file.type,
      });
      if (files.length % 250 === 0) onProgress?.(files.length);
    }
    if (truncated) break;
  }
  onProgress?.(files.length);
  return { files, truncated };
}

export async function getDirectoryIndexSnapshot(connectionId: string): Promise<DirectoryIndexSnapshot | null> {
  try {
    const db = await openDb();
    try {
      const tx = db.transaction(INDEX_STORE_NAME, 'readonly');
      const record = await txRequest(tx.objectStore(INDEX_STORE_NAME).get(connectionId)) as StoredDirectoryIndex | undefined;
      return record ? { indexedAt: record.indexedAt, fileCount: record.files.length, truncated: record.truncated } : null;
    } finally { db.close(); }
  } catch {
    return null;
  }
}

export async function searchDirectoryIndexes(query: string, limit = 25): Promise<IndexedFolderFile[]> {
  try {
    const normalized = query.trim().toLocaleLowerCase();
    if (!normalized) return [];
    const db = await openDb();
    try {
      const tx = db.transaction(INDEX_STORE_NAME, 'readonly');
      const records = await txRequest(tx.objectStore(INDEX_STORE_NAME).getAll()) as StoredDirectoryIndex[];
      return filterIndexedFolderFiles(records.flatMap((record) => record.files), normalized, limit);
    } finally { db.close(); }
  } catch {
    return [];
  }
}

export function filterIndexedFolderFiles(files: IndexedFolderFile[], query: string, limit = 25): IndexedFolderFile[] {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return [];
  return files.filter((file) =>
    `${file.name} ${file.relativePath} ${file.connectionName}`.toLocaleLowerCase().includes(normalized),
  ).slice(0, Math.min(50, Math.max(1, limit)));
}

export async function openIndexedFolderFile(file: IndexedFolderFile): Promise<File> {
  const root = await getDirectoryConnectionHandle(file.connectionId);
  if (!root || !await ensureReadPermission(root)) throw new Error('Folder access expired. Reconnect the folder and try again.');
  const parts = file.relativePath.split('/').filter(Boolean);
  if (!parts.length) throw new Error('Indexed file path is invalid.');
  let directory = root;
  for (const segment of parts.slice(0, -1)) directory = await directory.getDirectoryHandle(segment);
  return (await directory.getFileHandle(parts[parts.length - 1])).getFile();
}

export async function removeDirectoryConnection(id: string): Promise<void> {
  const db = await openDb();
  try {
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction([STORE_NAME, INDEX_STORE_NAME], 'readwrite');
      tx.objectStore(STORE_NAME).delete(id);
      tx.objectStore(INDEX_STORE_NAME).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error ?? new Error('Failed to remove folder connection'));
    });
  } finally { db.close(); }
}

export async function ensureReadPermission(handle: AuraFileSystemDirectoryHandle): Promise<boolean> {
  try {
    if (!handle.queryPermission) return true;
    const current = await handle.queryPermission({ mode: 'read' });
    if (current === 'granted') return true;
    if (!handle.requestPermission) return false;
    return await handle.requestPermission({ mode: 'read' }) === 'granted';
  } catch {
    return false;
  }
}

export function supportsDirectoryPicker(): boolean {
  return typeof (window as typeof window & { showDirectoryPicker?: unknown }).showDirectoryPicker === 'function';
}

export async function pickDirectoryConnection(): Promise<DirectoryConnection | null> {
  const picker = (window as typeof window & {
    showDirectoryPicker?: (options?: { mode?: 'read' | 'readwrite' }) => Promise<AuraFileSystemDirectoryHandle>;
  }).showDirectoryPicker;
  if (!picker) return null;
  const handle = await picker({ mode: 'read' });
  return saveDirectoryConnection(handle);
}
