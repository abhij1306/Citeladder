"""Bounded immutable guidance derived from persisted Opportunity evidence."""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.opportunities import (
    GUIDANCE_ENABLED_ENVIRONMENTS,
    GUIDANCE_GENERATOR_VERSION,
    GUIDANCE_HISTORY_DEFAULT_LIMIT,
    GUIDANCE_HISTORY_MAX_LIMIT,
    GUIDANCE_IDEMPOTENCY_KEY_MAX_LEN,
    GUIDANCE_MAX_EVIDENCE_KEYS,
    GUIDANCE_MAX_EVIDENCE_LIST_ITEMS,
    GUIDANCE_MAX_EVIDENCE_VALUE_CHARS,
    GUIDANCE_MAX_FINDINGS,
    GUIDANCE_MODEL,
    GUIDANCE_PROMPT_VERSION,
    GUIDANCE_PROVIDER,
)
from app.domain.opportunities.common import _OPPORTUNITY_NOT_FOUND, _iso
from app.domain.opportunities.errors import (
    OpportunityGuidanceIdempotencyConflictError,
    OpportunityGuidanceUnavailableError,
    OpportunityNotFoundError,
    OpportunityValidationError,
)
from app.domain.opportunities.projection import _target_label
from app.models.opportunity import Opportunity, OpportunityGuidance


def _guidance_enabled() -> bool:
    return str(settings.app_env or "").strip().lower() in GUIDANCE_ENABLED_ENVIRONMENTS


def _require_guidance_enabled() -> None:
    if not _guidance_enabled():
        raise OpportunityGuidanceUnavailableError(
            "Opportunity guidance is not available for this workspace"
        )


def _bounded_value(value: object, *, depth: int = 0) -> object:
    """Return a stable, JSON-safe, size-bounded evidence representation."""
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key)[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]: _bounded_value(
                child, depth=depth + 1
            )
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))[
                :GUIDANCE_MAX_EVIDENCE_KEYS
            ]
        }
    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(child, depth=depth + 1)
            for child in value[:GUIDANCE_MAX_EVIDENCE_LIST_ITEMS]
        ]
    if isinstance(value, str):
        return value[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]


def _guidance_input(row: Opportunity) -> dict:
    """Freeze only bounded, already persisted opportunity evidence."""
    return {
        "opportunity_id": str(row.id),
        "project_id": str(row.project_id),
        "rule_id": row.rule_id,
        "title": row.title or "",
        "severity": row.severity,
        "status": row.status,
        "target": {
            "key": row.target_key,
            "url": row.target_url,
            "theme": row.target_theme,
        },
        "evidence": _bounded_value(row.evidence or {}),
        "source_analysis_ids": sorted(
            str(value) for value in row.source_analysis_ids or []
        ),
        "source_issue_ids": sorted(str(value) for value in row.source_issue_ids or []),
        "source_metric_ids": sorted(
            str(value) for value in row.source_metric_ids or []
        ),
        "versions": {
            "analyzer": row.analyzer_version,
            "rule": row.rule_version,
            "formula": row.formula_version,
        },
    }


def _guidance_hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _guidance_findings(row: Opportunity, snapshot: dict) -> list[str]:
    evidence = snapshot.get("evidence") or {}
    findings = [f"{row.title or row.rule_id} is currently {row.status}."]
    target = _target_label(row)
    if target:
        findings.append(f"Affected target: {target}.")
    expected = (
        evidence.get("expected_schema_types") if isinstance(evidence, dict) else None
    )
    if expected:
        findings.append(f"Expected schema: {expected}.")
    return findings[:GUIDANCE_MAX_FINDINGS]


async def _guidance_opportunity(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> Opportunity:
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    return row


async def _existing_guidance(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    idempotency_key: str,
) -> OpportunityGuidance | None:
    return await session.scalar(
        select(OpportunityGuidance).where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
            OpportunityGuidance.idempotency_key == idempotency_key,
        )
    )


