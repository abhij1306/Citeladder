"""Pure seven-dimension AEO Readiness presentation projection.

This projects persisted rule evaluations into something a person can act on.
Two shaping rules matter more than the arithmetic:

* **Evidence is grouped by page, not by evaluation.** One page failing five
  checks is one row listing five checks — not five rows repeating the same URL.
* **Nothing here is named by its rule id.** Every check carries its catalog
  title and remediation, so the surface never asks a reader to know what
  ``aeo.answer_first`` means.

The counts stay exactly what they were: persisted outcomes, never a new score.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION,
    AEO_READINESS_RULE_DIMENSIONS,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)


@dataclass(frozen=True)
class ReadinessEvaluationInput:
    evaluation_id: uuid.UUID
    analysis_id: uuid.UUID
    site_url_id: uuid.UUID
    normalized_url: str
    rule_id: str
    outcome: str
    # Current catalog copy, resolved by the caller. Kept out of this pure module
    # so the projection never reaches into the rule catalog itself.
    title: str = ""
    remediation: str = ""


@dataclass(frozen=True)
class ReadinessCheck:
    """One mapped rule, rolled up in the reader's language."""

    rule_id: str
    title: str
    remediation: str
    pass_count: int
    fail_count: int
    not_applicable_count: int
    failing_page_count: int


@dataclass(frozen=True)
class ReadinessFailingCheck:
    rule_id: str
    title: str


@dataclass(frozen=True)
class ReadinessEvidencePage:
    """One page and every check of this dimension it failed."""

    site_url_id: uuid.UUID
    normalized_url: str
    failed_checks: tuple[ReadinessFailingCheck, ...]


@dataclass(frozen=True)
class ReadinessDimension:
    key: str
    label: str
    description: str
    rule_ids: tuple[str, ...]
    pass_count: int
    fail_count: int
    not_applicable_count: int
    error_count: int
    observed_evaluation_count: int
    expected_evaluation_count: int
    coverage: float | None
    checked_page_count: int
    failing_page_count: int
    checks: tuple[ReadinessCheck, ...]
    evidence_pages: tuple[ReadinessEvidencePage, ...]
    evidence_truncated: bool


@dataclass(frozen=True)
class ReadinessResult:
    dimensions: tuple[ReadinessDimension, ...]
    observed_evaluation_count: int
    expected_evaluation_count: int
    coverage: float | None
    limitations: tuple[str, ...]


def _title_of(rows: list[ReadinessEvaluationInput], rule_id: str) -> tuple[str, str]:
    """Catalog copy for a rule, falling back to its id only if nothing carried it."""
    for row in rows:
        if row.rule_id == rule_id and row.title:
            return row.title, row.remediation
    return rule_id, ""


def _checks(
    rows: list[ReadinessEvaluationInput], rules: tuple[str, ...]
) -> tuple[ReadinessCheck, ...]:
    """Per-rule rollups, worst first, so the row itself says what to fix."""
    checks: list[ReadinessCheck] = []
    for rule_id in rules:
        rule_rows = [row for row in rows if row.rule_id == rule_id]
        counts = Counter(row.outcome for row in rule_rows)
        title, remediation = _title_of(rule_rows, rule_id)
        checks.append(
            ReadinessCheck(
                rule_id=rule_id,
                title=title,
                remediation=remediation,
                pass_count=counts[RULE_OUTCOME_PASS],
                fail_count=counts[RULE_OUTCOME_FAIL],
                not_applicable_count=counts[RULE_OUTCOME_NOT_APPLICABLE],
                failing_page_count=len(
                    {
                        row.site_url_id
                        for row in rule_rows
                        if row.outcome == RULE_OUTCOME_FAIL
                    }
                ),
            )
        )
    return tuple(
        sorted(
            checks, key=lambda check: (-check.fail_count, check.title, check.rule_id)
        )
    )


