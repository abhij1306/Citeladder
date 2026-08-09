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

from app.core.config.site_health import PAGE_ANALYSIS_STATUS_COMPLETED
from app.core.config.site_intelligence import (
    CONTRADICTION_RESOLUTION_CORRECTED,
    CONTRADICTION_RESOLUTION_UNRESOLVED,
    CORRECTION_TARGET_ASSERTION,
    CORRECTION_TARGET_ENTITY,
    CORRECTION_TARGET_RELATION,
    COVERAGE_STATES,
    DIMENSION_IDS,
    REVIEW_STATE_OBSERVED,
)
from app.domain.site_health.corrections import (
    active_corrections_by_target,
    assertion_target_ref,
    correction_payload,
    entity_target_ref,
    relation_target_ref,
    stable_target_key,
)
from app.domain.site_health.service.common import SiteHealthNotFoundError
from app.models.knowledge import (
    Correction,
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
    "dimension_order",
    "get_intelligence_overview",
    "get_knowledge_assertions",
    "get_knowledge_contradictions",
    "get_knowledge_entities",
    "get_knowledge_relations",
    "get_schema_graph",
]

_CRAWL_NOT_FOUND = "crawl not found"
_MAX_PAGE_SIZE = 200
# Rows fetched per round trip while streaming the whole-crawl schema histogram.
# Bounds how many full ``normalized_facts`` blobs are resident at once.
_SCHEMA_GRAPH_CHUNK = 200


def _bounded(limit: int) -> int:
    """Clamp a caller-supplied page size into the server's own range."""
    return min(max(1, limit), _MAX_PAGE_SIZE)


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
        # ``available`` is computed HERE and placed last: a stored payload that
        # happened to carry the key must not be able to declare itself
        # available (or not) on the reader's behalf.
        payload = {**dict(snapshot.intelligence), "available": True}
    payload["crawl"] = {
        "id": str(crawl.id),
        "status": crawl.status,
        "root_url": crawl.root_url or "",
        "created_at": crawl.created_at.isoformat() if crawl.created_at else None,
    }
    payload.update(_snapshot_context(snapshot))
    return payload


def _snapshot_context(snapshot: SiteHealthSnapshot | None) -> dict:
    if snapshot is None:
        return {"snapshot_id": None, "prior_snapshot_id": None, "comparison": None}
    prior_id = str(snapshot.prior_snapshot_id) if snapshot.prior_snapshot_id else None
    return {
        "snapshot_id": str(snapshot.id),
        "prior_snapshot_id": prior_id,
        "comparison": (
            dict(snapshot.comparison) if snapshot.comparison is not None else None
        ),
    }


def _correction_projection(derived_value: dict, correction: Correction | None) -> dict:
    if correction is None:
        return {"effective_value": derived_value, "correction": None}
    return {
        "effective_value": dict(correction.corrected_value),
        "correction": correction_payload(correction),
    }


def _entity_context_ref(entity: KnowledgeEntity) -> dict:
    return entity_target_ref(entity.entity_type_id, entity.identity_key)


def _entity_correction_contexts(
    rows: Sequence[KnowledgeEntity],
) -> dict[str, dict]:
    return {
        stable_target_key(_entity_context_ref(entity)): _entity_context_ref(entity)
        for entity in rows
    }


def _assertion_correction_contexts(
    rows: Sequence[tuple[KnowledgeAssertion, KnowledgeEntity]],
) -> dict[str, dict]:
    return {
        _assertion_target_key(assertion, subject): _entity_context_ref(subject)
        for assertion, subject in rows
    }


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
                .limit(_bounded(limit))
            )
        )
        .scalars()
        .all()
    )
    corrections = await active_corrections_by_target(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=CORRECTION_TARGET_ENTITY,
        context_entity_refs=_entity_correction_contexts(rows),
    )
    return {
        "crawl_id": str(crawl.id),
        "total": total,
        "items": [
            _entity_payload(
                row,
                corrections.get(
                    stable_target_key(
                        entity_target_ref(row.entity_type_id, row.identity_key)
                    )
                ),
            )
            for row in rows
        ],
    }


def _entity_payload(entity: KnowledgeEntity, correction=None) -> dict:
    derived_value = {"canonical_name": entity.canonical_name}
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
        **_correction_projection(derived_value, correction),
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
        (
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
                .limit(_bounded(limit))
            )
        )
        .tuples()
        .all()
    )
    corrections = await active_corrections_by_target(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=CORRECTION_TARGET_ASSERTION,
        context_entity_refs=_assertion_correction_contexts(rows),
    )
    return {
        "crawl_id": str(crawl.id),
        "total": total,
        "items": [
            _assertion_payload(
                row[0],
                row[1],
                corrections.get(_assertion_target_key(row[0], row[1])),
            )
            for row in rows
        ],
    }


