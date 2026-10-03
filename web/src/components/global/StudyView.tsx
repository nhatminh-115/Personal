import { useEffect, useState } from 'react';
import { ArrowRight, BookOpenText, Play, Save } from 'lucide-react';
import type { LibraryItem, WorkspaceNote } from '../../data/workspaceData';
import type { StudyCardRating, StudyCardRecord, StudySessionRecord } from '../../types';
import './StudyView.css';

const EMPTY_STUDY_NOTES: WorkspaceNote[] = [];

interface StudyViewProps {
  libraryItems: LibraryItem[];
  notes?: WorkspaceNote[];
  hasMoreNotes?: boolean;
  loadingMoreNotes?: boolean;
  notesLoadError?: string | null;
  onLoadMoreNotes?: () => void;
  hasMoreLibrary?: boolean;
  loadingMoreLibrary?: boolean;
  libraryLoadError?: string | null;
  onLoadMoreLibrary?: () => void;
  onOpenItem: (item: LibraryItem) => void;
  onBrowseLibrary: () => void;
  onStartSession: (item: LibraryItem) => void;
  onStartNoteSession?: (note: WorkspaceNote) => void;
  sessions: StudySessionRecord[];
  hasMoreSessions?: boolean;
  loadingMoreSessions?: boolean;
  sessionsLoadError?: string | null;
  onLoadMoreSessions?: () => Promise<void>;
  cards?: StudyCardRecord[];
  hasMoreCards?: boolean;
  loadingMoreCards?: boolean;
  cardsLoadError?: string | null;
  onLoadMoreCards?: () => Promise<void>;
  dueCards?: StudyCardRecord[];
  hasMoreDueCards?: boolean;
  loadingDueCards?: boolean;
  loadingMoreDueCards?: boolean;
  dueCardsLoadError?: string | null;
  onLoadMoreDueCards?: () => Promise<void>;
  onRefreshDueCards?: () => Promise<void>;
  onCompleteSession: (sessionId: string) => void;
  onCreateCard: (sessionId: string, question: string, answer: string) => Promise<void>;
  onUpdateCard: (cardId: string, sessionId: string, question: string, answer: string) => Promise<void>;
  onReviewCard?: (cardId: string, sessionId: string, rating: StudyCardRating) => Promise<StudyCardRecord>;
  onDeleteCard: (cardId: string, sessionId: string) => Promise<void>;
  onSaveReflection: (sessionId: string, reflection: string) => Promise<void>;
  onOpenResearchFinding?: (objectId: string, projectName: string) => void;
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

function StudyCardRow({ card, onUpdate, onReview, onDelete }: {
  card: StudyCardRecord;
  onUpdate: (question: string, answer: string) => Promise<void>;
  onReview?: (rating: StudyCardRating) => Promise<StudyCardRecord>;
  onDelete: () => Promise<void>;
}) {
  const [revealed, setRevealed] = useState(false);
  const [reviewedCard, setReviewedCard] = useState(card);
  const [editing, setEditing] = useState(false);
  const [question, setQuestion] = useState(card.question);
  const [answer, setAnswer] = useState(card.answer);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setQuestion(card.question);
    setAnswer(card.answer);
    setReviewedCard(card);
  }, [card.id, card.question, card.answer, card.review_count, card.reviewed_at, card.next_review_at]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onUpdate(question, answer);
      setEditing(false);
    } catch {
      setError('Could not save this card. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      await onDelete();
    } catch {
      setError('Could not delete this card. Try again.');
      setBusy(false);
    }
  };

  const review = async (rating: StudyCardRating) => {
    if (!onReview) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await onReview(rating);
      setReviewedCard(updated);
      setRevealed(false);
    } catch {
      setError('Could not save this review. Try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className="study-card">
      {editing ? (
        <div className="study-card__edit">
          <label>Question<input value={question} maxLength={2000} onChange={(event) => setQuestion(event.target.value)} /></label>
          <label>Answer<textarea value={answer} maxLength={8000} rows={3} onChange={(event) => setAnswer(event.target.value)} /></label>
          <div className="study-card__actions">
            <button type="button" disabled={busy || !question.trim() || !answer.trim()} onClick={() => void save()}>{busy ? 'Saving…' : 'Save card'}</button>
            <button type="button" disabled={busy} onClick={() => { setQuestion(card.question); setAnswer(card.answer); setEditing(false); }}>Cancel</button>
          </div>
        </div>
      ) : (
        <>
          <strong>{card.question}</strong>
          {revealed ? (
            <>
              <p>{card.answer}</p>
              {onReview ? (
                <div className="study-card__review" role="group" aria-label="Schedule next review">
                  <span>How soon should you review this?</span>
                  <button type="button" disabled={busy} onClick={() => void review('again')}>Again · 1 day</button>
                  <button type="button" disabled={busy} onClick={() => void review('remembered')}>Remembered · 3 days</button>
                  <button type="button" disabled={busy} onClick={() => void review('easy')}>Easy · 7 days</button>
                </div>
              ) : null}
            </>
          ) : <button type="button" className="study-card__reveal" onClick={() => setRevealed(true)}>Reveal answer</button>}
          <small className="study-card__schedule">
            {reviewedCard.review_count ? `${reviewedCard.review_count} ${reviewedCard.review_count === 1 ? 'review' : 'reviews'} · next ${reviewedCard.next_review_at ? new Date(reviewedCard.next_review_at).toLocaleDateString() : 'not scheduled'}` : 'Not reviewed yet'}
          </small>
          <div className="study-card__actions">
            <button type="button" disabled={busy} onClick={() => setEditing(true)}>Edit</button>
            <button type="button" disabled={busy} onClick={() => void remove()}>{busy ? 'Deleting…' : 'Delete'}</button>
          </div>
        </>
      )}
      {error ? <p role="alert" className="study-reflection__error">{error}</p> : null}
    </article>
  );
}

