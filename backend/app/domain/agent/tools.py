"""Typed, bounded adapters over existing Site, Content, Demand, and Audit owners."""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.agent.gateway import ModelGateway
from app.core.config.agent import (
    AGENT_TOOL_RESULT_MAX_CHARS,
    AGENT_TOOL_RESULT_STRING_MAX_CHARS,
    TOOL_KIND_AUTOMATIC,
    TOOL_KIND_RUN_AUDIT,
    TOOL_KIND_SAVE_CONTENT,
    AgentToolKind,
)
from app.domain.audits.schedule_schemas import AuditScheduleCreate
from app.domain.audits.schedule_service import create_schedule, list_schedules
from app.domain.content.intelligence import create_faq_brief
from app.domain.content.service import enqueue_generation
from app.domain.prompts.generation import (
    generate_prompts,
    validate_generation_request,
)
from app.domain.prompts.schemas import PromptGenerateRequest
from app.models.content import ContentStrategySnapshot
from app.models.demand import DemandSnapshot
from app.models.opportunity import Opportunity
from app.models.site_health import SiteHealthSnapshot

TOOL_VERSION: Final = "1.0.0"
MAX_TOOL_RESULT_ITEMS: Final = 50
MAX_ROADMAP_ITEMS: Final = 10
_SENSITIVE_KEY_PARTS: Final = frozenset(
    {
        "authorization",
        "password",
        "secret",
    }
)
_SENSITIVE_KEYS: Final = frozenset(
    {"access_token", "api_key", "credential", "oauth", "refresh_token", "token"}
)
_SENSITIVE_KEY_COMPOUNDS: Final = (
    frozenset({"access", "token"}),
    frozenset({"api", "key"}),
    frozenset({"refresh", "token"}),
)


@dataclass(frozen=True, slots=True)
class AgentToolDefinition:
    name: str
    domain: str
    kind: AgentToolKind
    description: str
    idempotent: bool = True
    external_effect: bool = False
    maximum_result_items: int = MAX_TOOL_RESULT_ITEMS

    @property
    def version(self) -> str:
        return TOOL_VERSION


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    session: AsyncSession
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    idempotency_key: str
    gateway: ModelGateway | None = None


ToolExecutor = Callable[
    [ToolExecutionContext, dict[str, Any]], Awaitable[dict[str, Any]]
]


TOOL_DEFINITIONS: Final[dict[str, AgentToolDefinition]] = {
    item.name: item
    for item in (
        AgentToolDefinition(
            "site.read_snapshot",
            "site",
            TOOL_KIND_AUTOMATIC,
            "Read the latest persisted Site snapshot.",
        ),
        AgentToolDefinition(
            "site.compare_snapshots",
            "site",
            TOOL_KIND_AUTOMATIC,
            "Read one frozen compatible Site comparison.",
        ),
        AgentToolDefinition(
            "content.read_strategy",
            "content",
            TOOL_KIND_AUTOMATIC,
            "Read the latest persisted Content strategy.",
        ),
        AgentToolDefinition(
            "content.create_brief",
            "content",
            TOOL_KIND_AUTOMATIC,
            "Build an immutable brief from an eligible gap.",
        ),
        AgentToolDefinition(
            "content.generate_draft",
            "content",
            TOOL_KIND_SAVE_CONTENT,
            "Queue brief-driven content generation.",
        ),
        AgentToolDefinition(
            "demand.read_snapshot",
            "demand",
            TOOL_KIND_AUTOMATIC,
            "Read the latest persisted Demand snapshot.",
        ),
        AgentToolDefinition(
            "demand.compare_snapshots",
            "demand",
            TOOL_KIND_AUTOMATIC,
            "Read one frozen Demand comparison.",
        ),
        AgentToolDefinition(
            "demand.create_prompt_candidates",
            "demand",
            TOOL_KIND_AUTOMATIC,
            "Create bounded grounded prompt candidates.",
        ),
        AgentToolDefinition(
            "opportunities.read_ranked",
            "opportunities",
            TOOL_KIND_AUTOMATIC,
            "Read deterministic opportunity priority order.",
            maximum_result_items=MAX_ROADMAP_ITEMS,
        ),
        AgentToolDefinition(
            "audits.read_schedules",
            "audits",
            TOOL_KIND_AUTOMATIC,
            "Read persisted measurement schedules.",
        ),
        AgentToolDefinition(
            "audits.schedule",
            "audits",
            TOOL_KIND_RUN_AUDIT,
            "Create a recurring answer-engine audit schedule.",
            external_effect=True,
        ),
    )
}


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "version": item.version,
            "domain": item.domain,
            "kind": item.kind,
            "description": item.description,
            "idempotent": item.idempotent,
            "external_effect": item.external_effect,
            "maximum_result_items": item.maximum_result_items,
        }
        for item in TOOL_DEFINITIONS.values()
    ]


