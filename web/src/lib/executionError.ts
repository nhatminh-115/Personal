import { ApiError } from '../services/api';

const ROUTING_ERROR_GUIDANCE: Record<string, string> = {
  PrivacyBoundaryViolation: 'Privacy policy blocked this route. Review the profile scope and select a route that meets its privacy boundary.',
  ModelCapabilityMismatch: 'The selected model cannot meet this request’s capability requirements. Choose a compatible model or adjust the request requirements.',
  ReasoningControlUnsupported: 'The selected model does not support the requested reasoning control. Use Profile reasoning or choose a model with known support.',
  ModelUnavailable: 'The configured provider or exact model is currently unavailable. Reconnect it or choose Auto; AURA did not substitute another model.',
  NoEligibleRoute: 'No route meets the current privacy, fallback, capability, and reasoning constraints. Review the profile in Routing Studio.',
};

export function executionErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    const nextStep = error.code ? ROUTING_ERROR_GUIDANCE[error.code] : undefined;
    return `${error.message}${nextStep ? ` ${nextStep}` : ''}`;
  }
  return (error as Error)?.message || 'Execution failed';
}
