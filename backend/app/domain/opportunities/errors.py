"""Shared errors for the workspace-scoped Opportunities owner."""

from app.core.config.opportunities import CODE_OPPORTUNITY_SUPERSEDED


class OpportunityNotFoundError(Exception):
    """A workspace-scoped resource was missing or foreign (404)."""


class OpportunityValidationError(Exception):
    """An unknown filter, status, or request token was supplied (422)."""


class OpportunitySupersededError(Exception):
    """A mutation targeted a superseded row (409)."""

    code = CODE_OPPORTUNITY_SUPERSEDED


class OpportunityOrderConflictError(Exception):
    """The project order changed after the caller read its version."""


class OpportunityGuidanceUnavailableError(Exception):
    """Guidance is unavailable outside the configured eligibility gate."""


class OpportunityGuidanceIdempotencyConflictError(Exception):
    """An idempotency key was replayed for changed frozen input."""


class InvalidCursorError(Exception):
    """A cursor was tampered with or replayed across scopes (400)."""
