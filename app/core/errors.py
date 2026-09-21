"""Explicit error categories for AURA."""


class AuraError(Exception):
    """Base exception for all AURA domain errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


AURAError = AuraError



class ProviderError(AuraError):
    """Raised when an external model provider fails, times out, or errors."""
    pass


class MalformedModelOutputError(AuraError):
    """Raised when model response cannot be parsed or lacks expected structure."""
    pass


class ToolExecutionError(AuraError):
    """Raised when a tool fails during execution."""
    pass


class PermissionDeniedError(AuraError):
    """Raised when an action violates the capability policy or is explicitly denied."""
    pass


class ApprovalRequiredError(AuraError):
    """Raised/signaled when an action requires human-in-the-loop approval before proceeding."""
    pass


class WorkspaceEscapeError(PermissionDeniedError):
    """Raised when a tool attempts to access a path outside the configured workspace sandbox."""
    pass


class DatabaseError(AuraError):
    """Raised when a database query or transaction fails."""
    pass


class SessionNotFoundError(AuraError):
    """Raised when a requested session ID does not exist."""
    pass


class ApprovalNotFoundError(AuraError):
    """Raised when a requested approval ID does not exist."""
    pass


class InternalExecutionError(AuraError):
    """Raised when the agent runtime encounters an unrecoverable internal error."""
    pass


# Convenience aliases
PermissionError = PermissionDeniedError
ToolError = ToolExecutionError


# --- Routing Errors ---

class ModelUnavailable(AuraError):
    """Raised when a specified provider or model is not available or registered."""
    pass


class ModelCapabilityMismatch(AuraError):
    """Raised when a selected model lacks required capabilities (e.g., tools, vision)."""
    pass


class NoEligibleRoute(AuraError):
    """Raised when no provider/model combination satisfies the current routing context constraints."""
    pass


class ReasoningControlUnsupported(AuraError):
    """Raised when a routing context requests reasoning effort bounds that the model cannot natively control."""
    pass


class RoutingConfirmationRequired(AuraError):
    """Special domain outcome to halt execution when a cloud fallback is requested under ask_before_cloud policy."""
    pass


class PrivacyBoundaryViolation(AuraError):
    """Raised when a requested model/route violates a strict privacy boundary (e.g. local_only)."""
    pass


class InvalidRoutingProfile(AuraError):
    """Raised when a RoutingProfile configuration is semantically invalid or bounds are contradictory."""
    pass
