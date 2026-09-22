import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { PointerEvent as ReactPointerEvent } from 'react';
import {
  ArrowRight,
  BookOpenText,
  Bot,
  GitBranch,
  Check,
  ChevronRight,
  Code2,
  FileText,
  GitMerge,
  Link2,
  Maximize2,
  MessageSquareText,
  Minimize2,
  Network,
  NotebookPen,
  Rows3,
  Sparkles,
  SquareTerminal,
  UserRound,
} from 'lucide-react';
import type { AuraFlowNode, AuraNodeData, NodeDensity } from '../../types';


function updateGlow(event: ReactPointerEvent<HTMLDivElement>) {
  const rect = event.currentTarget.getBoundingClientRect();
  event.currentTarget.style.setProperty('--glow-x', `${event.clientX - rect.left}px`);
  event.currentTarget.style.setProperty('--glow-y', `${event.clientY - rect.top}px`);
}

const densityIcons: Record<NodeDensity, typeof Minimize2> = {
  collapsed: Rows3,
  compact: Maximize2,
  full: Minimize2,
};

function kindIcon(kind: AuraNodeData['kind']) {
  switch (kind) {
    case 'user':
      return UserRound;
    case 'answer':
      return Sparkles;
    case 'note':
      return NotebookPen;
    case 'bridge':
      return Link2;
    case 'merge':
      return GitMerge;
    case 'paper':
      return BookOpenText;
    case 'code-result':
      return Code2;
    case 'execution-result':
      return SquareTerminal;
    case 'execution':
      return Network;
    default:
      return FileText;
  }
}

export function AuraNodeCard({ id, data, selected }: NodeProps<AuraFlowNode>) {
  const Icon = kindIcon(data.kind);
  const DensityIcon = densityIcons[data.density];
  const isExecution = data.kind === 'execution';
  const displayText = data.density === 'collapsed' ? data.summary ?? data.body : data.density === 'compact' ? data.summary ?? data.body : data.body;

  return (
    <div
      onPointerMove={updateGlow}
      className={`aura-node glow-surface aura-node--${data.kind} aura-node--${data.accent ?? 'slate'} aura-node--${data.density} ${selected ? 'is-selected' : ''} ${data.running ? 'is-running' : ''}`}
    >
      <Handle id="target-left" type="target" position={Position.Left} className="aura-handle aura-handle--target" />
      <Handle id="source-left" type="source" position={Position.Left} className="aura-handle aura-handle--source" />
      <Handle id="target-right" type="target" position={Position.Right} className="aura-handle aura-handle--target" />
      <Handle id="source-right" type="source" position={Position.Right} className="aura-handle aura-handle--source" />
      <Handle id="target-top" type="target" position={Position.Top} className="aura-handle aura-handle--target" />
      <Handle id="source-top" type="source" position={Position.Top} className="aura-handle aura-handle--source" />
      <Handle id="target-bottom" type="target" position={Position.Bottom} className="aura-handle aura-handle--target" />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="aura-handle aura-handle--source" />

      <div className="aura-node__topline">
        <div className="aura-node__eyebrow">
          <span className="aura-node__icon"><Icon size={isExecution ? 11 : 13} /></span>
          <span>{data.eyebrow ?? data.kind.toUpperCase()}</span>
          {data.manual ? <span className="manual-tag">Manual</span> : null}
          {data.running ? <span className="node-running-dot" /> : null}
        </div>
        {isExecution ? null : (
          <button
            className="node-density nodrag nopan"
            type="button"
            title={`Current density: ${data.density}`}
            onClick={(event) => {
              event.stopPropagation();
              data.onCycleDensity?.(id);
            }}
          >
            <DensityIcon size={12} />
          </button>
        )}
      </div>

      <h3 className="aura-node__title">{data.title}</h3>

      {data.kind === 'bridge' && data.density === 'full' ? (
        <BridgeBody id={id} data={data} />
      ) : data.kind === 'merge' && data.density === 'full' ? (
        <MergeBody id={id} data={data} />
      ) : data.kind === 'note' && data.density === 'full' ? (
        <textarea
          className="note-editor nodrag nopan"
          value={data.body}
          onChange={(event) => data.onChangeBody?.(id, event.target.value)}
          aria-label="Edit manual note"
        />
      ) : (
        <p className="aura-node__body">{displayText}</p>
      )}

      {data.chip ? (
        <div className="node-execution-chip">
          <Bot size={11} />
          <span>{data.chip}</span>
        </div>
      ) : null}

      {data.kind === 'answer' ? (
        <div className="aura-node__actions nodrag nopan">
          <button type="button" onClick={() => data.onBranch?.(id)}>
            <GitBranch size={11} /> Branch from here
          </button>
        </div>
      ) : null}
    </div>
  );
}

function BridgeBody({ id, data }: { id: string; data: AuraNodeData }) {
  const options = data.bridgeOptions ?? {
    conclusions: true,
    observations: true,
    failed: false,
    artifacts: false,
  };

  return (
    <div className="bridge-body">
      <div className="bridge-route">
        <span>{data.from ?? 'Branch A'}</span>
        <ArrowRight size={13} />
        <span>{data.to ?? 'Branch B'}</span>
      </div>
      <div className="bridge-checks nodrag nopan">
        {([
          ['conclusions', 'Conclusions'],
          ['observations', 'Important observations'],
          ['failed', 'Failed attempts'],
          ['artifacts', 'Artifacts'],
        ] as const).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={options[key]}
              onChange={(event) => data.onBridgeOption?.(id, key, event.target.checked)}
            />
            <span className="custom-check">{options[key] ? <Check size={10} /> : null}</span>
            <span>{label}</span>
          </label>
        ))}
      </div>
      <div className="bridge-note">
        <span>User note</span>
        <p>{data.bridgeNote}</p>
      </div>
      <button className="node-primary-action nodrag nopan" type="button" onClick={() => data.onBridgeApply?.(id)}>
        Apply to Branch C <ChevronRight size={12} />
      </button>
    </div>
  );
}

function MergeBody({ id, data }: { id: string; data: AuraNodeData }) {
  return (
    <div className="merge-body">
      <div className="merge-count">{data.sourceCount ?? data.mergeItems?.length ?? 0} sources</div>
      <div className="merge-items">
        {(data.mergeItems ?? []).map((item) => (
          <div key={item}>
            <MessageSquareText size={11} />
            <span>{item}</span>
          </div>
        ))}
      </div>
      <button className="node-primary-action nodrag nopan" type="button" onClick={() => data.onContinueMerge?.(id)}>
        Continue from merged context <ChevronRight size={12} />
      </button>
    </div>
  );
}
