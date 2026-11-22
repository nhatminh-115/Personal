import {
  ArrowLeft,
  ArrowUp,
  ChevronRight,
  File,
  FileCode2,
  FileImage,
  FileJson2,
  FileSpreadsheet,
  FileText,
  Folder,
  FolderOpen,
  MoreHorizontal,
  RefreshCw,
  Search,
  Unplug,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getDirectoryIndexSnapshot,
  getDirectoryConnectionHandle,
  getFileAccessProvider,
  indexDirectoryConnection,
  listDirectoryEntries,
  type DirectoryBrowseEntry,
  type DirectoryConnection,
} from '../../lib/folderConnections';

interface ConnectedFolderViewProps {
  connection: DirectoryConnection;
  onBackToLibrary: () => void;
  onDisconnect: (connection: DirectoryConnection) => void;
  onOpenFile: (file: File, virtualPath: string) => void;
}

function iconForName(name: string) {
  const ext = name.split('.').pop()?.toLowerCase();
  if (ext === 'html' || ext === 'htm') return FileCode2;
  if (ext === 'csv' || ext === 'xlsx' || ext === 'xls') return FileSpreadsheet;
  if (ext === 'json') return FileJson2;
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'svg'].includes(ext ?? '')) return FileImage;
  if (['pdf', 'md', 'txt', 'doc', 'docx', 'epub', 'pptx'].includes(ext ?? '')) return FileText;
  return File;
}

