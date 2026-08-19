"""Comparable-crawl selection, evidence assembly, and immutable persistence."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.change_intel import (
    ChangePage,
    ExpectedChange,
    RuleState,
    compare_crawls,
)
from app.core.config.site_change_intel import (
    CHANGE_ANALYZER_VERSION,
    CHANGE_FIELD_RULES,
    CHANGE_MAX_CRAWL_CANDIDATES,
    CHANGE_MAX_PAGES,
    CHANGE_REASON_NO_PREVIOUS_CRAWL,
    CHANGE_REASON_NO_USABLE_EVIDENCE,
    CHANGE_REASON_SCOPE_MISMATCH,
    CHANGE_REASON_VERSION_MISMATCH,
    CHANGE_STATE_AVAILABLE,
    CHANGE_STATE_NON_COMPARABLE,
    CHANGE_STATE_UNAVAILABLE,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_COMPLETED,
    CRAWL_TERMINAL_STATUSES,
    PAGE_ANALYSIS_STATUS_COMPLETED,
)
from app.models.opportunity import OpportunityImplementationEvent
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl, SiteUrlObservation

_SCOPE_KEYS = (
    "discovery_mode",
    "sample_mode",
    "root_registrable_domain",
    "include_globs",
    "exclude_globs",
    "input_mode",
    "requested_page_limit",
    "seed_urls",
    "page_kinds",
    "automatic_monitor_limit",
)


@dataclass(frozen=True)
class _PageRow:
    analysis: SitePageAnalysis
    artifact: SiteFetchArtifact
    site_url: SiteUrl
    observation: SiteUrlObservation


def root_origin(crawl: SiteCrawl) -> str:
    parts = urlsplit(crawl.root_url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def crawl_scope_hash(crawl: SiteCrawl) -> str:
    configuration = crawl.configuration or {}
    material = {key: configuration.get(key) for key in _SCOPE_KEYS}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _complete(crawl: SiteCrawl) -> bool:
    return crawl.status == CRAWL_STATUS_COMPLETED and crawl.inventory_complete


async def select_previous_comparable_crawl(
    session: AsyncSession, *, crawl_b: SiteCrawl
) -> SiteCrawl | None:
    """Select the immediate earlier usable crawl under the locked dimensions."""
    candidates = list(
        (
            await session.scalars(
                select(SiteCrawl)
                .where(
                    SiteCrawl.workspace_id == crawl_b.workspace_id,
                    SiteCrawl.project_id == crawl_b.project_id,
                    SiteCrawl.id != crawl_b.id,
                    SiteCrawl.status.in_(CRAWL_TERMINAL_STATUSES),
                    SiteCrawl.analyzed_url_count > 0,
                    SiteCrawl.created_at < crawl_b.created_at,
                )
                .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
                .limit(CHANGE_MAX_CRAWL_CANDIDATES)
            )
        ).all()
    )
    if not candidates:
        return None
    comparable = next(
        (
            candidate
            for candidate in candidates
            if root_origin(candidate) == root_origin(crawl_b)
            and crawl_scope_hash(candidate) == crawl_scope_hash(crawl_b)
            and candidate.extractor_version == crawl_b.extractor_version
            and candidate.analyzer_version == crawl_b.analyzer_version
        ),
        None,
    )
    # Retain the immediate predecessor when no compatible predecessor exists so
    # the persisted projection can explain the exact non-comparable boundary.
    return comparable or candidates[0]


async def _page_rows(
    session: AsyncSession, crawl: SiteCrawl
) -> tuple[list[_PageRow], bool]:
    rows = list(
        (
            await session.execute(
                select(
                    SitePageAnalysis,
                    SiteFetchArtifact,
                    SiteUrl,
                    SiteUrlObservation,
                )
                .join(
                    SiteFetchArtifact,
                    SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
                )
                .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
                .join(
                    SiteUrlObservation,
                    (SiteUrlObservation.crawl_id == crawl.id)
                    & (SiteUrlObservation.site_url_id == SitePageAnalysis.site_url_id),
                )
                .where(
                    SitePageAnalysis.workspace_id == crawl.workspace_id,
                    SitePageAnalysis.project_id == crawl.project_id,
                    SitePageAnalysis.crawl_id == crawl.id,
                    SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                    SitePageAnalysis.is_current.is_(True),
                    SitePageAnalysis.analyzer_version == crawl.analyzer_version,
                    SiteFetchArtifact.extractor_version == crawl.extractor_version,
                )
                .order_by(SitePageAnalysis.site_url_id, SitePageAnalysis.id)
                .limit(CHANGE_MAX_PAGES + 1)
            )
        ).all()
    )
    return (
        [_PageRow(*row) for row in rows[:CHANGE_MAX_PAGES]],
        len(rows) > CHANGE_MAX_PAGES,
    )


async def _rules(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    analysis_ids: list[uuid.UUID],
) -> dict[uuid.UUID, dict[str, SiteRuleEvaluation]]:
    if not analysis_ids:
        return {}
    by_analysis: dict[uuid.UUID, dict[str, SiteRuleEvaluation]] = defaultdict(dict)
    rows = (
        await session.scalars(
            select(SiteRuleEvaluation).where(
                SiteRuleEvaluation.workspace_id == workspace_id,
                SiteRuleEvaluation.analysis_id.in_(analysis_ids),
                SiteRuleEvaluation.rule_id.in_(set(CHANGE_FIELD_RULES.values())),
            )
        )
    ).all()
    for row in rows:
        by_analysis[row.analysis_id][row.rule_id] = row
    return by_analysis


def _internal_link_count(facts: dict[str, Any]) -> int:
    """Count extracted internal anchors without scheduling reachability probes."""
    links = facts.get("links") or {}
    return sum(
        1
        for entry in links.get("anchors") or []
        if bool((entry or {}).get("is_internal"))
    )


def _field_values(row: _PageRow, internal_links: int) -> dict[str, Any]:
    facts = row.artifact.normalized_facts or {}
    headings = facts.get("headings") or {}
    structured = facts.get("structured_data") or {}
    robots = facts.get("robots") or {}
    return {
        "title": str(facts.get("title") or ""),
        "meta_description": str(facts.get("meta_description") or ""),
        "h1": list(headings.get("h1_texts") or []),
        "canonical": str(facts.get("canonical_url") or ""),
        "robots_noindex": bool(robots.get("noindex")),
        "json_ld_present": bool(structured.get("has_json_ld")),
        "internal_link_count": internal_links,
        "http_status": row.artifact.status_code or row.observation.status_code,
        "redirect_target": row.observation.final_url or row.artifact.final_url,
    }


def _change_page(
    row: _PageRow,
    *,
    evaluations: dict[str, SiteRuleEvaluation],
    internal_links: int,
) -> ChangePage:
    rule_states: dict[str, RuleState] = {}
    intended_indexable: bool | None = None
    for field, rule_id in CHANGE_FIELD_RULES.items():
        evaluation = evaluations.get(rule_id)
        if evaluation is None:
            continue
        rule_states[field] = RuleState(
            evaluation.outcome, evaluation.severity, evaluation.id
        )
        if field == "robots_noindex":
            intent = (evaluation.evidence or {}).get("indexing_intent")
            intended_indexable = True if intent == "intended_index" else None
    return ChangePage(
        site_url_id=row.site_url.id,
        normalized_url=row.site_url.normalized_url,
        analysis_id=row.analysis.id,
        artifact_id=row.artifact.id,
        fields=_field_values(row, internal_links),
        rules=rule_states,
        intended_indexable=intended_indexable,
    )


async def _pages(
    session: AsyncSession, crawl: SiteCrawl
) -> tuple[list[ChangePage], bool]:
    rows, capped = await _page_rows(session, crawl)
    analysis_ids = [row.analysis.id for row in rows]
    evaluations = await _rules(
        session, workspace_id=crawl.workspace_id, analysis_ids=analysis_ids
    )
    pages = [
        _change_page(
            row,
            evaluations=evaluations.get(row.analysis.id, {}),
            internal_links=_internal_link_count(row.artifact.normalized_facts or {}),
        )
        for row in rows
    ]
    return pages, capped


def _check_field(check: dict[str, Any]) -> tuple[str | None, Any]:
    if check.get("kind") == "page_fact":
        field = str(check.get("fact_key") or "")
        return field if field in {
            *CHANGE_FIELD_RULES,
            "internal_link_count",
            "http_status",
            "redirect_target",
        } else None, check.get("expected_value")
    if check.get("kind") == "site_rule":
        inverse = {rule_id: field for field, rule_id in CHANGE_FIELD_RULES.items()}
        return inverse.get(str(check.get("rule_id") or "")), check.get(
            "expected_outcome"
        )
    return None, None


async def _expected_changes(
    session: AsyncSession,
    *,
    crawl_a: SiteCrawl,
    crawl_b: SiteCrawl,
    pages_b: list[ChangePage],
) -> dict[tuple[uuid.UUID, str], ExpectedChange]:
    if crawl_b.completed_at is None:
        return {}
    lower = crawl_a.completed_at or crawl_a.created_at
    events = (
        await session.scalars(
            select(OpportunityImplementationEvent)
            .where(
                OpportunityImplementationEvent.workspace_id == crawl_b.workspace_id,
                OpportunityImplementationEvent.project_id == crawl_b.project_id,
                OpportunityImplementationEvent.declared_implemented_at > lower,
                OpportunityImplementationEvent.declared_implemented_at
                <= crawl_b.completed_at,
            )
            .order_by(
                OpportunityImplementationEvent.declared_implemented_at.desc(),
                OpportunityImplementationEvent.id.desc(),
            )
        )
    ).all()
    pages = {page.site_url_id: page for page in pages_b}
    result: dict[tuple[uuid.UUID, str], ExpectedChange] = {}
    for event in events:
        for key, expected in _event_expected_changes(event, pages):
            result.setdefault(key, expected)
    return result


def _event_expected_changes(
    event: OpportunityImplementationEvent, pages: dict[uuid.UUID, ChangePage]
) -> list[tuple[tuple[uuid.UUID, str], ExpectedChange]]:
    targets = {uuid.UUID(str(value)) for value in event.target_site_url_ids or []}
    matches: list[tuple[tuple[uuid.UUID, str], ExpectedChange]] = []
    for check in event.expected_checks or []:
        target_raw = check.get("target_site_url_id")
        if target_raw is None and len(targets) == 1:
            target_raw = next(iter(targets))
        if target_raw is None:
            continue
        target = uuid.UUID(str(target_raw))
        page = pages.get(target)
        if target not in targets or page is None:
            continue
        field, expected_value = _check_field(check)
        if field is None:
            continue
        actual = _expected_actual(check, page, field)
        if actual == expected_value:
            matches.append(
                (
                    (target, field),
                    ExpectedChange(event.id, page.fields.get(field)),
                )
            )
    return matches


def _expected_actual(check: dict[str, Any], page: ChangePage, field: str) -> Any:
    if check.get("kind") == "site_rule" and field in page.rules:
        return page.rules[field].outcome
    return page.fields.get(field)


def _source_hash(
    crawl_a: SiteCrawl | None, crawl_b: SiteCrawl, pages: list[ChangePage]
) -> str:
    material = {
        "crawl_a_id": str(crawl_a.id) if crawl_a else None,
        "crawl_b_id": str(crawl_b.id),
        "sources": sorted(
            (str(page.analysis_id), str(page.artifact_id)) for page in pages
        ),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _comparison_state(
    crawl_a: SiteCrawl | None,
    crawl_b: SiteCrawl,
    pages_a: list[ChangePage],
    pages_b: list[ChangePage],
) -> tuple[str, str | None]:
    if crawl_a is None:
        return CHANGE_STATE_UNAVAILABLE, CHANGE_REASON_NO_PREVIOUS_CRAWL
    if root_origin(crawl_a) != root_origin(crawl_b) or crawl_scope_hash(
        crawl_a
    ) != crawl_scope_hash(crawl_b):
        return CHANGE_STATE_NON_COMPARABLE, CHANGE_REASON_SCOPE_MISMATCH
    if (
        crawl_a.extractor_version != crawl_b.extractor_version
        or crawl_a.analyzer_version != crawl_b.analyzer_version
    ):
        return CHANGE_STATE_NON_COMPARABLE, CHANGE_REASON_VERSION_MISMATCH
    if not pages_a or not pages_b:
        return CHANGE_STATE_UNAVAILABLE, CHANGE_REASON_NO_USABLE_EVIDENCE
    return CHANGE_STATE_AVAILABLE, None


async def _existing_snapshot(
    session: AsyncSession,
    *,
    crawl_a: SiteCrawl | None,
    crawl_b: SiteCrawl,
    source_hash: str,
) -> SiteChangeSnapshot | None:
    return await session.scalar(
        select(SiteChangeSnapshot).where(
            SiteChangeSnapshot.workspace_id == crawl_b.workspace_id,
            SiteChangeSnapshot.crawl_a_id == (crawl_a.id if crawl_a else None),
            SiteChangeSnapshot.crawl_b_id == crawl_b.id,
            SiteChangeSnapshot.source_hash == source_hash,
            SiteChangeSnapshot.analyzer_version == CHANGE_ANALYZER_VERSION,
        )
    )


async def _previous_snapshot(
    session: AsyncSession, crawl_b: SiteCrawl
) -> SiteChangeSnapshot | None:
    return await session.scalar(
        select(SiteChangeSnapshot)
        .where(
            SiteChangeSnapshot.workspace_id == crawl_b.workspace_id,
            SiteChangeSnapshot.project_id == crawl_b.project_id,
        )
        .order_by(SiteChangeSnapshot.created_at.desc(), SiteChangeSnapshot.id.desc())
        .limit(1)
    )


async def _persist_snapshot(
    session: AsyncSession,
    *,
    crawl_a: SiteCrawl | None,
    crawl_b: SiteCrawl,
    pages_a: list[ChangePage],
    pages_b: list[ChangePage],
    source_hash: str,
    state: str,
    reason: str | None,
    complete_pair: bool,
    evidence_capped: bool,
    observations: tuple,
) -> SiteChangeSnapshot:
    all_pages = [*pages_a, *pages_b]
    previous = await _previous_snapshot(session, crawl_b)
    limitations = [] if complete_pair else ["partial_crawl_shared_urls_only"]
    if reason:
        limitations.append(reason)
    if evidence_capped:
        limitations.append("evidence_page_limit_reached")
    counts = Counter(item.change_class for item in observations)
    snapshot = SiteChangeSnapshot(
        workspace_id=crawl_b.workspace_id,
        project_id=crawl_b.project_id,
        crawl_a_id=crawl_a.id if crawl_a else None,
        crawl_b_id=crawl_b.id,
        supersedes_id=previous.id if previous else None,
        state=state,
        reason_code=reason,
        root_origin=root_origin(crawl_b),
        crawl_scope_hash=crawl_scope_hash(crawl_b),
        source_hash=source_hash,
        source_analysis_ids=sorted({page.analysis_id for page in all_pages}, key=str),
        source_artifact_ids=sorted({page.artifact_id for page in all_pages}, key=str),
        analyzer_version=CHANGE_ANALYZER_VERSION,
        page_analyzer_version=crawl_b.analyzer_version,
        extractor_version=crawl_b.extractor_version,
        complete_pair=complete_pair,
        coverage={
            "crawl_a_pages": len(pages_a),
            "crawl_b_pages": len(pages_b),
            "shared_pages": len(
                {page.site_url_id for page in pages_a}
                & {page.site_url_id for page in pages_b}
            ),
            "evidence_page_limit_reached": evidence_capped,
        },
        summary={"total": len(observations), "counts_by_class": dict(counts)},
        limitations=limitations,
    )
    session.add(snapshot)
    await session.flush()
    session.add_all(
        SiteChangeObservation(
            snapshot_id=snapshot.id,
            workspace_id=crawl_b.workspace_id,
            **item.__dict__,
        )
        for item in observations
    )
    await session.flush()
    return snapshot


async def build_change_snapshot(
    session: AsyncSession, *, crawl_b: SiteCrawl
) -> SiteChangeSnapshot:
    """Build or return the immutable latest-pair projection for one newer crawl."""
    crawl_a = await select_previous_comparable_crawl(session, crawl_b=crawl_b)
    pages_b, capped_b = await _pages(session, crawl_b)
    if crawl_a is not None:
        pages_a, capped_a = await _pages(session, crawl_a)
    else:
        pages_a, capped_a = [], False
    source_hash = _source_hash(crawl_a, crawl_b, [*pages_a, *pages_b])
    existing = await _existing_snapshot(
        session, crawl_a=crawl_a, crawl_b=crawl_b, source_hash=source_hash
    )
    if existing is not None:
        return existing
    state, reason = _comparison_state(crawl_a, crawl_b, pages_a, pages_b)
    evidence_capped = capped_a or capped_b
    complete_pair = bool(
        crawl_a and _complete(crawl_a) and _complete(crawl_b) and not evidence_capped
    )
    expected = (
        await _expected_changes(
            session, crawl_a=crawl_a, crawl_b=crawl_b, pages_b=pages_b
        )
        if crawl_a and state == CHANGE_STATE_AVAILABLE
        else {}
    )
    observations = (
        compare_crawls(pages_a, pages_b, complete_pair=complete_pair, expected=expected)
        if state == CHANGE_STATE_AVAILABLE
        else ()
    )
    return await _persist_snapshot(
        session,
        crawl_a=crawl_a,
        crawl_b=crawl_b,
        pages_a=pages_a,
        pages_b=pages_b,
        source_hash=source_hash,
        state=state,
        reason=reason,
        complete_pair=complete_pair,
        evidence_capped=evidence_capped,
        observations=observations,
    )


__all__ = [
    "build_change_snapshot",
    "crawl_scope_hash",
    "root_origin",
    "select_previous_comparable_crawl",
]