function StudyCardCollection({ cards, onCreate, onUpdate, onReview, onDelete }: {
  cards: StudyCardRecord[];
  onCreate: (question: string, answer: string) => Promise<void>;
  onUpdate: (cardId: string, question: string, answer: string) => Promise<void>;
  onReview?: (cardId: string, sessionId: string, rating: StudyCardRating) => Promise<StudyCardRecord>;
  onDelete: (cardId: string) => Promise<void>;
}) {
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = async () => {
    setSaving(true);
    setError(null);
    try {
      await onCreate(question, answer);
      setQuestion('');
      setAnswer('');
    } catch {
      setError('Could not save this card. Try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="study-cards">
      <strong className="study-cards__heading">Learning cards · {cards.length} loaded</strong>
      {cards.map((card) => (
        <StudyCardRow
          key={card.id}
          card={card}
          onUpdate={(nextQuestion, nextAnswer) => onUpdate(card.id, nextQuestion, nextAnswer)}
          onReview={onReview ? (rating) => onReview(card.id, card.session_id, rating) : undefined}
          onDelete={() => onDelete(card.id)}
        />
      ))}
      <div className="study-card__edit">
        <label>Question<input value={question} maxLength={2000} onChange={(event) => setQuestion(event.target.value)} placeholder="What should you remember?" /></label>
        <label>Answer<textarea value={answer} maxLength={8000} rows={3} onChange={(event) => setAnswer(event.target.value)} placeholder="Write the answer in your own words…" /></label>
        <button type="button" disabled={saving || !question.trim() || !answer.trim()} onClick={() => void create()}>{saving ? 'Saving…' : 'Add learning card'}</button>
      </div>
      {error ? <p role="alert" className="study-reflection__error">{error}</p> : null}
    </div>
  );
}

export function StudyView({ libraryItems, notes = EMPTY_STUDY_NOTES, hasMoreNotes = false, loadingMoreNotes = false, notesLoadError, onLoadMoreNotes, hasMoreLibrary = false, loadingMoreLibrary = false, libraryLoadError, onLoadMoreLibrary, onOpenItem, onBrowseLibrary, onStartSession, onStartNoteSession, sessions, hasMoreSessions = false, loadingMoreSessions = false, sessionsLoadError, cards = [], hasMoreCards = false, loadingMoreCards = false, cardsLoadError, onLoadMoreCards, dueCards = [], hasMoreDueCards = false, loadingDueCards = false, loadingMoreDueCards = false, dueCardsLoadError, onLoadMoreDueCards, onRefreshDueCards, onCompleteSession, onCreateCard, onUpdateCard, onReviewCard, onDeleteCard, onSaveReflection, onOpenResearchFinding, focusSessionId }: StudyViewProps) {
  const materials = libraryItems.filter(isStudyMaterial);
  const studyNotes = notes.filter((note) => note.source === 'live' || note.source === 'local');
  const materialIds = new Set([...materials.map((item) => item.id), ...studyNotes.map((note) => note.id)]);
  const unlinkedSessions = sessions.filter((session) => !materialIds.has(session.material_id ?? session.track_id));
  const activeWorkspaceSession = sessions.find((session) => session.status === 'in_progress');

  useEffect(() => {
    if (!focusSessionId) return;
    document.getElementById(`study-session-${focusSessionId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [focusSessionId, sessions, libraryItems, notes]);

  return (
    <section className="study-view">
      <div className="library-view__header">
        <div>
          <span className="eyebrow">STUDY</span>
          <h1>Study from the sources already in your workspace.</h1>
          <p>Study keeps durable sessions linked to saved Library references, Notes, or verified Research findings. It does not copy source text into the session.</p>
        </div>
        <button className="secondary-button" type="button" onClick={onBrowseLibrary}>Browse Library</button>
      </div>

      <section className="study-review-queue" aria-label="Cards due for review">
        <div className="study-review-queue__heading">
          <div><h2>Review queue</h2><p>Unreviewed cards and cards whose next review date has arrived.</p></div>
          <span>{dueCards.length} loaded</span>
        </div>
        {loadingDueCards && !dueCards.length ? <p role="status">Loading cards due for review…</p> : null}
        {dueCardsLoadError && !dueCards.length ? <p role="alert">Could not load the review queue: {dueCardsLoadError} <button type="button" onClick={() => void onRefreshDueCards?.()}>Retry</button></p> : null}
        {!loadingDueCards && !dueCardsLoadError && !dueCards.length ? <p>You’re all caught up. New cards will appear here until you review them.</p> : null}
        {dueCards.map((card) => (
          <article className="study-review-queue__card" key={card.id}>
            <small>{sessions.find((session) => session.id === card.session_id)?.track_title ?? 'Earlier Study session'}</small>
            <StudyCardRow
              card={card}
              onUpdate={(question, answer) => onUpdateCard(card.id, card.session_id, question, answer)}
              onReview={onReviewCard ? (rating) => onReviewCard(card.id, card.session_id, rating) : undefined}
              onDelete={() => onDeleteCard(card.id, card.session_id)}
            />
          </article>
        ))}
        {dueCardsLoadError && dueCards.length ? <p role="alert">Could not load more due cards: {dueCardsLoadError}</p> : null}
        {hasMoreDueCards ? <button type="button" className="notes-load-more" disabled={loadingMoreDueCards} onClick={() => void onLoadMoreDueCards?.()}>{loadingMoreDueCards ? 'Loading more due cards…' : 'Load more due cards'}</button> : null}
      </section>

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
                  <span>{completedCount} completed shown</span>
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
                        <StudyCardCollection
                          cards={cards.filter((card) => card.session_id === session.id)}
                          onCreate={(question, answer) => onCreateCard(session.id, question, answer)}
                          onUpdate={(cardId, question, answer) => onUpdateCard(cardId, session.id, question, answer)}
                          onReview={onReviewCard}
                          onDelete={(cardId) => onDeleteCard(cardId, session.id)}
                        />
                      </article>
                    ))}
                  </div>
                ) : null}
                {activeSession ? null : canStartSession ? (
                  activeWorkspaceSession ? (
                    <p className="study-material-note">
                      Finish “{activeWorkspaceSession.track_title}” before starting another Study session.
                    </p>
                  ) : (
                    <button className="study-start-button" type="button" onClick={() => onStartSession(item)}>
                      <Play size={13} /> Start short session
                    </button>
                  )
                ) : (
                  <p className="study-material-note">Save a personal Study or Research reference in Library to start a durable session.</p>
                )}
              </article>
            );
          })}
        </div>
      ) : studyNotes.length ? null : (
        <div className="study-track-empty">
          <BookOpenText size={22} />
          <h2>No Study sources yet</h2>
          <p>Add a personal Study or Research reference to Library, or save a Note, then start a session from it here.</p>
          <button className="primary-button" type="button" onClick={onBrowseLibrary}>Open Library</button>
        </div>
      )}

      {studyNotes.length ? (
        <section className="study-note-sources" aria-label="Saved Notes for Study">
          <h2>Saved Notes</h2>
          <div className="study-track-grid">
            {studyNotes.map((note) => {
              const noteSessions = sessions.filter((session) => (session.material_id ?? session.track_id) === note.id);
              const activeSession = noteSessions.find((session) => session.status === 'in_progress');
              const completedCount = noteSessions.filter((session) => session.status === 'completed').length;
              const canStartSession = note.source === 'live' && !activeSession && !activeWorkspaceSession;
              return (
                <article key={note.id} className="study-track-card study-track-card--cyan">
                  <div className="study-track-card__top">
                    <span className="study-track-icon"><BookOpenText size={18} /></span>
                    <div><strong>{note.title || 'Untitled Note'}</strong><small>Saved Note · {note.projectIds.length} project links</small></div>
                    <span>{completedCount} completed shown</span>
                  </div>
                  <p className="study-material-detail">{note.body || 'No note text added.'}</p>
                  {note.privacyPolicy ? <p className="study-material-note">Privacy · {note.privacyPolicy.replace(/_/g, ' ')}</p> : null}
                  {noteSessions.length ? (
                    <div className="study-session-list" aria-label={`${note.title || 'Note'} sessions`}>
                      {noteSessions.map((session) => (
                        <article
                          id={`study-session-${session.id}`}
                          key={session.id}
                          className={`study-session-row${session.id === focusSessionId ? ' is-focused' : ''}`}
                          tabIndex={-1}
                        >
                          <span>{session.status === 'completed' ? 'Completed' : 'In progress'} · {new Date(session.started_at).toLocaleDateString()}</span>
                          {session.status === 'in_progress' ? <button type="button" onClick={() => onCompleteSession(session.id)}>Mark complete</button> : null}
                          <StudyReflectionEditor session={session} onSave={onSaveReflection} />
                          <StudyCardCollection
                            cards={cards.filter((card) => card.session_id === session.id)}
                          onCreate={(question, answer) => onCreateCard(session.id, question, answer)}
                          onUpdate={(cardId, question, answer) => onUpdateCard(cardId, session.id, question, answer)}
                          onReview={onReviewCard}
                          onDelete={(cardId) => onDeleteCard(cardId, session.id)}
                          />
                        </article>
                      ))}
                    </div>
                  ) : null}
                  {activeSession ? null : canStartSession ? (
                    <button className="study-start-button" type="button" onClick={() => onStartNoteSession?.(note)}>
                      <Play size={13} /> Study this Note
                    </button>
                  ) : activeWorkspaceSession ? (
                    <p className="study-material-note">Finish “{activeWorkspaceSession.track_title}” before starting another Study session.</p>
                  ) : (
                    <p className="study-material-note">{note.source === 'live' ? 'Study session unavailable.' : 'Save this Note before starting a durable Study session.'}</p>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      ) : null}

      {notesLoadError ? <div className="notes-list-pagination" role="status"><span>Could not load saved Notes: {notesLoadError}</span><button type="button" disabled={loadingMoreNotes} onClick={onLoadMoreNotes}>Retry</button></div> : null}
      {loadingMoreNotes && !hasMoreNotes && !notesLoadError ? <div className="notes-list-pagination" role="status">Loading saved Notes…</div> : null}
      {!notesLoadError && hasMoreNotes ? <button className="notes-load-more" type="button" disabled={loadingMoreNotes} onClick={onLoadMoreNotes}>{loadingMoreNotes ? 'Loading notes…' : 'Load more saved Notes'}</button> : null}
      {libraryLoadError ? <div className="notes-list-pagination" role="status"><span>Could not load Library sources: {libraryLoadError}</span><button type="button" disabled={loadingMoreLibrary} onClick={onLoadMoreLibrary}>Retry</button></div> : null}
      {loadingMoreLibrary && !hasMoreLibrary && !libraryLoadError ? <div className="notes-list-pagination" role="status">Loading Library sources…</div> : null}
      {!libraryLoadError && hasMoreLibrary ? <button className="notes-load-more" type="button" disabled={loadingMoreLibrary} onClick={onLoadMoreLibrary}>{loadingMoreLibrary ? 'Loading sources…' : 'Load more Library sources'}</button> : null}

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
              {session.material_id && session.material_project_name && onOpenResearchFinding ? (
                <button type="button" onClick={() => {
                  const { material_id: objectId, material_project_name: projectName } = session;
                  if (objectId && projectName) onOpenResearchFinding(objectId, projectName);
                }}>
                  <ArrowRight size={13} /> Open Research finding
                </button>
              ) : null}
              {session.status === 'in_progress' ? <button type="button" onClick={() => onCompleteSession(session.id)}>Mark complete</button> : null}
              <StudyReflectionEditor session={session} onSave={onSaveReflection} />
              <StudyCardCollection
                cards={cards.filter((card) => card.session_id === session.id)}
                onCreate={(question, answer) => onCreateCard(session.id, question, answer)}
                onUpdate={(cardId, question, answer) => onUpdateCard(cardId, session.id, question, answer)}
                onReview={onReviewCard}
                onDelete={(cardId) => onDeleteCard(cardId, session.id)}
              />
            </article>
          ))}
        </section>
      ) : null}

      {hasMoreSessions || sessionsLoadError || hasMoreCards || cardsLoadError ? (
        <div className="study-cards-pagination">
          {sessionsLoadError ? <p role="alert" className="study-reflection__error">Could not load older sessions: {sessionsLoadError}</p> : null}
          {hasMoreSessions ? (
            <button type="button" disabled={loadingMoreSessions} onClick={() => void onLoadMoreSessions?.()}>
              {loadingMoreSessions ? 'Loading older sessions…' : sessionsLoadError ? 'Retry loading sessions' : 'Load older sessions'}
            </button>
          ) : null}
          {cardsLoadError ? <p role="alert" className="study-reflection__error">Could not load more learning cards: {cardsLoadError}</p> : null}
          {hasMoreCards ? (
            <button type="button" disabled={loadingMoreCards} onClick={() => void onLoadMoreCards?.()}>
              {loadingMoreCards ? 'Loading more cards…' : cardsLoadError ? 'Retry loading cards' : 'Load more cards'}
            </button>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
