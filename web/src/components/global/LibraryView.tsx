import {
  BookOpen,
  ExternalLink,
  File,
  FileCode2,
  FileImage,
  FileJson2,
  FileSpreadsheet,
  FileText,
  FolderOpen,
  Grid2X2,
  Link2,
  List,
  MoreHorizontal,
  Plus,
  Search,
  Trash2,
  Unplug,
  Upload,
  X,
} from 'lucide-react';
import { useMemo, useRef, useState } from 'react';
import { projects, type LibraryItem } from '../../data/workspaceData';
import type { DirectoryConnection } from '../../lib/folderConnections';

type LibraryViewMode = 'list' | 'grid';

interface LibraryViewProps {
  items: LibraryItem[];
  connections: DirectoryConnection[];
  directoryPickerSupported: boolean;
  onOpenItem: (item: LibraryItem) => void;
  onImportFiles: (files: File[]) => void;
  onToggleProjectLink: (itemId: string, projectId: string) => void;
  onRemoveItem: (item: LibraryItem) => void;
  onConnectFolder: () => void;
  onOpenConnection: (connection: DirectoryConnection) => void;
  onDisconnectConnection: (connection: DirectoryConnection) => void;
}

const collections = ['All', 'Study', 'Books', 'Research', 'Reference'] as const;

function iconFor(item: LibraryItem) {
  if (item.kind === 'HTML') return FileCode2;
  if (item.kind === 'CSV') return FileSpreadsheet;
  if (item.kind === 'PDF' || item.kind === 'MD' || item.kind === 'TXT') return FileText;
  if (item.kind === 'JSON') return FileJson2;
  if (item.kind === 'IMAGE') return FileImage;
  return File;
}

