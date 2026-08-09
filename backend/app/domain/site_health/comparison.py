"""Immutable compatible Site snapshot comparison and evidence-only resolution."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import SITE_ISSUE_TO_OPPORTUNITY_RULE_ID
from app.core.config.site_health import (
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_intelligence import (
    ACTION_RESOLUTION_PARTIAL,
    ACTION_RESOLUTION_UNRESOLVED,
    ACTION_RESOLUTION_VERIFIED,
    MAX_COMPARISON_CHANGE_ITEMS,
    SNAPSHOT_COMPARISON_VERSION,
)
from app.models.knowledge import KnowledgeAssertion, KnowledgeEntity
from app.models.site_health import (
    SiteCrawl,
    SiteHealthSnapshot,
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
)

__all__ = ["action_resolution_state", "build_snapshot_comparison"]


def action_resolution_state(outcomes: Sequence[str | None]) -> str:
    """Only an observed ``pass`` resolves work; absence never does."""
    passed = sum(outcome == RULE_OUTCOME_PASS for outcome in outcomes)
    if outcomes and passed == len(outcomes):
        return ACTION_RESOLUTION_VERIFIED
    if passed:
        return ACTION_RESOLUTION_PARTIAL
    return ACTION_RESOLUTION_UNRESOLVED


def _manifest(payload: Mapping | None) -> dict:
    value = (payload or {}).get("manifest")
    return dict(value) if isinstance(value, Mapping) else {}


def _compatibility_reason(
    prior: SiteHealthSnapshot,
    *,
    current_manifest: Mapping,
    analyzer_version: str,
    scoring_version: str,
    intelligence_version: str,
) -> str | None:
    if prior.intelligence_version != intelligence_version:
        return "intelligence_projection_version_changed"
    if prior.analyzer_version != analyzer_version:
        return "analyzer_version_changed"
    if prior.scoring_version != scoring_version:
        return "scoring_version_changed"
    if _manifest(prior.intelligence) != dict(current_manifest):
        return "industry_pack_manifest_changed"
    return None


def _delta(before: float | int | None, after: float | int | None) -> float | None:
    if before is None or after is None:
        return None
    return float(after) - float(before)


def _indexed(items: object, key: str) -> dict[str, dict]:
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return {}
    return {
        str(item.get(key)): dict(item)
        for item in items
        if isinstance(item, Mapping) and item.get(key)
    }


def _projection_comparison(before: Mapping, after: Mapping) -> dict:
    return {
        "questions": _question_comparison(before, after),
        "journeys": _journey_comparison(before, after),
        "dimensions": _dimension_comparison(before, after),
        "coverage": _coverage_comparison(before, after),
    }


def _question_comparison(before: Mapping, after: Mapping) -> dict:
    before_questions = _indexed(
        (before.get("coverage") or {}).get("questions"), "question_id"
    )
    after_questions = _indexed(
        (after.get("coverage") or {}).get("questions"), "question_id"
    )
    question_ids = sorted(set(before_questions) | set(after_questions))
    question_changes = [
        {
            "question_id": key,
            "before": before_questions.get(key, {}).get("state", "unavailable"),
            "after": after_questions.get(key, {}).get("state", "unavailable"),
        }
        for key in question_ids
        if before_questions.get(key, {}).get("state")
        != after_questions.get(key, {}).get("state")
    ]
    return {
        "changed_count": len(question_changes),
        "changes": question_changes[:MAX_COMPARISON_CHANGE_ITEMS],
        "truncated": len(question_changes) > MAX_COMPARISON_CHANGE_ITEMS,
    }


def _journey_comparison(before: Mapping, after: Mapping) -> dict:
    before_journeys = _indexed(before.get("journeys"), "journey_id")
    after_journeys = _indexed(after.get("journeys"), "journey_id")
    journey_ids = sorted(set(before_journeys) | set(after_journeys))
    journey_changes = [
        _journey_change(key, before_journeys.get(key), after_journeys.get(key))
        for key in journey_ids
        if before_journeys.get(key) != after_journeys.get(key)
    ]
    return {
        "changed_count": len(journey_changes),
        "changes": journey_changes[:MAX_COMPARISON_CHANGE_ITEMS],
        "truncated": len(journey_changes) > MAX_COMPARISON_CHANGE_ITEMS,
    }


def _journey_change(
    journey_id: str, before: Mapping | None, after: Mapping | None
) -> dict:
    before_row = dict(before or {})
    after_row = dict(after or {})
    before_stages = _indexed(before_row.get("stages"), "stage_id")
    after_stages = _indexed(after_row.get("stages"), "stage_id")
    stage_ids = sorted(set(before_stages) | set(after_stages))
    stage_changes = [
        {
            "stage_id": stage_id,
            "before_role_coverage": before_stages.get(stage_id, {}).get(
                "role_coverage"
            ),
            "after_role_coverage": after_stages.get(stage_id, {}).get("role_coverage"),
            "before_question_coverage": before_stages.get(stage_id, {}).get(
                "question_coverage"
            ),
            "after_question_coverage": after_stages.get(stage_id, {}).get(
                "question_coverage"
            ),
        }
        for stage_id in stage_ids
        if before_stages.get(stage_id) != after_stages.get(stage_id)
    ]
    return {
        "journey_id": journey_id,
        "before_role_coverage": before_row.get("role_coverage"),
        "after_role_coverage": after_row.get("role_coverage"),
        "before_question_coverage": before_row.get("question_coverage"),
        "after_question_coverage": after_row.get("question_coverage"),
        "stage_change_count": len(stage_changes),
        "stage_changes": stage_changes[:MAX_COMPARISON_CHANGE_ITEMS],
        "stages_truncated": len(stage_changes) > MAX_COMPARISON_CHANGE_ITEMS,
    }


def _dimension_comparison(before: Mapping, after: Mapping) -> dict:
    before_dimensions = _indexed(
        (before.get("dimensions") or {}).get("dimensions"), "dimension_id"
    )
    after_dimensions = _indexed(
        (after.get("dimensions") or {}).get("dimensions"), "dimension_id"
    )
    dimension_ids = sorted(set(before_dimensions) | set(after_dimensions))
    dimension_changes = [
        {
            "dimension_id": key,
            "before_score": before_dimensions.get(key, {}).get("score"),
            "after_score": after_dimensions.get(key, {}).get("score"),
            "score_delta": _delta(
                before_dimensions.get(key, {}).get("score"),
                after_dimensions.get(key, {}).get("score"),
            ),
            "before_coverage": before_dimensions.get(key, {}).get("coverage"),
            "after_coverage": after_dimensions.get(key, {}).get("coverage"),
            "coverage_delta": _delta(
                before_dimensions.get(key, {}).get("coverage"),
                after_dimensions.get(key, {}).get("coverage"),
            ),
        }
        for key in dimension_ids
        if before_dimensions.get(key) != after_dimensions.get(key)
    ]
    return {
        "changed_count": len(dimension_changes),
        "changes": dimension_changes[:MAX_COMPARISON_CHANGE_ITEMS],
        "truncated": len(dimension_changes) > MAX_COMPARISON_CHANGE_ITEMS,
        "composite_score_delta": _delta(
            (before.get("dimensions") or {}).get("composite_score"),
            (after.get("dimensions") or {}).get("composite_score"),
        ),
        "composite_coverage_delta": _delta(
            (before.get("dimensions") or {}).get("composite_coverage"),
            (after.get("dimensions") or {}).get("composite_coverage"),
        ),
    }


def _coverage_comparison(before: Mapping, after: Mapping) -> dict:
    return {
        "answered_ratio_delta": _delta(
            (before.get("coverage") or {}).get("answered_ratio"),
            (after.get("coverage") or {}).get("answered_ratio"),
        ),
        "denominator_before": (before.get("coverage") or {}).get("denominator", 0),
        "denominator_after": (after.get("coverage") or {}).get("denominator", 0),
    }


async def _facts(session: AsyncSession, crawl_id: uuid.UUID) -> dict[str, dict]:
    rows = (
        await session.execute(
            select(
                KnowledgeEntity.entity_type_id,
                KnowledgeEntity.identity_key,
                KnowledgeAssertion.predicate_id,
                KnowledgeAssertion.scope_key,
                KnowledgeAssertion.normalized_value,
                KnowledgeAssertion.id,
            )
            .join(
                KnowledgeEntity,
                KnowledgeEntity.id == KnowledgeAssertion.subject_entity_id,
            )
            .where(KnowledgeAssertion.crawl_id == crawl_id)
        )
    ).all()
    grouped: dict[str, dict] = {}
    for row in rows:
        key = "|".join(
            (
                row.entity_type_id,
                row.identity_key,
                row.predicate_id,
                row.scope_key,
            )
        )
        item = grouped.setdefault(
            key,
            {
                "subject": {
                    "entity_type_id": row.entity_type_id,
                    "identity_key": row.identity_key,
                },
                "predicate_id": row.predicate_id,
                "scope_key": row.scope_key,
                "values": [],
                "assertion_ids": [],
            },
        )
        item["values"].append(row.normalized_value)
        item["assertion_ids"].append(str(row.id))
    for item in grouped.values():
        item["values"].sort()
        item["assertion_ids"].sort()
    return grouped


def _map_changes(before: Mapping[str, dict], after: Mapping[str, dict]) -> dict:
    keys = sorted(set(before) | set(after))
    changes = [
        {"target_key": key, "before": before.get(key), "after": after.get(key)}
        for key in keys
        if before.get(key) != after.get(key)
    ]
    added = sum(key not in before for key in keys if before.get(key) != after.get(key))
    removed = sum(key not in after for key in keys if before.get(key) != after.get(key))
    return {
        "before_count": len(before),
        "after_count": len(after),
        "added_count": added,
        "removed_count": removed,
        "changed_count": len(changes) - added - removed,
        "changes": changes[:MAX_COMPARISON_CHANGE_ITEMS],
        "truncated": len(changes) > MAX_COMPARISON_CHANGE_ITEMS,
    }


async def _rules(session: AsyncSession, crawl_id: uuid.UUID) -> dict[str, dict]:
    ranked = (
        select(
            SitePageAnalysis.id.label("analysis_id"),
            SitePageAnalysis.site_url_id.label("site_url_id"),
            func.row_number()
            .over(
                partition_by=SitePageAnalysis.site_url_id,
                order_by=(
                    SitePageAnalysis.created_at.desc(),
                    SitePageAnalysis.id.desc(),
                ),
            )
            .label("latest_rank"),
        )
        .where(
            SitePageAnalysis.crawl_id == crawl_id,
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            SitePageAnalysis.is_current.is_(True),
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                ranked.c.site_url_id,
                SiteRuleEvaluation.id,
                SiteRuleEvaluation.rule_id,
                SiteRuleEvaluation.outcome,
            )
            .join(
                SiteRuleEvaluation,
                SiteRuleEvaluation.analysis_id == ranked.c.analysis_id,
            )
            .where(ranked.c.latest_rank == 1)
            .order_by(ranked.c.site_url_id, SiteRuleEvaluation.rule_id)
        )
    ).all()
    return {
        f"{row.site_url_id}|{row.rule_id}": {
            "site_url_id": str(row.site_url_id),
            "rule_id": row.rule_id,
            "outcome": row.outcome,
            "evaluation_id": str(row.id),
        }
        for row in rows
    }


async def _action_resolutions(
    session: AsyncSession,
    *,
    prior_crawl_id: uuid.UUID,
    current_rules: Mapping[str, dict],
) -> dict:
    issues = (
        await session.execute(
            select(SiteIssue, SiteUrl.normalized_url)
            .join(SiteUrl, SiteUrl.id == SiteIssue.site_url_id)
            .where(SiteIssue.crawl_id == prior_crawl_id)
            .order_by(SiteIssue.rule_id, SiteIssue.site_url_id, SiteIssue.id)
        )
    ).all()
    by_rule: dict[str, list[tuple[SiteIssue, str]]] = defaultdict(list)
    for issue, normalized_url in issues:
        opportunity_rule_id = SITE_ISSUE_TO_OPPORTUNITY_RULE_ID.get(issue.rule_id)
        if opportunity_rule_id is not None:
            by_rule[opportunity_rule_id].append((issue, normalized_url))
    resolutions = []
    for opportunity_rule_id, prior_issues in sorted(by_rule.items()):
        targets = []
        passed = 0
        outcomes: list[str | None] = []
        for issue, normalized_url in prior_issues:
            current = current_rules.get(f"{issue.site_url_id}|{issue.rule_id}")
            outcome = current.get("outcome") if current else None
            outcome = outcome if isinstance(outcome, str) else None
            outcomes.append(outcome)
            observed_pass = outcome == RULE_OUTCOME_PASS
            passed += int(observed_pass)
            targets.append(
                {
                    "site_url_id": str(issue.site_url_id),
                    "target_key": f"url:{normalized_url}",
                    "source_rule_id": issue.rule_id,
                    "prior_issue_id": str(issue.id),
                    "current_evaluation_id": current.get("evaluation_id")
                    if current
                    else None,
                    "current_outcome": outcome or "unavailable",
                    "observed_pass": observed_pass,
                }
            )
        state = action_resolution_state(outcomes)
        resolutions.append(
            {
                "opportunity_rule_id": opportunity_rule_id,
                "state": state,
                "verified_targets": passed,
                "target_count": len(targets),
                "targets": targets[:MAX_COMPARISON_CHANGE_ITEMS],
                "truncated": len(targets) > MAX_COMPARISON_CHANGE_ITEMS,
            }
        )
    counts = {
        state: sum(item["state"] == state for item in resolutions)
        for state in (
            ACTION_RESOLUTION_VERIFIED,
            ACTION_RESOLUTION_PARTIAL,
            ACTION_RESOLUTION_UNRESOLVED,
        )
    }
    return {
        "total": len(resolutions),
        "state_counts": counts,
        "items": resolutions[:MAX_COMPARISON_CHANGE_ITEMS],
        "truncated": len(resolutions) > MAX_COMPARISON_CHANGE_ITEMS,
    }


async def build_snapshot_comparison(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    intelligence: Mapping,
    analyzer_version: str,
    scoring_version: str,
    intelligence_version: str,
    scores: Mapping[str, float | int | None],
) -> tuple[uuid.UUID | None, dict]:
    """Compare only with the immediately preceding snapshot when compatible."""
    prior = await session.scalar(
        select(SiteHealthSnapshot)
        .join(SiteCrawl, SiteCrawl.id == SiteHealthSnapshot.crawl_id)
        .where(
            SiteHealthSnapshot.workspace_id == crawl.workspace_id,
            SiteHealthSnapshot.project_id == crawl.project_id,
            SiteHealthSnapshot.crawl_id != crawl.id,
            or_(
                SiteCrawl.created_at < crawl.created_at,
                and_(SiteCrawl.created_at == crawl.created_at, SiteCrawl.id < crawl.id),
            ),
        )
        .order_by(
            SiteCrawl.created_at.desc(),
            SiteCrawl.id.desc(),
            SiteHealthSnapshot.created_at.desc(),
            SiteHealthSnapshot.id.desc(),
        )
        .limit(1)
    )
    base = {"version": SNAPSHOT_COMPARISON_VERSION, "available": False}
    if prior is None:
        return None, {**base, "reason": "no_prior_snapshot"}
    reason = _compatibility_reason(
        prior,
        current_manifest=_manifest(intelligence),
        analyzer_version=analyzer_version,
        scoring_version=scoring_version,
        intelligence_version=intelligence_version,
    )
    if reason is not None:
        return prior.id, {**base, "reason": reason, "prior_snapshot_id": str(prior.id)}

    prior_payload = (
        prior.intelligence if isinstance(prior.intelligence, Mapping) else {}
    )
    before_facts, after_facts = (
        await _facts(session, prior.crawl_id),
        await _facts(session, crawl.id),
    )
    before_rules, after_rules = (
        await _rules(session, prior.crawl_id),
        await _rules(session, crawl.id),
    )
    projection = _projection_comparison(prior_payload, intelligence)
    return prior.id, {
        "version": SNAPSHOT_COMPARISON_VERSION,
        "available": True,
        "reason": None,
        "prior_snapshot_id": str(prior.id),
        "prior_crawl_id": str(prior.crawl_id),
        "facts": _map_changes(before_facts, after_facts),
        "rules": _map_changes(before_rules, after_rules),
        **projection,
        "scores": {
            "technical_delta": _delta(
                prior.technical_score, scores.get("technical_score")
            ),
            "aeo_delta": _delta(prior.aeo_score, scores.get("aeo_score")),
            "overall_delta": _delta(prior.overall_score, scores.get("overall_score")),
            "analyzed_url_delta": _delta(
                prior.analyzed_url_count, scores.get("analyzed_url_count")
            ),
            "issue_count_delta": _delta(prior.issue_count, scores.get("issue_count")),
        },
        "action_resolutions": await _action_resolutions(
            session, prior_crawl_id=prior.crawl_id, current_rules=after_rules
        ),
    }
