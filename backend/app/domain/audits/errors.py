"""Typed audit-planning failures at the API boundary."""

from __future__ import annotations

from typing import Any


class AuditValidationError(ValueError):
    """Raised when an audit request is invalid (bad prompts/engines/routes)."""


class AuditNotFoundError(LookupError):
    """Raised when an audit is missing or not in the caller's workspace."""


class FundedAdmissionError(RuntimeError):
    """Graceful funded-admission refusal mapped at the API layer."""

    def __init__(
        self, message: str, *, code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class PromptCountPolicyError(RuntimeError):
    """Funded/trial prompt-count admission refusal mapped at the API layer."""

    def __init__(
        self, message: str, *, code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
