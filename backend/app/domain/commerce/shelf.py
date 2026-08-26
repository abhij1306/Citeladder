"""Deterministic recommendation observations and AI Shelf formulas."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import (
    COMMERCE_RECOMMENDATION_MATCHER_VERSION,
    COMMERCE_RECOMMENDATION_PARSER_VERSION,
    COMMERCE_SHELF_FORMULA_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.commerce.schemas import (
    RecommendationObservationResponse,
    ShelfMetricResponse,
    ShelfResponse,
)
from app.domain.commerce.service import require_project
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.commerce import (
    CommerceCompetitorCandidate,
    CommerceObservationCitation,
    CommerceProduct,
    CommerceProductCategory,
    CommercePromptTarget,
    CommerceRecommendationObservation,
    CommerceShelfSnapshot,
)

_ORDERED = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.+)$")
_URL = re.compile(r"https?://[^\s)\]}>,]+", re.IGNORECASE)
_PRICE = re.compile(
    r"(?P<currency>[$£€₹]|AUD|USD|CAD|NZD|GBP|EUR|INR)\s*(?P<value>\d[\d,.]*(?:\.\d{1,2})?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Span:
    text: str
    rank: int | None
    order_observable: bool


def _spans(answer: str) -> list[_Span]:
    spans: list[_Span] = []
    for line in answer.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        ordered = _ORDERED.match(cleaned)
        if ordered:
            spans.append(
                _Span(
                    text=ordered.group(2).strip(),
                    rank=int(ordered.group(1)),
                    order_observable=True,
                )
            )
            continue
        bullet = _BULLET.match(cleaned)
        if bullet:
            spans.append(
                _Span(text=bullet.group(1).strip(), rank=None, order_observable=False)
            )
    return spans or [_Span(text=answer.strip(), rank=None, order_observable=False)]


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _price(span: str) -> tuple[float | None, str]:
    match = _PRICE.search(span)
    if not match:
        return None, ""
    token = match.group("currency").upper()
    currency = {
        "$": "USD",
        "£": "GBP",
        "€": "EUR",
        "₹": "INR",
    }.get(token, token)
    try:
        return float(match.group("value").replace(",", "")), currency
    except ValueError:
        return None, currency


def _merchant(span: str) -> tuple[str, str]:
    match = _URL.search(span)
    if not match:
        return "", ""
    url = match.group(0)
    return url, (urlsplit(url).hostname or "").casefold()


async def _task_target(
    session: AsyncSession, *, task: AuditTask
) -> CommercePromptTarget | None:
    audit = await session.get(Audit, task.audit_id)
    if audit is None or audit.audit_scope != "commerce":
        return None
    frozen = dict((audit.configuration or {}).get("commerce_measurement") or {})
    target_ids = _frozen_target_ids(frozen)
    if not target_ids:
        return None
    return await session.scalar(
        select(CommercePromptTarget)
        .join(
            AuditPromptSnapshot,
            AuditPromptSnapshot.prompt_id == CommercePromptTarget.prompt_id,
        )
        .where(
            AuditPromptSnapshot.id == task.prompt_snapshot_id,
            AuditPromptSnapshot.audit_id == audit.id,
            CommercePromptTarget.workspace_id == task.workspace_id,
            CommercePromptTarget.project_id == audit.project_id,
            CommercePromptTarget.id.in_(target_ids),
        )
    )


def _frozen_target_ids(frozen: dict) -> list[uuid.UUID]:
    values: list[uuid.UUID] = []
    for raw in frozen.get("prompt_target_ids") or []:
        try:
            values.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError, AttributeError):
            continue
    return values


async def _catalog(
    session: AsyncSession, *, target: CommercePromptTarget
) -> tuple[list[CommerceProduct], list[CommerceCompetitorCandidate]]:
    products_stmt = select(CommerceProduct).where(
        CommerceProduct.project_id == target.project_id,
        CommerceProduct.lifecycle_state == "active",
    )
    if target.target_kind == "product":
        products_stmt = products_stmt.where(CommerceProduct.id == target.target_id)
    else:
        products_stmt = products_stmt.join(
            CommerceProductCategory,
            CommerceProductCategory.product_id == CommerceProduct.id,
        ).where(CommerceProductCategory.category_id == target.target_id)
    products = list((await session.scalars(products_stmt)).all())
    candidates = list(
        (
            await session.scalars(
                select(CommerceCompetitorCandidate).where(
                    CommerceCompetitorCandidate.project_id == target.project_id,
                    CommerceCompetitorCandidate.target_kind == target.target_kind,
                    CommerceCompetitorCandidate.target_id == target.target_id,
                    CommerceCompetitorCandidate.state == "approved",
                )
            )
        ).all()
    )
    return products, candidates


def _match_product(
    text: str, products: list[CommerceProduct]
) -> tuple[CommerceProduct | None, float]:
    normalized = _normalize(text)
    for product in products:
        if _product_identity_matches(product, normalized):
            return product, 1.0
        if _product_attributes_match(product, normalized):
            return product, 0.9
    return None, 0.0


def _product_identity_matches(product: CommerceProduct, normalized: str) -> bool:
    identities = (
        product.canonical_url,
        product.gtin,
        product.sku,
        product.mpn,
        product.name,
    )
    tokens = (_normalize(identity) for identity in identities)
    return any(token and token in normalized for token in tokens)


def _product_attributes_match(product: CommerceProduct, normalized: str) -> bool:
    if not product.brand or _normalize(product.brand) not in normalized:
        return False
    values = (
        _normalize(str(value))
        for value in (product.attributes or {}).values()
        if isinstance(value, (str, int, float))
    )
    return any(value and value in normalized for value in values)


def _match_candidate(
    text: str, candidates: list[CommerceCompetitorCandidate]
) -> tuple[CommerceCompetitorCandidate | None, float]:
    normalized = _normalize(text)
    for candidate in candidates:
        for identity in (
            candidate.canonical_url,
            candidate.product_name,
            candidate.brand_name,
        ):
            token = _normalize(identity)
            if token and token in normalized:
                return candidate, 1.0
    return None, 0.0


async def analyze_commerce_task(session: AsyncSession, *, task: AuditTask) -> None:
    """Append deterministic observations for one successful target execution."""
    if task.result_artifact_id is None:
        return
    target = await _task_target(session, task=task)
    if target is None:
        return
    existing = await session.scalar(
        select(CommerceRecommendationObservation.id).where(
            CommerceRecommendationObservation.task_id == task.id,
            CommerceRecommendationObservation.parser_version
            == COMMERCE_RECOMMENDATION_PARSER_VERSION,
            CommerceRecommendationObservation.matcher_version
            == COMMERCE_RECOMMENDATION_MATCHER_VERSION,
        )
    )
    if existing is not None:
        return
    products, candidates = await _catalog(session, target=target)
    citations = list(
        (
            await session.scalars(
                select(Citation)
                .join(ResponseAnalysis, ResponseAnalysis.id == Citation.analysis_id)
                .where(ResponseAnalysis.task_id == task.id)
            )
        ).all()
    )
    for span in _spans(task.answer_text):
        observed_candidate = await _ai_observed_candidate(
            session,
            target=target,
            span=span,
            approved_candidates=candidates,
        )
        span_candidates = candidates + (
            [observed_candidate] if observed_candidate is not None else []
        )
        observation = _observation_for_span(
            task=task,
            target=target,
            span=span,
            products=products,
            candidates=span_candidates,
        )
        session.add(observation)
        await session.flush()
        _link_observation_citations(
            session, observation=observation, citations=citations, text=span.text
        )


async def _ai_observed_candidate(
    session: AsyncSession,
    *,
    target: CommercePromptTarget,
    span: _Span,
    approved_candidates: list[CommerceCompetitorCandidate],
) -> CommerceCompetitorCandidate | None:
    url, domain = _merchant(span.text)
    if not url or _match_candidate(span.text, approved_candidates)[0] is not None:
        return None
    existing = await session.scalar(
        select(CommerceCompetitorCandidate).where(
            CommerceCompetitorCandidate.project_id == target.project_id,
            CommerceCompetitorCandidate.target_kind == target.target_kind,
            CommerceCompetitorCandidate.target_id == target.target_id,
            CommerceCompetitorCandidate.canonical_url == url,
        )
    )
    if existing is not None:
        return existing
    candidate = CommerceCompetitorCandidate(
        workspace_id=target.workspace_id,
        project_id=target.project_id,
        target_kind=target.target_kind,
        target_id=target.target_id,
        canonical_url=url,
        product_name=span.text[:512],
        brand_name=domain,
        evidence={"observation_text": span.text[:2000]},
        source_kind="ai_observed",
        state="pending",
    )
    session.add(candidate)
    await session.flush()
    return candidate


def _observation_for_span(
    *,
    task: AuditTask,
    target: CommercePromptTarget,
    span: _Span,
    products: list[CommerceProduct],
    candidates: list[CommerceCompetitorCandidate],
) -> CommerceRecommendationObservation:
    product, confidence = _match_product(span.text, products)
    candidate, competitor_confidence = _match_candidate(span.text, candidates)
    price, currency = _price(span.text)
    merchant_url, merchant_domain = _merchant(span.text)
    classification = "unresolved"
    if product is not None:
        classification = "owned"
    elif candidate is not None:
        classification = (
            "approved_competitor"
            if candidate.state == "approved"
            else "observed_competitor"
        )
    return CommerceRecommendationObservation(
        workspace_id=task.workspace_id,
        project_id=target.project_id,
        audit_id=task.audit_id,
        task_id=task.id,
        artifact_id=task.result_artifact_id,
        target_kind=target.target_kind,
        target_id=target.target_id,
        product_id=product.id if product else None,
        competitor_candidate_id=candidate.id if candidate else None,
        observed_product=(
            product.name
            if product
            else candidate.product_name
            if candidate
            else span.text[:512]
        ),
        observed_brand=(
            product.brand if product else candidate.brand_name if candidate else ""
        ),
        classification=classification,
        observed_title=span.text[:512],
        observed_price=price,
        observed_currency=currency,
        merchant_url=merchant_url,
        merchant_domain=merchant_domain,
        surface_kind="recommendation",
        rank=span.rank,
        order_observable=span.order_observable,
        match_confidence=max(confidence, competitor_confidence),
    )


def _link_observation_citations(
    session: AsyncSession,
    *,
    observation: CommerceRecommendationObservation,
    citations: list[Citation],
    text: str,
) -> None:
    for citation in citations:
        if citation.url and citation.url in text:
            session.add(
                CommerceObservationCitation(
                    observation_id=observation.id, citation_id=citation.id
                )
            )


async def finalize_commerce_shelf(session: AsyncSession, *, audit: Audit) -> None:
    if audit.audit_scope != "commerce":
        return
    frozen = dict((audit.configuration or {}).get("commerce_measurement") or {})
    target_ids = _frozen_target_ids(frozen)
    if not target_ids:
        return
    targets = list(
        (
            await session.scalars(
                select(CommercePromptTarget).where(
                    CommercePromptTarget.workspace_id == audit.workspace_id,
                    CommercePromptTarget.project_id == audit.project_id,
                    CommercePromptTarget.id.in_(target_ids),
                )
            )
        ).all()
    )
    for target in targets:
        if await _snapshot_exists(session, audit=audit, target=target):
            continue
        tasks = await _target_tasks(session, audit=audit, target=target)
        observations = await _target_observations(session, audit=audit, target=target)
        session.add(
            _build_shelf_snapshot(
                audit=audit,
                target=target,
                tasks=tasks,
                observations=observations,
            )
        )


async def _snapshot_exists(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> bool:
    return (
        await session.scalar(
            select(CommerceShelfSnapshot.id).where(
                CommerceShelfSnapshot.audit_id == audit.id,
                CommerceShelfSnapshot.target_kind == target.target_kind,
                CommerceShelfSnapshot.target_id == target.target_id,
                CommerceShelfSnapshot.formula_version == COMMERCE_SHELF_FORMULA_VERSION,
            )
        )
        is not None
    )


async def _target_tasks(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> list[AuditTask]:
    return list(
        (
            await session.scalars(
                select(AuditTask)
                .join(
                    AuditPromptSnapshot,
                    AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
                )
                .join(
                    CommercePromptTarget,
                    CommercePromptTarget.prompt_id == AuditPromptSnapshot.prompt_id,
                )
                .where(
                    AuditTask.audit_id == audit.id,
                    AuditTask.status == TASK_STATUS_SUCCEEDED,
                    CommercePromptTarget.target_kind == target.target_kind,
                    CommercePromptTarget.target_id == target.target_id,
                )
            )
        ).all()
    )


async def _target_observations(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> list[CommerceRecommendationObservation]:
    return list(
        (
            await session.scalars(
                select(CommerceRecommendationObservation).where(
                    CommerceRecommendationObservation.audit_id == audit.id,
                    CommerceRecommendationObservation.target_kind == target.target_kind,
                    CommerceRecommendationObservation.target_id == target.target_id,
                )
            )
        ).all()
    )


def _build_shelf_snapshot(
    *,
    audit: Audit,
    target: CommercePromptTarget,
    tasks: list[AuditTask],
    observations: list[CommerceRecommendationObservation],
) -> CommerceShelfSnapshot:
    by_task: dict[uuid.UUID, list[CommerceRecommendationObservation]] = defaultdict(
        list
    )
    for observation in observations:
        by_task[observation.task_id].append(observation)
    recognized = [row for row in observations if row.classification != "unresolved"]
    owned = [row for row in recognized if row.classification == "owned"]
    ranked_owned = _ranked(owned)
    eligible_ranked = [_ranked(by_task[task.id]) for task in tasks]
    eligible_ranked = [rows for rows in eligible_ranked if rows]
    owned_tasks = _owned_task_count(tasks, by_task)
    return CommerceShelfSnapshot(
        workspace_id=audit.workspace_id,
        project_id=audit.project_id,
        audit_id=audit.id,
        target_kind=target.target_kind,
        target_id=target.target_id,
        product_visibility=owned_tasks / len(tasks) if tasks else 0.0,
        share_of_shelf=len(owned) / len(recognized) if recognized else None,
        average_shelf_position=_mean_rank(ranked_owned),
        first_position_win_rate=_first_position_rate(eligible_ranked),
        successful_execution_count=len(tasks),
        recognized_slot_count=len(recognized),
        ranked_execution_count=len(eligible_ranked),
        source_observation_ids=[str(row.id) for row in observations],
        context_snapshot={
            "target": {"kind": target.target_kind, "id": str(target.target_id)},
            "parser_version": COMMERCE_RECOMMENDATION_PARSER_VERSION,
            "matcher_version": COMMERCE_RECOMMENDATION_MATCHER_VERSION,
        },
    )


def _ranked(
    rows: list[CommerceRecommendationObservation],
) -> list[CommerceRecommendationObservation]:
    return sorted(
        (row for row in rows if row.order_observable and row.rank is not None),
        key=lambda row: row.rank or 0,
    )


def _owned_task_count(
    tasks: list[AuditTask],
    by_task: dict[uuid.UUID, list[CommerceRecommendationObservation]],
) -> int:
    return sum(
        any(row.classification == "owned" for row in by_task[task.id]) for task in tasks
    )


def _mean_rank(rows: list[CommerceRecommendationObservation]) -> float | None:
    return sum(row.rank or 0 for row in rows) / len(rows) if rows else None


def _first_position_rate(
    rows_by_task: list[list[CommerceRecommendationObservation]],
) -> float | None:
    if not rows_by_task:
        return None
    wins = sum(rows[0].classification == "owned" for rows in rows_by_task)
    return wins / len(rows_by_task)


async def get_shelf(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> ShelfResponse:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    snapshots_stmt = select(CommerceShelfSnapshot).where(
        CommerceShelfSnapshot.workspace_id == workspace_id,
        CommerceShelfSnapshot.project_id == project_id,
    )
    observations_stmt = select(CommerceRecommendationObservation).where(
        CommerceRecommendationObservation.workspace_id == workspace_id,
        CommerceRecommendationObservation.project_id == project_id,
    )
    if audit_id is not None:
        snapshots_stmt = snapshots_stmt.where(
            CommerceShelfSnapshot.audit_id == audit_id
        )
        observations_stmt = observations_stmt.where(
            CommerceRecommendationObservation.audit_id == audit_id
        )
    snapshots = list(
        (
            await session.scalars(
                snapshots_stmt.order_by(CommerceShelfSnapshot.created_at.desc())
            )
        ).all()
    )
    observations = list(
        (
            await session.scalars(
                observations_stmt.order_by(
                    CommerceRecommendationObservation.created_at.desc()
                )
            )
        ).all()
    )
    return ShelfResponse(
        snapshots=[ShelfMetricResponse.model_validate(row) for row in snapshots],
        observations=[
            RecommendationObservationResponse.model_validate(row)
            for row in observations
        ],
    )
