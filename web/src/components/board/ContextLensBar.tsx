import { Bot, GitBranch, FilePlus2, BookmarkPlus, GitMerge, Link2, X } from 'lucide-react';
import { useState } from 'react';
import type { AuraFlowNode } from '../../types';

interface ContextLensBarProps {
  nodes: AuraFlowNode[];
  onAsk: (prompt: string) => void;
  onCreateNote: () => void;
  onCreateBridge: () => void;
  onCreateBranch: () => void;
  onSaveContextSet: () => void;
  mergeTargets: Array<{ id: string; title: string }>;
  onMergeInto: (targetId: string) => void;
  onClear: () => void;
}

export function ContextLensBar({ nodes, onAsk, onCreateNote, onCreateBridge, onCreateBranch, onSaveContextSet, mergeTargets, onMergeInto, onClear }: ContextLensBarProps) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [mergeOpen, setMergeOpen] = useState(false);
  const [targetId, setTargetId] = useState('');

  const counts = nodes.reduce(
    (acc, node) => {
      if (node.data.kind === 'paper') acc.papers += 1;
      else if (node.data.kind === 'note') acc.notes += 1;
      else if (node.data.kind === 'code-result') acc.code += 1;
      else acc.turns += 1;
      return acc;
    },
    { turns: 0, notes: 0, papers: 0, code: 0 },
  );

  return (
    <div className="context-lens">
      <div className="context-lens__main">
        <strong>{nodes.length} objects selected</strong>
        <div className="context-lens__actions">
          <button type="button" onClick={() => setComposerOpen(!composerOpen)}>
            <Bot size={13} /> Ask AURA
          </button>
          <button type="button" onClick={onCreateNote}>
            <FilePlus2 size={13} /> Create Note
          </button>
          <button type="button" onClick={onCreateBridge}>
            <Link2 size={13} /> Create Bridge
          </button>
          <button type="button" onClick={onCreateBranch}>
            <GitBranch size={13} /> Create Branch
          </button>
          <button type="button" onClick={onSaveContextSet}>
            <BookmarkPlus size={13} /> Save Context Set
          </button>
          <button type="button" onClick={() => { setMergeOpen((open) => !open); setTargetId(''); }}>
            <GitMerge size={13} /> Merge Into…
          </button>
        </div>
        <button className="context-lens__close" type="button" onClick={onClear} aria-label="Clear selection">
          <X size={14} />
        </button>
      </div>

      {mergeOpen ? (
        <div className="context-lens__expanded context-lens__merge" aria-label="Merge selected context into branch">
          {mergeTargets.length ? <>
            <label htmlFor="context-lens-merge-target">Destination branch</label>
            <select id="context-lens-merge-target" value={targetId} onChange={(event) => setTargetId(event.target.value)}>
              <option value="">Choose a branch</option>
              {mergeTargets.map((target) => <option key={target.id} value={target.id}>{target.title}</option>)}
            </select>
            <button type="button" disabled={!targetId} onClick={() => { onMergeInto(targetId); setMergeOpen(false); setTargetId(''); }}>Create merged continuation</button>
          </> : <p role="status">Create a branch before merging selected context into it.</p>}
        </div>
      ) : null}

      {composerOpen ? (
        <div className="context-lens__expanded">
          <div className="lens-composer">
            <input
              autoFocus
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && prompt.trim()) {
                  onAsk(prompt);
                  setPrompt('');
                  setComposerOpen(false);
                }
              }}
              placeholder="Ask AURA about selected context…"
            />
            <button
              type="button"
              onClick={() => {
                if (!prompt.trim()) return;
                onAsk(prompt);
                setPrompt('');
                setComposerOpen(false);
              }}
            >
              Ask
            </button>
          </div>
          <div className="context-manifest">
            <span>Context:</span>
            <small>{counts.turns} conversation turns</small>
            <small>{counts.notes} note</small>
            <small>{counts.papers} papers</small>
            <small>{counts.code} code result</small>
            <strong>Ask AURA includes only selected objects and their explicit context links.</strong>
          </div>
        </div>
      ) : null}
    </div>
  );
}
