"""Per-phase handlers for ``SiteHealthWorker``: discover, analyze, link check.

These are MIXINS, not separate worker processes. The single claim loop is what
makes cross-kind reconcile correct (a crawl terminalizes only when every task
of every kind has drained) and what keeps the per-host politeness gate
coherent, so splitting the worker into four processes would mean four gates
over the same hosts plus a distributed terminalization protocol.

Splitting the FILE is the actual goal: each phase is now readable on its own,
while method resolution still happens on one class at runtime, so behaviour is
unchanged. The infrastructure each phase leans on (session factory, queue,
lease heartbeat, artifact/attempt writers) is declared once in
``PhaseSupport`` for type-checking.
"""

from __future__ import annotations

from app.workers.site_health.phases.analyze import AnalyzePhaseMixin
from app.workers.site_health.phases.discover import DiscoverPhaseMixin
from app.workers.site_health.phases.link_check import LinkCheckPhaseMixin

__all__ = ["AnalyzePhaseMixin", "DiscoverPhaseMixin", "LinkCheckPhaseMixin"]
