import { ArrowRight, BookOpenText, Play } from 'lucide-react';
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
}

function isStudyMaterial(item: LibraryItem) {
  return item.collection === 'Study' || item.collection === 'Research';
}

export function StudyView({ libraryItems, onOpenItem, onBrowseLibrary, onStartSession, sessions, onCompleteSession }: StudyViewProps) {
  const materials = libraryItems.filter(isStudyMaterial);
  const materialIds = new Set(materials.map((item) => item.id));
  const unlinkedSessions = sessions.filter((session) => !materialIds.has(session.material_id ?? session.track_id));

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
                {activeSession ? (
                  <button className="study-start-button" type="button" onClick={() => onCompleteSession(activeSession.id)}>
                    <Play size={13} /> Mark session complete
                  </button>
                ) : canStartSession ? (
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
            <article key={session.id}>
              <strong>{session.track_title}</strong>
              <span>{session.status === 'completed' ? 'Completed' : 'In progress'}</span>
              {session.status === 'in_progress' ? <button type="button" onClick={() => onCompleteSession(session.id)}>Mark complete</button> : null}
            </article>
          ))}
        </section>
      ) : null}
    </section>
  );
}
