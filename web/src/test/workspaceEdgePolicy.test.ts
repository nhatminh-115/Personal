import { describe, expect, it } from 'vitest';
import { isWorkspaceEdgeDeletable } from '../components/board/workspaceEdgePolicy';

describe('workspace edge deletion policy', () => {
  it('keeps system provenance read-only while allowing user and local prototype edges', () => {
    expect(isWorkspaceEdgeDeletable({ data: { createdBy: 'system' } })).toBe(false);
    expect(isWorkspaceEdgeDeletable({ data: { createdBy: 'user' } })).toBe(true);
    expect(isWorkspaceEdgeDeletable({ data: {} })).toBe(true);
  });
});
