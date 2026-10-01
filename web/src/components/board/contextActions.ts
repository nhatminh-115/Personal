export interface ContextObjectReference {
  id: string;
  title: string;
}

export function buildMergedContinuation(
  target: ContextObjectReference,
  selected: ContextObjectReference[],
) {
  const sourceIds = [...new Set([target.id, ...selected.map((item) => item.id)])];
  const byId = new Map([target, ...selected].map((item) => [item.id, item.title]));
  return {
    object_type: 'conversation_branch' as const,
    title: `Merged continuation from ${target.title}`,
    content: '',
    metadata_json: {
      branch_source_title: target.title,
      merged_into_branch_id: target.id,
      source_count: sourceIds.length,
      source_titles: sourceIds.map((id) => byId.get(id) ?? id),
    },
    source_object_ids: sourceIds,
  };
}
