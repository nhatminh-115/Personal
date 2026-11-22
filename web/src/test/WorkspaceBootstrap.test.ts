import { describe, expect, it } from 'vitest';
import { workspaceRecordsForRuntime } from '../lib/workspaceBootstrap';

describe('workspace fixture bootstrap', () => {
  const records = [
    { id: 'demo', source: 'demo' },
    { id: 'bundled-file', source: 'bundled' },
    { id: 'live', source: 'live' },
    { id: 'imported', source: 'imported' },
    { id: 'unmarked-user-record' },
  ];

  it('keeps demo fixtures in browser prototype mode', () => {
    expect(workspaceRecordsForRuntime(records, false)).toEqual(records);
  });

  it('filters demo fixtures from desktop while preserving real records', () => {
    expect(workspaceRecordsForRuntime(records, true)).toEqual([
      { id: 'live', source: 'live' },
      { id: 'imported', source: 'imported' },
      { id: 'unmarked-user-record' },
    ]);
  });
});
