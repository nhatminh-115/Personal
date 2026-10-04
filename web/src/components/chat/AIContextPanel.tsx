import { BadgeCheck, BookOpen, Braces, FileText, LocateFixed, Network, NotebookPen, ScrollText, Send, X } from 'lucide-react';
import type { AIContextItem } from '../../types';

interface AIContextPanelProps {
  items: AIContextItem[];
  contextIsLive: boolean;
  hasMore?: boolean;
  loading?: boolean;
  loadingOlder?: boolean;
  loadError?: string | null;
  onLoadOlder?: () => Promise<void>;
  onRetry?: () => void;
  onToggleItem: (id: string) => void;
  onToggleFileContent?: (objectId: string, include: boolean) => void;
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

export function AIContextPanel({ items, contextIsLive, hasMore = false, loading = false, loadingOlder = false, loadError = null, onLoadOlder, onRetry, onToggleItem, onToggleFileContent, onFocusItem, onClose }: AIContextPanelProps) {
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
        {items.length === 0 ? <p className="ai-context-empty">{loading ? 'Loading saved project objects…' : loadError ? 'Saved project objects could not be loaded.' : contextIsLive ? 'No saved workspace objects are available in this project yet.' : 'This demo uses illustrative context only.'}</p> : null}
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
              {contextIsLive && item.nodeId && item.kind === 'file' && item.fileContentAvailable && onToggleFileContent ? (
                <button
                  className={`ai-context-item__content ${item.fileContentIncluded ? 'is-enabled' : ''}`}
                  type="button"
                  aria-pressed={Boolean(item.fileContentIncluded)}
                  aria-label={`${item.fileContentIncluded ? 'Stop sending' : 'Send'} ${item.title} text to AURA`}
                  title={item.fileContentIncluded ? 'File text will be sent with the next message' : 'Send this browser-local text file with the next message'}
                  onClick={() => onToggleFileContent(item.nodeId!, !item.fileContentIncluded)}
                >
                  <Send size={12} /> {item.fileContentIncluded ? 'Text on' : 'Send text'}
                </button>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="ai-context-panel__foot">
        {loadError && onRetry ? <button type="button" onClick={onRetry}>Retry</button> : null}
        {hasMore && onLoadOlder ? <button type="button" onClick={() => void onLoadOlder()} disabled={loadingOlder}>{loadingOlder ? 'Loading older objects…' : 'Load older objects'}</button> : null}
        <small>{contextIsLive ? 'File text stays in this browser until you choose Send text. Included text is copied into the durable AURA run; cloud routing pauses for confirmation. Hidden chain-of-thought is never exposed.' : 'Illustrative demo context is not sent to the backend.'}</small>
      </div>
    </div>
  );
}