export function ConnectedFolderView({ connection, onBackToLibrary, onDisconnect, onOpenFile }: ConnectedFolderViewProps) {
  const [path, setPath] = useState<string[]>([]);
  const [entries, setEntries] = useState<DirectoryBrowseEntry[]>([]);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [permissionBlocked, setPermissionBlocked] = useState(false);
  const [directoryTruncated, setDirectoryTruncated] = useState(false);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [indexSnapshot, setIndexSnapshot] = useState<{ indexedAt: number; fileCount: number; truncated: boolean } | null>(null);
  const [indexing, setIndexing] = useState(false);
  const [indexProgress, setIndexProgress] = useState(0);
  const [indexError, setIndexError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void getDirectoryIndexSnapshot(connection.id).then((snapshot) => { if (active) setIndexSnapshot(snapshot); });
    return () => { active = false; };
  }, [connection.id]);

  const indexForSearch = useCallback(async () => {
    setIndexing(true);
    setIndexError(null);
    setIndexProgress(0);
    try {
      const snapshot = await indexDirectoryConnection(connection, setIndexProgress);
      setIndexSnapshot(snapshot);
    } catch (error) {
      setIndexError((error as Error)?.message ?? 'AURA could not index this folder.');
    } finally {
      setIndexing(false);
    }
  }, [connection]);

  const loadDirectory = useCallback(async () => {
    setLoading(true);
    setPermissionBlocked(false);
    try {
      const snapshot = await listDirectoryEntries(connection.id, path.join('/'));
      setEntries(snapshot.entries);
      setDirectoryTruncated(snapshot.truncated);
    } catch {
      setEntries([]);
      setPermissionBlocked(true);
    } finally {
      setLoading(false);
    }
  }, [connection.id, path, refreshNonce]);

  useEffect(() => { void loadDirectory(); }, [loadDirectory]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? entries.filter((entry) => entry.name.toLowerCase().includes(q)) : entries;
  }, [entries, query]);

  const openEntry = useCallback(async (entry: DirectoryBrowseEntry) => {
    if (entry.kind === 'directory') {
      setPath((current) => [...current, entry.name]);
      setQuery('');
      return;
    }
    try {
      const file = await getFileAccessProvider().openFolderFile(connection.id, entry.relativePath);
      onOpenFile(file, [connection.name, entry.relativePath].join('/'));
    } catch {
      // Permission changes are reflected on the next refresh.
    }
  }, [connection.id, connection.name, onOpenFile]);

  const restoreFolderAccess = async () => {
    if (getFileAccessProvider().kind === 'browser') {
      try {
        const root = await getDirectoryConnectionHandle(connection.id);
        if (root?.requestPermission && await root.requestPermission({ mode: 'read' }) !== 'granted') return;
      } catch {
        // Reconnecting from Library remains available if the saved browser handle expired.
      }
    }
    setRefreshNonce((value) => value + 1);
  };

  const crumbs = [connection.name, ...path];

  return (
    <section className="folder-explorer-view">
      <header className="folder-explorer-header">
        <div className="folder-explorer-heading">
          <button className="icon-button icon-button--lg" type="button" onClick={onBackToLibrary} title="Back to Library"><ArrowLeft size={18} /></button>
          <span className="folder-explorer-heading__icon"><FolderOpen size={20} /></span>
          <div>
            <span className="eyebrow">CONNECTED FOLDER</span>
            <h1>{connection.name}</h1>
            <p>AURA is browsing the original folder. Nothing is copied into the workspace.</p>
          </div>
        </div>
        <div className="folder-explorer-actions">
          <button className="secondary-button" type="button" onClick={() => setRefreshNonce((value) => value + 1)}><RefreshCw size={15} /> Refresh</button>
          <button className="secondary-button" type="button" disabled={indexing} onClick={() => void indexForSearch()}><Search size={15} /> {indexing ? `Indexing ${indexProgress.toLocaleString()}…` : indexSnapshot ? 'Refresh search index' : 'Index filenames'}</button>
          <button className="danger-quiet-button" type="button" onClick={() => onDisconnect(connection)}><Unplug size={15} /> Disconnect</button>
        </div>
      </header>

      <div className="folder-index-status" role="status">
        {indexing ? `Indexing file names and metadata (${indexProgress.toLocaleString()} found)…`
          : indexSnapshot ? `${indexSnapshot.fileCount.toLocaleString()} file names indexed for workspace search · updated ${new Date(indexSnapshot.indexedAt).toLocaleString()}${indexSnapshot.truncated ? ' · scan limit reached' : ''}`
            : 'This folder is not indexed for workspace search yet.'}
        <span>File contents stay in the original folder.</span>
      </div>
      {indexError ? <div className="folder-index-error" role="alert">{indexError}</div> : null}

      <div className="explorer-command-row">
        <div className="explorer-nav-buttons">
          <button className="icon-button icon-button--lg" type="button" disabled={!path.length} onClick={() => setPath((current) => current.slice(0, -1))} title="Up one folder"><ArrowUp size={18} /></button>
        </div>
        <div className="explorer-breadcrumbs" aria-label="Folder path">
          {crumbs.map((crumb, index) => (
            <span key={`${crumb}-${index}`} className="explorer-crumb-wrap">
              {index ? <ChevronRight size={14} /> : null}
              <button type="button" onClick={() => setPath(path.slice(0, Math.max(0, index)))}>{crumb}</button>
            </span>
          ))}
        </div>
        <label className="explorer-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${path.at(-1) ?? connection.name}`} /></label>
      </div>

      {permissionBlocked ? (
        <div className="folder-permission-card">
          <Folder size={28} />
          <div><strong>Folder access needs attention.</strong><span>{getFileAccessProvider().kind === 'browser' ? 'The browser may have revoked its saved permission. Grant access again or reconnect this folder from Library.' : 'AURA could not read the selected folder. Reconnect it from Library and try again.'}</span></div>
          <button className="primary-soft-button" type="button" onClick={() => void restoreFolderAccess()}>{getFileAccessProvider().kind === 'browser' ? 'Grant access' : 'Retry'}</button>
        </div>
      ) : (
        <div className="explorer-list-shell">
          <div className="explorer-list-head"><span>Name</span><span>Type</span><span>Location</span><span /></div>
          <div className="explorer-list-body">
            {loading ? <div className="explorer-loading">Reading folder…</div> : null}
            {!loading && !filtered.length ? <div className="explorer-loading">No matching items.</div> : null}
            {!loading ? filtered.map((entry) => {
              const Icon = entry.kind === 'directory' ? Folder : iconForName(entry.name);
              return (
                <div key={`${entry.kind}-${entry.name}`} className="explorer-row" role="button" tabIndex={0} onDoubleClick={() => void openEntry(entry)} onKeyDown={(event) => { if (event.key === 'Enter') void openEntry(entry); }}>
                  <span className={`explorer-row__name ${entry.kind === 'directory' ? 'is-folder' : ''}`}><Icon size={18} /><strong>{entry.name}</strong></span>
                  <span>{entry.kind === 'directory' ? 'Folder' : (entry.name.split('.').pop()?.toUpperCase() || 'File')}</span>
                  <span>{path.length ? `…/${path.join('/')}` : connection.name}</span>
                  <span className="explorer-row__actions"><button type="button" className="icon-button" onClick={() => void openEntry(entry)} title="Open"><MoreHorizontal size={17} /></button></span>
                </div>
              );
            }) : null}
          </div>
        </div>
      )}

      {directoryTruncated ? <div className="folder-index-error" role="status">This folder contains more than 2,000 entries. The list is limited to the first 2,000; narrow the folder or use filename indexing.</div> : null}

      <footer className="explorer-statusbar"><span>{entries.length} items</span><span>Read-only connected folder · filesystem remains the source of truth</span></footer>
    </section>
  );
}
