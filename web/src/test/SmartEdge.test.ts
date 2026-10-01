import { describe, expect, it } from 'vitest';
import { getEdgeLabel } from '../components/board/SmartEdge';

describe('Board relationship labels', () => {
  it('explains persisted Research provenance links', () => {
    expect(getEdgeLabel('semantic', 'contains_evidence')).toBe('Contains evidence');
    expect(getEdgeLabel('semantic', 'supports_claim')).toBe('Supports claim');
  });

  it('labels workspace context relationships and keeps generic fallbacks', () => {
    expect(getEdgeLabel('context', 'selected_into')).toBe('Included in context set');
    expect(getEdgeLabel('semantic', 'related_to')).toBe('Semantic link');
    expect(getEdgeLabel('reply')).toBe('Reply');
  });
});
