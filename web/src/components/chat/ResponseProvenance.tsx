import { Braces, FileText, Network, Route, Sparkles } from 'lucide-react';
import type { AIProvenanceItem } from '../../types';

interface ResponseProvenanceProps {
  route?: string;
  reasoning?: string;
  contextTokens?: number;
  items?: AIProvenanceItem[];
  onFocusObject?: (nodeId: string) => void;
}

export function ResponseProvenance({ route, reasoning, contextTokens, items = [], onFocusObject }: ResponseProvenanceProps) {
  if (!route && !contextTokens && items.length === 0) return null;

  return (
    <div className="response-provenance">
      <div className="response-provenance__summary">
        {route ? <span><Route size={11} /> {route}</span> : null}
        {reasoning ? <span><Sparkles size={11} /> {reasoning}</span> : null}
        {contextTokens ? <span><Network size={11} /> {(contextTokens / 1000).toFixed(1)}k context</span> : null}
      </div>

      {items.length ? (
        <div className="response-provenance__items">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => item.nodeId && onFocusObject?.(item.nodeId)}
              className={item.kind === 'artifact' ? 'is-artifact' : ''}
              title={item.detail}
            >
              {item.kind === 'artifact' ? <Braces size={11} /> : <FileText size={11} />}
              <span>{item.label}</span>
              <small>{item.detail}</small>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
