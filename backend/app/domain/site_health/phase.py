# The Site Health screen phase — resolved ONCE, on the server.
#
# This used to live in the browser (`frontend/lib/site-health/status.ts`) as a
# 14-clause ordered precedence chain over six independently-loading inputs:
# `crawl.status` (9 values), `discovery_status` (7), `analysis_status` (7),
# the phase-run statuses, the resolved access mode, and whether the project had
# a committed monitored set. Three of those arrived from three separate HTTP
# requests, so the client resolved against whichever landed first and corrected
# itself afterwards — which is what made the screen visibly flip between the URL
# list and the analysis view. Each such incident added another clause.
#
# The server holds all six inputs in one transaction, so it can answer once.
# The client renders what it is told and has no precedence rules of its own.
from __future__ import annotations

from typing import Final, Literal

from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_PAUSED,
    DISCOVERY_STATUS_CANCELLED,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    DISCOVERY_STATUS_STOPPED,
)
from app.models.site_health.crawl import SiteCrawl

SiteHealthPhase = Literal[
    "empty",
    "discovering",
    "analyzing",
    "dashboard",
    "terminal",
]

#: Discovery has no more live work in any of these states.
TERMINAL_DISCOVERY: Final[frozenset[str]] = frozenset(
    {
        DISCOVERY_STATUS_COMPLETED,
        DISCOVERY_STATUS_SAMPLE_COMPLETED,
        DISCOVERY_STATUS_FAILED,
        DISCOVERY_STATUS_CANCELLED,
        DISCOVERY_STATUS_STOPPED,
    }
)

#: A parked crawl keeps its inventory but has no live work.
_PARKED_STATUSES: Final[frozenset[str]] = frozenset(
    {CRAWL_STATUS_CANCELLED, CRAWL_STATUS_PAUSED}
)


def _has_real_scores(score_summary: dict | None) -> bool:
    """True when the summary carries an actual score, not just a shell.

    A fully-failed crawl persists a PRESENT-but-null-score summary
    (``persist_empty=True``), so ``score_summary is not None`` alone reads that
    shape as dashboard-worthy — the bug that hid every failed crawl behind an
    empty dashboard. Requiring at least one measured projection distinguishes them
    without a separate failure probe.
    """
    return score_summary is not None and (
        score_summary.get("technical_integrity_state", "not_measured") != "not_measured"
        or score_summary.get("aeo_measurement_state", "not_measured") != "not_measured"
    )


def resolve_phase(
    crawl: SiteCrawl | None,
    *,
    score_summary: dict | None,
    has_monitored_selection: bool,
) -> SiteHealthPhase:
    """Resolve the screen phase for ``crawl``.

    :param score_summary: the crawl's projected summary, if any.
    :param has_monitored_selection: the PROJECT has at least one active
        monitored URL committed.
    """
    if crawl is None:
        return "empty"

    # Finished, or finished with holes — the dashboard is the answer either way.
    if crawl.status in (CRAWL_STATUS_COMPLETED, CRAWL_STATUS_PARTIALLY_COMPLETED):
        return "dashboard"

    # Real partial scores outrank a failure: a crawl that analyzed something
    # before dying still has a dashboard worth showing.
    if _has_real_scores(score_summary):
        return "dashboard"

    if crawl.status == CRAWL_STATUS_FAILED:
        return "terminal"

    # A parked crawl with no scores is terminal. Page selection is not a crawl
    # phase: discovery and analysis are one bounded run, and a new crawl is the
    # only way to resume work.
    if crawl.status in _PARKED_STATUSES:
        return "terminal"

    # Everything below is an ACTIVE crawl (draft/validating/queued/running).
    #
    # A project with a committed monitored set is an analysis run from the
    # moment the crawl is created: the planner seeds the analyze tasks at
    # creation, so `analysis_status` merely lags at 'pending' until the
    # worker's first reconcile. Resolving it as discovery would bounce the
    # screen back to an inventory-only view after a new crawl starts.
    if has_monitored_selection:
        return "analyzing"

    if crawl.discovery_status not in TERMINAL_DISCOVERY:
        return "discovering"

    # Discovery completion never opens a separate selection/analysis step.
    # Automatic admission owns the bounded analysis set; keep the same live
    # results surface mounted until the crawl terminalizes.
    return "analyzing"
