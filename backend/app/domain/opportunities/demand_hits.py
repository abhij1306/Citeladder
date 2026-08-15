"""Approved Demand-signal mapping into the singular Opportunity owner."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.demand import DEMAND_OPPORTUNITY_SIGNAL_TYPES
from app.core.config.opportunities import (
    DEMAND_SIGNAL_GAP_FACTOR,
    DEMAND_SIGNAL_RULE_IDS,
)
from app.models.demand import DemandSignal, DemandSnapshot


def _targets(
    *, target_kind: str, target: str, resolved_page_url: str
) -> tuple[str | None, str | None]:
    if target_kind == "page":
        return target, None
    if target_kind == "query":
        return resolved_page_url or None, target
    return None, None


def _value_factor(priority_score: float | None) -> float:
    raw = float(priority_score or 0) / 100
    return max(0.01, min(1.0, raw))


def _hit(snapshot: DemandSnapshot, signal: DemandSignal) -> DetectorHit | None:
    evidence = dict(signal.evidence or {})
    target_kind = str(evidence.get("target_kind") or "")
    target = str(evidence.get("target") or "")
    if not target:
        return None
    target_url, target_theme = _targets(
        target_kind=target_kind,
        target=target,
        resolved_page_url=str(evidence.get("resolved_page_url") or ""),
    )
    return DetectorHit(
        rule_id=DEMAND_SIGNAL_RULE_IDS[signal.signal_type],
        target_key=f"demand:{signal.identity_hash}",
        target_prompt_id=None,
        target_url=target_url,
        target_theme=target_theme,
        evidence={
            "demand_snapshot_id": str(snapshot.id),
            "demand_signal_id": str(signal.id),
            "signal_type": signal.signal_type,
            "metrics": dict(signal.metrics or {}),
            "coverage": dict(signal.coverage or {}),
            "limitations": list(signal.limitations or []),
        },
        source_analysis_ids=(),
        source_issue_ids=(),
        source_metric_ids=tuple(evidence.get("source_metric_row_ids") or []),
        value_factor=_value_factor(signal.priority_score),
        gap_factor=DEMAND_SIGNAL_GAP_FACTOR,
    )


async def load_demand_hits(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[DemandSnapshot | None, list[DetectorHit]]:
    snapshot = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, []
    signals = list(
        (
            await session.scalars(
                select(DemandSignal)
                .where(
                    DemandSignal.workspace_id == workspace_id,
                    DemandSignal.project_id == project_id,
                    DemandSignal.snapshot_id == snapshot.id,
                    DemandSignal.signal_type.in_(DEMAND_OPPORTUNITY_SIGNAL_TYPES),
                    DemandSignal.state == "active",
                )
                .order_by(DemandSignal.identity_hash, DemandSignal.id)
            )
        ).all()
    )
    return snapshot, [hit for signal in signals if (hit := _hit(snapshot, signal))]
