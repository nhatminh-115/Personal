import { ArrowLeft, ExternalLink, File, FileCode2, FileSpreadsheet, FileText, Link2, Plus, Search, Upload, X } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { projectArtifacts, type LibraryItem, type ProjectRecord } from '../../data/workspaceData';

interface ProjectFilesViewProps {
  project: ProjectRecord;
  libraryItems: LibraryItem[];
  onBack: () => void;
  onOpenItem: (item: LibraryItem) => void;
  onImportFiles: (files: File[], projectId: string) => void;
  onToggleProjectLink: (itemId: string, projectId: string, candidate?: LibraryItem) => void;
  hasMoreLibrary?: boolean;
  loadingMoreLibrary?: boolean;
  libraryLoadError?: string | null;
  onLoadMoreLibrary?: () => void;
  searchItems?: LibraryItem[];
  searchHasMore?: boolean;
  searchLoading?: boolean;
  searchError?: string | null;
  onSearchLibrary?: (query: string) => void;
  onLoadMoreSearch?: () => void;
  linkCandidates?: LibraryItem[];
  linkCandidatesHasMore?: boolean;
  linkCandidatesLoading?: boolean;
  linkCandidatesError?: string | null;
  onSearchLinkCandidates?: (query: string) => void;
  onLoadMoreLinkCandidates?: () => void;
}

function iconForKind(kind: string) {
  if (kind === 'HTML' || kind === 'CODE') return FileCode2;
  if (kind === 'CSV') return FileSpreadsheet;
  if (kind === 'PDF' || kind === 'MD' || kind === 'NOTE') return FileText;
  return File;
}

