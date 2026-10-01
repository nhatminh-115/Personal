import { BadgeCheck, BookOpen, Braces, FileText, LocateFixed, Network, NotebookPen, ScrollText, X } from 'lucide-react';
import type { AIContextItem } from '../../types';

interface AIContextPanelProps {
  items: AIContextItem[];
  contextIsLive: boolean;
  onToggleItem: (id: string) => void;
  onFocusItem?: (nodeId: string) => void;
  onClose: () => void;
}

const iconByKind = {
  turn: ScrollText,
  note: NotebookPen,
  paper: BookOpen,
  claim: BadgeCheck,
  code: Braces,
  file: FileText,
} as const;

export function AIContextPanel({ items, contextIsLive, onToggleItem, onFocusItem, onClose }: AIContextPanelProps) {
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

      <div className="ai-context-summary">
        <span><Network size={13} /> {included.length} objects included</span>
        <strong>~{(tokens / 1000).toFixed(1)}k estimated tokens</strong>
      </div>

      <div className="ai-context-items">
        {items.length === 0 ? <p className="ai-context-empty">{contextIsLive ? 'No saved workspace objects are available in this project yet.' : 'This demo uses illustrative context only.'}</p> : null}
        {items.map((item) => {
          const Icon = iconByKind[item.kind];
          return (
            <div className="ai-context-item-row" key={item.id}>
              <button
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
                <em>~{item.tokens >= 1000 ? `${(item.tokens / 1000).toFixed(1)}k` : item.tokens}</em>
              </button>
              {contextIsLive && item.nodeId && onFocusItem ? (
                <button
                  className="ai-context-item__focus"
                  type="button"
                  aria-label={`Show ${item.title} on Board`}
                  title="Show on Board"
                  onClick={() => onFocusItem(item.nodeId!)}
                >
                  <LocateFixed size={13} />
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="ai-context-panel__foot">
        <small>{contextIsLive ? 'Only selected saved project objects are sent with this message. Hidden chain-of-thought is never exposed.' : 'Illustrative demo context is not sent to the backend.'}</small>
      </div>
    </div>
  );
}
