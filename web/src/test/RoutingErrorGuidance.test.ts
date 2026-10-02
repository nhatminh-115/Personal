import { describe, expect, it } from 'vitest';
import { executionErrorText } from '../lib/executionError';
import { ApiError } from '../services/api';

describe('routing error guidance', () => {
  it.each([
    ['ModelCapabilityMismatch', 'compatible model'],
    ['ReasoningControlUnsupported', 'Use Profile reasoning'],
    ['ModelUnavailable', 'AURA did not substitute another model'],
    ['NoEligibleRoute', 'Review the profile in Routing Studio'],
  ])('gives actionable guidance for %s without exposing structured details', (code, guidance) => {
    const message = executionErrorText(new ApiError(
      422,
      'Routing could not satisfy the request.',
      code,
      { internal_trace: 'private router internals' },
    ));

    expect(message).toContain('Routing could not satisfy the request.');
    expect(message).toContain(guidance);
    expect(message).not.toContain('private router internals');
    expect(message).not.toContain(code);
  });
});