export function ProjectFilesView({ project, libraryItems, onBack, onOpenItem, onImportFiles, onToggleProjectLink, hasMoreLibrary = false, loadingMoreLibrary = false, libraryLoadError, onLoadMoreLibrary, searchItems = [], searchHasMore = false, searchLoading = false, searchError, onSearchLibrary, onLoadMoreSearch, linkCandidates = [], linkCandidatesHasMore = false, linkCandidatesLoading = false, linkCandidatesError, onSearchLinkCandidates, onLoadMoreLinkCandidates }: ProjectFilesViewProps) {
  const [query, setQuery] = useState('');
  const [linkOpen, setLinkOpen] = useState(false);
  const [linkQuery, setLinkQuery] = useState('');
  const inputRef = useRef<HTMLInputElement | null>(null);
  const linked = useMemo(() => (query.trim() ? searchItems : libraryItems).filter((item) => item.projectLinks?.includes(project.id)), [libraryItems, project.id, query, searchItems]);
  const available = useMemo(() => linkCandidates.filter((item) => !item.projectLinks?.includes(project.id)), [linkCandidates, project.id]);
  const localArtifacts = useMemo(() => projectArtifacts.filter((item) => item.projectId === project.id), [project.id]);
  const q = query.trim().toLowerCase();
  const filteredLinked = linked.filter((item) => !q || `${item.name} ${item.collection} ${item.detail} ${item.tags.join(' ')}`.toLowerCase().includes(q));
  const filteredLocal = localArtifacts.filter((item) => !q || `${item.name} ${item.detail}`.toLowerCase().includes(q));

  useEffect(() => {
    const timer = window.setTimeout(() => onSearchLibrary?.(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [onSearchLibrary, query]);

  useEffect(() => {
    if (!linkOpen) return;
    const timer = window.setTimeout(() => onSearchLinkCandidates?.(linkQuery.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [linkOpen, linkQuery, onSearchLinkCandidates]);

  return (
    <section className="project-files-view">
      <div className="project-files-head">
        <div>
          <button className="back-link" type="button" onClick={onBack}><ArrowLeft size={14} /> Project overview</button>
          <span className="eyebrow">PROJECT FILES</span>
          <h1>{project.name}</h1>
          <p>Project-local artifacts stay here. Personal files are linked from Library instead of duplicated.</p>
        </div>
        <div className="project-files-actions">
          <input
            ref={inputRef}
            type="file"
            multiple
            hidden
            onChange={(event) => {
              const files = Array.from(event.target.files ?? []) as File[];
              if (files.length) onImportFiles(files, project.id);
              event.target.value = '';
            }}
          />
          <button className="soft-action-button" type="button" onClick={() => setLinkOpen((value) => !value)}><Link2 size={14} /> Link from Library</button>
          <button className="primary-soft-button" type="button" onClick={() => inputRef.current?.click()}><Upload size={14} /> Import & link</button>
        </div>
      </div>

      <label className="project-files-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search project files and artifacts" /></label>
      {query.trim() && <small className="notes-search-scope">Search covers all Library references linked to this project, plus project-local artifacts.</small>}

      {linkOpen ? (
        <div className="project-link-picker">
          <div className="project-link-picker__head"><span><strong>Link Library files</strong><small>Creates a reference; the original file remains in Personal Library.</small></span><button className="icon-button" type="button" onClick={() => setLinkOpen(false)}><X size={14} /></button></div>
          <label className="project-files-search project-link-picker__search"><Search size={14} /><input value={linkQuery} onChange={(event) => setLinkQuery(event.target.value)} placeholder="Search all unlinked Library files" /></label>
          {linkCandidatesError ? <div className="notes-list-pagination" role="status"><span>Could not search unlinked Library files: {linkCandidatesError}</span><button type="button" disabled={linkCandidatesLoading} onClick={() => onSearchLinkCandidates?.(linkQuery.trim())}>Retry</button></div> : null}
          <div className="project-link-picker__list">
            {available.length ? available.map((item) => (
              <button key={item.id} type="button" onClick={() => onToggleProjectLink(item.id, project.id, item)}>
                <span className={`file-kind file-kind--${item.kind.toLowerCase()}`}>{item.kind}</span>
                <span><strong>{item.name}</strong><small>{item.collection} · {item.detail}</small></span>
                <Plus size={13} />
              </button>
            )) : linkCandidatesLoading ? <span className="empty-inline" role="status">Searching Library references…</span> : linkCandidatesError ? null : linkQuery.trim() ? <span className="empty-inline">No unlinked Library files match this search.</span> : linkCandidatesHasMore ? <span className="empty-inline">Loading available Library references…</span> : <span className="empty-inline">Everything in Library is already linked to this project.</span>}
          </div>
          {linkCandidatesHasMore && !linkCandidatesError ? <button className="notes-load-more" type="button" disabled={linkCandidatesLoading} onClick={onLoadMoreLinkCandidates}>{linkCandidatesLoading ? 'Loading references…' : 'Load more Library references'}</button> : null}
        </div>
      ) : null}

      <div className="project-files-section">
        <div className="section-heading section-heading--compact"><div><span className="eyebrow">LINKED FROM LIBRARY</span><h2>{q ? `${filteredLinked.length}${searchHasMore ? '+' : ''} matching personal files` : `${linked.length}${hasMoreLibrary ? '+' : ''} loaded personal files`}</h2></div><small>Reusable across projects</small></div>
        <div className="project-file-list">
          {filteredLinked.length ? filteredLinked.map((item) => {
            const Icon = iconForKind(item.kind);
            return (
              <div key={item.id} className="project-file-row">
                <span className="project-file-row__icon"><Icon size={16} /></span>
                <span className="project-file-row__copy"><strong>{item.name}</strong><small>{item.detail}</small><em>Library · {item.collection} · {item.updated}</em></span>
                <button type="button" onClick={() => onOpenItem(item)}><ExternalLink size={13} /> Open</button>
                <button className="unlink-button" type="button" onClick={() => onToggleProjectLink(item.id, project.id)}>Unlink</button>
              </div>
            );
          }) : q && searchLoading ? <div className="notes-list-pagination" role="status">Searching project Library references…</div> : <div className="empty-section">No linked Library files match this search.</div>}
        </div>
        {q && searchError ? <div className="notes-list-pagination" role="status"><span>Could not search project Library references: {searchError}</span><button type="button" disabled={searchLoading} onClick={() => onSearchLibrary?.(q)}>Retry</button></div> : null}
        {libraryLoadError ? <div className="notes-list-pagination" role="status"><span>Could not load Library references: {libraryLoadError}</span><button type="button" disabled={loadingMoreLibrary} onClick={onLoadMoreLibrary}>Retry</button></div> : null}
        {loadingMoreLibrary && !hasMoreLibrary && !libraryLoadError ? <div className="notes-list-pagination" role="status">Loading Library references…</div> : null}
        {!q && !libraryLoadError && hasMoreLibrary ? <button className="notes-load-more" type="button" disabled={loadingMoreLibrary} onClick={onLoadMoreLibrary}>{loadingMoreLibrary ? 'Loading references…' : 'Load more Library references'}</button> : null}
        {q && searchHasMore && !searchError ? <button className="notes-load-more" type="button" disabled={searchLoading} onClick={onLoadMoreSearch}>{searchLoading ? 'Loading matches…' : 'Load more matches'}</button> : null}
      </div>

      <div className="project-files-section">
        <div className="section-heading section-heading--compact"><div><span className="eyebrow">PROJECT-LOCAL</span><h2>{localArtifacts.length} working artifacts</h2></div><small>Code, generated results and project-only notes</small></div>
        <div className="project-file-list">
          {filteredLocal.map((item) => {
            const Icon = iconForKind(item.kind);
            return (
              <div key={item.id} className="project-file-row project-file-row--local">
                <span className="project-file-row__icon"><Icon size={16} /></span>
                <span className="project-file-row__copy"><strong>{item.name}</strong><small>{item.detail}</small><em>{item.origin === 'generated' ? 'Generated by AURA' : 'Project workspace'} · {item.updated}</em></span>
                {item.linkedLibraryId ? <span className="linked-badge"><Link2 size={11} /> linked to Library note</span> : <span className={`artifact-status artifact-status--${item.status ?? 'ready'}`}>{item.status ?? 'ready'}</span>}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
