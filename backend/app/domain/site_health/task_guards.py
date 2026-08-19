# Pure worker-side guard functions (Task 5 wires these into the worker).
#
# Nothing here touches the database: the worker loads the crawl, task,
# membership, and runtime rows (under row lock before persistence) and passes
# them in, so the same decision can be re-checked immediately before network
# I/O and again immediately before evidence is written.
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeGuard

from app.core.config.site_health_contracts import (
    CRAWL_ACTIVE_STATUSES,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_USER,
)
from app.core.config.task_queue import (
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
)
from app.domain.site_health.entitlements import (
    runtime_allows_monitored_analysis,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from app.models.site_health.urls import MonitoredSiteUrl


@dataclass(frozen=True)
class GuardDecision:
    """The outcome of a worker guard check (pure, side-effect free)."""

    ok: bool
    reason: str = ""


def crawl_is_active(crawl: SiteCrawl | None) -> TypeGuard[SiteCrawl]:
    """True only when the crawl still exists and is in an active status.

    A cancelled/terminal crawl means the worker must abandon the task without
    persisting evidence (invariant 3 — no artifact for a cancelled task).
    """
    return crawl is not None and crawl.status in CRAWL_ACTIVE_STATUSES


def lease_is_owned(
    task: SiteCrawlTask | None, *, owner: str
) -> TypeGuard[SiteCrawlTask]:
    """True only when THIS worker still holds the task's lease and is working.

    Guards the double-claim / lost-lease case: between the network call and the
    write the sweeper could have reclaimed the lease and another worker could
    have re-claimed it. Only a leased/running row owned by ``owner`` may write.
    """
    return (
        task is not None
        and task.lease_owner == owner
        and task.status in (TASK_STATUS_LEASED, TASK_STATUS_RUNNING)
    )


def monitored_is_active(
    monitored: MonitoredSiteUrl | None,
) -> TypeGuard[MonitoredSiteUrl]:
    """True only when the URL is still an ACTIVE monitored membership.

    A URL removed mid-fetch (its membership deactivated) must not have its
    analysis persisted — the worker re-checks this immediately before I/O and
    again under row lock before evidence persistence.
    """
    return monitored is not None and monitored.active


def evaluate_task_guard(
    *,
    crawl: SiteCrawl | None,
    task: SiteCrawlTask | None,
    monitored: MonitoredSiteUrl | None,
    runtime: WorkspaceSiteHealthRuntime | None,
    owner: str,
) -> GuardDecision:
    """Combined pure guard the worker calls before I/O and before persistence.

    Re-checks, in order: lease ownership, crawl status, active monitoring, and
    the live runtime row (a lost allowance blocks new work on user-source rows
    while preserving evidence). Returns the first failing reason, or ``ok``
    when all pass. Pure: it never touches the DB — the worker loads the rows
    (under lock before persistence) and passes them in.
    """
    if not lease_is_owned(task, owner=owner):
        return GuardDecision(ok=False, reason="lease_not_owned")
    if not crawl_is_active(crawl):
        return GuardDecision(ok=False, reason="crawl_not_active")
    if not monitored_is_active(monitored):
        return GuardDecision(ok=False, reason="not_actively_monitored")
    source = getattr(monitored, "selection_source", SELECTION_SOURCE_USER)
    if not runtime_allows_monitored_analysis(runtime, selection_source=source):
        return GuardDecision(ok=False, reason="entitlement_revoked")
    return GuardDecision(ok=True)
