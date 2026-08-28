"""Portfolio source/action projection over persisted visibility-gap answers."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.analysis.opportunities.detectors import (
    AnalysisEvidence,
    PromptSnapshotEvidence,
)
from app.analysis.opportunities.source_patterns import by_domain
from app.core.config.opportunities import (
    ACTION_PATH_EARNED,
    ACTION_PATH_OWNED,
    EARNED_COMPETITOR_FACTOR_MAX,
    EARNED_SOURCE_MIN_ANSWERS,
    EARNED_SOURCE_MIN_USAGE_RATE,
    EARNED_SUGGESTED_ROLE_BY_CLASS,
    EARNED_SUGGESTED_SKILL_BY_CLASS,
    EARNED_USAGE_FACTOR_MAX,
    SOURCE_ROLLUP_MAX_DOMAINS,
    SOURCE_ROLLUP_MAX_PROMPTS,
    SOURCE_ROLLUP_MAX_URLS,
)
from app.core.config.source_patterns import (
    SOURCE_CLASS_BRAND_OWNED,
    SOURCE_CLASS_COMPETITOR_OWNED,
    SOURCE_CLASS_OTHER_THIRD_PARTY,
    SOURCE_MIX_PROJECTION_VERSION,
    SOURCE_TAXONOMY_VERSION,
)

_OWNED = ACTION_PATH_OWNED
_COMPETITIVE = "competitive_evidence"
_EARNED = ACTION_PATH_EARNED


def observational_path(source_class: str) -> str:
    if source_class == SOURCE_CLASS_BRAND_OWNED:
        return _OWNED
    if source_class == SOURCE_CLASS_COMPETITOR_OWNED:
        return _COMPETITIVE
    return _EARNED


def action_path(source_class: str) -> str | None:
    if source_class in {SOURCE_CLASS_BRAND_OWNED, SOURCE_CLASS_COMPETITOR_OWNED}:
        return _OWNED
    if source_class != SOURCE_CLASS_OTHER_THIRD_PARTY:
        return _EARNED
    return None


def _empty(state: str, eligible: int, limitations: list[str]) -> dict[str, Any]:
    return {
        "state": state,
        "projection_version": SOURCE_MIX_PROJECTION_VERSION,
        "taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "counts": {},
        "percentages": {},
        "observation_count": 0,
        "answers_with_sources": 0,
        "eligible_analyzed_answers": eligible,
        "coverage_rate": 0.0 if eligible else None,
        "limitations": limitations,
    }


def empty_source_projection() -> dict[str, Any]:
    """The canonical not-applicable mix — the shape callers get with no gap.

    Readers always receive a well-formed projection, so "no snapshot yet" and
    "no qualifying gap" render through the same branch as a computed mix.
    """
    return _empty("not_applicable", 0, ["No qualifying visibility gap."])


def _mix(counts: dict[str, int], eligible: int, answers: int) -> dict[str, Any]:
    total = sum(counts.values())
    return {
        "state": "available",
        "projection_version": SOURCE_MIX_PROJECTION_VERSION,
        "taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "counts": {key: counts[key] for key in sorted(counts)},
        "percentages": {
            key: round(counts[key] * 100 / total, 1) for key in sorted(counts)
        },
        "observation_count": total,
        "answers_with_sources": answers,
        "eligible_analyzed_answers": eligible,
        "coverage_rate": round(answers / eligible, 4) if eligible else None,
        "limitations": [],
    }


def _answer_domains(analysis: AnalysisEvidence):
    for domain, (source_class, citation) in by_domain(analysis.citations).items():
        yield domain, source_class, citation


def build_source_projection(
    *,
    analyses: tuple[AnalysisEvidence, ...],
    snapshots: tuple[PromptSnapshotEvidence, ...],
    gap_prompt_indices: set[int],
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Return three-way mix, action-path mix, and bounded domain rollups."""
    if not gap_prompt_indices:
        empty = empty_source_projection()
        return empty, dict(empty), []
    eligible_rows = [row for row in analyses if row.prompt_index in gap_prompt_indices]
    prompt_meta = {row.prompt_index: row for row in snapshots}
    observed_counts, action_counts, rollups, answers_with_sources = _accumulate(
        eligible_rows, prompt_meta
    )
    eligible = len(eligible_rows)
    if not observed_counts:
        empty = _empty(
            "unavailable", eligible, ["Gap answers had no usable citation domains."]
        )
        return empty, dict(empty), []
    projected = [_project_rollup(value, eligible) for value in rollups.values()]
    projected.sort(key=lambda row: (-row["answer_count"], row["canonical_domain"]))
    truncated = len(projected) > SOURCE_ROLLUP_MAX_DOMAINS
    projected = projected[:SOURCE_ROLLUP_MAX_DOMAINS]
    for row in projected:
        row["projection_truncated"] = truncated
    return (
        _mix(observed_counts, eligible, answers_with_sources),
        _mix(action_counts, eligible, answers_with_sources)
        if action_counts
        else _empty(
            "unavailable", eligible, ["No class-specific action path was observed."]
        ),
        projected,
    )


