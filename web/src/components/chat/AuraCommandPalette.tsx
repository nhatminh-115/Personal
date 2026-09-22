import { ArrowRight, BookOpen, FolderKanban, Library, NotebookPen, Search, Sparkles, Workflow, X } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { AutomationRecord, LibraryItem, WorkspaceNote } from '../../data/workspaceData';

interface AuraCommandPaletteProps {
  projectName?: string | null;
  libraryItems: LibraryItem[];
  notes: WorkspaceNote[];
  automations: AutomationRecord[];
  onClose: () => void;
  onOpenLibrary?: () => void;
  onOpenNotes?: () => void;
  onOpenAutomations?: () => void;
  onOpenProject?: (projectId: string) => void;
}

const suggestions = [
  'Find everything I have about recurrent memory',
  'What should I continue working on today?',
  'Compare the evidence across my active AI projects',
];

export function AuraCommandPalette({ projectName, libraryItems, notes, automations, onClose, onOpenLibrary, onOpenNotes, onOpenAutomations, onOpenProject }: AuraCommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [submitted, setSubmitted] = useState<string | null>(null);
  const scope = projectName ? `Current project · ${projectName}` : 'Personal workspace';
  const linkedFiles = libraryItems.filter((item) => item.projectLinks?.length);
  const activeAutomations = automations.filter((item) => item.enabled);
  const answer = useMemo(() => {
    if (!submitted) return null;
    return `I searched the local workspace manifest: ${libraryItems.length} Library files, ${notes.length} notes, and ${activeAutomations.length} active automations. The strongest reusable context still comes from explicitly linked project files/notes rather than hidden chat history, so you can open the source object directly or continue inside its project.`;
  }, [activeAutomations.length, libraryItems.length, notes.length, submitted]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const submit = () => {
    const value = query.trim();
    if (!value) return;
    setSubmitted(value);
  };

  return (
    <div className="aura-command-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="aura-command" role="dialog" aria-modal="true" aria-label="Ask AURA" onMouseDown={(event) => event.stopPropagation()}>
        <div className="aura-command__head">
          <span className="aura-command__mark"><Sparkles size={15} /></span>
          <div><span className="eyebrow">AURA QUICK ASK</span><strong>{scope}</strong></div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close"><X size={15} /></button>
        </div>

        <div className="aura-command__input">
          <Search size={15} />
          <input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') submit(); }} placeholder="Ask across your workspace…" />
          <button type="button" onClick={submit}><ArrowRight size={15} /></button>
        </div>

        {!submitted ? (
          <div className="aura-command__suggestions">
            <small>Try asking</small>
            {suggestions.map((item) => <button type="button" key={item} onClick={() => setQuery(item)}><Sparkles size={11} /> {item}</button>)}
          </div>
        ) : (
          <div className="aura-command__result">
            <div className="aura-command__answer">
              <span><Sparkles size={12} /> AURA</span>
              <p>{answer}</p>
              <div className="aura-command__trace"><span>Workspace retrieval · explicit objects</span><span>Adaptive routing · Medium</span></div>
            </div>

            <div className="aura-command__sources">
              <button type="button" onClick={() => onOpenProject?.('stateful')}><FolderKanban size={13} /><span><strong>Stateful Architecture</strong><small>Project · multiple chats</small></span><ArrowRight size={12} /></button>
              <button type="button" onClick={onOpenLibrary}><Library size={13} /><span><strong>{linkedFiles[0]?.name ?? 'Personal Library'}</strong><small>{libraryItems.length} files · reusable across projects</small></span><ArrowRight size={12} /></button>
              <button type="button" onClick={onOpenNotes}><NotebookPen size={13} /><span><strong>{notes[0]?.title ?? 'Workspace Notes'}</strong><small>{notes.length} notes · project links available</small></span><ArrowRight size={12} /></button>
              <button type="button" onClick={onOpenAutomations}><Workflow size={13} /><span><strong>Automations</strong><small>{activeAutomations.length} enabled routines</small></span><ArrowRight size={12} /></button>
              <button type="button" onClick={onOpenLibrary}><BookOpen size={13} /><span><strong>Study materials</strong><small>Backed by Library artifacts</small></span><ArrowRight size={12} /></button>
            </div>
          </div>
        )}

        <div className="aura-command__foot"><span>Enter to ask</span><span>Esc to close</span><span>Operational provenance only</span></div>
      </section>
    </div>
  );
}
