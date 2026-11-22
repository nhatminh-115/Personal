export interface SeededWorkspaceRecord {
  source?: string;
}

/** Keep bundled demo fixtures in the browser prototype, but out of a real desktop workspace. */
export function workspaceRecordsForRuntime<T extends SeededWorkspaceRecord>(
  records: T[],
  isDesktop: boolean,
): T[] {
  return isDesktop ? records.filter((record) => record.source !== 'demo' && record.source !== 'bundled') : records;
}
