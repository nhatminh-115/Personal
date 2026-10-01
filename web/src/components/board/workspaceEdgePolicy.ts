import type { AuraFlowEdge } from '../../types';

/** System-generated provenance is read-only; local prototype edges remain editable. */
export function isWorkspaceEdgeDeletable(edge: Pick<AuraFlowEdge, 'data'>): boolean {
  return edge.data?.createdBy !== 'system';
}
