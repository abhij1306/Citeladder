"""Pagination and DTO stages for the grouped Site Health issue catalog."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.site_health.normalization import (
    CursorScopeError,
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.domain.site_health.service.common import InvalidCursorError
from app.domain.site_health.service.presentation import (
    _SEVERITY_RANK,
    _iso,
    display_label_for,
)


class IssueGroupView(Protocol):
    group_id: uuid.UUID
    rule_id: str
    dimension: str
    category: str
    severity: str
    finding_class: str
    description: str
    remediation: str
    affected_url_count: int
    analyzer_version: str
    rule_version: str
    canonical_created_at: datetime


def issue_query_state(
    *,
    crawl_id: uuid.UUID,
    query: str | None,
    severity: str | None,
    category: str | None,
    dimension: str | None,
    rule: str | None,
    site_url_id: uuid.UUID | None,
    page_kind: str | None,
    finding_class: str,
    filter_clause: Callable[..., list],
) -> tuple[dict, list]:
    """Build the cursor fingerprint and persisted issue filter together."""
    filters = {
        "crawl_id": str(crawl_id),
        "query": (query or "").strip() or None,
        "severity": severity or None,
        "category": category or None,
        "dimension": dimension or None,
        "rule": rule or None,
        "site_url_id": str(site_url_id) if site_url_id else None,
        "page_kind": page_kind or None,
        "finding_class": finding_class,
    }
    clauses = filter_clause(
        crawl_id=crawl_id,
        query=query,
        severity=severity,
        category=category,
        dimension=dimension,
        rule=rule,
        site_url_id=site_url_id,
        page_kind=page_kind,
        finding_class=finding_class,
    )
    return filters, clauses


def page_issue_groups(
    groups: Sequence[IssueGroupView],
    *,
    limit: int,
    cursor: str | None,
    filters: dict,
) -> tuple[list[IssueGroupView], str | None]:
    """Apply the stable severity/rule/group keyset to a grouped window."""
    start = 0
    if cursor:
        try:
            rank_raw, rule_raw, id_raw = decode_keyset_cursor(
                cursor, scope="issues", filters=filters
            )
            cursor_key = (int(rank_raw), rule_raw, id_raw)
        except CursorScopeError as exc:
            raise InvalidCursorError(str(exc)) from exc
        except ValueError as exc:
            raise InvalidCursorError(str(exc)) from exc
        for idx, group in enumerate(groups):
            group_key = (
                _SEVERITY_RANK.get(group.severity, 99),
                group.rule_id,
                str(group.group_id),
            )
            if group_key > cursor_key:
                start = idx
                break
        else:
            start = len(groups)

    window = list(groups[start : start + limit + 1])
    if len(window) <= limit:
        return window, None
    window = window[:limit]
    last = window[-1]
    next_cursor = encode_keyset_cursor(
        scope="issues",
        filters=filters,
        sort_values=[
            _SEVERITY_RANK.get(last.severity, 99),
            last.rule_id,
            str(last.group_id),
        ],
    )
    return window, next_cursor


def issue_items(
    window: Sequence[IssueGroupView],
    *,
    crawl_id: uuid.UUID,
    page_kinds_by_rule: dict[str, list[str]],
) -> list[dict]:
    """Render grouped issue rows with an explicit stable group identity."""
    return [
        {
            "group_id": group.group_id,
            "crawl_id": crawl_id,
            "rule_id": group.rule_id,
            "page_kinds": page_kinds_by_rule.get(group.rule_id, []),
            "dimension": group.dimension,
            "category": group.category,
            "severity": group.severity,
            "finding_class": group.finding_class,
            "title": display_label_for(group.rule_id),
            "description": group.description,
            "remediation": group.remediation,
            "affected_url_count": group.affected_url_count,
            "analyzer_version": group.analyzer_version,
            "rule_version": group.rule_version,
            "created_at": _iso(group.canonical_created_at),
        }
        for group in window
    ]


async def issue_summary_for_filters(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    query: str | None,
    category: str | None,
    rule: str | None,
    site_url_id: uuid.UUID | None,
    page_kind: str | None,
    finding_class: str,
    filter_clause: Callable[..., list],
    summary: Callable[..., Awaitable[dict]],
) -> dict:
    """Compute filter-chip counts with severity/dimension filters removed."""
    common = {
        "crawl_id": crawl_id,
        "query": query,
        "severity": None,
        "category": category,
        "dimension": None,
        "rule": rule,
        "site_url_id": site_url_id,
        "page_kind": page_kind,
    }
    summary_clauses = filter_clause(**common, finding_class=finding_class)
    base_clauses = filter_clause(**common, finding_class=None)
    return await summary(
        session,
        clauses=summary_clauses,
        base_clauses=base_clauses,
    )
