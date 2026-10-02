import { Bot, Eye, GitBranch, FilePlus2, BookmarkPlus, GitMerge, Link2, X } from 'lucide-react';
import { useState } from 'react';
import type { AuraFlowNode, WorkspaceContextPreview } from '../../types';

interface ContextLensBarProps {
  nodes: AuraFlowNode[];
  onAsk: (prompt: string) => void;
  onPreviewContext?: () => void;
  contextPreview?: WorkspaceContextPreview | null;
  contextPreviewLoading?: boolean;
  contextPreviewError?: string | null;
  onCreateNote: () => void;
  onCreateBridge: () => void;
  onCreateBranch: () => void;
  onSaveContextSet: () => void;
  mergeTargets: Array<{ id: string; title: string }>;
  onMergeInto: (targetId: string) => void;
  onClear: () => void;
}

export function ContextLensBar({ nodes, onAsk, onCreateNote, onCreateBridge, onCreateBranch, onSaveContextSet, mergeTargets, onMergeInto, onClear, onPreviewContext, contextPreview, contextPreviewLoading = false, contextPreviewError }: ContextLensBarProps) {
  const [composerOpen, setComposerOpen] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [mergeOpen, setMergeOpen] = useState(false);
  const [targetId, setTargetId] = useState('');
  const [previewOpen, setPreviewOpen] = useState(false);

  const counts = nodes.reduce(
    (acc, node) => {
      if (node.data.workspaceObjectType === 'research_claim') acc.claims += 1;
      else if (node.data.workspaceObjectType === 'research_evidence') acc.evidence += 1;
      else if (node.data.kind === 'paper') acc.papers += 1;
      else if (node.data.kind === 'note') acc.notes += 1;
      else if (node.data.kind === 'code-result') acc.code += 1;
      else acc.turns += 1;
      return acc;
    },
    { turns: 0, notes: 0, papers: 0, evidence: 0, claims: 0, code: 0 },
  );

  return (
    <div className="context-lens">
      <div className="context-lens__main">
        <strong>{nodes.length} objects selected</strong>
        <div className="context-lens__actions">
          <button type="button" onClick={() => setComposerOpen(!composerOpen)}>
            <Bot size={13} /> Ask AURA
          </button>
          {onPreviewContext ? (
            <button type="button" aria-expanded={previewOpen} onClick={() => {
              const opening = !previewOpen;
              setPreviewOpen(opening);
              if (opening) onPreviewContext();
            }}>
              <Eye size={13} /> Preview Context
            </button>
          ) : null}
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

      {previewOpen ? (
        <section className="context-lens__expanded context-preview" aria-label="Compiled context preview" aria-live="polite">
          {contextPreviewLoading ? <p role="status">Compiling selected context…</p> : null}
          {contextPreviewError ? <p className="context-preview__error" role="alert">{contextPreviewError}</p> : null}
          {contextPreview && !contextPreviewLoading ? <>
            <div className="context-preview__summary">
              <strong>{contextPreview.estimated_tokens ?? 0} estimated tokens</strong>
              <span>{contextPreview.objects?.filter((object) => object.selected_by_user).length ?? 0} selected · {contextPreview.objects?.length ?? 0} included</span>
              <span>Privacy: {contextPreview.privacy_requirement ?? 'Unclassified'}</span>
              {(contextPreview.required_capabilities?.length ?? 0) > 0 ? <span>Capabilities: {contextPreview.required_capabilities?.join(', ')}</span> : null}
              {contextPreview.requires_tools || contextPreview.requires_vision || contextPreview.requires_structured_output || contextPreview.requires_long_context ? (
                <span>Requirements: {[
                  contextPreview.requires_tools && 'tools',
                  contextPreview.requires_vision && 'vision',
                  contextPreview.requires_structured_output && 'structured output',
                  contextPreview.requires_long_context && 'long context',
                ].filter(Boolean).join(', ')}</span>
              ) : null}
            </div>
            <ul className="context-preview__objects">
              {(contextPreview.objects ?? []).map((object) => (
                <li key={object.object_id}>
                  <span>{object.object_type.replace(/_/g, ' ')}</span>
                  <code>{object.object_id}</code>
                  <small>{object.selected_by_user ? 'selected' : 'included through context links'}</small>
                </li>
              ))}
            </ul>
            <details className="context-preview__text">
              <summary>Inspect compiled text</summary>
              <pre>{contextPreview.prompt_text}</pre>
            </details>
          </> : null}
        </section>
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
            <small>{counts.turns} conversation {counts.turns === 1 ? 'turn' : 'turns'}</small>
            <small>{counts.notes} note{counts.notes === 1 ? '' : 's'}</small>
            <small>{counts.papers} paper{counts.papers === 1 ? '' : 's'}</small>
            <small>{counts.evidence} research evidence {counts.evidence === 1 ? 'item' : 'items'}</small>
            <small>{counts.claims} research claim{counts.claims === 1 ? '' : 's'}</small>
            <small>{counts.code} code result{counts.code === 1 ? '' : 's'}</small>
            <strong>Ask AURA includes only selected objects and their explicit context links.</strong>
          </div>
        </div>
      ) : null}
    </div>
  );
}
