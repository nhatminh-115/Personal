import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  getSmoothStepPath,
  type EdgeProps,
} from '@xyflow/react';
import { Trash2 } from 'lucide-react';
import type { AuraFlowEdge } from '../../types';

const kindLabel = {
  reply: 'Reply',
  context: 'Context flow',
  semantic: 'Semantic link',
  execution: 'Execution',
} as const;

export function SmartEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
  selected,
}: EdgeProps<AuraFlowEdge>) {
  const kind = data?.edgeKind ?? 'reply';
  const isSemantic = kind === 'semantic';
  const isContext = kind === 'context';
  const isExecution = kind === 'execution';

  const pathResult = isSemantic
    ? getBezierPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
        curvature: 0.2,
      })
    : getSmoothStepPath({
        sourceX,
        sourceY,
        sourcePosition,
        targetX,
        targetY,
        targetPosition,
        borderRadius: 18,
        offset: isContext ? 24 : 18,
      });

  const [edgePath, labelX, labelY] = pathResult;
  const stroke = selected
    ? '#89dceb'
    : isContext
      ? '#61c8db'
      : isExecution
        ? '#4f7680'
        : isSemantic
          ? '#44525f'
          : '#34414f';

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        interactionWidth={22}
        style={{
          stroke,
          strokeWidth: selected ? 2.3 : isContext ? 2.05 : isExecution ? 1.35 : isSemantic ? 1.1 : 1.35,
          strokeDasharray: isSemantic ? '5 7' : isExecution ? '4 5' : undefined,
          opacity: selected ? 1 : isSemantic ? 0.64 : 0.9,
        }}
      />

      {selected ? (
        <EdgeLabelRenderer>
          <div
            className="edge-action-pill nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            <span>{kindLabel[kind]}</span>
            <button
              type="button"
              aria-label={`Delete ${kindLabel[kind].toLowerCase()}`}
              title="Delete link · Del"
              onClick={(event) => {
                event.stopPropagation();
                data?.onDelete?.(id);
              }}
            >
              <Trash2 size={11} />
            </button>
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}
