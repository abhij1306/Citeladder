"""Explicit execution phases for the Site Health worker.

All task kinds stay on one worker and one PostgreSQL queue. Each phase module
exposes ``run(ctx, task)`` and receives a frozen Site Health capability
context; the worker retains the claim loop, host gate, lease heartbeat, and
lifecycle owner. This is not a repository-wide worker abstraction, and
AuditWorker is intentionally unchanged.
"""

from __future__ import annotations