def validate_automatic_tools() -> None:
    offenders = [
        item.name
        for item in TOOL_DEFINITIONS.values()
        if item.kind == TOOL_KIND_AUTOMATIC and item.external_effect
    ]
    if offenders:
        raise RuntimeError(f"automatic tools cannot have external effects: {offenders}")


async def execute_tool(
    name: str, context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    definition = TOOL_DEFINITIONS.get(name)
    executor = _EXECUTORS.get(name)
    if definition is None or executor is None:
        raise ValueError(f"unknown agent tool: {name}")
    result = await executor(context, payload)
    return _bounded_result(result, maximum_items=definition.maximum_result_items)


async def _site_snapshot(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    snapshot_id = _optional_uuid(payload.get("snapshot_id"))
    query = select(SiteHealthSnapshot).where(
        SiteHealthSnapshot.workspace_id == context.workspace_id,
        SiteHealthSnapshot.project_id == context.project_id,
    )
    if snapshot_id is not None:
        query = query.where(SiteHealthSnapshot.id == snapshot_id)
    row = await context.session.scalar(
        query.order_by(
            SiteHealthSnapshot.created_at.desc(), SiteHealthSnapshot.id.desc()
        ).limit(1)
    )
    if row is None:
        return {
            "state": "unavailable",
            "reason": "no_site_snapshot",
            "artifact_refs": [],
        }
    return {
        "state": "available",
        "snapshot_id": str(row.id),
        "crawl_id": str(row.crawl_id),
        "scores": {
            "technical": row.technical_score,
            "aeo": row.aeo_score,
            "overall": row.overall_score,
        },
        "coverage": {
            "selected_urls": row.selected_url_count,
            "analyzed_urls": row.analyzed_url_count,
        },
        "versions": {
            "analyzer": row.analyzer_version,
            "scoring": row.scoring_version,
        },
        "artifact_refs": [{"kind": "site_snapshot", "id": str(row.id)}],
    }


async def _site_comparison(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    result = await _site_snapshot(context, payload)
    return {
        "state": "available" if result.get("comparison") is not None else "unavailable",
        "snapshot_id": result.get("snapshot_id"),
        "comparison": result.get("comparison"),
        "reason": "no_compatible_prior_snapshot"
        if result.get("comparison") is None
        else "",
        "artifact_refs": result.get("artifact_refs", []),
    }


async def _content_strategy(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    row = await context.session.scalar(
        select(ContentStrategySnapshot)
        .where(
            ContentStrategySnapshot.workspace_id == context.workspace_id,
            ContentStrategySnapshot.project_id == context.project_id,
        )
        .order_by(
            ContentStrategySnapshot.created_at.desc(), ContentStrategySnapshot.id.desc()
        )
        .limit(1)
    )
    if row is None:
        return {
            "state": "unavailable",
            "reason": "no_content_strategy",
            "artifact_refs": [],
        }
    return {
        "state": "available",
        "strategy_id": str(row.id),
        "site_snapshot_id": str(row.site_snapshot_id),
        "demand_snapshot_id": str(row.demand_snapshot_id)
        if row.demand_snapshot_id
        else None,
        "priorities": row.priorities,
        "program": row.program,
        "coverage": row.coverage,
        "limitations": row.limitations,
        "artifact_refs": [{"kind": "content_strategy", "id": str(row.id)}],
    }


async def _create_brief(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    row, created = await create_faq_brief(
        context.session,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        question_id=_required_string(payload, "question_id"),
        kind=str(payload.get("kind") or "faq"),
        target_url=str(payload.get("target_url") or ""),
        title=str(payload.get("title") or ""),
    )
    return {
        "state": "created" if created else "existing",
        "brief_id": str(row.id),
        "kind": row.kind,
        "title": row.title,
        "evidence_hash": row.evidence_hash,
        "artifact_refs": [{"kind": "content_brief", "id": str(row.id)}],
    }


async def _generate_draft(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    brief_id = _required_uuid(payload, "brief_id")
    row, created = await enqueue_generation(
        context.session,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        prompt="brief-driven",
        output_type="website_page",
        website_context_enabled=True,
        idempotency_key=context.idempotency_key,
        skill_id=str(payload.get("skill_id") or "faq"),
        brief_id=brief_id,
    )
    return {
        "state": "queued" if created else row.status,
        "generation_id": str(row.id),
        "brief_id": str(brief_id),
        "child_task": {"kind": "content_generation", "id": str(row.id)},
        "artifact_refs": [{"kind": "content_generation", "id": str(row.id)}],
    }


async def _demand_snapshot(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    snapshot_id = _optional_uuid(payload.get("snapshot_id"))
    query = select(DemandSnapshot).where(
        DemandSnapshot.workspace_id == context.workspace_id,
        DemandSnapshot.project_id == context.project_id,
    )
    if snapshot_id is not None:
        query = query.where(DemandSnapshot.id == snapshot_id)
    row = await context.session.scalar(
        query.order_by(
            DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc()
        ).limit(1)
    )
    if row is None:
        return {
            "state": "unavailable",
            "reason": "no_demand_snapshot",
            "artifact_refs": [],
        }
    return {
        "state": "available",
        "snapshot_id": str(row.id),
        "window": {
            "start": row.window_start.isoformat(),
            "end": row.window_end.isoformat(),
        },
        "summary": row.summary,
        "coverage": row.coverage,
        "comparison": row.comparison,
        "source_artifact_ids": row.source_artifact_ids,
        "source_metric_row_ids": row.source_metric_row_ids,
        "source_audit_ids": row.source_audit_ids,
        "artifact_refs": [{"kind": "demand_snapshot", "id": str(row.id)}],
    }


async def _demand_comparison(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    result = await _demand_snapshot(context, payload)
    return {
        "state": "available" if result.get("comparison") is not None else "unavailable",
        "snapshot_id": result.get("snapshot_id"),
        "comparison": result.get("comparison"),
        "reason": "no_prior_demand_snapshot"
        if result.get("comparison") is None
        else "",
        "artifact_refs": result.get("artifact_refs", []),
    }


async def _ranked_opportunities(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    rows = list(
        (
            await context.session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.workspace_id == context.workspace_id,
                    Opportunity.project_id == context.project_id,
                    Opportunity.superseded_at.is_(None),
                )
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.asc())
                .limit(MAX_ROADMAP_ITEMS + 1)
            )
        ).all()
    )
    emitted = rows[:MAX_ROADMAP_ITEMS]
    items = [
        {
            "id": str(row.id),
            "rank": index,
            "priority_score": row.priority_score,
            "severity": row.severity,
            "type": row.opportunity_type,
            "title": row.title,
            "remediation": row.remediation,
            "target_key": row.target_key,
            "target_url": row.target_url,
        }
        for index, row in enumerate(emitted, start=1)
    ]
    return {
        "state": "available" if items else "unavailable",
        "ordering": "priority_score_desc_then_id",
        "items": items,
        "truncated": len(rows) > MAX_ROADMAP_ITEMS,
        "artifact_refs": [{"kind": "opportunity", "id": item["id"]} for item in items],
    }


async def _read_schedules(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    rows = await list_schedules(
        context.session,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
    )
    return {
        "state": "available" if rows else "unavailable",
        "items": [
            {
                "id": str(row.id),
                "cadence": row.cadence,
                "enabled": row.enabled,
                "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
                "engines": row.engines,
            }
            for row in rows[:MAX_TOOL_RESULT_ITEMS]
        ],
        "artifact_refs": [
            {"kind": "audit_schedule", "id": str(row.id)} for row in rows
        ],
    }


async def _schedule_audit(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    schedule_payload = TypeAdapter(AuditScheduleCreate).validate_python(
        payload.get("schedule") or payload
    )
    row = await create_schedule(
        context.session,
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        payload=schedule_payload,
    )
    return {
        "state": "scheduled",
        "schedule_id": str(row.id),
        "next_run_at": row.next_run_at.isoformat() if row.next_run_at else None,
        "artifact_refs": [{"kind": "audit_schedule", "id": str(row.id)}],
    }


async def _prompt_candidates(
    context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    if context.gateway is None:
        raise ValueError("a configured model gateway is required")
    prompt_set_id = _required_uuid(payload, "prompt_set_id")
    request = PromptGenerateRequest.model_validate(
        {
            "count": payload.get("count", 10),
            "topic_id": payload.get("topic_id"),
            "intents": payload.get("intents", []),
            "cohort": payload.get("cohort", "core"),
        }
    )
    prompt_set = await validate_generation_request(
        context.session,
        workspace_id=context.workspace_id,
        prompt_set_id=prompt_set_id,
        payload=request,
    )
    if prompt_set.project_id != context.project_id:
        raise ValueError("prompt set is outside the authorized project")
    generated, topics, dropped = await generate_prompts(
        context.session,
        workspace_id=context.workspace_id,
        prompt_set_id=prompt_set_id,
        payload=request,
        agent=context.gateway,
        prompt_set=prompt_set,
    )
    return {
        "state": "created",
        "prompt_set_id": str(prompt_set_id),
        "prompt_ids": [str(row.id) for row in generated],
        "topic_ids": [str(row.id) for row in topics],
        "dropped_duplicates": dropped,
        "artifact_refs": [{"kind": "prompt", "id": str(row.id)} for row in generated],
    }


def _optional_uuid(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return uuid.UUID(str(value))


def _required_uuid(payload: dict[str, Any], key: str) -> uuid.UUID:
    value = _optional_uuid(payload.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _bounded_result(value: dict[str, Any], *, maximum_items: int) -> dict[str, Any]:
    bounded = _bounded_top_level_items(value, maximum_items)
    sanitized = _sanitize(bounded, maximum_items=maximum_items)
    if not isinstance(sanitized, dict):
        return {"state": "truncated", "reason": "invalid_tool_result"}
    if _serialized_chars(sanitized) <= AGENT_TOOL_RESULT_MAX_CHARS:
        return sanitized
    return _budget_fallback(sanitized)


def _bounded_top_level_items(
    value: dict[str, Any], maximum_items: int
) -> dict[str, Any]:
    bounded = dict(value)
    items = bounded.get("items")
    if isinstance(items, list) and len(items) > maximum_items:
        bounded["items"] = items[:maximum_items]
        bounded["truncated"] = True
    return bounded


def _budget_fallback(sanitized: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "state": sanitized.get("state", "truncated"),
        "truncated": True,
        "reason": "tool_result_budget",
        "artifact_refs": list(sanitized.get("artifact_refs", [])),
    }
    while (
        _serialized_chars(result) > AGENT_TOOL_RESULT_MAX_CHARS
        and result["artifact_refs"]
    ):
        result["artifact_refs"] = result["artifact_refs"][:-1]
    return result


def _sanitize(value: Any, *, maximum_items: int, depth: int = 0) -> Any:
    if depth > 8:
        return "[bounded]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            result[str(key)] = (
                "[redacted]"
                if _is_sensitive_key(key)
                else _sanitize(item, maximum_items=maximum_items, depth=depth + 1)
            )
        return result
    if isinstance(value, list):
        return [
            _sanitize(item, maximum_items=maximum_items, depth=depth + 1)
            for item in value[:maximum_items]
        ]
    if isinstance(value, str):
        return value[:AGENT_TOOL_RESULT_STRING_MAX_CHARS]
    return value


def _is_sensitive_key(key: object) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(key)).casefold()
    key_parts = frozenset(part for part in re.split(r"[^a-z0-9]+", normalized) if part)
    return (
        normalized in _SENSITIVE_KEYS
        or bool(key_parts & _SENSITIVE_KEY_PARTS)
        or any(compound <= key_parts for compound in _SENSITIVE_KEY_COMPOUNDS)
    )


def _serialized_chars(value: object) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str))


_EXECUTORS: Final[dict[str, ToolExecutor]] = {
    "site.read_snapshot": _site_snapshot,
    "site.compare_snapshots": _site_comparison,
    "content.read_strategy": _content_strategy,
    "content.create_brief": _create_brief,
    "content.generate_draft": _generate_draft,
    "demand.read_snapshot": _demand_snapshot,
    "demand.compare_snapshots": _demand_comparison,
    "demand.create_prompt_candidates": _prompt_candidates,
    "opportunities.read_ranked": _ranked_opportunities,
    "audits.read_schedules": _read_schedules,
    "audits.schedule": _schedule_audit,
}


validate_automatic_tools()
