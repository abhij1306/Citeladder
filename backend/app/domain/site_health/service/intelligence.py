"""Read-side projections for the Site Intelligence workspace.

Every function here renders PERSISTED state. None of them resolves a pack,
fetches a URL, reclassifies a page, or recomputes a score — the projection was
built once at crawl finalization and frozen onto the snapshot, and a read that
recomputed it could disagree with the report a user already exported.

The frozen manifest on the row is also what a historical crawl is rendered
under, so a later catalog release cannot retroactively change what an old crawl
reported.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_intelligence import (
    COVERAGE_STATES,
    DIMENSION_IDS,
    REVIEW_STATE_OBSERVED,
)
from app.domain.site_health.service.common import SiteHealthNotFoundError
from app.models.knowledge import (
    KnowledgeAssertion,
    KnowledgeEntity,
    KnowledgeRelation,
)
from app.models.site_health import (
    SiteCrawl,
    SiteFetchArtifact,
    SiteHealthSnapshot,
    SitePageAnalysis,
    SiteUrl,
)

__all__ = [
    "get_intelligence_overview",
    "get_knowledge_assertions",
    "get_knowledge_contradictions",
    "get_knowledge_entities",
    "get_schema_graph",
]

_CRAWL_NOT_FOUND = "crawl not found"
_MAX_PAGE_SIZE = 200


async def _load_crawl(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    crawl_id: uuid.UUID | None,
) -> SiteCrawl:
    """The named crawl, or the project's most recent one. Workspace-authorized."""
    statement = select(SiteCrawl).where(SiteCrawl.workspace_id == workspace_id)
    if project_id is not None:
        statement = statement.where(SiteCrawl.project_id == project_id)
    if crawl_id is not None:
        statement = statement.where(SiteCrawl.id == crawl_id)
    else:
        statement = statement.order_by(
            SiteCrawl.created_at.desc(), SiteCrawl.id.desc()
        ).limit(1)
    crawl = await session.scalar(statement)
    if crawl is None:
        raise SiteHealthNotFoundError(_CRAWL_NOT_FOUND)
    return crawl


async def _snapshot(
    session: AsyncSession, *, crawl: SiteCrawl
) -> SiteHealthSnapshot | None:
    return await session.scalar(
        select(SiteHealthSnapshot).where(SiteHealthSnapshot.crawl_id == crawl.id)
    )


def _empty_projection(reason: str) -> dict:
    """The shape a workspace renders when a crawl has produced no projection.

    Deliberately NOT zeros. A crawl that has not finished has no scores; showing
    0.0 for every dimension would read as a failing site rather than an
    incomplete run, and that is the single most misleading thing this endpoint
    could do.
    """
    return {
        "available": False,
        "reason": reason,
        "packed": False,
        "manifest": None,
        "corpus": {},
        "knowledge": {},
        "coverage": {
            "answered_ratio": None,
            "denominator": 0,
            "counts": dict.fromkeys(COVERAGE_STATES, 0),
            "questions": [],
        },
        "journeys": [],
        "dimensions": {
            "composite_score": None,
            "composite_coverage": None,
            "dimensions": [],
        },
        "versions": {},
    }


