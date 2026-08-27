"""Optional competitor discovery, deterministic validation, and decisions."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.parser import extract_page_facts
from app.connectors.commerce_competitors import (
    CompetitorProviderUnavailable,
    tavily_search,
)
from app.connectors.keenable import KeenableClient
from app.connectors.web_evidence.contracts import FetchError, FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.core.config.brand_discovery import brand_discovery_settings
from app.core.config.commerce_catalog import (
    COMMERCE_COMPETITOR_EXCLUDED_HOST_SUFFIXES,
    COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS,
    COMMERCE_COMPETITOR_KEENABLE_SNIPPET_CHARS,
    COMMERCE_COMPETITOR_PRICE_BANDS,
    COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT,
    COMMERCE_COMPETITOR_QUERY_ATTRIBUTE_LIMIT,
    COMMERCE_COMPETITOR_RESULT_LIMIT,
    COMMERCE_COMPETITOR_TARGET_NAME_MAX_WORDS,
    COMMERCE_COMPETITOR_VERIFY_CONCURRENCY,
    COMMERCE_COMPETITOR_VERIFY_TIMEOUT_SECONDS,
    COMMERCE_EDITORIAL_TITLE_PATTERNS,
    COMMERCE_SECOND_HAND_TOKENS,
)
from app.core.config.site_health_acquisition import FETCH_PURPOSE_ANALYZE
from app.core.config.task_queue import TASK_STATUS_QUEUED, TASK_TERMINAL_STATUSES
from app.domain.commerce.schemas import (
    CommerceTarget,
    CompetitorCandidateResponse,
    DiscoveryResponse,
    DiscoveryTaskResponse,
)
from app.domain.commerce.service import CommerceNotFoundError, require_project
from app.domain.site_health.normalization import canonical_identity
from app.models.analytics import AnalyticsTask
from app.models.brand import OwnedDomain
from app.models.commerce import (
    CommerceCategory,
    CommerceCompetitorAttempt,
    CommerceCompetitorCandidate,
    CommerceProduct,
)
from app.models.project import Project
from app.orchestration.executor_errors import TerminalExecutorError


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _target_names(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[CommerceTarget],
) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    category_ids = {target.id for target in targets if target.kind == "category"}
    product_ids = {target.id for target in targets if target.kind == "product"}
    contexts = await _category_contexts(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        category_ids=category_ids,
    )
    contexts.update(
        await _product_contexts(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            product_ids=product_ids,
        )
    )
    missing = next(
        (target for target in targets if (target.kind, target.id) not in contexts),
        None,
    )
    if missing is not None:
        raise CommerceNotFoundError(f"Commerce {missing.kind} not found")
    return contexts


async def _category_contexts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    category_ids: set[uuid.UUID],
) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    if not category_ids:
        return {}
    rows = await session.scalars(
        select(CommerceCategory).where(
            CommerceCategory.id.in_(category_ids),
            CommerceCategory.workspace_id == workspace_id,
            CommerceCategory.project_id == project_id,
        )
    )
    return {("category", row.id): {"name": str(row.name)} for row in rows}


async def _product_contexts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product_ids: set[uuid.UUID],
) -> dict[tuple[str, uuid.UUID], dict[str, Any]]:
    if not product_ids:
        return {}
    rows = await session.scalars(
        select(CommerceProduct).where(
            CommerceProduct.id.in_(product_ids),
            CommerceProduct.workspace_id == workspace_id,
            CommerceProduct.project_id == project_id,
        )
    )
    return {
        ("product", row.id): {
            "name": str(row.name),
            "attributes": dict(row.attributes or {}),
            "price": float(row.price) if row.price is not None else None,
            "currency": str(row.currency or ""),
        }
        for row in rows
    }


async def enqueue_discoveries(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[CommerceTarget],
) -> DiscoveryResponse:
    project = await require_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    contexts = await _target_names(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        targets=targets,
    )
    task_ids: list[uuid.UUID] = []
    run_id = uuid.uuid4()
    locale = "-".join(
        value for value in (project.language_code, project.country_code) if value
    )
    for target in targets:
        context = contexts[(target.kind, target.id)]
        key = f"commerce:competitors:{run_id}:{target.kind}:{target.id}"
        task_id = await session.scalar(
            insert(AnalyticsTask)
            .values(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                task_kind="commerce_competitor_discovery",
                payload={
                    "target": target.model_dump(mode="json"),
                    "target_context": context,
                    "locale": locale,
                    "run_id": str(run_id),
                },
                idempotency_key=key,
                status=TASK_STATUS_QUEUED,
            )
            .on_conflict_do_nothing(index_elements=[AnalyticsTask.idempotency_key])
            .returning(AnalyticsTask.id)
        )
        if task_id is None:
            task_id = await session.scalar(
                select(AnalyticsTask.id).where(AnalyticsTask.idempotency_key == key)
            )
        if task_id is None:
            raise RuntimeError("Competitor discovery task was not persisted")
        task_ids.append(task_id)
    await session.commit()
    return DiscoveryResponse(task_ids=task_ids)


async def list_discovery_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    task_ids: list[uuid.UUID],
) -> list[DiscoveryTaskResponse]:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    if not task_ids:
        return []
    rows = list(
        (
            await session.scalars(
                select(AnalyticsTask).where(
                    AnalyticsTask.id.in_(task_ids),
                    AnalyticsTask.workspace_id == workspace_id,
                    AnalyticsTask.project_id == project_id,
                    AnalyticsTask.task_kind == "commerce_competitor_discovery",
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    responses: list[DiscoveryTaskResponse] = []
    for task_id in dict.fromkeys(task_ids):
        row = by_id.get(task_id)
        if row is None:
            raise CommerceNotFoundError("Competitor discovery task not found")
        responses.append(_discovery_response(row))
    return responses


def _discovery_response(row: AnalyticsTask) -> DiscoveryTaskResponse:
    return DiscoveryTaskResponse(
        id=row.id,
        target=CommerceTarget.model_validate(dict(row.payload or {}).get("target")),
        status=row.status,
        error_code=row.error_code,
        terminal=row.status in TASK_TERMINAL_STATUSES,
    )


async def list_active_discovery_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[DiscoveryTaskResponse]:
    """Every discovery still in flight for the project.

    Task ids lived only in React state, so a tab switch or a reload dropped
    the running banner and the poll with it -- a discovery could finish with
    nobody watching, and a stuck one was invisible. Server-held state is the
    only thing a reload can recover from.
    """
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    rows = await session.scalars(
        select(AnalyticsTask)
        .where(
            AnalyticsTask.workspace_id == workspace_id,
            AnalyticsTask.project_id == project_id,
            AnalyticsTask.task_kind == "commerce_competitor_discovery",
            AnalyticsTask.status.not_in(tuple(TASK_TERMINAL_STATUSES)),
        )
        .order_by(AnalyticsTask.created_at.asc())
    )
    return [_discovery_response(row) for row in rows]


async def list_candidates(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[CompetitorCandidateResponse]:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    rows = list(
        (
            await session.scalars(
                select(CommerceCompetitorCandidate)
                .where(
                    CommerceCompetitorCandidate.workspace_id == workspace_id,
                    CommerceCompetitorCandidate.project_id == project_id,
                )
                .order_by(CommerceCompetitorCandidate.created_at.desc())
            )
        ).all()
    )
    return [CompetitorCandidateResponse.model_validate(row) for row in rows]


async def decide_candidate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    decision: str,
) -> CompetitorCandidateResponse:
    row = await session.scalar(
        select(CommerceCompetitorCandidate).where(
            CommerceCompetitorCandidate.id == candidate_id,
            CommerceCompetitorCandidate.workspace_id == workspace_id,
            CommerceCompetitorCandidate.project_id == project_id,
        )
    )
    if row is None:
        raise CommerceNotFoundError("Competitor candidate not found")
    row.state = decision
    row.decision_at = _utcnow()
    await session.commit()
    return CompetitorCandidateResponse.model_validate(row)


def _host(value: str) -> str:
    normalized = value.strip()
    parsed = urlsplit(normalized if "://" in normalized else f"//{normalized}")
    return (parsed.hostname or "").casefold().removeprefix("www.")


def _marketplace(host: str) -> bool:
    """True for a marketplace/aggregator host, which is never a competitor."""
    return any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in COMMERCE_COMPETITOR_EXCLUDED_HOST_SUFFIXES
    )


def _owned(host: str, owned_hosts: set[str]) -> bool:
    return any(host == value or host.endswith(f".{value}") for value in owned_hosts)


async def _owned_hosts(session: AsyncSession, *, project: Project) -> set[str]:
    values = {
        _host(value)
        for value in await session.scalars(
            select(OwnedDomain.domain).where(OwnedDomain.project_id == project.id)
        )
    }
    values.add(_host(project.website_url))
    return {value for value in values if value}


def _usable_target_name(name: str) -> bool:
    """Whether a target name can carry a search query.

    A leftover page title -- separator-joined, or a whole sentence of
    marketing copy -- is not a category anyone searches for, and putting it in
    the query is what returned marketplace listings for unrelated products.
    """
    cleaned = " ".join(name.split())
    if len(cleaned) < 2:
        return False
    if any(separator in cleaned for separator in ("|", "–", "—", "»")):
        return False
    return len(cleaned.split()) <= COMMERCE_COMPETITOR_TARGET_NAME_MAX_WORDS


def _discovery_query(
    target: CommerceTarget, name: str, context: dict[str, Any] | None = None
) -> str:
    if target.kind == "category":
        # Merchant intent, not ranking intent. "leading {name} brands" is the
        # phrasing a search engine answers with listicles -- it returned
        # "The 5 Best Stainless Steel Cookware Sets of 2026, Tested & Reviewed"
        # as a cookware competitor. Asking where to BUY returns shops.
        return f"buy {name} online store"
    context = context or {}
    attributes = dict(context.get("attributes") or {})
    details = [
        _product_type(attributes),
        *_query_attributes(attributes),
        _price_band(context),
    ]
    qualifiers = " ".join(value for value in details if value)
    return f"buy {name}{f' {qualifiers}' if qualifiers else ''} online store"


def _product_type(attributes: dict[str, Any]) -> str:
    values = (
        str(attributes.get(key) or "").strip()
        for key in ("product_type", "type", "category")
    )
    return next((value for value in values if value), "")


def _query_attributes(attributes: dict[str, Any]) -> list[str]:
    excluded = {"product_type", "type", "category", "availability"}
    values = [
        str(value).strip()
        for key, value in attributes.items()
        if key not in excluded and isinstance(value, (str, int, float))
    ]
    return [value for value in values if value][
        :COMMERCE_COMPETITOR_QUERY_ATTRIBUTE_LIMIT
    ]


def _price_band(context: dict[str, Any]) -> str:
    raw = context.get("price")
    if not isinstance(raw, (int, float)) or raw < 0:
        return ""
    label = next(
        label for ceiling, label in COMMERCE_COMPETITOR_PRICE_BANDS if raw < ceiling
    )
    currency = str(context.get("currency") or "").strip().upper()
    return f"price {currency + ' ' if currency else ''}{label}"


def _precheck(
    item: dict[str, Any], *, owned_hosts: set[str]
) -> tuple[str, str, str] | None:
    checked, _ = _precheck_result(item, owned_hosts=owned_hosts)
    return checked


def _precheck_result(
    item: dict[str, Any], *, owned_hosts: set[str]
) -> tuple[tuple[str, str, str] | None, str]:
    raw_url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not raw_url or not title:
        return None, "excluded_missing_identity"
    try:
        canonical = canonical_identity(raw_url)[0]
    except (TypeError, ValueError):
        return None, "excluded_invalid_url"
    excluded = _exclusion_reason(canonical, title, owned_hosts=owned_hosts)
    if excluded:
        return None, excluded
    return (canonical, title, str(item.get("content") or "")[:1000]), "eligible"


def _exclusion_reason(canonical: str, title: str, *, owned_hosts: set[str]) -> str:
    """Why this result is not a competitor, or an empty string if it may be."""
    host = _host(canonical)
    lowered = f"{canonical} {title}".casefold()
    if _owned(host, owned_hosts):
        return "excluded_owned_domain"
    if _marketplace(host):
        return "excluded_marketplace"
    if any(token in lowered for token in COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS):
        return "excluded_editorial"
    if _editorial(lowered):
        return "excluded_editorial"
    if any(token in lowered for token in COMMERCE_SECOND_HAND_TOKENS):
        return "excluded_incompatible"
    return ""


_EDITORIAL = tuple(re.compile(pattern) for pattern in COMMERCE_EDITORIAL_TITLE_PATTERNS)


def _editorial(lowered: str) -> bool:
    """A ranked listicle or review, which is a publisher and not a shop."""
    return any(pattern.search(lowered) for pattern in _EDITORIAL)


async def _verify_url(url: str, fetcher: SecureFetcher) -> bool:
    request = FetchRequest(url=url, purpose=FETCH_PURPOSE_ANALYZE)
    try:
        result = await fetcher.fetch(request, enforce_scope=False)
    except FetchError:
        return False
    if not (
        200 <= result.status_code < 400 and result.content_type.startswith("text/html")
    ):
        return False
    facts = extract_page_facts(
        result.body,
        final_url=result.final_url,
        content_type=result.content_type,
        charset=result.charset,
        status_code=result.status_code,
    )
    assessment = classify(result.final_url, facts)
    product = dict((facts.get("structured_data") or {}).get("product") or {})
    has_product_identity = any(
        product.get(key) for key in ("name", "sku", "gtin", "mpn")
    )
    has_visible_identity = bool(facts.get("title")) and bool(
        (facts.get("commerce") or {}).get("visible_price")
    )
    return assessment.page_kind == "product" and (
        has_product_identity or has_visible_identity
    )


async def run_competitor_discovery(session_factory, task: AnalyticsTask) -> None:
    if task.project_id is None:
        raise ValueError("Commerce discovery task has no project")
    payload = dict(task.payload or {})
    target = CommerceTarget.model_validate(payload.get("target"))
    context = dict(payload.get("target_context") or {})
    name = str(context.get("name") or payload.get("target_name") or "")
    if not _usable_target_name(name):
        # A category whose name is still a raw page title produces a query like
        # "leading Daydreamer Oversized Tops ... | Red Dress brands", which
        # returns other retailers' listings. Refuse it instead of persisting
        # candidates nobody can act on.
        raise TerminalExecutorError(
            "unusable_target", f"Target name is not searchable: {name!r}"
        )
    query = _discovery_query(target, name, context)
    locale = str(payload.get("locale") or "")
    status, error_code, results, should_retry = await _provider_results(
        query, locale=locale
    )
    async with session_factory() as session:
        await _persist_discovery(
            session,
            task=task,
            target=target,
            query=query,
            locale=locale,
            status=status,
            error_code=error_code,
            results=results,
        )
    if should_retry:
        raise RuntimeError("Competitor discovery provider failed")
    if status == "unavailable":
        # Reported as `succeeded` with zero candidates before, so an
        # unconfigured provider looked like a brand with no competitors.
        raise TerminalExecutorError(error_code or "provider_unavailable")


async def _provider_results(
    query: str, *, locale: str
) -> tuple[str, str, list[dict[str, Any]], bool]:
    """Tavily first, Keenable second. Only both failing is a discovery failure.

    Keenable is already a configured search transport for onboarding research,
    so an unconfigured or failing Tavily no longer means "this project cannot
    discover competitors" -- it means try the other one.
    """
    try:
        return "succeeded", "", await tavily_search(query, locale=locale), False
    except CompetitorProviderUnavailable:
        return await _keenable_results(query, unavailable_code="provider_unavailable")
    except Exception:
        return await _keenable_results(
            query, unavailable_code="provider_failed", retry_when_unavailable=True
        )


async def _keenable_results(
    query: str, *, unavailable_code: str, retry_when_unavailable: bool = False
) -> tuple[str, str, list[dict[str, Any]], bool]:
    client = _keenable_client()
    if client is None:
        return "unavailable", unavailable_code, [], retry_when_unavailable
    try:
        response = await client.search(
            query,
            max_results=COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT,
            snippet_max_length=COMMERCE_COMPETITOR_KEENABLE_SNIPPET_CHARS,
        )
    except Exception:
        return "failed", "provider_failed", [], True
    return (
        "succeeded",
        "",
        [
            {
                "url": result.url,
                "title": result.title,
                "content": result.snippet or result.description,
            }
            for result in response.results
        ],
        False,
    )


def _keenable_client() -> KeenableClient | None:
    key = brand_discovery_settings.keenable_api_key.get_secret_value()
    if not key:
        return None
    return KeenableClient(
        api_key=key,
        base_url=brand_discovery_settings.keenable_base_url,
        timeout_seconds=brand_discovery_settings.keenable_request_timeout_seconds,
    )


async def _persist_discovery(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    target: CommerceTarget,
    query: str,
    locale: str,
    status: str,
    error_code: str,
    results: list[dict[str, Any]],
) -> None:
    if task.project_id is None:
        raise ValueError("Commerce discovery task has no project")
    project = await require_project(
        session, workspace_id=task.workspace_id, project_id=task.project_id
    )
    attempt_number = (
        int(
            await session.scalar(
                select(func.count()).where(CommerceCompetitorAttempt.task_id == task.id)
            )
        )
        or 0
    ) + 1
    result_payload: list[dict[str, Any]] = []
    survivors: list[tuple[str, str, str]] = []
    if status == "succeeded":
        result_payload, survivors = await _validated_results(
            results, owned_hosts=await _owned_hosts(session, project=project)
        )
    attempt = CommerceCompetitorAttempt(
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        task_id=task.id,
        target_kind=target.kind,
        target_id=target.id,
        attempt_number=attempt_number,
        query=query,
        locale=locale,
        status=status,
        result_payload=result_payload,
        error_code=error_code,
    )
    session.add(attempt)
    await session.flush()
    if survivors:
        await _add_candidates(
            session, task=task, target=target, attempt=attempt, rows=survivors
        )
    await session.commit()


async def _validated_results(
    results: list[dict[str, Any]], *, owned_hosts: set[str]
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    """Pre-check every result deterministically, then verify the survivors.

    Verification used to run inside this loop, one `await` at a time, each with
    its own `SecureFetcher` and DNS resolver: ten candidates meant ten
    sequential full page downloads, which is why a discovery took minutes and
    held its queue lease open the whole time. The pre-check is pure, so the
    only network work is the verification of the candidates that survive it,
    and those run concurrently over one shared fetcher.
    """
    prechecked = _prechecked_results(results, owned_hosts=owned_hosts)
    verified = await _verified_urls(
        [checked for _, checked, _ in prechecked if checked is not None]
    )
    return _admitted_results(prechecked, verified)


_Prechecked = list[tuple[dict[str, Any], tuple[str, str, str] | None, str]]


def _prechecked_results(
    results: list[dict[str, Any]], *, owned_hosts: set[str]
) -> _Prechecked:
    """Each bounded result with its pure verdict, distinct canonicals only."""
    prechecked: _Prechecked = []
    seen: set[str] = set()
    for item in results[:COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT]:
        checked, outcome = _precheck_result(item, owned_hosts=owned_hosts)
        if checked is not None:
            if checked[0] in seen:
                checked, outcome = None, "excluded_duplicate"
            else:
                seen.add(checked[0])
        prechecked.append((item, checked, outcome))
    return prechecked


async def _verified_urls(candidates: list[tuple[str, str, str]]) -> dict[str, bool]:
    """Fetch the surviving candidates concurrently over one shared fetcher."""
    if not candidates:
        return {}
    semaphore = asyncio.Semaphore(COMMERCE_COMPETITOR_VERIFY_CONCURRENCY)

    async def verify(url: str, fetcher: SecureFetcher) -> tuple[str, bool]:
        async with semaphore:
            try:
                async with asyncio.timeout(COMMERCE_COMPETITOR_VERIFY_TIMEOUT_SECONDS):
                    return url, await _verify_url(url, fetcher)
            except Exception:  # noqa: BLE001 - one bad page never fails a run
                return url, False

    async with SecureFetcher(resolver=SystemDnsResolver()) as fetcher:
        return dict(
            await asyncio.gather(
                *(verify(checked[0], fetcher) for checked in candidates)
            )
        )


def _admitted_results(
    prechecked: _Prechecked, verified: dict[str, bool]
) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    outcomes: list[dict[str, Any]] = []
    survivors: list[tuple[str, str, str]] = []
    for item, checked, outcome in prechecked:
        if checked is not None:
            if not verified.get(checked[0]):
                outcome = "excluded_unavailable"
            elif len(survivors) >= COMMERCE_COMPETITOR_RESULT_LIMIT:
                # The limit applies to what is ACCEPTED, as it did when this
                # ran sequentially -- a candidate that fails verification must
                # not consume a slot.
                outcome = "excluded_limit"
            else:
                outcome = "accepted"
                survivors.append(checked)
        outcomes.append(_result_outcome(item, outcome=outcome))
    return outcomes, survivors


def _result_outcome(item: dict[str, Any], *, outcome: str) -> dict[str, Any]:
    return {
        "url": str(item.get("url") or "")[:2048],
        "title": str(item.get("title") or "")[:512],
        "content": str(item.get("content") or "")[:1000],
        "validation_outcome": outcome,
    }


async def _add_candidates(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    target: CommerceTarget,
    attempt: CommerceCompetitorAttempt,
    rows: list[tuple[str, str, str]],
) -> None:
    for url, title, content in rows:
        await session.execute(
            insert(CommerceCompetitorCandidate)
            .values(
                id=uuid.uuid4(),
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                attempt_id=attempt.id,
                target_kind=target.kind,
                target_id=target.id,
                canonical_url=url,
                product_name=title,
                evidence={"search_excerpt": content},
            )
            .on_conflict_do_nothing(
                index_elements=[
                    CommerceCompetitorCandidate.project_id,
                    CommerceCompetitorCandidate.target_kind,
                    CommerceCompetitorCandidate.target_id,
                    CommerceCompetitorCandidate.canonical_url,
                ]
            )
        )
