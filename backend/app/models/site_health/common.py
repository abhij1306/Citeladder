# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

from datetime import UTC, datetime

# FK target references + ondelete actions as named constants. A typo in a
# ``table.column`` reference would otherwise silently bind the wrong parent;
# naming them once also makes a future table rename a single-line change.
_FK_WORKSPACE = "workspaces.id"
_FK_PROJECT = "projects.id"
_FK_SITE_HEALTH_PROFILE = "site_health_profiles.id"
_FK_SITE_CRAWL = "site_crawls.id"
_FK_SITE_CRAWL_PHASE_RUN = "site_crawl_phase_runs.id"
_FK_SITE_CRAWL_TASK = "site_crawl_tasks.id"
_FK_SITE_URL = "site_urls.id"
_FK_SITE_FETCH_ARTIFACT = "site_fetch_artifacts.id"
_FK_SITE_PAGE_ANALYSIS = "site_page_analyses.id"
_FK_SITE_RULE_EVALUATION = "site_rule_evaluations.id"
_ON_DELETE_CASCADE = "CASCADE"
_ON_DELETE_SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)
