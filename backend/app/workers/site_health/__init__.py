"""Collaborators of ``SiteHealthWorker``.

The worker was one 3,100-line class whose politeness state, lease mechanics,
per-phase handlers and persistence helpers were only separated by comments.
This package splits it by COLLABORATOR, not by process: there is still exactly
one worker class running one claim loop (which is what makes cross-kind
reconcile correct and the per-host gate coherent), but the pieces it delegates
to are now independently readable and testable.
"""

from __future__ import annotations

from app.workers.site_health.host_gate import HostGate
from app.workers.site_health.lifecycle import CrawlLifecycle
from app.workers.site_health.lifecycle_finalize import crawl_root_identity

__all__ = ["CrawlLifecycle", "HostGate", "crawl_root_identity"]
