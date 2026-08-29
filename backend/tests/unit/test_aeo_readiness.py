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


def _row(
    rule_id: str,
    outcome: str,
    *,
    site_url_id: uuid.UUID | None = None,
    url: str = "https://example.test/page",
    title: str = "",
) -> ReadinessEvaluationInput:
    return ReadinessEvaluationInput(
        evaluation_id=uuid.uuid4(),
        analysis_id=uuid.uuid4(),
        site_url_id=site_url_id or uuid.uuid4(),
        normalized_url=url,
        rule_id=rule_id,
        outcome=outcome,
        title=title,
    )


def test_taxonomy_is_exact_known_and_one_to_one() -> None:
    assert set(AEO_READINESS_RULE_DIMENSIONS) <= set(SITE_HEALTH_RULES_BY_ID)
    assert set(AEO_READINESS_RULE_DIMENSIONS.values()) == set(AEO_READINESS_DIMENSIONS)
    # 21 with aeo.reviewer_identified, the trait-scoped reviewer check.
    assert len(AEO_READINESS_RULE_DIMENSIONS) == 21


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
    errored = next(
        check
        for check in answerability.checks
        if check.rule_id == "technical.thin_content"
    )
    assert errored.error_count == 1
    assert result.observed_evaluation_count == 4
    assert result.expected_evaluation_count == 21
    assert all(
        check.rule_id != "technical.title_present" for check in answerability.checks
    )
    assert all(
        failed.rule_id != "technical.title_present"
        for page in answerability.evidence_pages
        for failed in page.failed_checks
    )


def test_evidence_is_one_row_per_failing_page_never_per_evaluation() -> None:
    """One page failing three checks is one row, not three repeated URLs."""
    page = uuid.uuid4()
    rows = [
        _row("aeo.answer_first", "fail", site_url_id=page, title="Answer not first"),
        _row(
            "aeo.question_headings",
            "fail",
            site_url_id=page,
            title="No question headings",
        ),
        _row(
            "aeo.no_expand_gating",
            "fail",
            site_url_id=page,
            title="Answer behind a click",
        ),
        _row("technical.thin_content", "pass", site_url_id=page),
    ]

    answerability = project_aeo_readiness(rows, analysis_count=1).dimensions[0]

    assert len(answerability.evidence_pages) == 1
    assert answerability.failing_page_count == 1
    assert [check.title for check in answerability.evidence_pages[0].failed_checks] == [
        "Answer behind a click",
        "Answer not first",
        "No question headings",
    ]
    assert answerability.checked_page_count == 1


def test_evidence_pages_are_worst_first_bounded_and_report_the_true_total() -> None:
    """A capped list must never read as the complete set of failing pages."""
    worst = uuid.uuid4()
    rows = [
        _row(
            "aeo.answer_first", "fail", site_url_id=worst, url="https://example.test/z"
        ),
        _row(
            "aeo.question_headings",
            "fail",
            site_url_id=worst,
            url="https://example.test/z",
        ),
    ]
    rows += [
        _row("aeo.answer_first", "fail", url=f"https://example.test/{index}")
        for index in range(30)
    ]

    answerability = project_aeo_readiness(rows, analysis_count=31).dimensions[0]

    assert len(answerability.evidence_pages) == 25
    assert answerability.failing_page_count == 31
    assert answerability.evidence_truncated is True
    # The page failing two checks leads, because that is the order someone
    # fixing the site would work in.
    assert answerability.evidence_pages[0].site_url_id == worst


def test_checks_carry_catalog_copy_and_never_fall_back_to_a_rule_id() -> None:
    rows = [
        _row("aeo.answer_first", "fail", title="Answer not stated first"),
        _row("aeo.answer_first", "pass", title="Answer not stated first"),
    ]

    answerability = project_aeo_readiness(
        rows,
        analysis_count=2,
        rule_copy={
            "aeo.answer_first": ("Answer not stated first", "Lead with the answer."),
            "aeo.question_headings": ("Question headings", "Use question headings."),
        },
    ).dimensions[0]
    answer_first = next(
        check for check in answerability.checks if check.rule_id == "aeo.answer_first"
    )

    assert answer_first.title == "Answer not stated first"
    assert answer_first.fail_count == 1
    assert answer_first.failing_page_count == 1
    assert all(
        check.rule_id != "aeo.question_headings" for check in answerability.checks
    )
    # Worst-first ordering puts the only failing check at the top.
    assert answerability.checks[0].rule_id == "aeo.answer_first"


def test_dimensions_carry_a_plain_language_description() -> None:
    result = project_aeo_readiness([], analysis_count=0)
    assert all(dimension.description for dimension in result.dimensions)
    assert "answer" in result.dimensions[0].description.lower()
