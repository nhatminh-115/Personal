import { ArrowRight, BookOpenText, Clock3, Play, Sparkles } from 'lucide-react';
import { studyTracks, type LibraryItem } from '../../data/workspaceData';

interface StudyViewProps {
  libraryItems: LibraryItem[];
  onOpenItem: (item: LibraryItem) => void;
  onStartSession: (trackId: string) => void;
}

export function StudyView({ libraryItems, onOpenItem, onStartSession }: StudyViewProps) {
  return (
    <section className="study-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">STUDY</span>
          <h1>Progress, materials, and the next small session.</h1>
          <p>Study does not duplicate files. It points back to artifacts in your personal Library.</p>
        </div>
        <div className="study-today-pill"><Sparkles size={14} /><span><strong>Today</strong><small>1 focused session is enough</small></span></div>
      </div>

      <div className="study-track-grid">
        {studyTracks.map((track) => {
          const files = track.libraryIds.map((id) => libraryItems.find((item) => item.id === id)).filter(Boolean) as LibraryItem[];
          return (
            <article key={track.id} className={`study-track-card study-track-card--${track.accent}`}>
              <div className="study-track-card__top">
                <span className="study-track-icon"><BookOpenText size={18} /></span>
                <div><strong>{track.title}</strong><small>{track.subtitle}</small></div>
                <span>{track.progress}%</span>
              </div>
              <div className="study-progress"><span style={{ width: `${track.progress}%` }} /></div>
              <div className="study-stats">
                {track.sessions.map((session) => <div key={session.label}><span>{session.label}</span><strong>{session.value}</strong></div>)}
              </div>
              <div className="study-next"><Clock3 size={13} /><span><small>Next</small><strong>{track.next}</strong></span></div>
              <div className="study-files">
                <span>Linked materials</span>
                {files.map((file) => <button key={file.id} type="button" onClick={() => onOpenItem(file)}><span className={`file-kind file-kind--${file.kind.toLowerCase()}`}>{file.kind}</span><strong>{file.name}</strong><ArrowRight size={12} /></button>)}
              </div>
              <button className="study-start-button" type="button" onClick={() => onStartSession(track.id)}><Play size={13} /> Start short session</button>
            </article>
          );
        })}
      </div>
    </section>
  );
}
