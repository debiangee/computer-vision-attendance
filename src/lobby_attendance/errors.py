"""Application-level exceptions with safe, non-biometric error messages."""


class LobbyAttendanceError(Exception):
    """Base class for expected application errors."""


class ConfigurationError(LobbyAttendanceError):
    """Raised when deployment configuration is invalid."""


class AuthorizationError(LobbyAttendanceError):
    """Raised when a principal lacks a required permission."""


class ComplianceApprovalError(LobbyAttendanceError):
    """Raised when biometric activation lacks explicit privacy/legal approval."""


class TemplateLifecycleError(LobbyAttendanceError):
    """Raised when activation lacks a current protected template lifecycle record."""


class StorageError(LobbyAttendanceError):
    """Raised when durable local storage cannot complete an operation."""


class IntegrityError(StorageError):
    """Raised when an append-only or idempotency invariant is violated."""
