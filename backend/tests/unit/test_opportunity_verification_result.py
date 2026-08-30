from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config.site_health_contracts import RULE_OUTCOME_PARTIAL
from app.domain.opportunities import verification, verification_result


def test_numeric_state_preserves_unavailable_and_observed_zero() -> None:
    assert verification_result._state(None) == "unavailable"
    assert verification_result._state(0) == "observed_zero"
    assert verification_result._state(0.1) == "available"


@pytest.mark.asyncio
async def test_site_rule_verification_accepts_partial_outcomes() -> None:
    analysis_id = uuid.uuid4()
    evaluation_id = uuid.uuid4()
    session = SimpleNamespace(
        scalar=AsyncMock(
            return_value=SimpleNamespace(
                id=evaluation_id,
                outcome=RULE_OUTCOME_PARTIAL,
            )
        )
    )
    result = verification._Evaluation()

    await verification._evaluate_site_rule(
        session,
        declaration=SimpleNamespace(workspace_id=uuid.uuid4()),
        analysis=SimpleNamespace(id=analysis_id),
        check={"rule_id": "aeo.example", "expected_outcome": "partial"},
        result=result,
    )

    assert result.observed == 1
    assert result.matched == 1
    assert result.limitations == []


@pytest.mark.asyncio
async def test_visibility_leg_suppresses_a_changed_audit_cohort(monkeypatch) -> None:
    baseline_audit_id = uuid.uuid4()
    post_audit_id = uuid.uuid4()
    baseline = SimpleNamespace(audit_id=baseline_audit_id)
    audits = {
        baseline_audit_id: SimpleNamespace(id=baseline_audit_id),
        post_audit_id: SimpleNamespace(id=post_audit_id),
    }
    session = SimpleNamespace(
        get=AsyncMock(side_effect=lambda _model, key: audits[key])
    )

    async def identity(_session, audit) -> str:
        return f"cohort:{audit.id}"

    monkeypatch.setattr(verification_result, "_audit_identity", identity)

    result = await verification_result._visibility_leg(session, baseline, post_audit_id)

    assert result["state"] == "non_comparable"
    assert result["delta"] is None
    assert result["baseline_source_ids"] == [str(baseline_audit_id)]
    assert result["post_source_ids"] == [str(post_audit_id)]
    assert "model/retrieval" in result["limitations"][0]


@pytest.mark.asyncio
async def test_visibility_leg_is_unavailable_when_either_score_is_missing(
    monkeypatch,
) -> None:
    baseline_audit_id = uuid.uuid4()
    post_audit_id = uuid.uuid4()
    baseline_metric_id = uuid.uuid4()
    post_metric_id = uuid.uuid4()
    baseline = SimpleNamespace(audit_id=baseline_audit_id)
    audits = {
        baseline_audit_id: SimpleNamespace(id=baseline_audit_id),
        post_audit_id: SimpleNamespace(id=post_audit_id),
    }
    metrics = [
        SimpleNamespace(
            id=baseline_metric_id, visibility_score=None, analyzer_version="v1"
        ),
        SimpleNamespace(
            id=post_metric_id, visibility_score=42.0, analyzer_version="v1"
        ),
    ]
    session = SimpleNamespace(
        get=AsyncMock(side_effect=lambda _model, key: audits[key]),
        scalar=AsyncMock(side_effect=metrics),
    )

    async def identity(_session, _audit) -> str:
        return "same"

    monkeypatch.setattr(verification_result, "_audit_identity", identity)

    result = await verification_result._visibility_leg(session, baseline, post_audit_id)

    assert result["state"] == "unavailable"
    assert result["baseline_source_ids"] == [str(baseline_metric_id)]
    assert result["post_source_ids"] == [str(post_metric_id)]
    assert result["limitations"] == ["Visibility metric is unavailable."]


def test_gap_changes_stay_empty_until_a_post_action_snapshot_exists() -> None:
    before = {"gap-a", "gap-b"}

    assert verification_result._gap_changes(before, set(), None) == {
        "no_longer_observed": [],
        "persistent": [],
        "new": [],
        "state": "not_run",
    }
    assert verification_result._gap_changes(before, {"gap-b", "gap-c"}, object()) == {
        "no_longer_observed": ["gap-a"],
        "persistent": ["gap-b"],
        "new": ["gap-c"],
        "state": "available",
    }
