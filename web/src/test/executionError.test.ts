import { describe, expect, it } from 'vitest';
import { ApiError } from '../services/api';
import { executionErrorText } from '../lib/executionError';

describe('structured routing error guidance', () => {
  it.each([
    ['PrivacyBoundaryViolation', 'Review the profile scope'],
    ['ModelCapabilityMismatch', 'Choose a compatible model'],
    ['ReasoningControlUnsupported', 'Use Profile reasoning'],
    ['ModelUnavailable', 'AURA did not substitute another model'],
    ['NoEligibleRoute', 'Review the profile in Routing Studio'],
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

  it('explains revision conflicts for routing profiles and Library references', () => {
    expect(executionErrorText(new ApiError(409, 'Profile changed.', 'RoutingProfileVersionConflict')))
      .toContain('Reload the profile in Routing Studio');
    expect(executionErrorText(new ApiError(409, 'Library reference changed.', 'WorkspaceLibraryRevisionConflict')))
      .toContain('Refresh the AURA workspace');
  });
});
