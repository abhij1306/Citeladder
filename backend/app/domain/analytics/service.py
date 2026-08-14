# AI Referrals read service. It serves only persisted snapshot rows and never
# recomputes or calls a provider at read time.
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.analytics import (
    AI_REFERRAL_ANALYZER_VERSION,
    AI_REFERRAL_FORMULA_VERSION,
    ANALYTICS_DEFAULT_GRANULARITY,
    ANALYTICS_MAX_WINDOW_DAYS,
    ANALYTICS_SNAPSHOT_GRANULARITIES,
)
from app.domain.analytics.schemas import (
    AiReferralSourceRow,
    AiReferralsResponse,
    metric_series_points,
)
from app.models.analytics import AiReferralsSnapshot


class AiReferralsQueryError(ValueError):
    """Raised for an invalid AI Referrals granularity or date range.

    The API layer maps this to HTTP 422; it is never a not-found condition.
    Mirrors the trends surface's ``TrendQueryError`` contract without
    reusing that trends-specific class (one owner per surface).
    """


def _validate_window(from_date: date | None, to_date: date | None) -> None:
    """The from/to contract: both-or-neither, ordered, within the max span."""
    if (from_date is None) != (to_date is None):
        raise AiReferralsQueryError("'from' and 'to' must be supplied together")
    if from_date is None or to_date is None:
        return
    if to_date < from_date:
        raise AiReferralsQueryError("'to' must not be before 'from'")
    if (to_date - from_date).days + 1 > ANALYTICS_MAX_WINDOW_DAYS:
        raise AiReferralsQueryError(
            f"window exceeds ANALYTICS_MAX_WINDOW_DAYS ({ANALYTICS_MAX_WINDOW_DAYS})"
        )


def _validate_granularity(granularity: str) -> str:
    granularity = granularity or ANALYTICS_DEFAULT_GRANULARITY
    if granularity not in ANALYTICS_SNAPSHOT_GRANULARITIES:
        raise AiReferralsQueryError(f"unknown granularity: {granularity!r}")
    return granularity


async def _load_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> AiReferralsSnapshot | None:
    """The persisted snapshot serving the request, or ``None``.

    An explicit ``from``/``to`` selects the snapshot persisted for exactly
    that window (read endpoints serve persisted snapshot windows only —
    arbitrary custom windows are never recomputed). Without a window the
    project's LATEST persisted snapshot at the granularity is served, so a
    default landing still renders the freshest projection.
    """
    stmt = (
        select(AiReferralsSnapshot)
        .where(AiReferralsSnapshot.workspace_id == workspace_id)
        .where(AiReferralsSnapshot.project_id == project_id)
        .where(AiReferralsSnapshot.granularity == granularity)
        .where(AiReferralsSnapshot.analyzer_version == AI_REFERRAL_ANALYZER_VERSION)
        .where(AiReferralsSnapshot.formula_version == AI_REFERRAL_FORMULA_VERSION)
    )
    if from_date is not None and to_date is not None:
        stmt = stmt.where(AiReferralsSnapshot.window_start == from_date)
        stmt = stmt.where(AiReferralsSnapshot.window_end == to_date)
    else:
        stmt = stmt.order_by(
            AiReferralsSnapshot.window_end.desc(),
            AiReferralsSnapshot.window_start.desc(),
        )
    return await session.scalar(stmt.limit(1))


def _empty_ai_referrals(
    *,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> AiReferralsResponse:
    """The empty payload for an absent snapshot (never a recomputation)."""
    return AiReferralsResponse(
        project_id=project_id,
        window_start=from_date.isoformat() if from_date is not None else "",
        window_end=to_date.isoformat() if to_date is not None else "",
        granularity=granularity,
        referral_volume=[],
        referral_share=[],
        sources=[],
        analyzer_version=AI_REFERRAL_ANALYZER_VERSION,
        formula_version=AI_REFERRAL_FORMULA_VERSION,
    )


async def get_ai_referrals(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    granularity: str = ANALYTICS_DEFAULT_GRANULARITY,
) -> AiReferralsResponse:
    """Serve the headline AEO projection from the persisted snapshot.

    The persisted ``metrics`` JSONB already carries the exact DTO fragments
    (A8 writes them in the served shape); this maps them into the strict
    response model. An absent snapshot yields the empty payload.
    """
    granularity = _validate_granularity(granularity)
    _validate_window(from_date, to_date)
    snapshot = await _load_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        granularity=granularity,
    )
    if snapshot is None:
        return _empty_ai_referrals(
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
            granularity=granularity,
        )

    metrics = snapshot.metrics or {}
    sources = [
        AiReferralSourceRow(
            ai_source=str(row.get("ai_source") or ""),
            sessions=int(row.get("sessions") or 0),
            share=row.get("share"),
        )
        for row in metrics.get("sources") or []
        if isinstance(row, dict)
    ]
    return AiReferralsResponse(
        project_id=project_id,
        window_start=snapshot.window_start.isoformat(),
        window_end=snapshot.window_end.isoformat(),
        granularity=snapshot.granularity,
        referral_volume=metric_series_points(metrics.get("referral_volume")),
        referral_share=metric_series_points(metrics.get("referral_share")),
        sources=sources,
        analyzer_version=snapshot.analyzer_version,
        formula_version=snapshot.formula_version,
    )
