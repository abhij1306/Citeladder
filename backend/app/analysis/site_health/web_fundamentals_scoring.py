"""Deterministic Web Fundamentals scoring shared by page and crawl rollups."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from app.analysis.site_health.rules import RuleEvaluation
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    SEVERITY_CRITICAL,
)
from app.core.config.site_health_measurement import (
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_MEASURED,
    TECHNICAL_MEASURED_MIN_COVERAGE,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_PAGE,
    SCORE_ROLE_WEB_FUNDAMENTALS,
)


class WebFundamentalsRule(Protocol):
    @property
    def score(self) -> float | None: ...

    @property
    def coverage(self) -> float: ...

    @property
    def score_roles(self) -> tuple[str, ...]: ...

    @property
    def weight(self) -> float: ...

    @property
    def severity(self) -> str: ...


_DETERMINATE = frozenset(
    {RULE_OUTCOME_SATISFIED, RULE_OUTCOME_PARTIAL, RULE_OUTCOME_MISSING}
)


def checkpoint_credit(outcome: str) -> float:
    if outcome == RULE_OUTCOME_SATISFIED:
        return 1.0
    if outcome == RULE_OUTCOME_PARTIAL:
        return 0.5
    return 0.0


def measurement_ratio(
    numerator: float, denominator: float, *, score: bool
) -> float | None:
    if denominator <= 0:
        return None
    value = numerator / denominator
    return round(100.0 * value, 1) if score else round(value, 4)


def web_fundamentals_state(
    *, has_expected: bool, has_determinate: bool, coverage: float | None, complete: bool
) -> str:
    if not has_expected or not has_determinate:
        return MEASUREMENT_STATE_NOT_MEASURED
    if (
        coverage is not None
        and coverage >= TECHNICAL_MEASURED_MIN_COVERAGE
        and complete
    ):
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


def _weight(rows: Iterable[RuleEvaluation]) -> float:
    return sum(max(0.0, float(row.weight)) for row in rows)


def score_page_web_fundamentals(
    evaluations: list[RuleEvaluation],
) -> tuple[float | None, float | None, str, float, float, float, bool]:
    expected = [
        row
        for row in evaluations
        if row.expected_profile_membership
        and row.scope == RULE_SCOPE_PAGE
        and SCORE_ROLE_WEB_FUNDAMENTALS in row.score_roles
    ]
    determinate = [row for row in expected if row.outcome in _DETERMINATE]
    expected_weight = _weight(expected)
    determinate_weight = _weight(determinate)
    earned = sum(
        max(0.0, float(row.weight)) * checkpoint_credit(row.outcome)
        for row in determinate
    )
    score = measurement_ratio(earned, determinate_weight, score=True)
    coverage = measurement_ratio(determinate_weight, expected_weight, score=False)
    critical_complete = all(
        row.outcome in _DETERMINATE
        for row in expected
        if row.severity == SEVERITY_CRITICAL
    )
    state = web_fundamentals_state(
        has_expected=bool(expected),
        has_determinate=bool(determinate),
        coverage=coverage,
        complete=critical_complete,
    )
    return (
        score,
        coverage,
        state,
        round(earned, 4),
        round(determinate_weight, 4),
        round(expected_weight, 4),
        critical_complete,
    )


def _aggregate_rules(
    rules: Iterable[WebFundamentalsRule],
) -> list[WebFundamentalsRule]:
    return [rule for rule in rules if SCORE_ROLE_WEB_FUNDAMENTALS in rule.score_roles]


def _aggregate_contributions(
    rules: Iterable[WebFundamentalsRule],
) -> list[tuple[float, float]]:
    return [
        (float(rule.score), rule.weight * rule.coverage)
        for rule in rules
        if rule.score is not None and rule.coverage > 0
    ]


def _critical_rules_complete(rules: Iterable[WebFundamentalsRule]) -> bool:
    return all(
        rule.coverage >= 1.0 and rule.score is not None
        for rule in rules
        if rule.severity == SEVERITY_CRITICAL
    )


def aggregate_web_fundamentals(
    rules: Iterable[WebFundamentalsRule],
) -> tuple[float | None, float | None, str]:
    expected_rules = _aggregate_rules(rules)
    contributions = _aggregate_contributions(expected_rules)
    expected = sum(rule.weight for rule in expected_rules)
    determinate = sum(weight for _score, weight in contributions)
    earned = sum(score * weight for score, weight in contributions)
    score = measurement_ratio(earned, determinate, score=True)
    coverage = measurement_ratio(determinate, expected, score=False)
    critical_complete = _critical_rules_complete(expected_rules)
    state = web_fundamentals_state(
        has_expected=expected > 0,
        has_determinate=determinate > 0,
        coverage=coverage,
        complete=critical_complete,
    )
    return score, coverage, state
