"""Read-only observed-architecture projection over the persisted model.

Projects the immutable ``SiteObservedArchitecture`` row a crawl's post-terminal
architecture task wrote. It never re-derives the model, never crawls, and never
scores. The one mutable input is the project's ``archetype_override`` — the
single correction surface — which is applied HERE, at read time: it re-runs the
same versioned common-structure policy over the same persisted hierarchy and
leaves the evidence row untouched.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.architecture import common_structure_observations
from app.core.config.site_health_archetypes import (
    ARCHETYPE_OTHER,
    ARCHETYPE_POLICY_VERSION,
    ARCHETYPE_SOURCE_USER,
    ARCHETYPES,
    ARCHITECTURE_FORMULA_VERSION,
)
from app.core.config.site_health_link_metrics import COVERAGE_STATE_COMPLETE
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    _load_project,
    resolve_usable_crawl,
)
from app.models.site_health.architecture import SiteObservedArchitecture
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.runtime import SiteHealthProfile


class InvalidArchetypeError(Exception):
    """A correction named an archetype outside the frozen vocabulary (422)."""


def _unavailable(reason: str, *, crawl_id: uuid.UUID | None = None) -> dict:
    return {
        "state": "unavailable",
        "crawl_id": crawl_id,
        "coverage_state": "unknown",
        "page_count": 0,
        "page_kind_counts": {},
        "archetype": {
            "archetype": ARCHETYPE_OTHER,
            "source": "abstained",
            "reason": "model_unavailable",
            "business_model": "",
            "observed": [],
            "not_observed": [],
            "market_scope": "",
        },
        "families": [],
        "nodes": [],
        "architecture_formula_version": ARCHITECTURE_FORMULA_VERSION,
        "archetype_policy_version": ARCHETYPE_POLICY_VERSION,
        "limitations": [reason],
    }


async def _latest_model(
    session: AsyncSession, *, crawl: SiteCrawl
) -> SiteObservedArchitecture | None:
    """The newest persisted model for this crawl, whatever version wrote it.

    Selecting by version would blank the tab the moment a formula token moves;
    the response reports the versions the row it actually read carries.
    """
    return await session.scalar(
        select(SiteObservedArchitecture)
        .where(
            SiteObservedArchitecture.workspace_id == crawl.workspace_id,
            SiteObservedArchitecture.project_id == crawl.project_id,
            SiteObservedArchitecture.crawl_id == crawl.id,
        )
        .order_by(
            SiteObservedArchitecture.created_at.desc(),
            SiteObservedArchitecture.id.desc(),
        )
        .limit(1)
    )


async def _archetype_override(
    session: AsyncSession, *, project_id: uuid.UUID
) -> str | None:
    override = await session.scalar(
        select(SiteHealthProfile.archetype_override).where(
            SiteHealthProfile.project_id == project_id
        )
    )
    return override if override in ARCHETYPES else None


def _node(row: dict) -> dict:
    return {
        "site_url_id": str(row.get("site_url_id") or ""),
        "url": str(row.get("url") or ""),
        "title": str(row.get("title") or ""),
        "page_kind": str(row.get("page_kind") or ""),
        "family": str(row.get("family") or ""),
        "parent_site_url_id": (
            str(row["parent_site_url_id"]) if row.get("parent_site_url_id") else None
        ),
        "parent_source": str(row.get("parent_source") or "unknown"),
        "depth_from_home": row.get("depth_from_home"),
    }


def _family(row: dict) -> dict:
    return {
        "family": str(row.get("family") or ""),
        "url_count": int(row.get("url_count") or 0),
        "page_kind_distribution": dict(row.get("page_kind_distribution") or {}),
        "median_depth": row.get("median_depth"),
        "indexable_count": int(row.get("indexable_count") or 0),
        "metadata_duplication_rate": float(row.get("metadata_duplication_rate") or 0.0),
        "orphan_count": row.get("orphan_count"),
    }


def _persisted_archetype(persisted: dict) -> dict:
    evidence = persisted.get("profile_evidence") or {}
    return {
        "archetype": str(persisted.get("archetype") or ARCHETYPE_OTHER),
        "source": str(persisted.get("source") or "abstained"),
        "reason": str(persisted.get("reason") or ""),
        "business_model": str(persisted.get("business_model") or ""),
        "observed": list(persisted.get("observed") or []),
        "not_observed": list(persisted.get("not_observed") or []),
        "market_scope": str(evidence.get("market_scope") or ""),
    }


def _archetype_block(
    persisted: dict, *, override: str | None, nodes: list[dict], coverage_state: str
) -> dict:
    """Project the persisted assessment, re-running the policy on a correction.

    The override changes WHICH archetype's common structures are compared; it
    never changes the observed evidence, and it cannot resurrect absence
    advisories on a crawl that did not prove completeness.
    """
    block = _persisted_archetype(persisted)
    if override is None or override == block["archetype"]:
        return block
    observed, not_observed = common_structure_observations(
        archetype=override,
        pages=[(node["page_kind"], node["url"]) for node in nodes],
        market_scope=block["market_scope"],
    )
    return {
        **block,
        "archetype": override,
        "source": ARCHETYPE_SOURCE_USER,
        "reason": "user_corrected",
        "observed": observed,
        "not_observed": (
            not_observed if coverage_state == COVERAGE_STATE_COMPLETE else []
        ),
    }


def _limitations(coverage_state: str) -> list[str]:
    if coverage_state == COVERAGE_STATE_COMPLETE:
        return []
    prefix = (
        "This crawl hit its page budget"
        if coverage_state == "partial"
        else "This crawl could not prove it saw the whole site"
    )
    return [
        f"{prefix}, so these are the pages CiteLadder observed — not the whole "
        "site. Structures reported as missing are withheld, because a partial "
        "crawl cannot prove absence."
    ]


async def get_architecture(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Project the crawl's persisted observed-architecture model."""
    crawl = await resolve_usable_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if crawl is None:
        return _unavailable("No usable persisted crawl has an observed architecture.")
    model = await _latest_model(session, crawl=crawl)
    if model is None:
        return _unavailable(
            "This crawl has no observed architecture yet — it is derived after "
            "the crawl finishes.",
            crawl_id=crawl.id,
        )
    override = await _archetype_override(session, project_id=project_id)
    return _projection(model, crawl_id=crawl.id, override=override)


