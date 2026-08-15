"""Pure deterministic comparison of two explicitly comparable crawl inputs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config.site_change_intel import (
    CHANGE_CLASS_CRITICAL,
    CHANGE_CLASS_IMPROVEMENT,
    CHANGE_CLASS_NEUTRAL,
    CHANGE_CLASS_REGRESSION,
    CHANGE_FIELDS,
)


@dataclass(frozen=True)
class RuleState:
    outcome: str
    severity: str
    evaluation_id: uuid.UUID


@dataclass(frozen=True)
class ChangePage:
    site_url_id: uuid.UUID
    normalized_url: str
    analysis_id: uuid.UUID
    artifact_id: uuid.UUID
    fields: dict[str, Any]
    rules: dict[str, RuleState]
    intended_indexable: bool | None = None


@dataclass(frozen=True)
class ExpectedChange:
    implementation_event_id: uuid.UUID
    expected_value: Any


@dataclass(frozen=True)
class ChangeObservation:
    site_url_id: uuid.UUID
    normalized_url: str
    field: str
    change_class: str
    before_value: Any
    after_value: Any
    source_analysis_a_id: uuid.UUID | None
    source_analysis_b_id: uuid.UUID | None
    source_artifact_a_id: uuid.UUID | None
    source_artifact_b_id: uuid.UUID | None
    source_evaluation_a_id: uuid.UUID | None
    source_evaluation_b_id: uuid.UUID | None
    expected: bool
    implementation_event_id: uuid.UUID | None


def _rule_class(before: RuleState | None, after: RuleState | None) -> str | None:
    if before is None or after is None or before.outcome == after.outcome:
        return None
    if before.outcome == "fail" and after.outcome == "pass":
        return CHANGE_CLASS_IMPROVEMENT
    if before.outcome == "pass" and after.outcome == "fail":
        return (
            CHANGE_CLASS_CRITICAL
            if after.severity == "critical"
            else CHANGE_CLASS_REGRESSION
        )
    return None


def _http_class(before: Any, after: Any) -> str:
    before_ok = isinstance(before, int) and 200 <= before < 300
    after_ok = isinstance(after, int) and 200 <= after < 300
    after_error = isinstance(after, int) and 400 <= after < 600
    before_error = isinstance(before, int) and 400 <= before < 600
    if before_ok and after_error:
        return CHANGE_CLASS_CRITICAL
    if before_error and after_ok:
        return CHANGE_CLASS_IMPROVEMENT
    return CHANGE_CLASS_NEUTRAL


def _change_class(field: str, before: ChangePage, after: ChangePage) -> str:
    rule_class = _rule_class(before.rules.get(field), after.rules.get(field))
    if rule_class:
        return rule_class
    if field == "http_status":
        return _http_class(before.fields.get(field), after.fields.get(field))
    if (
        field == "robots_noindex"
        and before.intended_indexable is True
        and before.fields.get(field) is False
        and after.fields.get(field) is True
    ):
        return CHANGE_CLASS_CRITICAL
    return CHANGE_CLASS_NEUTRAL


def _expected_link(
    expected: dict[tuple[uuid.UUID, str], ExpectedChange],
    *,
    site_url_id: uuid.UUID,
    field: str,
    after_value: Any,
) -> tuple[bool, uuid.UUID | None]:
    item = expected.get((site_url_id, field))
    if item is None or item.expected_value != after_value:
        return False, None
    return True, item.implementation_event_id


def _paired_observations(
    before: ChangePage,
    after: ChangePage,
    expected: dict[tuple[uuid.UUID, str], ExpectedChange],
) -> list[ChangeObservation]:
    observations: list[ChangeObservation] = []
    for field in CHANGE_FIELDS:
        before_value = before.fields.get(field)
        after_value = after.fields.get(field)
        before_rule = before.rules.get(field)
        after_rule = after.rules.get(field)
        rule_changed = (
            before_rule is not None
            and after_rule is not None
            and (
                before_rule.outcome != after_rule.outcome
                or before_rule.severity != after_rule.severity
            )
        )
        if before_value == after_value and not rule_changed:
            continue
        is_expected, event_id = _expected_link(
            expected,
            site_url_id=after.site_url_id,
            field=field,
            after_value=after_value,
        )
        observations.append(
            ChangeObservation(
                site_url_id=after.site_url_id,
                normalized_url=after.normalized_url,
                field=field,
                change_class=_change_class(field, before, after),
                before_value=before_value,
                after_value=after_value,
                source_analysis_a_id=before.analysis_id,
                source_analysis_b_id=after.analysis_id,
                source_artifact_a_id=before.artifact_id,
                source_artifact_b_id=after.artifact_id,
                source_evaluation_a_id=(
                    before_rule.evaluation_id if before_rule else None
                ),
                source_evaluation_b_id=after_rule.evaluation_id if after_rule else None,
                expected=is_expected,
                implementation_event_id=event_id,
            )
        )
    return observations


def compare_crawls(
    crawl_a: list[ChangePage],
    crawl_b: list[ChangePage],
    *,
    complete_pair: bool,
    expected: dict[tuple[uuid.UUID, str], ExpectedChange] | None = None,
) -> tuple[ChangeObservation, ...]:
    """Compare selected evidence without partial-pair URL presence claims."""
    expected = expected or {}
    pages_a = {page.site_url_id: page for page in crawl_a}
    pages_b = {page.site_url_id: page for page in crawl_b}
    observations: list[ChangeObservation] = []
    for site_url_id in sorted(pages_a.keys() & pages_b.keys(), key=str):
        observations.extend(
            _paired_observations(pages_a[site_url_id], pages_b[site_url_id], expected)
        )
    if complete_pair:
        for site_url_id in sorted(pages_b.keys() - pages_a.keys(), key=str):
            page = pages_b[site_url_id]
            observations.append(
                ChangeObservation(
                    site_url_id=site_url_id,
                    normalized_url=page.normalized_url,
                    field="url_presence",
                    change_class=CHANGE_CLASS_IMPROVEMENT,
                    before_value=False,
                    after_value=True,
                    source_analysis_a_id=None,
                    source_analysis_b_id=page.analysis_id,
                    source_artifact_a_id=None,
                    source_artifact_b_id=page.artifact_id,
                    source_evaluation_a_id=None,
                    source_evaluation_b_id=None,
                    expected=False,
                    implementation_event_id=None,
                )
            )
        for site_url_id in sorted(pages_a.keys() - pages_b.keys(), key=str):
            page = pages_a[site_url_id]
            observations.append(
                ChangeObservation(
                    site_url_id=site_url_id,
                    normalized_url=page.normalized_url,
                    field="url_presence",
                    change_class=CHANGE_CLASS_REGRESSION,
                    before_value=True,
                    after_value=False,
                    source_analysis_a_id=page.analysis_id,
                    source_analysis_b_id=None,
                    source_artifact_a_id=page.artifact_id,
                    source_artifact_b_id=None,
                    source_evaluation_a_id=None,
                    source_evaluation_b_id=None,
                    expected=False,
                    implementation_event_id=None,
                )
            )
    return tuple(observations)


__all__ = [
    "ChangeObservation",
    "ChangePage",
    "ExpectedChange",
    "RuleState",
    "compare_crawls",
]
