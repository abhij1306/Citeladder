"""Pure composition of Site Health page understanding and measurement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analysis.site_health.page_kinds import PageKindAssessment, classify
from app.analysis.site_health.page_traits import derive_traits
from app.analysis.site_health.rules import RuleEvaluation, evaluate_rule
from app.analysis.site_health.scoring import AnalysisScores, score_analysis
from app.core.config.site_health_contracts import APPLICABILITY_CRAWL_FINALIZE
from app.core.config.site_health_rules import SITE_HEALTH_RULES


@dataclass(frozen=True)
class PageAnalysisResult:
    """One deterministic interpretation of immutable extracted page facts."""

    assessment: PageKindAssessment
    traits: tuple[str, ...]
    evaluations: tuple[RuleEvaluation, ...]
    scores: AnalysisScores


def analyze_page(
    facts: dict[str, Any],
    *,
    sitemap_member: bool = False,
    site_facts: dict[str, Any] | None = None,
) -> PageAnalysisResult:
    """Classify, evaluate, and score one page without mutating its facts.

    ``site_facts`` must be supplied only for the crawl root. Finalize-scoped
    rules are excluded because their persisted evaluations have a separate
    single writer after crawl convergence.
    """
    final_url = str((facts.get("delivery") or {}).get("final_url") or "")
    assessment = classify(final_url, facts)
    traits = derive_traits(final_url, facts)
    evaluation_facts = {
        **facts,
        "page_kind": assessment.page_kind,
        "page_kind_evidence": assessment.to_evidence(),
        "page_traits": list(traits),
        "sitemap_member": sitemap_member,
    }
    if site_facts is not None:
        evaluation_facts["site"] = site_facts
    evaluations = tuple(
        evaluate_rule(rule, evaluation_facts)
        for rule in SITE_HEALTH_RULES
        if rule.applicability_key != APPLICABILITY_CRAWL_FINALIZE
    )
    scores = score_analysis(
        list(evaluations),
        page_kind=assessment.page_kind,
        page_traits=traits,
        crawl_context={"is_site_root": site_facts is not None},
    )
    return PageAnalysisResult(assessment, traits, evaluations, scores)
