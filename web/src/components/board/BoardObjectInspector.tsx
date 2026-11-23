import { ArrowDownLeft, ArrowUpRight, Link2, Sparkles, X } from 'lucide-react';
import type { AuraFlowNode } from '../../types';
import './BoardObjectInspector.css';

export interface BoardObjectRelation {
  id: string;
  node: AuraFlowNode;
  direction: 'Incoming' | 'Outgoing';
  label: string;
}

interface BoardObjectInspectorProps {
  node: AuraFlowNode;
  relationships: BoardObjectRelation[];
  onClose: () => void;
  onSelectRelationship: (node: AuraFlowNode) => void;
  onAskWithContext?: (prompt: string, objectIds: string[]) => void | Promise<void>;
}

function originLabel(node: AuraFlowNode): string {
  if (node.data.workspaceCreatedBy === 'user') return 'User-authored';
  if (node.data.workspaceCreatedBy === 'assistant') return 'AURA-generated';
  return node.data.workspaceCreatedBy || 'Workspace object';
}

export function BoardObjectInspector({
  node,
  relationships,
  onClose,
  onSelectRelationship,
  onAskWithContext,
}: BoardObjectInspectorProps) {
  const objectType = node.data.workspaceObjectType?.replace(/_/g, ' ') || node.data.eyebrow || node.data.kind;
  const description = node.data.body || node.data.summary || 'No additional description is stored for this object.';

  return (
    <aside className="board-object-inspector" aria-label="Board object inspector">
      <header className="board-object-inspector__header">
        <div>
          <span>OBJECT INSPECTOR</span>
          <i aria-hidden="true" />
        </div>
        <button type="button" aria-label="Close object inspector" title="Close inspector" onClick={onClose}>
          <X size={14} />
        </button>
      </header>

      <div className="board-object-inspector__scroll">
        <span className={`board-object-inspector__type board-object-inspector__type--${node.data.accent ?? 'cyan'}`}>
          {objectType}
        </span>
        <h3>{node.data.title || 'Untitled object'}</h3>
        <p className="board-object-inspector__description">{description}</p>

        <section className="board-object-inspector__origin">
          <span className="board-object-inspector__section-label">ORIGIN & PROVENANCE</span>
          <dl>
            <div><dt>Created by</dt><dd>{originLabel(node)}</dd></div>
            <div><dt>Object ID</dt><dd title={node.id}>{node.id}</dd></div>
            {node.data.messageId ? <div><dt>Source message</dt><dd title={node.data.messageId}>{node.data.messageId}</dd></div> : null}
            {typeof node.data.workspaceRevision === 'number' ? <div><dt>Revision</dt><dd>v{node.data.workspaceRevision}</dd></div> : null}
          </dl>
        </section>

        <section className="board-object-inspector__relationships">
          <div className="board-object-inspector__section-heading">
            <strong>Relationships</strong>
            <span>{relationships.length}</span>
          </div>
          {relationships.length ? (
            <div className="board-object-inspector__relation-list">
              {relationships.map((relationship) => {
                const DirectionIcon = relationship.direction === 'Outgoing' ? ArrowUpRight : ArrowDownLeft;
                return (
                  <button
                    key={relationship.id}
                    type="button"
                    className="board-object-inspector__relation"
                    onClick={() => onSelectRelationship(relationship.node)}
                    aria-label={`Open related object ${relationship.node.data.title}`}
                  >
                    <span className={`board-object-inspector__relation-dot board-object-inspector__relation-dot--${relationship.node.data.accent ?? 'cyan'}`} />
                    <span className="board-object-inspector__relation-copy">
                      <strong>{relationship.node.data.title}</strong>
                      <small><DirectionIcon size={10} /> {relationship.direction} · {relationship.label}</small>
                    </span>
                    <Link2 size={12} />
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="board-object-inspector__empty">No linked objects are recorded yet.</p>
          )}
        </section>
      </div>

      {onAskWithContext ? (
        <footer className="board-object-inspector__footer">
          <button
            type="button"
            onClick={() => void onAskWithContext(
              `Review “${node.data.title}” and explain its relationship to the surrounding project context.`,
              [node.id],
            )}
          >
            <Sparkles size={13} /> Ask AURA with this object
          </button>
        </footer>
      ) : null}
    </aside>
  );
}
