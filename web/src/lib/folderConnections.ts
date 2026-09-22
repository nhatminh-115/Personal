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
const DB_VERSION = 1;

function openDb(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    return Promise.reject(new Error('IndexedDB is not supported in this environment'));
  }
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) db.createObjectStore(STORE_NAME, { keyPath: 'id' });
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

export async function removeDirectoryConnection(id: string): Promise<void> {
  const db = await openDb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    tx.objectStore(STORE_NAME).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Failed to remove folder connection'));
  });
  db.close();
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
