import type { AIProvenanceItem, RunEvent } from '../types';

const OBJECT_LABELS: Record<string, string> = {
  context_bridge: 'Context Bridge',
  context_set: 'Context Set',
  conversation_branch: 'Conversation branch',
  manual_note: 'Manual note',
  research_source: 'Research source',
  research_evidence: 'Research evidence',
  research_claim: 'Research claim',
};

export function contextProvenanceFromRunEvents(events: RunEvent[]): AIProvenanceItem[] {
  const manifest = [...events].reverse().find((event) => event.event_type === 'context_compiled')?.payload;
  const objects = manifest?.objects;
  if (!Array.isArray(objects)) return [];

  return objects.flatMap((value, index) => {
    if (!value || typeof value !== 'object') return [];
    const item = value as Record<string, unknown>;
    if (typeof item.object_id !== 'string' || typeof item.object_type !== 'string') return [];

    const objectType = item.object_type;
    const label = OBJECT_LABELS[objectType]
      ?? (objectType.split('_').filter(Boolean).map((part) => part[0].toUpperCase() + part.slice(1)).join(' ')
        || 'Workspace object');
    const kind: AIProvenanceItem['kind'] = objectType === 'research_source'
      ? 'source'
      : /artifact|code|execution_result/.test(objectType) ? 'artifact' : 'context';

    return [{
      id: `context-${item.object_id}-${index}`,
      label,
      detail: `${item.selected_by_user === true ? 'Selected' : 'Included through selected context'} · ${item.object_id}`,
      kind,
      nodeId: item.object_id,
    }];
  });
}

export function compiledContextTokenCount(events: RunEvent[]): number | undefined {
  const manifest = [...events].reverse().find((event) => event.event_type === 'context_compiled')?.payload;
  return typeof manifest?.estimated_tokens === 'number' && Number.isFinite(manifest.estimated_tokens)
    ? manifest.estimated_tokens
    : undefined;
}