def _accumulate(
    eligible_rows: list[AnalysisEvidence],
    prompt_meta: dict[int, PromptSnapshotEvidence],
) -> tuple[dict[str, int], dict[str, int], dict[str, dict[str, Any]], int]:
    observed_counts: dict[str, int] = defaultdict(int)
    action_counts: dict[str, int] = defaultdict(int)
    rollups: dict[str, dict[str, Any]] = {}
    answers_with_sources = 0
    for analysis in eligible_rows:
        domains = list(_answer_domains(analysis))
        if domains:
            answers_with_sources += 1
        prompt = prompt_meta.get(analysis.prompt_index)
        for domain, source_class, citation in domains:
            observed_counts[observational_path(source_class)] += 1
            selected_action = action_path(source_class)
            if selected_action:
                action_counts[selected_action] += 1
            item = rollups.setdefault(
                domain,
                {
                    "canonical_domain": domain,
                    "source_class": source_class,
                    "pathway": selected_action,
                    "analysis_ids": set(),
                    "artifact_ids": set(),
                    "prompt_indices": set(),
                    "themes": set(),
                    "competitors": set(),
                    "citations": {},
                },
            )
            item["analysis_ids"].add(str(analysis.analysis_id))
            if analysis.artifact_id is not None:
                item["artifact_ids"].add(str(analysis.artifact_id))
            item["prompt_indices"].add(analysis.prompt_index)
            if prompt and prompt.theme:
                item["themes"].add(prompt.theme)
            item["competitors"].update(analysis.competitor_names)
            item["citations"].setdefault(citation.url, citation.title)
    return observed_counts, action_counts, rollups, answers_with_sources


def _project_rollup(value: dict[str, Any], eligible: int) -> dict[str, Any]:
    answer_count = len(value["analysis_ids"])
    rate = answer_count / eligible if eligible else 0.0
    competitor_count = len(value["competitors"])
    usage_factor = min(EARNED_USAGE_FACTOR_MAX, 1.0 + rate)
    competitor_factor = min(EARNED_COMPETITOR_FACTOR_MAX, 1.0 + competitor_count * 0.1)
    citations = sorted(value["citations"].items())
    prompts = sorted(value["prompt_indices"])
    return {
        "canonical_domain": value["canonical_domain"],
        "source_class": value["source_class"],
        "pathway": value["pathway"],
        "answer_count": answer_count,
        "distinct_prompt_count": len(prompts),
        "prompt_indices": prompts[:SOURCE_ROLLUP_MAX_PROMPTS],
        "themes": sorted(value["themes"])[:SOURCE_ROLLUP_MAX_PROMPTS],
        "competitors": sorted(value["competitors"])[:SOURCE_ROLLUP_MAX_PROMPTS],
        "usage_numerator": answer_count,
        "usage_denominator": eligible,
        "usage_percentage": round(rate * 100, 1),
        "coverage_state": "available",
        "analysis_ids": sorted(value["analysis_ids"]),
        "artifact_ids": sorted(value["artifact_ids"]),
        "representative_citations": [
            {"url": url, "title": title}
            for url, title in citations[:SOURCE_ROLLUP_MAX_URLS]
        ],
        "truncated": len(citations) > SOURCE_ROLLUP_MAX_URLS
        or len(prompts) > SOURCE_ROLLUP_MAX_PROMPTS,
        "actionable": bool(
            value["pathway"] == _EARNED
            and answer_count >= EARNED_SOURCE_MIN_ANSWERS
            and rate >= EARNED_SOURCE_MIN_USAGE_RATE
        ),
        "usage_factor": round(usage_factor, 4),
        "competitor_cooccurrence_factor": round(competitor_factor, 4),
        "suggested_role": EARNED_SUGGESTED_ROLE_BY_CLASS.get(
            value["source_class"], "Marketing"
        ),
        "suggested_skill_id": EARNED_SUGGESTED_SKILL_BY_CLASS.get(
            value["source_class"], "article"
        ),
    }