def _projection(
    model: SiteObservedArchitecture, *, crawl_id: uuid.UUID, override: str | None
) -> dict:
    nodes = [_node(row) for row in model.hierarchy or [] if isinstance(row, dict)]
    coverage_state = model.coverage_state or "unknown"
    return {
        "state": "available",
        "crawl_id": crawl_id,
        "coverage_state": coverage_state,
        "page_count": int(model.page_count or 0),
        "page_kind_counts": dict(model.page_kind_counts or {}),
        "archetype": _archetype_block(
            dict(model.archetype or {}),
            override=override,
            nodes=nodes,
            coverage_state=coverage_state,
        ),
        "families": [
            _family(row) for row in model.families or [] if isinstance(row, dict)
        ],
        "nodes": nodes,
        "architecture_formula_version": model.architecture_formula_version,
        "archetype_policy_version": model.archetype_policy_version,
        "limitations": _limitations(coverage_state),
    }


async def set_archetype_override(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    archetype: str | None,
) -> dict:
    """Persist (or clear) the project's archetype correction.

    Writes only to the project's mutable Site Health profile — no evidence row
    is rewritten, no rule re-evaluated, and no score touched.
    """
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    if archetype is not None and archetype not in ARCHETYPES:
        raise InvalidArchetypeError(f"unknown archetype: {archetype!r}")
    profile = await session.scalar(
        select(SiteHealthProfile).where(SiteHealthProfile.project_id == project_id)
    )
    if profile is None:
        raise SiteHealthNotFoundError("Site Health profile not found")
    profile.archetype_override = archetype
    await session.flush()
    return {"project_id": project_id, "archetype_override": archetype}


__all__ = [
    "InvalidArchetypeError",
    "get_architecture",
    "set_archetype_override",
]
