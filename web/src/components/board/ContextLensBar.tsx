import { Bot, GitBranch, FilePlus2, GitMerge, X } from 'lucide-react';
import { useState } from 'react';
import type { AuraFlowNode } from '../../types';

interface ContextLensBarProps {
  nodes: AuraFlowNode[];
  onAsk: (prompt: string) => void;
  onCreateNote: () => void;
  onCreateBranch: () => void;
  onMerge: () => void;
  onClear: () => void;
}

export function ContextLensBar({ nodes, onAsk, onCreateNote, onCreateBranch, onMerge, onClear }: ContextLensBarProps) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [prompt, setPrompt] = useState('');

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

  const estimatedTokens = (nodes.length * 2.07).toFixed(1);

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
          <button type="button" onClick={onCreateBranch}>
            <GitBranch size={13} /> Create Branch
          </button>
          <button type="button" onClick={onMerge}>
            <GitMerge size={13} /> Merge Into…
          </button>
        </div>
        <button className="context-lens__close" type="button" onClick={onClear} aria-label="Clear selection">
          <X size={14} />
        </button>
      </div>

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
            <strong>Estimated context: {estimatedTokens}k tokens</strong>
          </div>
        </div>
      ) : null}
    </div>
  );
}