async def _commit_guidance(
    session: AsyncSession,
    *,
    guidance: OpportunityGuidance,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    idempotency_key: str,
    input_hash: str,
) -> tuple[OpportunityGuidance, bool]:
    session.add(guidance)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await _existing_guidance(
            session,
            workspace_id=workspace_id,
            opportunity_id=opportunity_id,
            idempotency_key=idempotency_key,
        )
        if winner is not None and winner.input_hash == input_hash:
            return winner, False
        if winner is not None:
            raise OpportunityGuidanceIdempotencyConflictError(
                "Idempotency-Key was already used for an earlier guidance input"
            ) from None
        raise
    await session.refresh(guidance)
    return guidance, True


async def create_guidance(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[OpportunityGuidance, bool]:
    """Persist one deterministic guidance version or replay its exact key."""
    _require_guidance_enabled()
    key = idempotency_key.strip()
    if not key or len(key) > GUIDANCE_IDEMPOTENCY_KEY_MAX_LEN:
        raise OpportunityValidationError("a bounded Idempotency-Key is required")
    row = await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    snapshot = _guidance_input(row)
    input_hash = _guidance_hash(snapshot)
    existing = await _existing_guidance(
        session,
        workspace_id=workspace_id,
        opportunity_id=opportunity_id,
        idempotency_key=key,
    )
    if existing is not None:
        if existing.input_hash == input_hash:
            return existing, False
        raise OpportunityGuidanceIdempotencyConflictError(
            "Idempotency-Key was already used for an earlier guidance input"
        )

    guidance = OpportunityGuidance(
        workspace_id=workspace_id,
        project_id=row.project_id,
        opportunity_id=row.id,
        idempotency_key=key,
        input_snapshot=snapshot,
        input_hash=input_hash,
        findings=_guidance_findings(row, snapshot),
        recommendations=[row.remediation or "Review the persisted evidence."],
        source_analysis_ids=list(row.source_analysis_ids or []),
        source_issue_ids=list(row.source_issue_ids or []),
        source_metric_ids=list(row.source_metric_ids or []),
        analyzer_version=row.analyzer_version,
        rule_version=row.rule_version,
        formula_version=row.formula_version,
        generator_version=GUIDANCE_GENERATOR_VERSION,
        prompt_version=GUIDANCE_PROMPT_VERSION,
        provider=GUIDANCE_PROVIDER,
        model=GUIDANCE_MODEL,
    )
    return await _commit_guidance(
        session,
        guidance=guidance,
        workspace_id=workspace_id,
        opportunity_id=opportunity_id,
        idempotency_key=key,
        input_hash=input_hash,
    )


async def get_latest_guidance(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> OpportunityGuidance | None:
    _require_guidance_enabled()
    await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    return await session.scalar(
        select(OpportunityGuidance)
        .where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
        )
        .order_by(OpportunityGuidance.created_at.desc(), OpportunityGuidance.id.desc())
        .limit(1)
    )


async def list_guidance_history(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    limit: int | None = None,
) -> list[OpportunityGuidance]:
    _require_guidance_enabled()
    await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    capped = max(
        1, min(limit or GUIDANCE_HISTORY_DEFAULT_LIMIT, GUIDANCE_HISTORY_MAX_LIMIT)
    )
    rows = await session.scalars(
        select(OpportunityGuidance)
        .where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
        )
        .order_by(OpportunityGuidance.created_at.desc(), OpportunityGuidance.id.desc())
        .limit(capped)
    )
    return list(rows.all())


def project_guidance(row: OpportunityGuidance) -> dict:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "input_hash": row.input_hash,
        "findings": list(row.findings or []),
        "recommendations": list(row.recommendations or []),
        "source_analysis_ids": list(row.source_analysis_ids or []),
        "source_issue_ids": list(row.source_issue_ids or []),
        "source_metric_ids": list(row.source_metric_ids or []),
        "analyzer_version": row.analyzer_version,
        "rule_version": row.rule_version,
        "formula_version": row.formula_version,
        "generator_version": row.generator_version,
        "prompt_version": row.prompt_version,
        "provider": row.provider,
        "model": row.model,
        "created_at": _iso(row.created_at),
    }
