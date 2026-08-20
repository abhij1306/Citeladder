# Site Health read-model + mutation service (Slice 6, workspace-safe).
#
# Owns every workspace-scoped projection the Site Health API exposes: the
# entitlement view, crawl summaries/list, keyset inventory, monitored set, page
# summaries/detail, grouped issues + issue detail + per-URL issue history, the
# dashboard, event replay, and the atomic crawl cancel. It is the single place
# the plan's projection rules live:
#
#   - model aliases: ``random_seed -> seed``, count aliases,
#     ``rule_catalog_version -> rule_version``;
#   - grouped-issue / evaluation ``title`` reads the CURRENT
#     ``SITE_HEALTH_RULES_BY_ID[rule_id].display_label`` (unknown -> rule_id);
#   - the grouped-issue canonical id is the earliest immutable ``SiteIssue`` UUID
#     by ``(created_at, id)`` (never a synthetic id);
#   - ``blocked`` = the latest analyze task ended under a config-owned policy
#     denial code (robots/SSRF); any other terminal-unsuccessful analysis maps to
#     ``error``; ``failed`` is internal and never surfaced as page copy;
#   - a Free workspace (``count_disclosure`` False) never sees a discovered/total
#     count (redacted to ``None``).
#
# Every lookup is filtered by the resolved workspace, so a foreign / missing id
# is a 404 (never a cross-workspace leak). Reuses the ``planner`` /
# ``selection`` / ``entitlements`` / ``state_events`` domain helpers directly.
#
# This was one 2,055-line module at MI 0.0 (plan P3.2). It is now a package
# split by RESPONSIBILITY, and this file is only the façade — every existing
# ``from app.domain.site_health.service import x`` keeps working:
#
#   - ``presentation`` — pure ORM-row -> contract projections (no session);
#   - ``common``       — errors, the limit clamp, workspace-scoped loaders,
#                        typed keyset-cursor decoders;
#   - ``queries``      — entitlement / crawl / inventory / pages / page detail;
#   - ``issues``       — the grouped issue catalog, detail and history (the
#                        other half of the read surface: grouping is its own
#                        algorithm, not another row projection);
#   - ``lifecycle``    — ``cancel_crawl``, the dashboard, event replay.
from __future__ import annotations

from app.domain.site_health.service.aeo_readiness import get_aeo_readiness
from app.domain.site_health.service.changes import (
    InvalidChangeSelectionError,
    get_change,
    get_changes_summary,
    list_changes,
)
from app.domain.site_health.service.common import (
    InvalidCursorError,
    SiteHealthNotFoundError,
)
from app.domain.site_health.service.issues import (
    get_grouped_issue_history,
    get_issue_detail,
    get_issue_history,
    get_issues,
    issue_group_page_kinds,
)
from app.domain.site_health.service.lifecycle import (
    cancel_crawl,
    get_dashboard,
    load_crawl_for_stream,
    load_events,
)
from app.domain.site_health.service.presentation import (
    _score_summary,
    crawl_count_disclosure,
    display_label_for,
    presentation_status_for,
    project_crawl,
    project_phase_run,
)
from app.domain.site_health.service.queries import (
    get_crawl_summary,
    get_entitlement_view,
    get_inventory,
    get_monitored_set,
    get_page_detail,
    get_pages,
    list_crawls,
)

__all__ = [
    "SiteHealthNotFoundError",
    "InvalidCursorError",
    "InvalidChangeSelectionError",
    "get_entitlement_view",
    "get_crawl_summary",
    "list_crawls",
    "cancel_crawl",
    "get_inventory",
    "get_monitored_set",
    "get_pages",
    "get_page_detail",
    "get_issues",
    "issue_group_page_kinds",
    "get_issue_detail",
    "get_issue_history",
    "get_grouped_issue_history",
    "get_dashboard",
    "get_aeo_readiness",
    "get_change",
    "get_changes_summary",
    "list_changes",
    "load_events",
    "load_crawl_for_stream",
    "presentation_status_for",
    "project_crawl",
    "project_phase_run",
    "display_label_for",
    "crawl_count_disclosure",
    # Re-exported for the pure unit tests, which predate the split and should
    # not have to know which module it ended up in.
    "_score_summary",
]