def _assertion_target_key(
    assertion: KnowledgeAssertion, subject: KnowledgeEntity
) -> str:
    return stable_target_key(
        assertion_target_ref(
            subject_entity_type_id=subject.entity_type_id,
            subject_identity_key=subject.identity_key,
            predicate_id=assertion.predicate_id,
            scope_key=assertion.scope_key,
        )
    )


def _assertion_payload(
    assertion: KnowledgeAssertion, subject: KnowledgeEntity, correction=None
) -> dict:
    derived_value = {
        "raw_value": assertion.raw_value,
        "normalized_value": assertion.normalized_value,
        "numeric_value": assertion.numeric_value,
        "unit": assertion.unit or "",
        "currency": assertion.currency or "",
        "value_type": assertion.value_type,
    }
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
        # False means a pack-REQUIRED qualifier was never evidenced — a fee with
        # no stated year or grade. Omitting it rendered such a claim exactly
        # like a fully qualified one, which is the one thing the model forbids.
        "scope_complete": bool(assertion.scope_complete),
        "temporal_state": assertion.temporal_state,
        **_assertion_temporal_payload(assertion),
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
        **_correction_projection(derived_value, correction),
    }


def _assertion_temporal_payload(assertion: KnowledgeAssertion) -> dict:
    effective_from = (
        assertion.effective_from.isoformat() if assertion.effective_from else None
    )
    effective_to = (
        assertion.effective_to.isoformat() if assertion.effective_to else None
    )
    return {"effective_from": effective_from, "effective_to": effective_to}


def _contradiction_group(
    key: str,
    assertion: KnowledgeAssertion,
    subject: KnowledgeEntity,
    correction: Correction | None,
) -> dict:
    resolution_state = (
        CONTRADICTION_RESOLUTION_CORRECTED
        if correction is not None
        else CONTRADICTION_RESOLUTION_UNRESOLVED
    )
    correction_item = correction_payload(correction) if correction is not None else None
    return {
        "contradiction_group_id": key,
        "predicate_id": assertion.predicate_id,
        "scope": dict(assertion.scope or {}),
        "subject": {
            "id": str(subject.id),
            "entity_type_id": subject.entity_type_id,
            "canonical_name": subject.canonical_name,
        },
        "resolution_state": resolution_state,
        "correction": correction_item,
        "sides": [],
    }


async def get_knowledge_contradictions(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    limit: int = _MAX_PAGE_SIZE,
) -> dict:
    """Every disputed claim, with ALL of its sides.

    Contradictions are returned as GROUPS rather than as flagged rows: a reader
    who sees only one side cannot tell what the dispute is, and the whole point
    of preserving every side is that no side was silently chosen.

    Bounded like every other list here. A crawl with pathological conflict is
    precisely the one whose response would be largest, so the endpoint that
    reports it must not be the one that can be made unbounded.
    """

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    where = (
        KnowledgeAssertion.crawl_id == crawl.id,
        KnowledgeAssertion.workspace_id == workspace_id,
        KnowledgeAssertion.contradiction_group_id.is_not(None),
    )
    total = int(
        await session.scalar(
            select(func.count(func.distinct(KnowledgeAssertion.contradiction_group_id)))
            .select_from(KnowledgeAssertion)
            .where(*where)
        )
        or 0
    )
    # Bounded by GROUP, then every side of the kept groups is fetched.
    # Truncating rows instead would show a dispute with one of its sides
    # missing, which reads as an uncontested fact.
    kept = (
        (
            await session.execute(
                select(KnowledgeAssertion.contradiction_group_id)
                .where(*where)
                .distinct()
                .order_by(KnowledgeAssertion.contradiction_group_id)
                .limit(_bounded(limit))
            )
        )
        .scalars()
        .all()
    )
    rows = (
        (
            (
                await session.execute(
                    select(KnowledgeAssertion, KnowledgeEntity)
                    .join(
                        KnowledgeEntity,
                        KnowledgeEntity.id == KnowledgeAssertion.subject_entity_id,
                    )
                    .where(*where, KnowledgeAssertion.contradiction_group_id.in_(kept))
                    .order_by(
                        KnowledgeAssertion.contradiction_group_id,
                        KnowledgeAssertion.normalized_value,
                    )
                )
            )
            .tuples()
            .all()
        )
        if kept
        else []
    )

    corrections = await active_corrections_by_target(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=CORRECTION_TARGET_ASSERTION,
        context_entity_refs=_assertion_correction_contexts(rows),
    )
    groups: dict[str, dict] = {}
    for assertion, subject in rows:
        key = str(assertion.contradiction_group_id)
        correction = corrections.get(_assertion_target_key(assertion, subject))
        group = groups.setdefault(
            key,
            _contradiction_group(key, assertion, subject, correction),
        )
        group["sides"].append(_assertion_payload(assertion, subject, correction))

    return {
        # Every disputed claim in the crawl, not the size of this page of them.
        "crawl_id": str(crawl.id),
        "total": total,
        "items": list(groups.values()),
    }


