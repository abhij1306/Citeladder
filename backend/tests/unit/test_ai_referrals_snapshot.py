"""Pure AI-referral snapshot math over canonical GA4 session facts."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app.core.config.analytics import (
    AI_SOURCE_CHATGPT,
    AI_SOURCE_GEMINI,
    AI_SOURCE_OTHER,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
)
from app.domain.analytics.ai_referrals_snapshot import (
    ReferralFactInput,
    build_ai_referrals_projection,
    select_latest_referral_facts,
)

WINDOW = (date(2026, 7, 20), date(2026, 7, 22))
_PROPERTY = "properties/123456789"


def _fact(
    occurred: date,
    *,
    is_ai: bool | None = True,
    ai_source: str = AI_SOURCE_CHATGPT,
    sessions: int = 1,
    resync_seq: int = 0,
    dimension_key: str = "chatgpt / referral | 20260720",
    classified: bool = True,
) -> ReferralFactInput:
    return ReferralFactInput(
        classification_id=uuid.uuid4() if classified else None,
        is_ai_referral=is_ai,
        ai_source=ai_source,
        occurred_date=occurred,
        sessions=sessions,
        row_identity=(
            _PROPERTY,
            "ga4",
            DATASET_GA4_SOURCE_MEDIUM_DAILY,
            occurred,
            dimension_key,
        ),
        resync_seq=resync_seq,
    )


def _build(*, referral_facts=(), granularity: str = "day", window=WINDOW):
    return build_ai_referrals_projection(
        referral_facts=list(referral_facts),
        window_start=window[0],
        window_end=window[1],
        granularity=granularity,
    )


def test_latest_resync_revision_is_the_only_folded_fact() -> None:
    stale = _fact(date(2026, 7, 20), sessions=5, resync_seq=0)
    fresh = _fact(date(2026, 7, 20), sessions=9, resync_seq=1)

    assert select_latest_referral_facts([stale, fresh]) == [fresh]
    projection = _build(referral_facts=[fresh, stale])
    assert projection.metrics["referral_volume"][0]["value"] == 9
    assert projection.source_classification_ids == [str(fresh.classification_id)]


def test_volume_share_and_sources_use_one_canonical_denominator() -> None:
    facts = [
        _fact(date(2026, 7, 20), sessions=4),
        _fact(
            date(2026, 7, 20),
            ai_source=AI_SOURCE_GEMINI,
            sessions=1,
            dimension_key="gemini / referral | 20260720",
        ),
        _fact(
            date(2026, 7, 20),
            is_ai=False,
            ai_source=AI_SOURCE_OTHER,
            sessions=5,
            dimension_key="google / organic | 20260720",
        ),
        _fact(
            date(2026, 7, 21),
            is_ai=False,
            ai_source=AI_SOURCE_OTHER,
            sessions=6,
            dimension_key="direct / none | 20260721",
        ),
    ]

    projection = _build(referral_facts=facts)
    assert [point["value"] for point in projection.metrics["referral_volume"]] == [
        5,
        0,
        None,
    ]
    assert projection.metrics["referral_share"][0]["value"] == pytest.approx(0.5)
    assert projection.metrics["referral_share"][1]["value"] == 0.0
    assert projection.metrics["referral_share"][2]["value"] is None
    assert projection.metrics["sources"] == [
        {"ai_source": AI_SOURCE_CHATGPT, "sessions": 4, "share": pytest.approx(0.25)},
        {"ai_source": AI_SOURCE_GEMINI, "sessions": 1, "share": pytest.approx(0.0625)},
    ]
    assert set(projection.metrics) == {"referral_volume", "referral_share", "sources"}


def test_incomplete_classification_stays_unmeasured() -> None:
    known = _fact(date(2026, 7, 20), sessions=4)
    unknown = _fact(
        date(2026, 7, 20),
        is_ai=None,
        ai_source="",
        sessions=6,
        dimension_key="unknown / referral | 20260720",
        classified=False,
    )

    projection = _build(referral_facts=[known, unknown])
    assert projection.metrics["referral_volume"][0]["value"] is None
    assert projection.metrics["referral_share"][0]["value"] is None
    assert projection.metrics["sources"] == []
    assert projection.source_classification_ids == [str(known.classification_id)]


@pytest.mark.parametrize("granularity", ["week", "month"])
def test_week_and_month_change_buckets_not_window_totals(granularity: str) -> None:
    facts = [
        _fact(date(2026, 7, 20), sessions=2, dimension_key="a | 20260720"),
        _fact(date(2026, 7, 22), sessions=3, dimension_key="a | 20260722"),
    ]
    projection = _build(referral_facts=facts, granularity=granularity)
    assert projection.metrics["referral_volume"] == [{"date": "2026-07-20", "value": 5}]
    assert projection.metrics["referral_share"] == [
        {"date": "2026-07-20", "value": 1.0}
    ]


def test_empty_evidence_is_unavailable_not_measured_zero() -> None:
    projection = _build()
    assert [point["value"] for point in projection.metrics["referral_volume"]] == [
        None,
        None,
        None,
    ]
    assert projection.metrics["sources"] == []


def test_invalid_granularity_and_window_raise() -> None:
    with pytest.raises(ValueError, match="unknown AI Referrals granularity"):
        _build(granularity="hour")
    reversed_window = (date(2026, 7, 22), date(2026, 7, 20))
    with pytest.raises(ValueError, match="window_end before window_start"):
        _build(window=reversed_window)
