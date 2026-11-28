import { ApiError } from '../services/api';

const MODEL_ERROR_GUIDANCE: Record<string, string> = {
  ModelProviderError: 'Check the provider connection and choose an available model in the composer.',
  PrivacyBoundaryViolation: 'This conversation cannot send its current context to the selected provider. Choose an eligible model or remove sensitive context.',
  ModelCapabilityMismatch: 'The selected model cannot meet this request’s capability requirements. Choose a compatible model or adjust the request requirements.',
  ReasoningControlUnsupported: 'This model does not offer that reasoning level. Choose Auto or select a model that supports it.',
  ModelUnavailable: 'The selected model is unavailable. Reconnect its provider or choose another available model; Kuractus did not substitute a different model.',
  NoEligibleRoute: 'No available model can handle this request with its current context and capabilities. Select a different model or adjust the request.',
};

export function executionErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'AutomationRevisionConflict') {
      return 'This automation changed elsewhere. Reload the Automations list, then retry your change.';
    }
    if (error.code === 'RoutingProfileVersionConflict') {
      return 'Internal model settings changed elsewhere. Reload Kuractus, then retry your request.';
    }
    if (error.code === 'RoutingAssignmentRevisionConflict') {
      return 'Internal model settings changed elsewhere. Reload Kuractus, then retry your request.';
    }
    if (error.code === 'WorkspaceLibraryRevisionConflict') {
      return 'This Library reference changed elsewhere. Refresh the Kuractus workspace before changing its project links or removing it.';
    }
    if (error.code === 'WorkspaceProjectRevisionConflict') {
      return 'This project archive state changed elsewhere. Reload Kuractus if the Projects list still looks stale, then retry.';
    }
    const nextStep = error.code ? MODEL_ERROR_GUIDANCE[error.code] : undefined;
    return `${error.message}${nextStep ? ` ${nextStep}` : ''}`;
  }
  return (error as Error)?.message || 'Execution failed';
}
