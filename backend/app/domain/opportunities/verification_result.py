"""Comparable three-signal result for one implementation declaration."""

from __future__ import annotations

import json
import uuid
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.demand import DEMAND_SIGNAL_BRANDED_QUERY
from app.models.analysis import MetricSnapshot
from app.models.analytics import AiReferralsSnapshot
from app.models.audit import Audit, AuditEngineSnapshot, AuditPromptSnapshot
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.opportunity import OpportunityImplementationEvent, OpportunitySnapshot


def _state(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return "observed_zero" if value == 0 else "available"


def _leg(
    *,
    state: str,
    baseline_id=None,
    post_id=None,
    baseline=None,
    post=None,
    versions=None,
    limitations=None,
):
    return {
        "state": state,
        "baseline_source_ids": [str(baseline_id)] if baseline_id else [],
        "post_source_ids": [str(post_id)] if post_id else [],
        "baseline_value": baseline,
        "post_value": post,
        "delta": round(post - baseline, 4)
        if isinstance(baseline, (int, float)) and isinstance(post, (int, float))
        else None,
        "versions": versions or {},
        "limitations": limitations or [],
    }


async def _audit_identity(session: AsyncSession, audit: Audit) -> str:
    prompts = (
        await session.execute(
            select(
                AuditPromptSnapshot.text,
                AuditPromptSnapshot.cohort,
                AuditPromptSnapshot.buyer_stage,
                AuditPromptSnapshot.prompt_intent,
                AuditPromptSnapshot.intent,
            )
            .where(AuditPromptSnapshot.audit_id == audit.id)
            .order_by(AuditPromptSnapshot.prompt_index)
        )
    ).all()
    engines = (
        await session.execute(
            select(
                AuditEngineSnapshot.logical_engine,
                AuditEngineSnapshot.transport_provider,
                AuditEngineSnapshot.transport_model,
            )
            .where(AuditEngineSnapshot.audit_id == audit.id)
            .order_by(AuditEngineSnapshot.logical_engine)
        )
    ).all()
    identity = {
        "prompts": [tuple(row) for row in prompts],
        "engines": [tuple(row) for row in engines],
        "benchmark_mode": audit.benchmark_mode,
        "repetitions": audit.repetitions,
        "locale": (audit.configuration or {}).get("locale")
        or {
            "country_code": (audit.configuration or {}).get("country_code"),
            "language_code": (audit.configuration or {}).get("language_code"),
        },
        "retrieval": (audit.configuration or {}).get("retrieval_policy"),
    }
    return sha256(
        json.dumps(identity, sort_keys=True, default=str).encode()
    ).hexdigest()


async def _visibility_leg(
    session: AsyncSession,
    baseline: OpportunitySnapshot,
    post_audit_id: uuid.UUID | None,
) -> dict:
    if baseline.audit_id is None or post_audit_id is None:
        return _leg(
            state="not_run", limitations=["A comparable post-action audit has not run."]
        )
    before_audit = await session.get(Audit, baseline.audit_id)
    after_audit = await session.get(Audit, post_audit_id)
    if before_audit is None or after_audit is None:
        return _leg(
            state="unavailable", limitations=["Audit provenance is unavailable."]
        )
    if await _audit_identity(session, before_audit) != await _audit_identity(
        session, after_audit
    ):
        return _leg(
            state="non_comparable",
            baseline_id=before_audit.id,
            post_id=after_audit.id,
            limitations=[
                "Prompt, engine, model/retrieval, locale, or repetition identity "
                "changed."
            ],
        )
    before = await session.scalar(
        select(MetricSnapshot).where(MetricSnapshot.audit_id == before_audit.id)
    )
    after = await session.scalar(
        select(MetricSnapshot).where(MetricSnapshot.audit_id == after_audit.id)
    )
    if before is None or after is None:
        return _leg(
            state="unavailable",
            limitations=["Visibility metric snapshot is unavailable."],
        )
    versions = {
        "baseline_analyzer": before.analyzer_version,
        "post_analyzer": after.analyzer_version,
    }
    if before.visibility_score is None or after.visibility_score is None:
        return _leg(
            state="unavailable",
            baseline_id=before.id,
            post_id=after.id,
            versions=versions,
            limitations=["Visibility metric is unavailable."],
        )
    value = float(after.visibility_score)
    return _leg(
        state=_state(value),
        baseline_id=before.id,
        post_id=after.id,
        baseline=float(before.visibility_score),
        post=value,
        versions=versions,
    )


async def _referral_leg(
    session: AsyncSession, declaration: OpportunityImplementationEvent
) -> dict:
    before = await _referral_snapshot(session, declaration, after=False)
    after = await _referral_snapshot(session, declaration, after=True)
    if after is None:
        return _leg(
            state="not_run", limitations=["No post-action AI referral snapshot."]
        )
    if before is None:
        return _leg(
            state="unavailable",
            post_id=after.id,
            limitations=["No baseline AI referral snapshot."],
        )
    if not _referral_comparable(before, after):
        return _leg(
            state="non_comparable",
            baseline_id=before.id,
            post_id=after.id,
            limitations=["Referral windows or granularity differ."],
        )
    before_value = _ai_referral_value(before)
    after_value = _ai_referral_value(after)
    if not isinstance(before_value, (int, float)) or not isinstance(
        after_value, (int, float)
    ):
        return _leg(
            state="unavailable",
            baseline_id=before.id,
            post_id=after.id,
            limitations=["AI referral metric is unavailable."],
        )
    return _leg(
        state=_state(float(after_value)),
        baseline_id=before.id,
        post_id=after.id,
        baseline=float(before_value),
        post=float(after_value),
        versions={"analyzer": after.analyzer_version, "formula": after.formula_version},
    )


async def _referral_snapshot(session, declaration, *, after: bool):
    boundary = (
        AiReferralsSnapshot.created_at > declaration.declared_implemented_at
        if after
        else AiReferralsSnapshot.created_at <= declaration.declared_implemented_at
    )
    return await session.scalar(
        select(AiReferralsSnapshot)
        .where(
            AiReferralsSnapshot.workspace_id == declaration.workspace_id,
            AiReferralsSnapshot.project_id == declaration.project_id,
            boundary,
        )
        .order_by(AiReferralsSnapshot.created_at.desc())
        .limit(1)
    )


def _referral_comparable(before, after) -> bool:
    return before.granularity == after.granularity and (
        before.window_end - before.window_start
    ) == (after.window_end - after.window_start)


def _ai_referral_value(snapshot) -> object:
    metrics = snapshot.metrics or {}
    totals = metrics.get("totals") or {}
    return totals.get("ai_referrals", metrics.get("ai_referrals"))


async def _branded_value(
    session: AsyncSession, snapshot_id: uuid.UUID
) -> tuple[float, list[str], dict]:
    rows = list(
        (
            await session.scalars(
                select(DemandSignal).where(
                    DemandSignal.snapshot_id == snapshot_id,
                    DemandSignal.signal_type == DEMAND_SIGNAL_BRANDED_QUERY,
                )
            )
        ).all()
    )
    value = sum(float((row.metrics or {}).get("impressions") or 0) for row in rows)
    return (
        value,
        [str(row.id) for row in rows],
        {"analyzer": rows[0].analyzer_version, "formula": rows[0].formula_version}
        if rows
        else {},
    )


async def _demand_leg(
    session: AsyncSession,
    declaration: OpportunityImplementationEvent,
    baseline: OpportunitySnapshot,
) -> dict:
    if baseline.demand_snapshot_id is None:
        return _leg(
            state="unavailable", limitations=["No branded-demand baseline was frozen."]
        )
    after = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == declaration.workspace_id,
            DemandSnapshot.project_id == declaration.project_id,
            DemandSnapshot.created_at > declaration.declared_implemented_at,
        )
        .order_by(DemandSnapshot.created_at.desc())
        .limit(1)
    )
    if after is None:
        return _leg(
            state="not_run",
            baseline_id=baseline.demand_snapshot_id,
            limitations=["No post-action demand snapshot."],
        )
    before = await session.get(DemandSnapshot, baseline.demand_snapshot_id)
    if before is None:
        return _leg(
            state="unavailable", limitations=["Frozen demand baseline is unavailable."]
        )
    before_value, before_ids, _ = await _branded_value(session, before.id)
    after_value, after_ids, versions = await _branded_value(session, after.id)
    result = _leg(
        state=_state(after_value),
        baseline_id=before.id,
        post_id=after.id,
        baseline=before_value,
        post=after_value,
        versions=versions,
    )
    result["baseline_source_ids"].extend(before_ids)
    result["post_source_ids"].extend(after_ids)
    return result


