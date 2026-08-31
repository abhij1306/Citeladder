"""Pure snapshot-time construction of the immutable AEO diagnostic read model."""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import Row

from app.analysis.site_health.rules import rule_for
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    AEO_READINESS_MAX_EVALUATIONS,
    AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION,
    RULE_FAILING_OUTCOMES,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.site_health_rule_types import SCORE_ROLE_AEO
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.models.site_health.crawl import SiteCrawl


@dataclass(frozen=True, slots=True)
class ReadinessPage:
    analysis_id: uuid.UUID
    site_url_id: uuid.UUID
    normalized_url: str


class SnapshotReadinessAggregate(Protocol):
    @property
    def aeo_readiness_score(self) -> float | None: ...

    @property
    def aeo_measurement_coverage(self) -> float | None: ...

    @property
    def aeo_measurement_state(self) -> str: ...

    @property
    def readiness_dimensions(self) -> tuple[dict, ...]: ...


def _bounded_evaluations(rows: Sequence[Row]) -> tuple[list[Row], bool]:
    return (
        list(rows[:AEO_READINESS_MAX_EVALUATIONS]),
        len(rows) > AEO_READINESS_MAX_EVALUATIONS,
    )


def _bounded_readiness_rows(evaluations: Sequence[Row]) -> tuple[list[Row], bool]:
    readiness_rows = [
        row
        for row in evaluations
        if row.rule_id in SITE_HEALTH_RULES_BY_ID
        and str(row.readiness_dimension or "")
        and SCORE_ROLE_AEO in tuple(row.score_roles or ())
    ]
    return _bounded_evaluations(readiness_rows)


def _failing_entity_count(scope: str, rows: Sequence[Row]) -> int:
    failing = [row for row in rows if row.outcome in RULE_FAILING_OUTCOMES]
    if scope == "page":
        return len({row.analysis_id for row in failing})
    if scope == "site":
        return int(bool(failing))
    return sum(
        max(
            1,
            int(value)
            if (
                isinstance(
                    value := (row.evidence or {}).get("failure_count"), (int, float)
                )
                and math.isfinite(value)
            )
            or (isinstance(value, str) and value.strip().isdigit())
            else 0,
        )
        for row in failing
    )


def _check_projection(rule_id: str, rows: Sequence[Row]) -> dict | None:
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    if rule is None or not rows or not str(rows[0].readiness_dimension or ""):
        return None
    first = rows[0]
    counts = Counter(row.outcome for row in rows)
    return {
        "rule_id": rule_id,
        "scope": first.scope,
        "title": rule.display_label,
        "remediation": rule.remediation,
        "satisfied_count": counts[RULE_OUTCOME_SATISFIED],
        "partial_count": counts[RULE_OUTCOME_PARTIAL],
        "missing_count": counts[RULE_OUTCOME_MISSING],
        "unknown_count": counts[RULE_OUTCOME_UNKNOWN],
        "not_applicable_count": counts[RULE_OUTCOME_NOT_APPLICABLE],
        "error_count": counts[RULE_OUTCOME_ERROR],
        "failing_entity_count": _failing_entity_count(first.scope, rows),
        "checkpoint_family": str(first.checkpoint_family or ""),
        "readiness_weight": float(first.readiness_weight or 0.0),
        "content_addressable": rule.content_addressable,
    }


def rule_guidance(rule_id: str) -> tuple[str, str]:
    rule = rule_for(rule_id)
    return ("", "") if rule is None else (rule.description, rule.remediation)


