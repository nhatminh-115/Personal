import { describe, expect, it } from 'vitest';
import { executionErrorText } from '../lib/executionError';
import { ApiError } from '../services/api';

describe('model error guidance', () => {
  it.each([
    ['ModelProviderError', 'Check the provider connection'],
    ['PrivacyBoundaryViolation', 'remove sensitive context'],
    ['ModelCapabilityMismatch', 'compatible model'],
    ['ReasoningControlUnsupported', 'Choose Auto'],
    ['ModelUnavailable', 'Kuractus did not substitute a different model'],
    ['NoEligibleRoute', 'Select a different model'],
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