async def get_intelligence_overview(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """The one Site Intelligence projection every workspace panel is driven by."""

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    snapshot = await _snapshot(session, crawl=crawl)
    if snapshot is None or not isinstance(snapshot.intelligence, Mapping):
        payload = _empty_projection(
            "this crawl has not produced an intelligence snapshot yet"
        )
    else:
        payload = {"available": True, **dict(snapshot.intelligence)}
    payload["crawl"] = {
        "id": str(crawl.id),
        "status": crawl.status,
        "root_url": crawl.root_url or "",
        "created_at": crawl.created_at.isoformat() if crawl.created_at else None,
    }
    payload["snapshot_id"] = str(snapshot.id) if snapshot is not None else None
    return payload


async def get_knowledge_entities(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    entity_type_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Entities this crawl established, most-evidenced first."""

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    where = [
        KnowledgeEntity.crawl_id == crawl.id,
        KnowledgeEntity.workspace_id == workspace_id,
    ]
    if entity_type_id:
        where.append(KnowledgeEntity.entity_type_id == entity_type_id)

    total = int(
        await session.scalar(
            select(func.count()).select_from(KnowledgeEntity).where(*where)
        )
        or 0
    )
    rows = (
        (
            await session.execute(
                select(KnowledgeEntity)
                .where(*where)
                .order_by(
                    KnowledgeEntity.evidence_page_count.desc(),
                    KnowledgeEntity.canonical_name,
                    KnowledgeEntity.id,
                )
                .offset(max(0, offset))
                .limit(min(max(1, limit), _MAX_PAGE_SIZE))
            )
        )
        .scalars()
        .all()
    )
    return {
        "crawl_id": str(crawl.id),
        "total": total,
        "items": [_entity_payload(row) for row in rows],
    }


def _entity_payload(entity: KnowledgeEntity) -> dict:
    return {
        "id": str(entity.id),
        "entity_type_id": entity.entity_type_id,
        "identity_key": entity.identity_key,
        "canonical_name": entity.canonical_name,
        "aliases": list(entity.aliases or []),
        "identifiers": dict(entity.identifiers or {}),
        "review_state": entity.review_state or REVIEW_STATE_OBSERVED,
        "evidence_page_count": int(entity.evidence_page_count or 0),
        "evidence_refs": list(entity.evidence_refs or []),
        "manifest": {
            "pack_id": entity.industry_pack_id or "",
            "pack_version": entity.industry_pack_version or "",
            "extractor_version": entity.extractor_version or "",
        },
    }


async def get_knowledge_assertions(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    predicate_id: str | None = None,
    subject_entity_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Claims this crawl derived, each with its subject and its evidence."""

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    where = [
        KnowledgeAssertion.crawl_id == crawl.id,
        KnowledgeAssertion.workspace_id == workspace_id,
    ]
    if predicate_id:
        where.append(KnowledgeAssertion.predicate_id == predicate_id)
    if subject_entity_id is not None:
        where.append(KnowledgeAssertion.subject_entity_id == subject_entity_id)

    total = int(
        await session.scalar(
            select(func.count()).select_from(KnowledgeAssertion).where(*where)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(KnowledgeAssertion, KnowledgeEntity)
            .join(
                KnowledgeEntity,
                KnowledgeEntity.id == KnowledgeAssertion.subject_entity_id,
            )
            .where(*where)
            .order_by(
                KnowledgeAssertion.predicate_id,
                KnowledgeAssertion.scope_key,
                KnowledgeAssertion.id,
            )
            .offset(max(0, offset))
            .limit(min(max(1, limit), _MAX_PAGE_SIZE))
        )
    ).all()
    return {
        "crawl_id": str(crawl.id),
        "total": total,
        "items": [_assertion_payload(row[0], row[1]) for row in rows],
    }


def _assertion_payload(
    assertion: KnowledgeAssertion, subject: KnowledgeEntity
) -> dict:
    return {
        "id": str(assertion.id),
        "predicate_id": assertion.predicate_id,
        "value_type": assertion.value_type,
        "raw_value": assertion.raw_value,
        "normalized_value": assertion.normalized_value,
        "numeric_value": assertion.numeric_value,
        "unit": assertion.unit or "",
        "currency": assertion.currency or "",
        "scope": dict(assertion.scope or {}),
        "temporal_state": assertion.temporal_state,
        "effective_from": (
            assertion.effective_from.isoformat() if assertion.effective_from else None
        ),
        "effective_to": (
            assertion.effective_to.isoformat() if assertion.effective_to else None
        ),
        "derivation_method": assertion.derivation_method or "",
        "confidence": assertion.confidence,
        "review_state": assertion.review_state or REVIEW_STATE_OBSERVED,
        # Null here means nothing disputes this claim. It is NOT "resolved".
        "contradiction_group_id": (
            str(assertion.contradiction_group_id)
            if assertion.contradiction_group_id
            else None
        ),
        "evidence_refs": list(assertion.evidence_refs or []),
        "subject": {
            "id": str(subject.id),
            "entity_type_id": subject.entity_type_id,
            "canonical_name": subject.canonical_name,
        },
    }


async def get_knowledge_contradictions(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Every disputed claim, with ALL of its sides.

    Contradictions are returned as GROUPS rather than as flagged rows: a reader
    who sees only one side cannot tell what the dispute is, and the whole point
    of preserving every side is that no side was silently chosen.
    """

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    rows = (
        await session.execute(
            select(KnowledgeAssertion, KnowledgeEntity)
            .join(
                KnowledgeEntity,
                KnowledgeEntity.id == KnowledgeAssertion.subject_entity_id,
            )
            .where(
                KnowledgeAssertion.crawl_id == crawl.id,
                KnowledgeAssertion.workspace_id == workspace_id,
                KnowledgeAssertion.contradiction_group_id.is_not(None),
            )
            .order_by(
                KnowledgeAssertion.contradiction_group_id,
                KnowledgeAssertion.normalized_value,
            )
        )
    ).all()

    groups: dict[str, dict] = {}
    for assertion, subject in rows:
        key = str(assertion.contradiction_group_id)
        group = groups.setdefault(
            key,
            {
                "contradiction_group_id": key,
                "predicate_id": assertion.predicate_id,
                "scope": dict(assertion.scope or {}),
                "subject": {
                    "id": str(subject.id),
                    "entity_type_id": subject.entity_type_id,
                    "canonical_name": subject.canonical_name,
                },
                # Nothing in the deterministic pipeline resolves a contradiction;
                # this stays open until a person acts on it.
                "resolution_state": "unresolved",
                "sides": [],
            },
        )
        group["sides"].append(_assertion_payload(assertion, subject))

    return {
        "crawl_id": str(crawl.id),
        "total": len(groups),
        "items": list(groups.values()),
    }


async def get_schema_graph(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Structured-data types observed across the crawl, and where they came from.

    Read from each artifact's persisted ``normalized_facts``: the parse already
    happened at analysis time and is immutable evidence. Re-parsing here would
    be a second, divergent implementation of the same extraction.
    """

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    rows = (
        await session.execute(
            select(
                SitePageAnalysis.site_url_id,
                SiteUrl.normalized_url,
                SiteFetchArtifact.normalized_facts,
            )
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .where(
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.is_current.is_(True),
            )
        )
    ).all()

    types: dict[str, dict] = {}
    pages_with_schema = 0
    invalid_pages: list[dict] = []
    for site_url_id, url, facts in rows:
        blocks = _blocks(facts)
        if not blocks:
            continue
        pages_with_schema += 1
        for block in blocks:
            schema_type = str(block.get("type") or "")
            if not schema_type:
                continue
            entry = types.setdefault(
                schema_type,
                {"type": schema_type, "pages": 0, "valid": 0, "invalid": 0},
            )
            entry["pages"] += 1
            entry["valid" if block.get("valid") else "invalid"] += 1
            if not block.get("valid") and len(invalid_pages) < _MAX_PAGE_SIZE:
                invalid_pages.append(
                    {
                        "site_url_id": str(site_url_id),
                        "url": str(url or ""),
                        "type": schema_type,
                        "missing": list(block.get("missing") or []),
                    }
                )

    return {
        "crawl_id": str(crawl.id),
        "analyzed_pages": len(rows),
        "pages_with_schema": pages_with_schema,
        "types": sorted(types.values(), key=lambda item: -item["pages"]),
        "invalid": invalid_pages,
    }


def _blocks(facts: object) -> Sequence[Mapping]:
    if not isinstance(facts, Mapping):
        return ()
    structured = facts.get("structured_data")
    if not isinstance(structured, Mapping):
        return ()
    return [
        block for block in structured.get("blocks") or () if isinstance(block, Mapping)
    ]


def dimension_order(dimension_id: str) -> int:
    """Stable report ordering for a dimension id."""
    try:
        return DIMENSION_IDS.index(dimension_id)
    except ValueError:
        return len(DIMENSION_IDS)


async def get_knowledge_relations(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    limit: int = 100,
) -> dict:
    """Edges between this crawl's entities, with both endpoints resolved."""

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    source = KnowledgeEntity.__table__.alias("source_entity")
    target = KnowledgeEntity.__table__.alias("target_entity")
    rows = (
        await session.execute(
            select(
                KnowledgeRelation.id,
                KnowledgeRelation.relation_type_id,
                KnowledgeRelation.temporal_state,
                KnowledgeRelation.evidence_refs,
                source.c.canonical_name.label("source_name"),
                source.c.entity_type_id.label("source_type"),
                target.c.canonical_name.label("target_name"),
                target.c.entity_type_id.label("target_type"),
            )
            .join(source, source.c.id == KnowledgeRelation.source_entity_id)
            .join(target, target.c.id == KnowledgeRelation.target_entity_id)
            .where(
                KnowledgeRelation.crawl_id == crawl.id,
                KnowledgeRelation.workspace_id == workspace_id,
            )
            .order_by(KnowledgeRelation.relation_type_id, KnowledgeRelation.id)
            .limit(min(max(1, limit), _MAX_PAGE_SIZE))
        )
    ).all()
    return {
        "crawl_id": str(crawl.id),
        "total": len(rows),
        "items": [
            {
                "id": str(row.id),
                "relation_type_id": row.relation_type_id,
                "temporal_state": row.temporal_state,
                "source": {
                    "name": row.source_name,
                    "entity_type_id": row.source_type,
                },
                "target": {
                    "name": row.target_name,
                    "entity_type_id": row.target_type,
                },
                "evidence_refs": list(row.evidence_refs or []),
            }
            for row in rows
        ],
    }
