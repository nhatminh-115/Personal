import { Link2, NotebookPen, Pin, Plus, Search, X } from 'lucide-react';
import { useMemo, useState } from 'react';
import { projects, type WorkspaceNote } from '../../data/workspaceData';

interface NotesViewProps {
  notes: WorkspaceNote[];
  onNotesChange: (notes: WorkspaceNote[]) => void;
  onOpenProject: (projectId: string) => void;
}

export function NotesView({ notes, onNotesChange, onOpenProject }: NotesViewProps) {
  const [query, setQuery] = useState('');
  const [activeId, setActiveId] = useState(notes[0]?.id ?? null);
  const [creating, setCreating] = useState(false);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return notes.filter((note) => !q || `${note.title} ${note.body} ${note.tags.join(' ')}`.toLowerCase().includes(q));
  }, [notes, query]);
  const active = notes.find((note) => note.id === activeId) ?? null;

  const updateActive = (patch: Partial<WorkspaceNote>) => {
    if (!active) return;
    onNotesChange(notes.map((note) => note.id === active.id ? { ...note, ...patch, updated: 'just now' } : note));
  };

  const createNote = () => {
    const id = `note-${Date.now()}`;
    const next: WorkspaceNote = { id, title: 'Untitled note', body: '', updated: 'just now', tags: [], projectIds: [] };
    onNotesChange([next, ...notes]);
    setActiveId(id);
    setCreating(false);
  };

  return (
    <section className="notes-view">
      <aside className="notes-list-panel">
        <div className="notes-list-panel__head">
          <div><span className="eyebrow">NOTES</span><h2>Personal notes</h2></div>
          <button className="icon-button" type="button" title="New note" onClick={() => setCreating(true)}><Plus size={15} /></button>
        </div>
        <label className="notes-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search notes" /></label>
        {creating ? (
          <button className="note-create-card" type="button" onClick={createNote}><NotebookPen size={15} /><span><strong>Create blank note</strong><small>Global by default · link to projects later</small></span></button>
        ) : null}
        <div className="notes-list">
          {filtered.map((note) => (
            <button key={note.id} className={`note-list-item ${active?.id === note.id ? 'is-active' : ''}`} type="button" onClick={() => setActiveId(note.id)}>
              <span>{note.pinned ? <Pin size={11} /> : <NotebookPen size={11} />}</span>
              <span className="note-list-item__copy"><strong>{note.title}</strong><small>{note.body || 'Empty note'}</small><em>{note.updated}</em></span>
            </button>
          ))}
        </div>
      </aside>

      <div className="note-editor-panel">
        {active ? (
          <>
            <div className="note-editor-panel__meta">
              <span className="eyebrow">{active.projectIds.length ? 'LINKED NOTE' : 'PERSONAL NOTE'}</span>
              <button className={`pin-note ${active.pinned ? 'is-active' : ''}`} type="button" onClick={() => updateActive({ pinned: !active.pinned })}><Pin size={13} /> {active.pinned ? 'Pinned' : 'Pin'}</button>
            </div>
            <input className="note-title-input" value={active.title} onChange={(event) => updateActive({ title: event.target.value })} />
            <textarea className="note-body-input" value={active.body} onChange={(event) => updateActive({ body: event.target.value })} placeholder="Write anything…" />

            <div className="note-link-section">
              <div><Link2 size={14} /><span><strong>Linked projects</strong><small>Linked notes become available to that project's chats/context.</small></span></div>
              <div className="note-project-links">
                {projects.map((project) => {
                  const linked = active.projectIds.includes(project.id);
                  return (
                    <button
                      key={project.id}
                      className={linked ? 'is-linked' : ''}
                      type="button"
                      onClick={() => updateActive({ projectIds: linked ? active.projectIds.filter((id) => id !== project.id) : [...active.projectIds, project.id] })}
                    >
                      <span className={`project-dot project-dot--${project.accent}`} /> {project.name} {linked ? <X size={11} /> : <Plus size={11} />}
                    </button>
                  );
                })}
              </div>
              {active.projectIds.length ? (
                <div className="note-linked-shortcuts">
                  {active.projectIds.map((id) => {
                    const project = projects.find((item) => item.id === id);
                    return project ? <button key={id} type="button" onClick={() => onOpenProject(id)}>Open {project.name} →</button> : null;
                  })}
                </div>
              ) : null}
            </div>
          </>
        ) : <div className="empty-note-editor"><NotebookPen size={24} /><strong>Select a note</strong></div>}
      </div>
    </section>
  );
}