def _gap_changes(before_keys: set, after_keys: set, latest) -> dict:
    """Before/after gap comparison, empty until a post-action snapshot exists.

    With no later snapshot there is no observation of the gaps at all, so
    the arrays stay empty rather than reporting every baseline gap as
    resolved against an absent "after" set.
    """
    if latest is None:
        return {
            "no_longer_observed": [],
            "persistent": [],
            "new": [],
            "state": "not_run",
        }
    return {
        "no_longer_observed": sorted(before_keys - after_keys),
        "persistent": sorted(before_keys & after_keys),
        "new": sorted(after_keys - before_keys),
        "state": "available",
    }


async def build_verification_result(
    session: AsyncSession,
    *,
    declaration: OpportunityImplementationEvent,
    post_audit_id: uuid.UUID | None,
) -> dict:
    baseline = await session.get(
        OpportunitySnapshot, declaration.opportunity_snapshot_id
    )
    if baseline is None:
        return {
            "state": "unavailable",
            "legs": {},
            "limitations": ["Frozen Opportunity snapshot is unavailable."],
        }
    latest = await session.scalar(
        select(OpportunitySnapshot)
        .where(
            OpportunitySnapshot.workspace_id == declaration.workspace_id,
            OpportunitySnapshot.project_id == declaration.project_id,
            OpportunitySnapshot.created_at > declaration.declared_implemented_at,
        )
        .order_by(OpportunitySnapshot.created_at.desc())
        .limit(1)
    )
    before_keys = set((baseline.source_mix or {}).get("gap_keys") or [])
    after_keys = (
        set((latest.source_mix or {}).get("gap_keys") or []) if latest else set()
    )
    overlaps = list(
        (
            await session.scalars(
                select(OpportunityImplementationEvent.id).where(
                    OpportunityImplementationEvent.workspace_id
                    == declaration.workspace_id,
                    OpportunityImplementationEvent.project_id == declaration.project_id,
                    OpportunityImplementationEvent.id != declaration.id,
                    OpportunityImplementationEvent.declared_implemented_at
                    >= declaration.declared_implemented_at,
                    OpportunityImplementationEvent.declared_implemented_at
                    <= (
                        latest.created_at
                        if latest
                        else declaration.declared_implemented_at
                    ),
                )
            )
        ).all()
    )
    legs = {
        "visibility": await _visibility_leg(session, baseline, post_audit_id),
        "ai_referral_traffic": await _referral_leg(session, declaration),
        "branded_search_demand": await _demand_leg(session, declaration, baseline),
    }
    return {
        "state": "available",
        "legs": legs,
        "gap_changes": _gap_changes(before_keys, after_keys, latest),
        "overlapping_action_ids": [str(item) for item in overlaps],
        "causality_notice": (
            "Later observations are not proof that this implementation caused the "
            "change."
        ),
    }