def _page_evidence(
    dimension: str,
    rows: Sequence[Row],
    pages: dict[uuid.UUID, ReadinessPage],
) -> list[dict]:
    by_analysis: dict[uuid.UUID, list[Row]] = {}
    for row in rows:
        if (
            row.rule_id in SITE_HEALTH_RULES_BY_ID
            and row.readiness_dimension == dimension
            and row.scope == "page"
            and row.outcome in RULE_FAILING_OUTCOMES
            and row.analysis_id in pages
        ):
            by_analysis.setdefault(row.analysis_id, []).append(row)
    ordered = sorted(
        by_analysis.items(),
        key=lambda item: (-len(item[1]), pages[item[0]].normalized_url, str(item[0])),
    )
    evidence_pages: list[dict] = []
    for analysis_id, failures in ordered[
        :AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION
    ]:
        page = pages[analysis_id]
        failures.sort(key=lambda row: row.rule_id)
        guidance = {row.rule_id: rule_guidance(row.rule_id) for row in failures}
        evidence_pages.append(
            {
                "site_url_id": str(page.site_url_id),
                "source_analysis_id": str(page.analysis_id),
                "normalized_url": page.normalized_url,
                "failed_checks": [
                    {
                        "rule_id": row.rule_id,
                        "title": SITE_HEALTH_RULES_BY_ID[row.rule_id].display_label,
                        "observed_evidence": row.evidence or {},
                        "expected_capability": guidance[row.rule_id][0],
                        "remediation": guidance[row.rule_id][1],
                        "content_addressable": SITE_HEALTH_RULES_BY_ID[
                            row.rule_id
                        ].content_addressable,
                    }
                    for row in failures
                ],
            }
        )
    return evidence_pages


def _failing_analysis_ids(rows: Sequence[Row]) -> set[uuid.UUID]:
    return {row.analysis_id for row in rows if row.outcome in RULE_FAILING_OUTCOMES}


def _outcome_page_count(rows: Sequence[Row], outcomes: frozenset[str]) -> int:
    return len({row.analysis_id for row in rows if row.outcome in outcomes})


def _dimension_projection(
    persisted: dict,
    rows: Sequence[Row],
    pages: dict[uuid.UUID, ReadinessPage],
) -> dict:
    key = str(persisted.get("key") or "")
    dimension_rows = [row for row in rows if row.readiness_dimension == key]
    page_rows = [row for row in dimension_rows if row.scope == "page"]
    counts = Counter(row.outcome for row in dimension_rows)
    checkpoint_ids = sorted({row.rule_id for row in dimension_rows})
    evidence_pages = _page_evidence(key, dimension_rows, pages)
    failing_page_count = len(_failing_analysis_ids(page_rows))
    return {
        "key": key,
        "label": AEO_READINESS_DIMENSION_LABELS[key],
        "description": AEO_READINESS_DIMENSION_DESCRIPTIONS[key],
        "dimension_applicability": persisted.get(
            "dimension_applicability", "applicable"
        ),
        "dimension_measurement_state": persisted.get(
            "dimension_measurement_state", "not_measured"
        ),
        "score": persisted.get("score"),
        "reason": persisted.get("reason", ""),
        "checkpoint_ids": checkpoint_ids,
        "determinate_checkpoint_ids": persisted.get("determinate_checkpoint_ids", []),
        "checkpoint_families": persisted.get("checkpoint_families", []),
        "earned_points": persisted.get("earned_points", 0.0),
        "determinate_points": persisted.get("determinate_points", 0.0),
        "expected_points": persisted.get("expected_points", 0.0),
        "satisfied_count": counts[RULE_OUTCOME_SATISFIED],
        "partial_count": counts[RULE_OUTCOME_PARTIAL],
        "missing_count": counts[RULE_OUTCOME_MISSING],
        "unknown_count": counts[RULE_OUTCOME_UNKNOWN],
        "not_applicable_count": counts[RULE_OUTCOME_NOT_APPLICABLE],
        "error_count": counts[RULE_OUTCOME_ERROR],
        "coverage": persisted.get("coverage"),
        "checked_page_count": _outcome_page_count(
            page_rows,
            frozenset(
                {RULE_OUTCOME_SATISFIED, RULE_OUTCOME_PARTIAL, RULE_OUTCOME_MISSING}
            ),
        ),
        "failing_page_count": failing_page_count,
        "checks": [
            projection
            for rule_id in checkpoint_ids
            if (
                projection := _check_projection(
                    rule_id,
                    [row for row in dimension_rows if row.rule_id == rule_id],
                )
            )
            is not None
        ],
        "evidence_pages": evidence_pages,
        "evidence_truncated": failing_page_count > len(evidence_pages),
    }


