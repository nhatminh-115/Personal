import { BookOpen, Braces, FileText, Network, NotebookPen, ScrollText, X } from 'lucide-react';
import type { AIContextItem, ContextScope } from '../../types';

interface AIContextPanelProps {
  items: AIContextItem[];
  scope: ContextScope;
  onScopeChange: (scope: ContextScope) => void;
  onToggleItem: (id: string) => void;
  onClose: () => void;
}

const scopes: { id: ContextScope; label: string }[] = [
  { id: 'branch', label: 'Current branch' },
  { id: 'project', label: 'Project' },
  { id: 'selection', label: 'Selected objects' },
  { id: 'library', label: 'Library' },
];

const iconByKind = {
  turn: ScrollText,
  note: NotebookPen,
  paper: BookOpen,
  code: Braces,
  file: FileText,
} as const;

export function AIContextPanel({ items, scope, onScopeChange, onToggleItem, onClose }: AIContextPanelProps) {
  const included = items.filter((item) => item.included);
  const tokens = included.reduce((sum, item) => sum + item.tokens, 0);

  return (
    <div className="ai-context-panel">
      <div className="ai-context-panel__head">
        <div>
          <span className="eyebrow">CONTEXT</span>
          <strong>What AURA can use</strong>
        </div>
        <button className="icon-button" type="button" onClick={onClose} aria-label="Close context panel">
          <X size={14} />
        </button>
      </div>

      <div className="ai-context-scope" role="tablist" aria-label="Context scope">
        {scopes.map((entry) => (
          <button
            type="button"
            key={entry.id}
            className={scope === entry.id ? 'is-active' : ''}
            onClick={() => onScopeChange(entry.id)}
          >
            {entry.label}
          </button>
        ))}
      </div>

      <div className="ai-context-summary">
        <span><Network size={13} /> {included.length} objects included</span>
        <strong>{(tokens / 1000).toFixed(1)}k tokens</strong>
      </div>

      <div className="ai-context-items">
        {items.map((item) => {
          const Icon = iconByKind[item.kind];
          return (
            <button
              key={item.id}
              type="button"
              className={`ai-context-item ${item.included ? 'is-included' : ''}`}
              onClick={() => onToggleItem(item.id)}
              aria-pressed={item.included}
            >
              <span className="ai-context-item__check" aria-hidden="true">{item.included ? '✓' : ''}</span>
              <span className="ai-context-item__icon"><Icon size={13} /></span>
              <span className="ai-context-item__copy">
                <strong>{item.title}</strong>
                <small>{item.detail}</small>
              </span>
              <em>{item.tokens >= 1000 ? `${(item.tokens / 1000).toFixed(1)}k` : item.tokens}</em>
            </button>
          );
        })}
      </div>

      <div className="ai-context-panel__foot">
        <small>Explicit manifest only. Hidden chain-of-thought is never exposed.</small>
      </div>
    </div>
  );
}
