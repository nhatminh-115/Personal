import { ArrowUpRight, FileText, LoaderCircle, Search } from 'lucide-react';
import type { WorkspaceSearchResult } from '../../types';

interface WorkspaceSearchViewProps {
  query: string;
  results: WorkspaceSearchResult[];
  loading: boolean;
  error: string | null;
  onOpenProject: (name: string, objectId: string) => void;
  onOpenNote: (objectId: string) => void;
  onOpenLibraryItem: (objectId: string) => void;
  onOpenFile: (result: WorkspaceSearchResult) => void;
}

const TYPE_LABELS: Record<string, string> = {
  chat_message: 'Chat',
  manual_note: 'Note',
  research_artifact: 'Research',
  context_bridge: 'Context Bridge',
  file_reference: 'Library reference',
};

export function WorkspaceSearchView({ query, results, loading, error, onOpenProject, onOpenNote, onOpenLibraryItem, onOpenFile }: WorkspaceSearchViewProps) {
  return (
    <section className="workspace-search" aria-labelledby="workspace-search-title">
      <header className="workspace-search__header">
        <div className="workspace-search__icon"><Search size={20} /></div>
        <div>
          <p className="workspace-search__eyebrow">AURA workspace</p>
          <h1 id="workspace-search-title">Search results</h1>
          <p>Results for <strong>“{query}”</strong></p>
        </div>
        {loading ? <LoaderCircle className="workspace-search__spinner" size={20} aria-label="Searching" /> : null}
      </header>

      {error ? <div className="workspace-search__notice" role="alert">Search failed: {error}</div> : null}
      {!loading && !error && results.length === 0 ? (
        <div className="workspace-search__empty">
          <Search size={22} />
          <h2>No matches yet</h2>
          <p>Try another phrase. AURA searches saved workspace objects, Library references, and file names from connected folders you have indexed.</p>
        </div>
      ) : null}
      <div className="workspace-search__results" aria-live="polite">
        {results.map((result) => (
          <article className="workspace-search__result" key={result.object_id}>
            <div className="workspace-search__result-icon"><FileText size={17} /></div>
            <div className="workspace-search__result-body">
              <h2>{result.title}</h2>
              <p>{result.excerpt || 'No text preview is available for this object.'}</p>
              <div className="workspace-search__meta">
                <span>{result.source === 'connected-folder' ? 'Connected file' : TYPE_LABELS[result.object_type] ?? result.object_type.replace(/_/g, ' ')}</span>
                {result.source === 'connected-folder' ? <span>{result.connection_name} · {result.size?.toLocaleString()} B</span>
                  : result.object_type === 'manual_note' ? <><span>Personal workspace</span><button type="button" onClick={() => onOpenNote(result.object_id)}>Open note <ArrowUpRight size={12} /></button></>
                    : result.object_type === 'file_reference' ? <><span>Library</span><button type="button" onClick={() => onOpenLibraryItem(result.object_id)}>Open in Library <ArrowUpRight size={12} /></button></>
                    : result.project_name ? <><span>{result.project_name}</span><button type="button" onClick={() => onOpenProject(result.project_name!, result.object_id)}>Open in Board <ArrowUpRight size={12} /></button></>
                    : <span>Personal workspace</span>}
                <time dateTime={result.updated_at}>{new Date(result.updated_at).toLocaleDateString()}</time>
                {result.source === 'connected-folder' ? <button type="button" onClick={() => onOpenFile(result)}>Open file <ArrowUpRight size={12} /></button> : null}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

