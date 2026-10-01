import type { AIProvenanceItem, RunEvent } from '../types';

export interface RoutingProvenanceSummary {
  routeLabel?: string;
  reasoningLabel?: string;
}

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
  return contextProvenanceFromManifest(manifest);
}

export function contextProvenanceFromManifest(manifest: Record<string, any> | undefined): AIProvenanceItem[] {
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
  return compiledContextTokenCountFromManifest(manifest);
}

export function compiledContextTokenCountFromManifest(manifest: Record<string, any> | undefined): number | undefined {
  return typeof manifest?.estimated_tokens === 'number' && Number.isFinite(manifest.estimated_tokens)
    ? manifest.estimated_tokens
    : undefined;
}

export function routingSummaryFromRunEvents(events: RunEvent[]): RoutingProvenanceSummary {
  const modelSelection = [...events].reverse().find((event) => event.event_type === 'model_selected')?.payload;
  const reasoningSelection = [...events].reverse().find((event) => event.event_type === 'reasoning_effort_selected')?.payload;
  return routingSummaryFromProvenance({
    provider: modelSelection?.provider,
    model: modelSelection?.model,
    reasoning_effort: reasoningSelection?.selected_effort,
  });
}

export function routingSummaryFromProvenance(provenance: Record<string, any> | undefined): RoutingProvenanceSummary {
  const provider = typeof provenance?.provider === 'string' ? provenance.provider : null;
  const model = typeof provenance?.model === 'string' ? provenance.model : null;
  const effort = typeof provenance?.reasoning_effort === 'string' ? provenance.reasoning_effort : null;
  const routeLabel = provider && model ? `${provider}:${model}` : null;
  const reasoningLabel = !effort || effort === 'unknown'
    ? null
    : effort === 'fixed_by_model' ? 'Fixed by model'
      : effort === 'unsupported' ? 'Reasoning control unsupported'
        : `Reasoning · ${effort[0].toUpperCase()}${effort.slice(1)}`;
  return { routeLabel: routeLabel ?? undefined, reasoningLabel: reasoningLabel ?? undefined };
}
