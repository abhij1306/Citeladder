"""Persisted fetch-resolution assembly for crawl-finalize rules."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.finalize import evaluate_canonical_resolvable
from app.analysis.site_health.rules import RuleEvaluation
from app.core.config.site_health_acquisition import SITE_HEALTH_MAX_EVIDENCE_URLS
from app.core.config.site_health_contracts import RULE_OUTCOME_UNKNOWN
from app.domain.site_health.normalization import canonical_or_empty
from app.models.site_health.acquisition import SiteFetchArtifact, SiteFetchAttempt
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask

Resolution = tuple[int | None, str, bool, uuid.UUID, uuid.UUID, uuid.UUID | None]


async def fetch_resolutions(
    session: AsyncSession, *, crawl: SiteCrawl
) -> dict[str, Resolution]:
    """Map each directly requested URL to its latest bounded fetch result."""
    rows = (
        await session.execute(
            select(
                SiteCrawlTask.requested_url,
                SiteCrawlTask.id,
                SiteFetchAttempt.status_code,
                SiteFetchAttempt.id,
                SiteFetchArtifact.final_url,
                SiteFetchArtifact.redirect_chain,
                SiteFetchArtifact.id,
            )
            .join(SiteFetchAttempt, SiteFetchAttempt.task_id == SiteCrawlTask.id)
            .outerjoin(
                SiteFetchArtifact,
                (SiteFetchArtifact.task_id == SiteCrawlTask.id)
                & (SiteFetchArtifact.crawl_id == crawl.id)
                & (SiteFetchArtifact.workspace_id == crawl.workspace_id),
            )
            .where(
                SiteCrawlTask.crawl_id == crawl.id,
                SiteCrawlTask.workspace_id == crawl.workspace_id,
                SiteFetchAttempt.crawl_id == crawl.id,
                SiteFetchAttempt.workspace_id == crawl.workspace_id,
            )
            .order_by(SiteFetchAttempt.created_at, SiteFetchAttempt.id)
        )
    ).all()
    resolutions: dict[str, Resolution] = {}
    for (
        requested_url,
        task_id,
        status_code,
        attempt_id,
        final_url,
        redirect_chain,
        artifact_id,
    ) in rows:
        requested = canonical_or_empty(str(requested_url or ""))
        final = canonical_or_empty(str(final_url or ""))
        if requested:
            resolutions[requested] = (
                status_code,
                final,
                bool(redirect_chain) or bool(final and final != requested),
                task_id,
                attempt_id,
                artifact_id,
            )
        if final and status_code is not None:
            resolutions.setdefault(
                final, (status_code, final, False, task_id, attempt_id, artifact_id)
            )
    return resolutions


def _is_rate_limited(resolution: Resolution | None) -> bool:
    return resolution is not None and resolution[0] == 429


def rate_limited_targets(resolutions: dict[str, Resolution]) -> set[str]:
    return {target for target, value in resolutions.items() if _is_rate_limited(value)}


def _canonical_resolution_evidence(
    evaluation: RuleEvaluation, *, target: str, resolution: Resolution | None
) -> dict:
    if resolution is None:
        return {
            **evaluation.evidence,
            "canonical_url": target,
            "final_url": "",
            "redirect_chain_present": False,
            "resolution_source_ids": [],
        }
    return {
        **evaluation.evidence,
        "canonical_url": target,
        "final_url": resolution[1],
        "redirect_chain_present": resolution[2],
        "observed_status_code": resolution[0],
        "resolution_source_ids": [
            str(value) for value in resolution[3:] if value is not None
        ],
    }


def canonical_resolution_evaluations(
    artifacts: Sequence[Any],
    *,
    analysis_ids_by_artifact: dict[uuid.UUID, list[uuid.UUID]],
    resolutions: dict[str, Resolution],
) -> list[tuple[uuid.UUID, RuleEvaluation]]:
    """Evaluate each analyzed page's canonical target against fetch results."""
    evaluations: list[tuple[uuid.UUID, RuleEvaluation]] = []
    for artifact_id, final_url, facts in artifacts:
        declared = str((facts or {}).get("canonical_url") or "")
        target = canonical_or_empty(urljoin(str(final_url or ""), declared))
        target = target or canonical_or_empty(str(final_url or ""))
        resolution = resolutions.get(target)
        rate_limited = _is_rate_limited(resolution)
        evaluation = evaluate_canonical_resolvable(
            target_url=target,
            checked=resolution is not None and not rate_limited,
            status_code=resolution[0] if resolution else None,
            redirected=resolution[2] if resolution else False,
        )
        if rate_limited:
            evaluation = replace(
                evaluation,
                reason_code="rate_limited",
                evidence={
                    **evaluation.evidence,
                    "reason": "rate_limited",
                    "status_code": 429,
                },
            )
        evaluations.extend(
            (
                analysis_id,
                replace(
                    evaluation,
                    evidence=_canonical_resolution_evidence(
                        evaluation, target=target, resolution=resolution
                    ),
                ),
            )
            for analysis_id in analysis_ids_by_artifact[artifact_id]
        )
    return evaluations


