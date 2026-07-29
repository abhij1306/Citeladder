"""The shared queue-drain loop every worker exposes for tests/one-shot runs.

``run_until_idle`` was reimplemented verbatim in five workers (audit, analytics,
content, integration, site health). The body is trivial, which is exactly why
copies drift silently: one worker's bound could be changed, or a copy could
stop honouring the "a claim that returns nothing means idle" contract, without
anything failing loudly.

The mixin only needs a ``run_once``-shaped coroutine returning the number of
tasks handled, so it composes with any of the worker loop styles (the audit
worker overrides it to drive its pipelined pump instead).
"""

from __future__ import annotations

from typing import Protocol


class _RunsOnce(Protocol):
    async def run_once(self) -> int: ...


class DrainableWorkerMixin:
    """Adds ``run_until_idle`` to a worker exposing ``run_once``."""

    async def run_until_idle(self: _RunsOnce, *, max_batches: int = 1000) -> int:
        """Drain the queue until a claim returns nothing (test/one-shot).

        ``max_batches`` bounds the degenerate case where new work keeps
        arriving faster than the queue empties, so a test can never hang.
        """
        total = 0
        for _ in range(max(1, max_batches)):
            ran = await self.run_once()
            if ran == 0:
                break
            total += ran
        return total
