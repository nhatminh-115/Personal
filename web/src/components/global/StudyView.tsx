import { ArrowRight, BookOpenText, Check, Clock3, Play, Sparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import { studyTracks, type LibraryItem } from '../../data/workspaceData';
import type { StudySessionRecord } from '../../types';

interface StudyViewProps {
  libraryItems: LibraryItem[];
  sessions: StudySessionRecord[];
  sessionsUnavailable?: boolean;
  onOpenItem: (item: LibraryItem) => void;
  onStartSession: (trackId: string) => Promise<void>;
  onCompleteSession: (sessionId: string) => Promise<void>;
}

function formatDuration(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`;
}

export function StudyView({ libraryItems, sessions, sessionsUnavailable = false, onOpenItem, onStartSession, onCompleteSession }: StudyViewProps) {
  const [now, setNow] = useState(Date.now());
  const activeSession = sessions.find((session) => session.status === 'active') ?? null;

  useEffect(() => {
    if (!activeSession) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [activeSession?.id]);

  return (
    <section className="study-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">STUDY</span>
          <h1>Progress, materials, and the next small session.</h1>
          <p>Study sessions are saved durably. Materials stay in your personal Library.</p>
        </div>
        <div className="study-today-pill"><Sparkles size={14} /><span><strong>Today</strong><small>1 focused session is enough</small></span></div>
      </div>

      {sessionsUnavailable ? <div className="study-unavailable-notice" role="status">Study history is unavailable. Connect to AURA to view or save focus sessions.</div> : null}

      <div className="study-track-grid">
        {studyTracks.map((track) => {
          const files = track.libraryIds.map((id) => libraryItems.find((item) => item.id === id)).filter(Boolean) as LibraryItem[];
          const trackSessions = sessions.filter((session) => session.track_id === track.id);
          const completed = trackSessions.filter((session) => session.status === 'completed');
          const focusedSeconds = completed.reduce((sum, session) => sum + (session.duration_seconds ?? 0), 0);
          const currentSession = activeSession?.track_id === track.id ? activeSession : null;
          const elapsed = currentSession ? Math.max(0, Math.floor((now - Date.parse(currentSession.started_at)) / 1000)) : 0;
          return (
            <article key={track.id} className={`study-track-card study-track-card--${track.accent}`}>
              <div className="study-track-card__top">
                <span className="study-track-icon"><BookOpenText size={18} /></span>
                <div><strong>{track.title}</strong><small>{track.subtitle}</small></div>
                <span>{completed.length} sessions</span>
              </div>
              <div className="study-stats">
                <div><span>Completed</span><strong>{completed.length}</strong></div>
                <div><span>Focus time</span><strong>{Math.floor(focusedSeconds / 60)} min</strong></div>
                <div><span>Last session</span><strong>{completed[0] ? new Date(completed[0].started_at).toLocaleDateString() : '—'}</strong></div>
              </div>
              <div className="study-next"><Clock3 size={13} /><span><small>Suggested next</small><strong>{track.next}</strong></span></div>
              <div className="study-files">
                <span>Linked materials</span>
                {files.map((file) => <button key={file.id} type="button" onClick={() => onOpenItem(file)}><span className={`file-kind file-kind--${file.kind.toLowerCase()}`}>{file.kind}</span><strong>{file.name}</strong><ArrowRight size={12} /></button>)}
              </div>
              <button
                className="study-start-button"
                type="button"
                onClick={() => currentSession ? void onCompleteSession(currentSession.id) : void onStartSession(track.id)}
                disabled={!currentSession && Boolean(activeSession)}
              >
                {currentSession ? <><Check size={13} /> Finish session · {formatDuration(elapsed)}</> : <><Play size={13} /> Start short session</>}
              </button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
