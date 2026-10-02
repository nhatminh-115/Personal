import { useEffect, useState } from 'react';
import { ArrowRight, BookOpenText, Play, Save } from 'lucide-react';
import type { LibraryItem } from '../../data/workspaceData';
import type { StudySessionRecord } from '../../types';
import './StudyView.css';

interface StudyViewProps {
  libraryItems: LibraryItem[];
  onOpenItem: (item: LibraryItem) => void;
  onBrowseLibrary: () => void;
  onStartSession: (item: LibraryItem) => void;
  sessions: StudySessionRecord[];
  onCompleteSession: (sessionId: string) => void;
  onSaveReflection: (sessionId: string, reflection: string) => Promise<void>;
  focusSessionId?: string | null;
}

function isStudyMaterial(item: LibraryItem) {
  return item.collection === 'Study' || item.collection === 'Research';
}

function StudyReflectionEditor({ session, onSave }: { session: StudySessionRecord; onSave: (sessionId: string, reflection: string) => Promise<void> }) {
  const savedReflection = session.reflection ?? '';
  const [draft, setDraft] = useState(savedReflection);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(savedReflection), [session.id, savedReflection]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await onSave(session.id, draft);
    } catch {
      setError('Could not save this reflection. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="study-reflection">
      <label htmlFor={`study-reflection-${session.id}`}>What did you learn?</label>
      <textarea
        id={`study-reflection-${session.id}`}
        value={draft}
        maxLength={12000}
        rows={3}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Write a reflection or key ideas to remember…"
      />
      <div className="study-reflection__footer">
        <small>{draft.length.toLocaleString()} / 12,000</small>
        <button type="button" disabled={saving || draft === savedReflection} onClick={() => void save()}>
          <Save size={13} /> {saving ? 'Saving…' : 'Save reflection'}
        </button>
      </div>
      {error ? <p role="alert" className="study-reflection__error">{error}</p> : null}
    </div>
  );
}

export function StudyView({ libraryItems, onOpenItem, onBrowseLibrary, onStartSession, sessions, onCompleteSession, onSaveReflection, focusSessionId }: StudyViewProps) {
  const materials = libraryItems.filter(isStudyMaterial);
  const materialIds = new Set(materials.map((item) => item.id));
  const unlinkedSessions = sessions.filter((session) => !materialIds.has(session.material_id ?? session.track_id));

  useEffect(() => {
    if (!focusSessionId) return;
    document.getElementById(`study-session-${focusSessionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusSessionId, sessions, libraryItems]);

  return (
    <section className="study-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">STUDY</span>
          <h1>Study from the sources already in your workspace.</h1>
          <p>Study keeps a durable session linked to each Library reference. It does not copy or upload file contents.</p>
        </div>
        <button className="secondary-button" type="button" onClick={onBrowseLibrary}>Browse Library</button>
      </div>

      {materials.length ? (
        <div className="study-track-grid" aria-label="Study materials">
          {materials.map((item) => {
            const itemSessions = sessions.filter((session) => (session.material_id ?? session.track_id) === item.id);
            const activeSession = itemSessions.find((session) => session.status === 'in_progress');
            const completedCount = itemSessions.filter((session) => session.status === 'completed').length;
            const canStartSession = item.source === 'imported' && item.syncState === 'synced';
            return (
              <article key={item.id} className="study-track-card study-track-card--cyan">
                <div className="study-track-card__top">
                  <span className="study-track-icon"><BookOpenText size={18} /></span>
                  <div><strong>{item.name}</strong><small>{item.collection} · {item.kind}</small></div>
                  <span>{completedCount} complete</span>
                </div>
                <p className="study-material-detail">{item.detail || 'No Library description added.'}</p>
                <div className="study-files">
                  <span>{item.source === 'bundled' ? 'Preview reference' : item.syncState === 'synced' ? 'Workspace reference' : 'Saving reference'}</span>
                  <button type="button" onClick={() => onOpenItem(item)}>
                    <span className={`file-kind file-kind--${item.kind.toLowerCase()}`}>{item.kind}</span>
                    <strong>Open material</strong><ArrowRight size={12} />
                  </button>
                </div>
                {itemSessions.length ? (
                  <div className="study-session-list" aria-label={`${item.name} sessions`}>
                    {itemSessions.map((session) => (
                      <article
                        id={`study-session-${session.id}`}
                        key={session.id}
                        className={`study-session-row${session.id === focusSessionId ? ' is-focused' : ''}`}
                        tabIndex={-1}
                      >
                        <span>{session.status === 'completed' ? 'Completed' : 'In progress'} · {new Date(session.started_at).toLocaleDateString()}</span>
                        {session.status === 'in_progress' ? <button type="button" onClick={() => onCompleteSession(session.id)}>Mark complete</button> : null}
                        <StudyReflectionEditor session={session} onSave={onSaveReflection} />
                      </article>
                    ))}
                  </div>
                ) : null}
                {activeSession ? null : canStartSession ? (
                  <button className="study-start-button" type="button" onClick={() => onStartSession(item)}>
                    <Play size={13} /> Start short session
                  </button>
                ) : (
                  <p className="study-material-note">Save a personal Study or Research reference in Library to start a durable session.</p>
                )}
              </article>
            );
          })}
        </div>
      ) : (
        <div className="study-track-empty">
          <BookOpenText size={22} />
          <h2>No Study sources yet</h2>
          <p>Add a personal reference to the Study or Research collection in Library, then start a session from it here.</p>
          <button className="primary-button" type="button" onClick={onBrowseLibrary}>Open Library</button>
        </div>
      )}

      {unlinkedSessions.length ? (
        <section className="study-history" aria-label="Earlier Study sessions">
          <h2>Earlier sessions</h2>
          {unlinkedSessions.map((session) => (
            <article
              id={`study-session-${session.id}`}
              key={session.id}
              className={session.id === focusSessionId ? 'is-focused' : undefined}
              tabIndex={-1}
            >
              <strong>{session.track_title}</strong>
              <span>{session.status === 'completed' ? 'Completed' : 'In progress'}</span>
              {session.status === 'in_progress' ? <button type="button" onClick={() => onCompleteSession(session.id)}>Mark complete</button> : null}
              <StudyReflectionEditor session={session} onSave={onSaveReflection} />
            </article>
          ))}
        </section>
      ) : null}
    </section>
  );
}
