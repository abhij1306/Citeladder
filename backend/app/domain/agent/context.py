"""Authorized, bounded, inspectable context assembly for Growth Agent runs."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.agent import (
    AGENT_CONTEXT_EXCERPT_MAX_CHARS,
    AGENT_CONTEXT_MAX_CHARS,
    AGENT_CONTEXT_MAX_ITEMS,
    AGENT_CONTEXT_POLICY_VERSION,
    AGENT_CONTEXT_SECTION_MAX_CHARS,
)
from app.models.content import ContentStrategySnapshot, TaskContextPackage
from app.models.demand import DemandSnapshot
from app.models.knowledge import Correction
from app.models.opportunity import Opportunity
from app.models.site_health import SiteHealthSnapshot

_REDACTED_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "client_secret",
        "credential",
        "oauth",
        "password",
        "refresh_token",
        "secret",
        "token",
    }
)
_TEXT_SECRET_PATTERN = re.compile(
    rf"(?i)[\"']?\b({'|'.join(sorted(_REDACTED_KEYS, key=len, reverse=True))})\b"
    rf"[\"']?\s*[:=]\s*(?:[\"'][^\"']*[\"']|[^,;\r\n]+)"
)


async def build_agent_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    task_type: str,
    resource_scope: dict[str, Any],
) -> TaskContextPackage:
    site = await _latest(session, SiteHealthSnapshot, workspace_id, project_id)
    content = await _latest(session, ContentStrategySnapshot, workspace_id, project_id)
    demand = await _latest(session, DemandSnapshot, workspace_id, project_id)
    corrections = list(
        (
            await session.scalars(
                select(Correction)
                .where(
                    Correction.workspace_id == workspace_id,
                    Correction.project_id == project_id,
                    Correction.state == "active",
                )
                .order_by(Correction.created_at.desc(), Correction.id.desc())
                .limit(AGENT_CONTEXT_MAX_ITEMS)
            )
        ).all()
    )
    opportunities = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.project_id == project_id,
                    Opportunity.superseded_at.is_(None),
                )
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.asc())
                .limit(AGENT_CONTEXT_MAX_ITEMS)
            )
        ).all()
    )
    rendered = _rendered_context(
        task_type=task_type,
        resource_scope=resource_scope,
        site=site,
        content=content,
        demand=demand,
        corrections=corrections,
        opportunities=opportunities,
    )
    rendered, truncations = _enforce_budgets(rendered)
    manifest = _manifest(
        site=site,
        content=content,
        demand=demand,
        corrections=corrections,
        opportunities=opportunities,
        truncations=truncations,
    )
    omissions = _omissions(
        site=site, content=content, demand=demand, truncations=truncations
    )
    canonical = json.dumps(
        {"manifest": manifest, "rendered_context": rendered, "omissions": omissions},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    package = TaskContextPackage(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        project_id=project_id,
        brief_id=None,
        task_type=task_type,
        manifest=manifest,
        rendered_context=rendered,
        omissions=omissions,
        selection_policy_version=AGENT_CONTEXT_POLICY_VERSION,
        manifest_hash=hashlib.sha256(canonical.encode()).hexdigest(),
        char_count=len(canonical),
    )
    session.add(package)
    await session.flush()
    return package


async def _latest(
    session: AsyncSession, model, workspace_id: uuid.UUID, project_id: uuid.UUID
):
    return await session.scalar(
        select(model)
        .where(model.workspace_id == workspace_id, model.project_id == project_id)
        .order_by(model.created_at.desc(), model.id.desc())
        .limit(1)
    )


def _rendered_context(
    *,
    task_type: str,
    resource_scope: dict[str, Any],
    site: SiteHealthSnapshot | None,
    content: ContentStrategySnapshot | None,
    demand: DemandSnapshot | None,
    corrections: list[Correction],
    opportunities: list[Opportunity],
) -> dict[str, Any]:
    site_intelligence = _redact(site.intelligence or {}) if site else None
    return {
        "task": {"type": task_type, "scope": _redact(resource_scope)},
        "corrections": [
            {
                "id": str(row.id),
                "target_kind": row.target_kind,
                "target_ref": _redact(row.target_ref),
                "corrected_value": _redact(row.corrected_value),
                "effective_scope": row.effective_scope,
                "reason": _redacted_text(row.reason),
            }
            for row in corrections
        ],
        "site": (
            {
                "snapshot_id": str(site.id),
                "scores": {
                    "technical": site.technical_score,
                    "aeo": site.aeo_score,
                    "overall": site.overall_score,
                },
                "coverage": {
                    "selected_urls": site.selected_url_count,
                    "analyzed_urls": site.analyzed_url_count,
                },
                "intelligence": site_intelligence,
                "comparison": _redact(site.comparison),
            }
            if site
            else None
        ),
        "content": (
            {
                "strategy_id": str(content.id),
                "priorities": _redact(content.priorities),
                "program": _redact(content.program),
                "coverage": _redact(content.coverage),
                "limitations": _redact(content.limitations),
            }
            if content
            else None
        ),
        "demand": (
            {
                "snapshot_id": str(demand.id),
                "window": [
                    demand.window_start.isoformat(),
                    demand.window_end.isoformat(),
                ],
                "summary": _redact(demand.summary),
                "coverage": _redact(demand.coverage),
                "comparison": _redact(demand.comparison),
            }
            if demand
            else None
        ),
        "opportunities": [
            {
                "id": str(row.id),
                "rank": rank,
                "priority_score": row.priority_score,
                "severity": _redacted_text(row.severity),
                "type": _redacted_text(row.opportunity_type),
                "title": _redacted_text(row.title),
                "remediation": _redacted_text(row.remediation),
                "target_key": _redacted_text(row.target_key),
            }
            for rank, row in enumerate(opportunities, start=1)
        ],
    }


def _manifest(
    *,
    site: SiteHealthSnapshot | None,
    content: ContentStrategySnapshot | None,
    demand: DemandSnapshot | None,
    corrections: list[Correction],
    opportunities: list[Opportunity],
    truncations: dict[str, int],
) -> dict[str, Any]:
    pack = ((site.intelligence or {}).get("pack_manifest") or {}) if site else {}
    selected = {
        "site_snapshot_ids": [str(site.id)] if site else [],
        "content_strategy_ids": [str(content.id)] if content else [],
        "demand_snapshot_ids": [str(demand.id)] if demand else [],
        "correction_ids": [str(row.id) for row in corrections],
        "opportunity_ids": [str(row.id) for row in opportunities],
    }
    return {
        "policy_version": AGENT_CONTEXT_POLICY_VERSION,
        "industry_pack": {
            "id": str(pack.get("pack_id") or ""),
            "version": str(pack.get("pack_version") or ""),
            "content_hash": str(pack.get("content_hash") or ""),
        },
        "selected": selected,
        "quality": {
            "eligible_count": sum(len(value) for value in selected.values()),
            "selected_count": sum(len(value) for value in selected.values()),
            "omitted_count": sum(truncations.values()),
            "stale_count": 0,
            "contradictory_count": _contradiction_count(site),
            "correction_count": len(corrections),
            "derived_count": len(opportunities)
            + int(site is not None)
            + int(demand is not None),
            "truncation_by_section": truncations,
            "retrieval_version": "structured-v1",
            "reranker_version": "none",
        },
    }


def _contradiction_count(site: SiteHealthSnapshot | None) -> int:
    if site is None or not isinstance(site.intelligence, dict):
        return 0
    knowledge = site.intelligence.get("knowledge")
    if not isinstance(knowledge, dict):
        return 0
    value = knowledge.get("contradiction_count", 0)
    return value if isinstance(value, int) and value >= 0 else 0


def _omissions(
    *,
    site: SiteHealthSnapshot | None,
    content: ContentStrategySnapshot | None,
    demand: DemandSnapshot | None,
    truncations: dict[str, int],
) -> list[dict[str, Any]]:
    omissions: list[dict[str, Any]] = []
    for section, row in (("site", site), ("content", content), ("demand", demand)):
        if row is None:
            omissions.append({"section": section, "reason": "unavailable", "count": 1})
    omissions.extend(
        {"section": section, "reason": "budget", "count": count}
        for section, count in truncations.items()
        if count
    )
    return omissions


def _enforce_budgets(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    bounded: dict[str, Any] = {}
    truncations: dict[str, int] = {}
    sections = list(value.items())
    for index, (section, section_value) in enumerate(sections):
        if _serialized_size(bounded) >= AGENT_CONTEXT_MAX_CHARS:
            _record_remaining_truncations(truncations, sections[index:])
            break
        section_size = len(
            json.dumps(section_value, sort_keys=True, ensure_ascii=False)
        )
        candidate = {**bounded, section: section_value}
        if (
            section_size <= AGENT_CONTEXT_SECTION_MAX_CHARS
            and _serialized_size(candidate) <= AGENT_CONTEXT_MAX_CHARS
        ):
            bounded = candidate
            truncations[section] = 0
            continue
        if not isinstance(section_value, list):
            truncations[section] = 1
            continue
        _add_bounded_list(bounded, truncations, section, section_value)
    return bounded, truncations


def _add_bounded_list(
    bounded: dict[str, Any],
    truncations: dict[str, int],
    section: str,
    values: list[Any],
) -> None:
    kept = _bounded_list_section(bounded, section, values)
    if kept or not values:
        bounded[section] = kept
    truncations[section] = len(values) - len(kept)


def _bounded_list_section(
    bounded: dict[str, Any], section: str, values: list[Any]
) -> list[Any]:
    kept: list[Any] = []
    for item in values:
        next_items = [*kept, item]
        section_fits = (
            len(json.dumps(next_items, ensure_ascii=False))
            <= AGENT_CONTEXT_SECTION_MAX_CHARS
        )
        context_fits = (
            _serialized_size({**bounded, section: next_items})
            <= AGENT_CONTEXT_MAX_CHARS
        )
        if not section_fits or not context_fits:
            break
        kept = next_items
    return kept


def _serialized_size(value: dict[str, Any]) -> int:
    return len(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    )


def _record_remaining_truncations(
    truncations: dict[str, int], sections: list[tuple[str, Any]]
) -> None:
    for section, value in sections:
        truncations[section] = len(value) if isinstance(value, list) else 1


def _redact(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[bounded]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).casefold()
            if any(token in normalized for token in _REDACTED_KEYS):
                result[str(key)] = "[redacted]"
            else:
                result[str(key)] = _redact(item, depth=depth + 1)
        return result
    if isinstance(value, list):
        return [
            _redact(item, depth=depth + 1) for item in value[:AGENT_CONTEXT_MAX_ITEMS]
        ]
    if isinstance(value, str):
        return value[:AGENT_CONTEXT_EXCERPT_MAX_CHARS]
    return value


def _redacted_text(value: object) -> str:
    redacted = _TEXT_SECRET_PATTERN.sub(r"\1=[redacted]", str(value))
    return redacted[:AGENT_CONTEXT_EXCERPT_MAX_CHARS]
