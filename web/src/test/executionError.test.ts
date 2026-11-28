import { describe, expect, it } from 'vitest';
import { ApiError } from '../services/api';
import { executionErrorText } from '../lib/executionError';

describe('structured model error guidance', () => {
  it.each([
    ['PrivacyBoundaryViolation', 'remove sensitive context'],
    ['ModelCapabilityMismatch', 'Choose a compatible model'],
    ['ReasoningControlUnsupported', 'Choose Auto'],
    ['ModelUnavailable', 'Kuractus did not substitute a different model'],
    ['NoEligibleRoute', 'Select a different model'],
  ])('gives actionable guidance for %s without exposing raw details', (code, guidance) => {
    const message = executionErrorText(new ApiError(422, 'Routing request failed.', code, { raw: 'internal diagnostic' }));

    expect(message).toContain('Routing request failed.');
    expect(message).toContain(guidance);
    expect(message).not.toContain('internal diagnostic');
    expect(message).not.toContain('{');
  });

  it('keeps ordinary error messages and supplies a fallback for empty errors', () => {
    expect(executionErrorText(new Error('Network disconnected'))).toBe('Network disconnected');
    expect(executionErrorText(null)).toBe('Execution failed');
  });

  it('explains internal setting conflicts and Library references without exposing an admin UI', () => {
    expect(executionErrorText(new ApiError(409, 'Profile changed.', 'RoutingProfileVersionConflict')))
      .toContain('Reload Kuractus');
    expect(executionErrorText(new ApiError(409, 'Assignment changed.', 'RoutingAssignmentRevisionConflict')))
      .toContain('Internal model settings changed elsewhere');
    expect(executionErrorText(new ApiError(409, 'Library reference changed.', 'WorkspaceLibraryRevisionConflict')))
      .toContain('Refresh the Kuractus workspace');
    expect(executionErrorText(new ApiError(409, 'Project archive state changed.', 'WorkspaceProjectRevisionConflict')))
      .toContain('Reload Kuractus');
  });
});
