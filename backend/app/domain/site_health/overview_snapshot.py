"""Snapshot-time inputs for the persisted Site Health Overview projection."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_link_metrics import COVERAGE_FORMULA_VERSION
from app.core.config.site_health_measurement import (
    CLASSIFICATION_FORMULA_VERSION,
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
    SITE_HEALTH_OVERVIEW_TREND_POINT_LIMIT,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.snapshot import SiteHealthSnapshot

_DETERMINATE_OUTCOMES = {
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_MISSING,
}
_CHANGE_METRICS = (
    ("web_fundamentals_score", "Web Fundamentals"),
    ("web_fundamentals_coverage", "Web Fundamentals coverage"),
    ("aeo_readiness_score", "AEO Readiness"),
    ("aeo_measurement_coverage", "AEO coverage"),
)


def measurement_check_counts(rows: Sequence[Row]) -> tuple[int, int]:
    """Count determinate and expected scored evaluations already being persisted."""
    expected = [
        row for row in rows if row.expected_profile_membership and bool(row.score_roles)
    ]
    measured = sum(row.outcome in _DETERMINATE_OUTCOMES for row in expected)
    return measured, len(expected)


def _change_metric(
    *, key: str, label: str, previous: float | None, current: float | None
) -> dict:
    if previous is None or current is None:
        delta = None
        direction = "unavailable"
    else:
        delta = round(current - previous, 4)
        if delta > 0:
            direction = "increased"
        elif delta < 0:
            direction = "decreased"
        else:
            direction = "unchanged"
    return {
        "key": key,
        "label": label,
        "previous": previous,
        "current": current,
        "delta": delta,
        "direction": direction,
    }


def _comparison_reason(
    previous: SiteHealthSnapshot | None, *, composition_changed: bool
) -> str:
    if previous is None:
        return "no_comparable_snapshot"
    if composition_changed:
        return "cohort_composition_changed"
    return "comparable_snapshot"


def _scored_kind_counts(snapshot: SiteHealthSnapshot | None) -> dict[str, int]:
    if snapshot is None:
        return {}
    return {
        str(key): int(value)
        for key, value in (snapshot.scored_page_count_by_kind or {}).items()
    }


def _cohort_composition(
    previous_counts: dict[str, int], current_counts: dict[str, int]
) -> dict[str, object]:
    return {
        "added_page_kinds": sorted(set(current_counts) - set(previous_counts)),
        "removed_page_kinds": sorted(set(previous_counts) - set(current_counts)),
        "previous_page_count_by_kind": previous_counts,
        "current_page_count_by_kind": dict(sorted(current_counts.items())),
    }


async def build_overview_history(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    analyzer_version: str,
    scoring_version: str,
    current_metrics: dict[str, float | None],
    scored_page_count_by_kind: dict[str, int],
    observed_at: datetime,
) -> tuple[dict, dict]:
    """Build bounded trends over snapshots with the exact same measurement identity."""
    history = list(
        await session.scalars(
            select(SiteHealthSnapshot)
            .where(
                SiteHealthSnapshot.workspace_id == crawl.workspace_id,
                SiteHealthSnapshot.project_id == crawl.project_id,
                SiteHealthSnapshot.crawl_id != crawl.id,
                SiteHealthSnapshot.analyzer_version == analyzer_version,
                SiteHealthSnapshot.scoring_version == scoring_version,
                SiteHealthSnapshot.profile_version == PROFILE_VERSION,
                SiteHealthSnapshot.schema_contract_version == SCHEMA_CONTRACT_VERSION,
                SiteHealthSnapshot.presentation_version == PRESENTATION_VERSION,
                SiteHealthSnapshot.coverage_formula_version == COVERAGE_FORMULA_VERSION,
                SiteHealthSnapshot.classification_formula_version
                == CLASSIFICATION_FORMULA_VERSION,
            )
            .order_by(
                SiteHealthSnapshot.created_at.desc(), SiteHealthSnapshot.id.desc()
            )
            .limit(SITE_HEALTH_OVERVIEW_TREND_POINT_LIMIT - 1)
        )
    )
    history.reverse()
    series = [
        {
            "label": row.created_at.date().isoformat(),
            "value": row.aeo_readiness_score,
        }
        for row in history
    ]
    series.append(
        {
            "label": observed_at.date().isoformat(),
            "value": current_metrics["aeo_readiness_score"],
        }
    )
    previous = history[-1] if history else None
    previous_counts = _scored_kind_counts(previous)
    composition_changed = (
        previous is not None and previous_counts != scored_page_count_by_kind
    )
    reason = _comparison_reason(previous, composition_changed=composition_changed)
    available = previous is not None
    composition = _cohort_composition(previous_counts, scored_page_count_by_kind)
    return (
        {
            "state": "measured" if available else "unavailable",
            "reason": reason,
            "metric": "aeo_readiness_score",
            "series": series,
            "cohort_composition": composition,
        },
        {
            "state": "measured" if available else "unavailable",
            "reason": reason,
            "metrics": [
                _change_metric(
                    key=key,
                    label=label,
                    previous=(None if previous is None else getattr(previous, key)),
                    current=current_metrics[key],
                )
                for key, label in _CHANGE_METRICS
            ],
            "cohort_composition": composition,
        },
    )


__all__ = ["build_overview_history", "measurement_check_counts"]