def _readiness_limitations(
    *,
    state: str,
    coverage_state: str,
    audited_page_count: int,
    evaluations_truncated: bool,
) -> list[str]:
    limitations: list[str] = []
    if state != "measured":
        limitations.append(
            "Readiness evidence is limited; review dimension coverage below."
        )
    if coverage_state != "complete":
        limitations.append(
            f"AEO Readiness describes {audited_page_count} audited pages; "
            f"crawl coverage is {coverage_state}."
        )
    if evaluations_truncated:
        limitations.append(
            "Readiness diagnostic counts and evidence are truncated at "
            f"{AEO_READINESS_MAX_EVALUATIONS} evaluations."
        )
    return limitations


def _readiness_dimension_projections(
    persisted_dimensions: Sequence[dict],
    rows: Sequence[Row],
    pages: dict[uuid.UUID, ReadinessPage],
) -> list[dict]:
    persisted_by_key = {
        str(dimension.get("key")): dimension for dimension in persisted_dimensions
    }
    return [
        _dimension_projection(persisted_by_key.get(key, {"key": key}), rows, pages)
        for key in AEO_READINESS_DIMENSIONS
    ]


def build_aeo_readiness_descriptor(
    *,
    crawl_id: uuid.UUID,
    score: float | None,
    coverage: float | None,
    state: str,
    coverage_state: str,
    readiness_dimensions: Sequence[dict],
    evaluations: Sequence[Row],
    pages: dict[uuid.UUID, ReadinessPage],
    profile_version: str,
    schema_contract_version: str,
    scoring_version: str,
    presentation_version: str,
    analyzer_version: str,
) -> dict:
    bounded, evaluations_truncated = _bounded_readiness_rows(evaluations)
    limitations = _readiness_limitations(
        state=state,
        coverage_state=coverage_state,
        audited_page_count=len(pages),
        evaluations_truncated=evaluations_truncated,
    )
    return {
        "state": state,
        "crawl_id": str(crawl_id),
        "score": score,
        "coverage": coverage,
        "profile_version": profile_version,
        "schema_contract_version": schema_contract_version,
        "scoring_version": scoring_version,
        "presentation_version": presentation_version,
        "analyzer_version": analyzer_version,
        "source_analysis_ids": [str(value) for value in pages],
        "analysis_count": len(pages),
        "affected_page_count": len(
            _failing_analysis_ids([row for row in bounded if row.scope == "page"])
        ),
        "dimensions": _readiness_dimension_projections(
            readiness_dimensions, bounded, pages
        ),
        "limitations": limitations,
    }


def build_snapshot_aeo_readiness_descriptor(
    *,
    crawl: SiteCrawl,
    aggregate: SnapshotReadinessAggregate,
    coverage_state: str,
    evaluations: Sequence[Row],
    analysis_rows: Sequence[Row],
    analyzer_version: str,
    scoring_version: str,
) -> dict:
    """Adapt frozen snapshot inputs to the public diagnostic descriptor."""
    pages = {
        row.id: ReadinessPage(
            analysis_id=row.id,
            site_url_id=row.site_url_id,
            normalized_url=row.normalized_url,
        )
        for row in analysis_rows
    }
    return build_aeo_readiness_descriptor(
        crawl_id=crawl.id,
        score=aggregate.aeo_readiness_score,
        coverage=aggregate.aeo_measurement_coverage,
        state=aggregate.aeo_measurement_state,
        coverage_state=coverage_state,
        readiness_dimensions=aggregate.readiness_dimensions,
        evaluations=evaluations,
        pages=pages,
        profile_version=PROFILE_VERSION,
        schema_contract_version=SCHEMA_CONTRACT_VERSION,
        scoring_version=scoring_version,
        presentation_version=PRESENTATION_VERSION,
        analyzer_version=analyzer_version,
    )


__all__ = [
    "ReadinessPage",
    "build_aeo_readiness_descriptor",
    "build_snapshot_aeo_readiness_descriptor",
    "rule_guidance",
]