async def get_schema_graph(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    limit: int = _MAX_PAGE_SIZE,
) -> dict:
    """Structured-data types observed across the crawl, and where they came from.

    Read from each artifact's persisted ``normalized_facts``: the parse already
    happened at analysis time and is immutable evidence. Re-parsing here would
    be a second, divergent implementation of the same extraction.

    This is a whole-crawl histogram, so unlike every paged reader here it cannot
    take a row LIMIT without reporting a partial site as the whole one. It is
    STREAMED instead: each row carries a complete ``normalized_facts`` blob —
    headings, anchors, structured data — and a crawl with thousands of analyzed
    pages would otherwise materialize all of it in the API process at once.
    """

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    statement = (
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
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            SitePageAnalysis.is_current.is_(True),
        )
        .execution_options(yield_per=_SCHEMA_GRAPH_CHUNK)
    )

    types: dict[str, dict] = {}
    analyzed_pages = 0
    pages_with_schema = 0
    invalid_pages: list[dict] = []
    bound = _bounded(limit)
    async for site_url_id, url, facts in await session.stream(statement):
        analyzed_pages += 1
        blocks = _blocks(facts)
        if not blocks:
            continue
        pages_with_schema += 1
        # A page publishing three Product blocks is ONE page with Product
        # markup. Counting blocks in the ``pages`` column made one page look
        # like a whole section of the site.
        counted: set[str] = set()
        for block in blocks:
            schema_type = str(block.get("type") or "")
            if not schema_type:
                continue
            entry = types.setdefault(
                schema_type,
                {"type": schema_type, "pages": 0, "valid": 0, "invalid": 0},
            )
            if schema_type not in counted:
                entry["pages"] += 1
                counted.add(schema_type)
            entry["valid" if block.get("valid") else "invalid"] += 1
            if not block.get("valid") and len(invalid_pages) < bound:
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
        "analyzed_pages": analyzed_pages,
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
    offset: int = 0,
) -> dict:
    """Edges between this crawl's entities, with both endpoints resolved.

    Paged like the entity and assertion readers: ``total`` is the full count, so
    a caller shown "120 relations" over a 100-row page needs an offset to reach
    the rest. The ordering is deterministic, which is what makes paging stable.
    """

    crawl = await _load_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    total = int(
        await session.scalar(
            select(func.count())
            .select_from(KnowledgeRelation)
            .where(
                KnowledgeRelation.crawl_id == crawl.id,
                KnowledgeRelation.workspace_id == workspace_id,
            )
        )
        or 0
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
                KnowledgeRelation.is_current,
                source.c.canonical_name.label("source_name"),
                source.c.entity_type_id.label("source_type"),
                source.c.identity_key.label("source_identity_key"),
                target.c.canonical_name.label("target_name"),
                target.c.entity_type_id.label("target_type"),
                target.c.identity_key.label("target_identity_key"),
            )
            .join(source, source.c.id == KnowledgeRelation.source_entity_id)
            .join(target, target.c.id == KnowledgeRelation.target_entity_id)
            .where(
                KnowledgeRelation.crawl_id == crawl.id,
                KnowledgeRelation.workspace_id == workspace_id,
            )
            .order_by(KnowledgeRelation.relation_type_id, KnowledgeRelation.id)
            .offset(max(0, offset))
            .limit(_bounded(limit))
        )
    ).all()
    corrections = await active_corrections_by_target(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=CORRECTION_TARGET_RELATION,
        context_entity_refs={
            stable_target_key(
                relation_target_ref(
                    relation_type_id=row.relation_type_id,
                    source_entity_type_id=row.source_type,
                    source_identity_key=row.source_identity_key,
                    target_entity_type_id=row.target_type,
                    target_identity_key=row.target_identity_key,
                )
            ): entity_target_ref(row.source_type, row.source_identity_key)
            for row in rows
        },
    )
    items = []
    for row in rows:
        correction = corrections.get(
            stable_target_key(
                relation_target_ref(
                    relation_type_id=row.relation_type_id,
                    source_entity_type_id=row.source_type,
                    source_identity_key=row.source_identity_key,
                    target_entity_type_id=row.target_type,
                    target_identity_key=row.target_identity_key,
                )
            )
        )
        items.append(_relation_payload(row, correction))
    return {
        # The crawl's real edge count, not the size of this page of it.
        "crawl_id": str(crawl.id),
        "total": total,
        "items": items,
    }


def _relation_payload(row, correction: Correction | None) -> dict:
    return {
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
        **_correction_projection({"is_current": bool(row.is_current)}, correction),
    }