def _resolution_target_groups(
    targets: Sequence[str], *, resolutions: dict[str, Resolution]
) -> tuple[list[str], list[str], list[str]]:
    checked: list[str] = []
    rate_limited: list[str] = []
    broken: list[str] = []
    for target in targets:
        resolution = resolutions.get(target)
        if _is_rate_limited(resolution):
            rate_limited.append(target)
            continue
        if resolution is None or resolution[0] is None:
            continue
        checked.append(target)
        if int(resolution[0]) >= 400:
            broken.append(target)
    return checked, rate_limited, broken


def _rate_limit_unknown(
    evaluation: RuleEvaluation,
    *,
    rate_limited: list[str],
    broken: list[str],
) -> RuleEvaluation:
    if not rate_limited or broken:
        return evaluation
    return replace(
        evaluation,
        outcome=RULE_OUTCOME_UNKNOWN,
        reason_code="rate_limited_targets",
        evidence={**evaluation.evidence, "reason": "rate_limited_targets"},
    )


def _resolution_source_ids(
    targets: Sequence[str], *, resolutions: dict[str, Resolution]
) -> list[str]:
    values = {
        str(value)
        for target in targets
        for value in resolutions[target][3:]
        if value is not None
    }
    return sorted(values)[:SITE_HEALTH_MAX_EVIDENCE_URLS]


def resolution_set_evaluation(
    targets: Sequence[str],
    *,
    resolutions: dict[str, Resolution],
    evaluator: Callable[..., RuleEvaluation],
    failure_key: str,
) -> RuleEvaluation:
    """Run a URL-set resolution rule over canonicalized checked targets."""
    checked, rate_limited, broken = _resolution_target_groups(
        targets, resolutions=resolutions
    )
    evaluation = evaluator(
        total_count=len(targets),
        checked_count=len(checked),
        **{failure_key: broken},
    )
    evaluation = _rate_limit_unknown(
        evaluation, rate_limited=rate_limited, broken=broken
    )
    evidenced_targets = [*checked, *rate_limited]
    return replace(
        evaluation,
        evidence={
            **evaluation.evidence,
            "failing_targets": [
                {"url": target, "status_code": int(resolutions[target][0] or 0)}
                for target in broken[:SITE_HEALTH_MAX_EVIDENCE_URLS]
            ],
            "rate_limited_targets": [
                {"url": target, "status_code": 429}
                for target in rate_limited[:SITE_HEALTH_MAX_EVIDENCE_URLS]
            ],
            "resolution_source_ids": _resolution_source_ids(
                evidenced_targets, resolutions=resolutions
            ),
        },
    )


__all__ = [
    "Resolution",
    "canonical_resolution_evaluations",
    "fetch_resolutions",
    "rate_limited_targets",
    "resolution_set_evaluation",
]
