# AI Referrals API DTOs — persisted projections only (invariant 7).
from __future__ import annotations

import uuid

from pydantic import BaseModel


class MetricSeriesPoint(BaseModel):
    """One dated point of a metric series (``None`` = unmeasured bucket)."""

    date: str
    value: float | None


def metric_series_points(raw: object) -> list[MetricSeriesPoint]:
    """Normalize a persisted series fragment into strict DTO points.

    Single owner of the snapshot-JSONB -> DTO read shape shared by the
    traffic + analytics read services (invariant 2): non-list fragments
    and non-dict entries degrade to nothing rather than failing the read.
    """
    points: list[MetricSeriesPoint] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        points.append(
            MetricSeriesPoint(
                date=str(entry.get("date") or ""), value=entry.get("value")
            )
        )
    return points


class AiReferralSourceRow(BaseModel):
    """One per-``ai_source`` referral breakdown row (window-level)."""

    ai_source: str
    sessions: int
    share: float | None


class AiReferralsResponse(BaseModel):
    """``GET /projects/{id}/ai-referrals`` — persisted referral measures.

    Served from the persisted ``AiReferralsSnapshot`` matching
    ``(window, granularity)``; an absent snapshot yields an empty payload
    (empty series and source breakdown), never a recomputation (invariant 7).
    """

    project_id: uuid.UUID
    window_start: str
    window_end: str
    granularity: str
    referral_volume: list[MetricSeriesPoint]
    referral_share: list[MetricSeriesPoint]
    sources: list[AiReferralSourceRow]
    analyzer_version: str
    formula_version: str
