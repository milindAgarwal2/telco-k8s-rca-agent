"""Typed failures surfaced by the AIDE command line."""


class AideError(Exception):
    """Base class for expected, user-actionable AIDE failures."""

    exit_code = 2


class ConfigurationError(AideError):
    """Committed or local configuration is absent or invalid."""


class SafetyError(AideError):
    """A path, target, or action violates a safety boundary."""

    exit_code = 3


class ConflictError(AideError):
    """An existing user-owned or locally modified artifact conflicts."""

    exit_code = 4


class ApprovalError(AideError):
    """Required approval is missing, stale, unreadable, or wrong-target."""

    exit_code = 5


class VerificationError(AideError):
    """Required evidence is failed, stale, absent, or not executable."""

    exit_code = 6
