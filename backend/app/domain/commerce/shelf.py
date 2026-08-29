"""Deterministic recommendation observations and AI Shelf formulas."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.gateway import ModelGateway
from app.core.config.commerce_catalog import (
    COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS,
    COMMERCE_COMPETITOR_NON_PDP_HOST_SUFFIXES,
    COMMERCE_DOLLAR_CURRENCY_BY_COUNTRY,
    COMMERCE_RECOMMENDATION_MATCHER_VERSION,
    COMMERCE_RECOMMENDATION_PARSER_VERSION,
    COMMERCE_RECOMMENDATION_RESOLVER_RESULT_LIMIT,
    COMMERCE_RECOMMENDATION_RESOLVER_SPAN_CHARS,
    COMMERCE_RECOMMENDATION_RESOLVER_SPAN_LIMIT,
)
from app.domain.commerce.price import normalized_price_value
from app.domain.site_health.normalization import canonical_identity
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.commerce import (
    CommerceCompetitorCandidate,
    CommerceObservationCitation,
    CommercePromptTarget,
    CommerceRecommendationObservation,
)

_ORDERED = re.compile(r"^\s*(\d{1,2})[.)]\s+(.+)$")
_BULLET = re.compile(r"^\s*[-*•]\s+(.+)$")
_URL = re.compile(r"https?://[^\s)\]}>,]+", re.IGNORECASE)
_PRICE = re.compile(
    r"(?P<currency>[$£€₹]|AUD|USD|CAD|NZD|GBP|EUR|INR)\s*(?P<value>\d[\d,.]*)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Span:
    text: str
    rank: int | None
    order_observable: bool


@dataclass(frozen=True)
class _FrozenProduct:
    id: uuid.UUID
    canonical_url: str
    name: str
    brand: str
    gtin: str | None
    sku: str | None
    mpn: str | None
    attributes: dict[str, Any]


@dataclass(frozen=True)
class _FrozenCandidate:
    id: uuid.UUID
    canonical_url: str
    product_name: str
    brand_name: str
    state: str = "approved"


class _ResolvedRecommendation(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    brand: str = Field(default="", max_length=255)
    product_url: str = Field(default="", max_length=2048)
    merchant_url: str = Field(default="", max_length=2048)
    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    surface_kind: str = Field(
        default="recommendation", pattern="^(recommendation|shopping_result)$"
    )


class _ResolvedBatch(BaseModel):
    recommendations: list[_ResolvedRecommendation] = Field(
        max_length=COMMERCE_RECOMMENDATION_RESOLVER_RESULT_LIMIT
    )


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
            continue
        if spans:
            previous = spans[-1]
            spans[-1] = _Span(
                text=f"{previous.text} {cleaned}",
                rank=previous.rank,
                order_observable=previous.order_observable,
            )
    if spans:
        return spans
    unresolved = [
        value.strip()
        for value in re.split(r"(?<=[.!?])\s+|\s*;\s*", answer.strip())
        if value.strip()
    ]
    return [
        _Span(
            text=value[:COMMERCE_RECOMMENDATION_RESOLVER_SPAN_CHARS],
            rank=None,
            order_observable=False,
        )
        for value in unresolved[:COMMERCE_RECOMMENDATION_RESOLVER_SPAN_LIMIT]
    ] or [_Span(text="", rank=None, order_observable=False)]


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _price(span: str, *, locale: str = "") -> tuple[float | None, str]:
    match = _PRICE.search(span)
    if not match:
        return None, ""
    token = match.group("currency").upper()
    currency = {
        "£": "GBP",
        "€": "EUR",
        "₹": "INR",
    }.get(token, token)
    if token == "$":
        currency = _dollar_currency(locale)
    value = _parse_price_value(match.group("value"))
    return value, currency


def _dollar_currency(locale: str) -> str:
    parts = re.split(r"[-_]", locale.upper())
    matches = {
        COMMERCE_DOLLAR_CURRENCY_BY_COUNTRY[part]
        for part in parts
        if part in COMMERCE_DOLLAR_CURRENCY_BY_COUNTRY
    }
    return matches.pop() if len(matches) == 1 else ""


def _parse_price_value(raw: str) -> float | None:
    normalized = normalized_price_value(raw)
    return float(normalized) if normalized is not None else None


def _merchant(span: str) -> tuple[str, str]:
    match = _URL.search(span)
    if not match:
        return "", ""
    url = match.group(0)
    return url, (urlsplit(url).hostname or "").casefold()


async def _task_target(
    session: AsyncSession, *, task: AuditTask
) -> tuple[CommercePromptTarget | None, str, dict[str, Any] | None]:
    audit = await session.get(Audit, task.audit_id)
    if audit is None or audit.audit_scope != "commerce":
        return None, "", None
    frozen = dict((audit.configuration or {}).get("commerce_measurement") or {})
    target_ids = _frozen_target_ids(frozen)
    if not target_ids:
        return None, "", None
    target = await session.scalar(
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
    locale = "-".join(
        value
        for value in (
            str((audit.configuration or {}).get("language_code") or ""),
            str((audit.configuration or {}).get("country_code") or ""),
        )
        if value
    )
    return target, locale, _frozen_target(frozen, target=target)


def _frozen_target(
    frozen: dict[str, Any], *, target: CommercePromptTarget | None
) -> dict[str, Any] | None:
    if target is None:
        return None
    for row in frozen.get("targets") or []:
        if not isinstance(row, dict):
            continue
        identity = (str(row.get("kind")), str(row.get("id")))
        if identity == (target.target_kind, str(target.target_id)):
            return row
    return None


def _frozen_target_ids(frozen: dict) -> list[uuid.UUID]:
    values: list[uuid.UUID] = []
    for raw in frozen.get("prompt_target_ids") or []:
        try:
            values.append(uuid.UUID(str(raw)))
        except (TypeError, ValueError, AttributeError):
            continue
    return values


def _frozen_catalog(
    frozen_target: dict[str, Any],
) -> tuple[list[_FrozenProduct], list[_FrozenCandidate]]:
    products = [_frozen_product(row) for row in frozen_target.get("products") or []]
    candidates = [
        _frozen_candidate(row)
        for row in frozen_target.get("approved_competitors") or []
    ]
    return (
        [row for row in products if row is not None],
        [row for row in candidates if row is not None],
    )


@dataclass(frozen=True)
class _AnalysisContext:
    task: AuditTask
    target: CommercePromptTarget
    products: list[_FrozenProduct]
    candidates: list[_FrozenCandidate]
    locale: str
    citations: list[Citation]
    gateway: ModelGateway | None


def _frozen_product(row: Any) -> _FrozenProduct | None:
    if not isinstance(row, dict):
        return None
    try:
        return _FrozenProduct(
            id=uuid.UUID(str(row["id"])),
            canonical_url=str(row.get("canonical_url") or ""),
            name=str(row.get("name") or ""),
            brand=str(row.get("brand") or ""),
            gtin=_optional_text(row.get("gtin")),
            sku=_optional_text(row.get("sku")),
            mpn=_optional_text(row.get("mpn")),
            attributes=dict(row.get("attributes") or {}),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _frozen_candidate(row: Any) -> _FrozenCandidate | None:
    if not isinstance(row, dict):
        return None
    try:
        return _FrozenCandidate(
            id=uuid.UUID(str(row["id"])),
            canonical_url=str(row.get("canonical_url") or ""),
            product_name=str(row.get("product_name") or ""),
            brand_name=str(row.get("brand_name") or ""),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _match_product(
    text: str, products: list[_FrozenProduct]
) -> tuple[_FrozenProduct | None, float]:
    normalized = _normalize(text)
    for product in products:
        if _product_identity_matches(product, normalized):
            return product, 1.0
        if _product_attributes_match(product, normalized):
            return product, 0.9
    return None, 0.0


def _product_identity_matches(product: _FrozenProduct, normalized: str) -> bool:
    identities = (
        product.canonical_url,
        product.gtin,
        product.sku,
        product.mpn,
        product.name,
    )
    tokens = (_normalize(str(identity or "")) for identity in identities)
    return any(token and token in normalized for token in tokens)


def _product_attributes_match(product: _FrozenProduct, normalized: str) -> bool:
    if not product.brand or _normalize(str(product.brand or "")) not in normalized:
        return False
    values = (
        _normalize(str(value))
        for value in (product.attributes or {}).values()
        if isinstance(value, (str, int, float))
    )
    return any(value and value in normalized for value in values)


def _match_candidate(
    text: str, candidates: list[_FrozenCandidate]
) -> tuple[_FrozenCandidate | None, float]:
    normalized = _normalize(text)
    for candidate in candidates:
        for identity in (
            candidate.canonical_url,
            candidate.product_name,
            candidate.brand_name,
        ):
            token = _normalize(str(identity or ""))
            if token and token in normalized:
                return candidate, 1.0
    return None, 0.0


async def analyze_commerce_task(session: AsyncSession, *, task: AuditTask) -> None:
    """Append deterministic observations for one successful target execution."""
    if task.result_artifact_id is None:
        return
    target, locale, frozen_target = await _task_target(session, task=task)
    if target is None or frozen_target is None:
        return
    existing = await session.scalar(
        select(CommerceRecommendationObservation.id).where(
            CommerceRecommendationObservation.workspace_id == task.workspace_id,
            CommerceRecommendationObservation.project_id == target.project_id,
            CommerceRecommendationObservation.task_id == task.id,
            CommerceRecommendationObservation.parser_version
            == COMMERCE_RECOMMENDATION_PARSER_VERSION,
            CommerceRecommendationObservation.matcher_version
            == COMMERCE_RECOMMENDATION_MATCHER_VERSION,
        )
    )
    if existing is not None:
        return
    products, candidates = _frozen_catalog(frozen_target)
    citations = list(
        (
            await session.scalars(
                select(Citation)
                .join(ResponseAnalysis, ResponseAnalysis.id == Citation.analysis_id)
                .where(ResponseAnalysis.task_id == task.id)
            )
        ).all()
    )
    context = _AnalysisContext(
        task=task,
        target=target,
        products=products,
        candidates=candidates,
        locale=locale,
        citations=citations,
        gateway=_model_gateway(),
    )
    for span in _spans(task.answer_text)[:COMMERCE_RECOMMENDATION_RESOLVER_SPAN_LIMIT]:
        await _analyze_span(session, context=context, span=span)


async def _analyze_span(
    session: AsyncSession, *, context: _AnalysisContext, span: _Span
) -> None:
    product, product_confidence = _match_product(span.text, context.products)
    candidate, candidate_confidence = _match_candidate(span.text, context.candidates)
    if product is not None or candidate is not None:
        await _persist_observation(
            session,
            context=context,
            span=span,
            product=product,
            product_confidence=product_confidence,
            candidate=candidate,
            candidate_confidence=candidate_confidence,
        )
        return
    resolved_rows = await _resolve_span(span, gateway=context.gateway)
    if not resolved_rows:
        await _persist_observation(session, context=context, span=span)
        return
    # One span carries at most ONE position. When the resolver reads several
    # recommendations out of "1. A, B and C", every observation inherited
    # `rank=1, order_observable=True`, so three products each claimed first
    # place -- which is a made-up ordering the answer never stated, and it
    # skewed both the mean rank and the first-position rate. The position is
    # only observable when the span resolved to a single product.
    positioned = span if len(resolved_rows) == 1 else _unordered(span)
    for resolved in resolved_rows:
        await _persist_resolved(
            session, context=context, span=positioned, resolved=resolved
        )


def _unordered(span: _Span) -> _Span:
    """The same span with its position withheld rather than shared out."""
    return _Span(text=span.text, rank=None, order_observable=False)


async def _persist_resolved(
    session: AsyncSession,
    *,
    context: _AnalysisContext,
    span: _Span,
    resolved: _ResolvedRecommendation,
) -> None:
    identity_text = " ".join(
        value
        for value in (resolved.title, resolved.brand, resolved.product_url)
        if value
    )
    product, product_confidence = _match_product(identity_text, context.products)
    candidate, candidate_confidence = _match_candidate(
        identity_text, context.candidates
    )
    observed_candidate = None
    if product is None and candidate is None:
        observed_candidate = await _ai_observed_candidate(
            session,
            target=context.target,
            resolved=resolved,
            span=span,
            citations=context.citations,
        )
    await _persist_observation(
        session,
        context=context,
        span=span,
        product=product,
        product_confidence=product_confidence,
        candidate=candidate,
        candidate_confidence=candidate_confidence,
        observed_candidate=observed_candidate,
        resolved=resolved,
        model_version=context.gateway.model if context.gateway is not None else "",
    )


def _model_gateway() -> ModelGateway | None:
    try:
        return create_model_gateway()
    except AgentNotConfiguredError:
        return None


async def _resolve_span(
    span: _Span, *, gateway: ModelGateway | None
) -> list[_ResolvedRecommendation] | None:
    if gateway is None or not span.text.strip():
        return None
    try:
        raw = await gateway.complete_structured_json(
            system=(
                "Extract only recommended products from this bounded answer span. "
                "Keep product identity separate from merchant and citation URLs. "
                "Set product_url only when the URL identifies the recommended PDP; "
                "set merchant_url only for a seller link. Return an empty list "
                "when uncertain."
            ),
            user=json.dumps(
                {"span": span.text[:COMMERCE_RECOMMENDATION_RESOLVER_SPAN_CHARS]}
            ),
            schema_name="commerce_recommendation_resolution",
            schema=_ResolvedBatch.model_json_schema(),
        )
        batch = _ResolvedBatch.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - any model or schema fault means no resolution, not a failed shelf
        return None
    return batch.recommendations or None


async def _ai_observed_candidate(
    session: AsyncSession,
    *,
    target: CommercePromptTarget,
    resolved: _ResolvedRecommendation,
    span: _Span,
    citations: list[Citation],
) -> CommerceCompetitorCandidate | None:
    url = _resolved_product_url(resolved.product_url, citations=citations)
    if url is None:
        return None
    existing = await session.scalar(
        select(CommerceCompetitorCandidate).where(
            CommerceCompetitorCandidate.workspace_id == target.workspace_id,
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
        product_name=resolved.title,
        brand_name=resolved.brand,
        evidence={
            "observation_text": span.text[:COMMERCE_RECOMMENDATION_RESOLVER_SPAN_CHARS],
            "resolved_product_url": url,
            "merchant_url": resolved.merchant_url,
        },
        source_kind="ai_observed",
        state="pending",
    )
    session.add(candidate)
    await session.flush()
    return candidate


def _resolved_product_url(raw_url: str, *, citations: list[Citation]) -> str | None:
    try:
        url = canonical_identity(raw_url.strip())[0]
    except (TypeError, ValueError):
        return None
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.")
    lowered = url.casefold()
    if not host or any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in COMMERCE_COMPETITOR_NON_PDP_HOST_SUFFIXES
    ):
        return None
    if any(token in lowered for token in COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS):
        return None
    # Both sides canonicalized: `url` already is, and comparing it against raw
    # citation URLs let a trailing slash, a fragment, or a tracking parameter
    # slip a cited publisher page through as a competitor candidate.
    return None if url in _canonical_citation_urls(citations) else url


def _canonical_citation_urls(citations: list[Citation]) -> set[str]:
    canonical: set[str] = set()
    for citation in citations:
        if not citation.url:
            continue
        try:
            canonical.add(canonical_identity(citation.url.strip())[0])
        except (TypeError, ValueError):
            continue
    return canonical


async def _persist_observation(
    session: AsyncSession,
    *,
    context: _AnalysisContext,
    span: _Span,
    product: _FrozenProduct | None = None,
    product_confidence: float = 0.0,
    candidate: _FrozenCandidate | None = None,
    candidate_confidence: float = 0.0,
    observed_candidate: CommerceCompetitorCandidate | None = None,
    resolved: _ResolvedRecommendation | None = None,
    model_version: str = "",
) -> None:
    task = context.task
    target = context.target
    price, currency = (
        (resolved.price, resolved.currency.upper())
        if resolved is not None and resolved.price is not None
        else _price(span.text, locale=context.locale)
    )
    merchant_url, merchant_domain = _observation_merchant(span, resolved=resolved)
    observation = CommerceRecommendationObservation(
        workspace_id=task.workspace_id,
        project_id=target.project_id,
        audit_id=task.audit_id,
        task_id=task.id,
        artifact_id=task.result_artifact_id,
        target_kind=target.target_kind,
        target_id=target.target_id,
        product_id=product.id if product else None,
        competitor_candidate_id=_candidate_id(candidate, observed_candidate),
        observed_product=_observed_product(
            span, product, candidate, observed_candidate, resolved
        ),
        observed_brand=_observed_brand(
            product, candidate, observed_candidate, resolved
        ),
        classification=_observation_class(product, candidate, observed_candidate),
        observed_title=resolved.title if resolved else span.text[:512],
        observed_price=price,
        observed_currency=currency,
        merchant_url=merchant_url,
        merchant_domain=merchant_domain,
        surface_kind=resolved.surface_kind if resolved else "recommendation",
        rank=span.rank,
        order_observable=span.order_observable,
        match_confidence=max(product_confidence, candidate_confidence),
        model_version=model_version,
    )
    session.add(observation)
    await session.flush()
    _link_observation_citations(
        session,
        observation=observation,
        citations=context.citations,
        text=span.text,
    )


def _observation_merchant(
    span: _Span, *, resolved: _ResolvedRecommendation | None
) -> tuple[str, str]:
    extracted_url, extracted_domain = _merchant(span.text)
    resolved_url = resolved.merchant_url.strip() if resolved is not None else ""
    url = resolved_url or extracted_url
    domain = (urlsplit(url).hostname or "").casefold() if url else extracted_domain
    return url, domain


def _candidate_id(
    candidate: _FrozenCandidate | None,
    observed_candidate: CommerceCompetitorCandidate | None,
) -> uuid.UUID | None:
    row = candidate or observed_candidate
    return row.id if row is not None else None


def _observation_class(
    product: _FrozenProduct | None,
    candidate: _FrozenCandidate | None,
    observed_candidate: CommerceCompetitorCandidate | None,
) -> str:
    if product is not None:
        return "owned"
    if candidate is not None:
        return "approved_competitor"
    return "ai_observed_competitor" if observed_candidate is not None else "unresolved"


def _observed_product(
    span: _Span,
    product: _FrozenProduct | None,
    candidate: _FrozenCandidate | None,
    observed_candidate: CommerceCompetitorCandidate | None,
    resolved: _ResolvedRecommendation | None,
) -> str:
    rows = (product, candidate, observed_candidate)
    names = ("name", "product_name", "product_name")
    for row, field in zip(rows, names, strict=True):
        if row is not None:
            return str(getattr(row, field))
    return resolved.title if resolved is not None else span.text[:512]


def _observed_brand(
    product: _FrozenProduct | None,
    candidate: _FrozenCandidate | None,
    observed_candidate: CommerceCompetitorCandidate | None,
    resolved: _ResolvedRecommendation | None,
) -> str:
    rows = (product, candidate, observed_candidate)
    fields = ("brand", "brand_name", "brand_name")
    for row, field in zip(rows, fields, strict=True):
        if row is not None:
            return str(getattr(row, field))
    return resolved.brand if resolved is not None else ""


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
