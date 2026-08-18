from __future__ import annotations

import uuid

from app.analysis.site_health.aeo_readiness import (
    ReadinessEvaluationInput,
    project_aeo_readiness,
)
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSIONS,
    AEO_READINESS_RULE_DIMENSIONS,
)
from app.core.config.site_health_rules import (
    SITE_HEALTH_RULES_BY_ID,
)


def _row(rule_id: str, outcome: str) -> ReadinessEvaluationInput:
    return ReadinessEvaluationInput(
        evaluation_id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        site_url_id=uuid.uuid4(),
        normalized_url="https://example.test/page",
        rule_id=rule_id,
        outcome=outcome,
    )


def test_taxonomy_is_exact_known_and_one_to_one() -> None:
    assert set(AEO_READINESS_RULE_DIMENSIONS) <= set(SITE_HEALTH_RULES_BY_ID)
    assert set(AEO_READINESS_RULE_DIMENSIONS.values()) == set(AEO_READINESS_DIMENSIONS)
    assert len(AEO_READINESS_RULE_DIMENSIONS) == 20


def test_projection_reconciles_states_and_never_guesses_unmapped_rules() -> None:
    evaluations = [
        _row("aeo.answer_first", "pass"),
        _row("aeo.question_headings", "fail"),
        _row("aeo.no_expand_gating", "not_applicable"),
        _row("technical.thin_content", "error"),
        _row("technical.title_present", "fail"),
    ]

    result = project_aeo_readiness(evaluations, analysis_count=1)
    answerability = result.dimensions[0]

    assert [item.key for item in result.dimensions] == list(AEO_READINESS_DIMENSIONS)
    assert (
        answerability.pass_count,
        answerability.fail_count,
        answerability.not_applicable_count,
        answerability.error_count,
    ) == (1, 1, 1, 1)
    assert answerability.coverage == 1.0
    assert result.observed_evaluation_count == 4
    assert result.expected_evaluation_count == 20
    assert all(
        link.rule_id != "technical.title_present" for link in answerability.evidence
    )


def test_evidence_links_are_fail_first_and_bounded() -> None:
    rows = [_row("aeo.answer_first", "pass") for _ in range(30)]
    failure = _row("aeo.answer_first", "fail")

    result = project_aeo_readiness([*rows, failure], analysis_count=31)
    answerability = result.dimensions[0]

    assert len(answerability.evidence) == 25
    assert answerability.evidence[0] == failure
