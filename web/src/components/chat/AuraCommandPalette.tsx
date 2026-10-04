import { ArrowRight, ArrowUpRight, FileText, LoaderCircle, Search, Sparkles, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { WorkspaceSearchResult } from '../../types';
import { api } from '../../services/api';
import { searchDirectoryIndexes } from '../../lib/folderConnections';

interface AuraCommandPaletteProps {
  projectName?: string | null;
  onClose: () => void;
  onOpenResult: (result: WorkspaceSearchResult) => void;
  onOpenFile: (result: WorkspaceSearchResult) => void;
}

const suggestions = [
  'recurrent memory',
  'research evidence',
  'project decisions',
];

export function AuraCommandPalette({ projectName, onClose, onOpenResult, onOpenFile }: AuraCommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [submittedQuery, setSubmittedQuery] = useState('');
  const [results, setResults] = useState<WorkspaceSearchResult[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const search = async (value: string) => {
    const normalized = value.trim();
    if (!normalized) return;
    const currentRequest = ++requestId.current;
    setSubmittedQuery(normalized);
    setResults([]);
    setNextCursor(null);
    setLoading(true);
    setError(null);
    try {
      const [workspace, folders] = await Promise.allSettled([
        api.searchWorkspace(normalized, projectName ?? undefined),
        projectName ? Promise.resolve([]) : searchDirectoryIndexes(normalized),
      ]);
      if (requestId.current !== currentRequest) return;
      const workspaceItems = workspace.status === 'fulfilled' ? workspace.value.items : [];
      const folderItems = folders.status === 'fulfilled' ? folders.value.map((file): WorkspaceSearchResult => ({
        object_id: `external:${file.connectionId}:${file.relativePath}`,
        object_type: 'file_reference',
        title: file.name,
        excerpt: `${file.connectionName} / ${file.relativePath}`,
        project_name: null,
        created_by: 'external',
        updated_at: new Date(file.lastModified).toISOString(),
        source: 'connected-folder',
        connection_id: file.connectionId,
        connection_name: file.connectionName,
        relative_path: file.relativePath,
        size: file.size,
        mime_type: file.mimeType,
      })) : [];
      setResults([...workspaceItems, ...folderItems]);
      setNextCursor(workspace.status === 'fulfilled' ? workspace.value.nextCursor : null);
      if (workspace.status === 'rejected') {
        const detail = workspace.reason instanceof Error ? workspace.reason.message : 'Workspace search failed.';
        setError(folderItems.length ? `Saved workspace search is unavailable; showing connected-folder matches. ${detail}` : detail);
      }
    } catch (cause) {
      if (requestId.current !== currentRequest) return;
      setError(cause instanceof Error ? cause.message : 'Workspace search failed.');
    } finally {
      if (requestId.current === currentRequest) setLoading(false);
    }
  };

  const loadMore = async () => {
    if (!nextCursor || loadingMore || !submittedQuery) return;
    const currentRequest = requestId.current;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await api.searchWorkspace(submittedQuery, projectName ?? undefined, nextCursor);
      if (requestId.current !== currentRequest) return;
      setResults((current) => {
        const seen = new Set(current.map((item) => item.object_id));
        return [...current, ...page.items.filter((item) => !seen.has(item.object_id))];
      });
      setNextCursor(page.nextCursor);
    } catch (cause) {
      if (requestId.current !== currentRequest) return;
      setError(cause instanceof Error ? cause.message : 'Could not load more results.');
    } finally {
      if (requestId.current === currentRequest) setLoadingMore(false);
    }
  };

  const hasSearched = Boolean(submittedQuery);
  const scope = projectName ? `Current project · ${projectName}` : 'Personal workspace';

  return (
    <div className="aura-command-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="aura-command" role="dialog" aria-modal="true" aria-label="Search workspace" onMouseDown={(event) => event.stopPropagation()}>
        <div className="aura-command__head">
          <span className="aura-command__mark"><Sparkles size={15} /></span>
          <div><span className="eyebrow">AURA WORKSPACE SEARCH</span><strong>{scope}</strong></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>

        <form className="aura-command__input" onSubmit={(event) => { event.preventDefault(); void search(query); }}>
          <Search size={15} />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search saved workspace content…" aria-label="Search saved workspace content" />
          <button type="submit" disabled={!query.trim() || loading} aria-label="Search"><ArrowRight size={15} /></button>
        </form>

        {!hasSearched ? (
          <div className="aura-command__suggestions">
            <small>Search indexed content</small>
            {suggestions.map((item) => <button type="button" key={item} onClick={() => { setQuery(item); void search(item); }}><Search size={11} /> {item}</button>)}
          </div>
        ) : (
          <div className="aura-command__result" aria-live="polite">
            <div className="aura-command__answer">
              <span><Search size={12} /> Workspace matches</span>
              <p>{loading ? 'Searching saved workspace objects…' : error ? `Search failed: ${error}` : results.length ? `${results.length}${nextCursor ? '+' : ''} matching saved objects for “${submittedQuery}”.` : `No saved workspace objects matched “${submittedQuery}”.`}</p>
              <div className="aura-command__trace"><span>Saved objects · text search</span><span>{projectName ? scope : 'Also searches browser-local connected-folder names'}</span></div>
            </div>

            {loading && !results.length ? <div className="aura-command__loading"><LoaderCircle size={16} aria-hidden="true" /> Searching</div> : null}
            <div className="aura-command__sources">
              {results.map((result) => (
                <button type="button" key={result.object_id} onClick={() => result.source === 'connected-folder' ? onOpenFile(result) : onOpenResult(result)}>
                  <FileText size={13} />
                  <span><strong>{result.title}</strong><small>{result.source === 'connected-folder' ? 'Connected file' : result.object_type.replace(/_/g, ' ')}{result.source === 'connected-folder' ? ` · ${result.excerpt}` : result.project_name ? ` · ${result.project_name}` : ' · Personal workspace'}{result.source !== 'connected-folder' && result.excerpt ? ` — ${result.excerpt}` : ''}</small></span>
                  <ArrowUpRight size={12} />
                </button>
              ))}
            </div>
            {nextCursor ? <button className="aura-command__more" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? 'Loading…' : 'Load more results'}</button> : null}
          </div>
        )}

        <div className="aura-command__foot"><span>Enter to search</span><span>Esc to close</span><span>Results link to saved objects</span></div>
      </section>
    </div>
  );
}
