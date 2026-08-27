"""Executor failures whose handling the queue worker must not have to guess."""

from __future__ import annotations

__all__ = ["TerminalExecutorError"]


class TerminalExecutorError(RuntimeError):
    """A failure retrying cannot fix, carrying the code the caller should see.

    An unconfigured or refusing upstream provider is the case this exists for:
    it used to be swallowed into a `succeeded` task with zero results, so the
    workspace was shown an empty, apparently successful discovery and no
    reason. Terminal, and it does not consume the retry budget.

    Lives outside the worker because the domain executors that raise it are
    themselves imported by the worker's dispatch table.
    """

    def __init__(self, error_code: str, detail: str = "") -> None:
        super().__init__(detail or error_code)
        self.error_code = error_code