function formatSize(size?: number) {
  if (!size) return null;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function LibraryView({
  items: libraryItems,
  connections,
  directoryPickerSupported,
  onOpenItem,
  onImportFiles,
  onToggleProjectLink,
  onRemoveItem,
  onConnectFolder,
  onOpenConnection,
  onDisconnectConnection,
}: LibraryViewProps) {
  const [collection, setCollection] = useState<(typeof collections)[number]>('All');
  const [query, setQuery] = useState('');
  const [view, setView] = useState<LibraryViewMode>('list');
  const [linkingId, setLinkingId] = useState<string | null>(null);
  const [menuId, setMenuId] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return libraryItems.filter((item) => {
      const inCollection = collection === 'All' || item.collection === collection;
      const searchable = `${item.name} ${item.detail} ${item.tags.join(' ')}`.toLowerCase();
      return inCollection && (!q || searchable.includes(q));
    });
  }, [collection, libraryItems, query]);

  return (
    <section className="library-view library-view--explorer">
      <div className="library-view__header library-view__header--roomy">
        <div>
          <span className="eyebrow">PERSONAL LIBRARY</span>
          <h1>Your files can stay where they already live.</h1>
          <p>Connect real folders from anywhere on your computer, or import individual files into AURA's browser-local index. Projects and collections only reference them.</p>
        </div>
        <div className="library-header-actions">
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []) as File[];
              if (files.length) onImportFiles(files);
              event.target.value = '';
            }}
          />
          <button className="primary-soft-button primary-soft-button--lg" type="button" onClick={onConnectFolder}><FolderOpen size={17} /> Connect folder</button>
          <button className="secondary-button secondary-button--lg" type="button" onClick={() => inputRef.current?.click()}><Upload size={16} /> Add files</button>
        </div>
      </div>

      {!directoryPickerSupported ? (
        <div className="browser-capability-note"><FolderOpen size={17} /><span><strong>Folder connections need Chrome or Edge on localhost/HTTPS.</strong> This browser does not expose the File System Access directory picker, so individual file imports still work.</span></div>
      ) : null}

      <section className="library-section library-section--connections">
        <div className="library-section-head">
          <div><FolderOpen size={17} /><span><strong>Connected folders</strong><small>Original filesystem locations · no copies</small></span></div>
          <span className="library-section-count">{connections.length}</span>
        </div>
        {connections.length ? (
          <div className="folder-connection-grid">
            {connections.map((connection) => (
              <article className="folder-connection-card" key={connection.id}>
                <button type="button" className="folder-connection-card__main" onClick={() => onOpenConnection(connection)}>
                  <span className="folder-connection-icon"><FolderOpen size={22} /></span>
                  <span><strong>{connection.name}</strong><small>Connected folder</small><em>Browse the original files</em></span>
                </button>
                <div className="folder-connection-card__actions">
                  <button type="button" className="secondary-button" onClick={() => onOpenConnection(connection)}>Open</button>
                  <button type="button" className="icon-button" onClick={() => onDisconnectConnection(connection)} title="Disconnect from AURA"><Unplug size={16} /></button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <button className="connect-folder-empty" type="button" onClick={onConnectFolder}>
            <FolderOpen size={26} />
            <span><strong>Connect your first folder</strong><small>Pick Books, Downloads, Papers, TOEIC, a project folder, or any other directory. AURA keeps a permission handle instead of moving the data.</small></span>
            <Plus size={18} />
          </button>
        )}
      </section>

      <section className="library-section library-section--index">
        <div className="library-section-head library-section-head--stackable">
          <div><BookOpen size={17} /><span><strong>Indexed files & artifacts</strong><small>Virtual collections and project references</small></span></div>
          <span className="library-section-count">{libraryItems.length}</span>
        </div>

        <div className="library-toolbar library-toolbar--comfortable">
          <label className="library-search"><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search files, tags, notes…" /></label>
          <div className="library-collections">{collections.map((item) => <button key={item} type="button" className={collection === item ? 'is-active' : ''} onClick={() => setCollection(item)}>{item}</button>)}</div>
          <div className="library-view-switch"><button type="button" className={view === 'list' ? 'is-active' : ''} onClick={() => setView('list')} title="List view"><List size={16} /></button><button type="button" className={view === 'grid' ? 'is-active' : ''} onClick={() => setView('grid')} title="Grid view"><Grid2X2 size={16} /></button></div>
        </div>

        <div className={`library-items library-items--${view} library-items--v8`}>
          {items.map((item) => {
            const Icon = iconFor(item);
            const linkedProjects = (item.projectLinks ?? []).map((id) => projects.find((project) => project.id === id)).filter(Boolean);
            return (
              <article key={item.id} className={`library-item library-item--${view} library-item--v8`}>
                <button className="library-item__open" type="button" onClick={() => onOpenItem(item)}>
                  <span className={`library-file-icon library-file-icon--${item.kind.toLowerCase()}`}><Icon size={20} /></span>
                  <span className="library-item__copy">
                    <strong>{item.name}</strong>
                    <small>{item.detail}</small>
                    <span>{item.collection} · {item.updated}{formatSize(item.size) ? ` · ${formatSize(item.size)}` : ''}</span>
                  </span>
                </button>

                <div className="library-item__links">
                  <span className="library-origin">{item.source === 'imported' ? 'AURA INDEX' : item.kind}</span>
                  {linkedProjects.slice(0, 2).map((project) => project ? <span key={project.id} className={`library-project-chip library-project-chip--${project.accent}`}><span className={`project-dot project-dot--${project.accent}`} />{project.name}</span> : null)}
                  {linkedProjects.length > 2 ? <span className="library-project-more">+{linkedProjects.length - 2}</span> : null}
                  <button className="library-link-trigger" type="button" onClick={() => { setLinkingId(linkingId === item.id ? null : item.id); setMenuId(null); }}><Link2 size={14} /> Link</button>
                  <button className="icon-button icon-button--lg" type="button" onClick={() => { setMenuId(menuId === item.id ? null : item.id); setLinkingId(null); }} title="File actions"><MoreHorizontal size={18} /></button>
                </div>

                {menuId === item.id ? (
                  <div className="library-action-popover">
                    <button type="button" onClick={() => { onOpenItem(item); setMenuId(null); }}><ExternalLink size={15} /><span><strong>Open</strong><small>Open this file or artifact</small></span></button>
                    <button type="button" className="is-danger" onClick={() => { onRemoveItem(item); setMenuId(null); }}><Trash2 size={15} /><span><strong>Remove from Library</strong><small>{item.source === 'imported' ? 'Delete AURA’s indexed copy, not an external folder' : 'Remove this reference from the prototype'}</small></span></button>
                  </div>
                ) : null}

                {linkingId === item.id ? (
                  <div className="library-link-popover">
                    <div><strong>Link to projects</strong><button className="icon-button" type="button" onClick={() => setLinkingId(null)}><X size={15} /></button></div>
                    {projects.map((project) => {
                      const linked = item.projectLinks?.includes(project.id) ?? false;
                      return <button key={project.id} type="button" className={linked ? 'is-linked' : ''} onClick={() => onToggleProjectLink(item.id, project.id)}><span className={`project-dot project-dot--${project.accent}`} /><span><strong>{project.name}</strong><small>{linked ? 'Linked' : 'Not linked'}</small></span>{linked ? <X size={14} /> : <Plus size={14} />}</button>;
                    })}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>

        {!items.length ? <div className="library-empty"><File size={26} /><strong>No files here yet.</strong><span>Change the filter, connect a folder, or import a local file.</span></div> : null}
      </section>
    </section>
  );
}