def _evidence_pages(
    rows: list[ReadinessEvaluationInput],
) -> tuple[tuple[ReadinessEvidencePage, ...], int]:
    """Failing pages, each listing its own failed checks once.

    Returns the bounded page list plus the TRUE failing-page total, so a capped
    list is never presented as the complete one.
    """
    failures = [row for row in rows if row.outcome == RULE_OUTCOME_FAIL]
    by_page: dict[uuid.UUID, list[ReadinessEvaluationInput]] = {}
    for row in failures:
        by_page.setdefault(row.site_url_id, []).append(row)
    ordered = sorted(
        by_page.items(),
        # Most-broken pages first: that is the order someone fixing the site
        # would choose, and it survives the cap meaningfully.
        key=lambda item: (-len(item[1]), item[1][0].normalized_url, str(item[0])),
    )
    pages = tuple(
        ReadinessEvidencePage(
            site_url_id=site_url_id,
            normalized_url=page_rows[0].normalized_url,
            failed_checks=tuple(
                ReadinessFailingCheck(rule_id=rule_id, title=title)
                for rule_id, title in sorted(
                    {(row.rule_id, row.title or row.rule_id) for row in page_rows},
                    key=lambda pair: pair[1],
                )
            ),
        )
        for site_url_id, page_rows in ordered[
            :AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION
        ]
    )
    return pages, len(ordered)


def _dimension(
    key: str,
    *,
    analysis_count: int,
    evaluations: list[ReadinessEvaluationInput],
) -> ReadinessDimension:
    rules = tuple(
        rule_id
        for rule_id, dimension in AEO_READINESS_RULE_DIMENSIONS.items()
        if dimension == key
    )
    rows = [
        row for row in evaluations if AEO_READINESS_RULE_DIMENSIONS[row.rule_id] == key
    ]
    counts = Counter(row.outcome for row in rows)
    expected = analysis_count * len(rules)
    evidence_pages, failing_page_count = _evidence_pages(rows)
    return ReadinessDimension(
        key=key,
        label=AEO_READINESS_DIMENSION_LABELS[key],
        description=AEO_READINESS_DIMENSION_DESCRIPTIONS[key],
        rule_ids=rules,
        pass_count=counts[RULE_OUTCOME_PASS],
        fail_count=counts[RULE_OUTCOME_FAIL],
        not_applicable_count=counts[RULE_OUTCOME_NOT_APPLICABLE],
        error_count=counts[RULE_OUTCOME_ERROR],
        observed_evaluation_count=len(rows),
        expected_evaluation_count=expected,
        coverage=round(len(rows) / expected, 4) if expected else None,
        # A page counts as CHECKED only where a rule actually applied to it.
        # Counting not-applicable pages would make a dimension look broadly
        # measured when nothing in it was.
        checked_page_count=len(
            {
                row.site_url_id
                for row in rows
                if row.outcome in (RULE_OUTCOME_PASS, RULE_OUTCOME_FAIL)
            }
        ),
        failing_page_count=failing_page_count,
        checks=_checks(rows, rules),
        evidence_pages=evidence_pages,
        evidence_truncated=(
            failing_page_count > AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION
        ),
    )


def project_aeo_readiness(
    evaluations: list[ReadinessEvaluationInput], *, analysis_count: int
) -> ReadinessResult:
    """Group only explicitly mapped persisted evaluations; never guess."""
    mapped = [
        row for row in evaluations if row.rule_id in AEO_READINESS_RULE_DIMENSIONS
    ]
    dimensions = tuple(
        _dimension(key, analysis_count=analysis_count, evaluations=mapped)
        for key in AEO_READINESS_DIMENSIONS
    )
    observed = sum(item.observed_evaluation_count for item in dimensions)
    expected = sum(item.expected_evaluation_count for item in dimensions)
    limitations: list[str] = []
    if observed < expected:
        limitations.append(
            "Some checks did not apply to every analyzed page, so they were "
            "not measured there."
        )
    error_count = sum(item.error_count for item in dimensions)
    if error_count:
        limitations.append(
            f"{error_count} check{'s' if error_count != 1 else ''} could not be "
            "evaluated and count as neither a pass nor a failure."
        )
    return ReadinessResult(
        dimensions=dimensions,
        observed_evaluation_count=observed,
        expected_evaluation_count=expected,
        coverage=round(observed / expected, 4) if expected else None,
        limitations=tuple(limitations),
    )


__all__ = [
    "ReadinessCheck",
    "ReadinessEvaluationInput",
    "ReadinessEvidencePage",
    "ReadinessFailingCheck",
    "ReadinessResult",
    "project_aeo_readiness",
]
