"""Unit tests for the crawl_finalize evaluators (v2 P2 — spec §5.3).

The two cross-page rules (``technical.sitemap_orphan``,
``technical.hreflang_conflict``) are evaluated
in a second pass at crawl terminalization, owned by the finalize-writer. The
evaluators are pure: they take pre-normalized, bounded inputs and produce
``RuleEvaluation`` values with weight 0.0 (issues, never score denominators)
and sh-rules-2 provenance. Pure, offline.
"""

from __future__ import annotations

from app.analysis.site_health.finalize import (
    _MAX_EVIDENCE_URLS,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
)
from app.core.config.site_health_contracts import (
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_UNAVAILABLE,
)


def test_finalize_rules_carry_catalog_provenance_and_zero_weight():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=1, orphan_urls=[], coverage_state="complete"
    )
    assert ev.rule_id == "technical.sitemap_orphan"
    assert ev.rule_version == RULE_CATALOG_VERSION
    assert ev.dimension == DIMENSION_TECHNICAL
    # Weight 0: finalize rules produce issues, never score denominators.
    assert ev.weight == 0.0
    assert ev.remediation


# --- technical.sitemap_orphan ------------------------------------------------


def test_sitemap_orphan_not_applicable_without_sitemap():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=0, orphan_urls=[], coverage_state="complete"
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_sitemap"}
    assert ev.display_applicability is False
    assert ev.reason_code == "no_sitemap"


def test_sitemap_orphan_passes_when_all_linked():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=7, orphan_urls=[], coverage_state="complete"
    )
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["sitemap_url_count"] == 7
    assert ev.evidence["orphan_count"] == 0


def test_sitemap_orphan_fails_with_bounded_evidence():
    orphans = [f"https://x.example/orphan-{i}" for i in range(_MAX_EVIDENCE_URLS + 2)]
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=50, orphan_urls=orphans, coverage_state="complete"
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.rule_id == "technical.sitemap_orphan"
    assert ev.evidence["orphan_count"] == _MAX_EVIDENCE_URLS + 2
    assert len(ev.evidence["orphan_urls"]) == _MAX_EVIDENCE_URLS


def test_sitemap_orphan_abstains_when_coverage_is_not_complete():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=50,
        orphan_urls=["https://x.example/orphan"],
        coverage_state="partial",
    )
    assert ev.outcome == RULE_OUTCOME_UNAVAILABLE
    assert ev.display_applicability is True
    assert ev.reason_code == "coverage_not_complete"
    assert ev.evidence == {
        "reason": "coverage_not_complete",
        "coverage_state": "partial",
    }


# --- technical.hreflang_conflict ---------------------------------------------


def test_hreflang_conflict_not_applicable_without_hreflang():
    ev = evaluate_hreflang_conflict(
        alternate_count=0,
        checked_count=0,
        unchecked_count=0,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_hreflang"}


def test_hreflang_conflict_unavailable_when_nothing_checkable():
    # Alternates exist but none were analyzed in this crawl: absence
    # fabricates nothing — unavailable carries the counts.
    ev = evaluate_hreflang_conflict(
        alternate_count=3,
        checked_count=0,
        unchecked_count=3,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_UNAVAILABLE
    assert ev.evidence["reason"] == "no_checkable_alternates"
    assert ev.evidence["alternate_count"] == 3
    assert ev.evidence["unchecked_count"] == 3


def test_hreflang_conflict_passes_when_return_tags_complete():
    ev = evaluate_hreflang_conflict(
        alternate_count=2,
        checked_count=2,
        unchecked_count=0,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["checked_count"] == 2


def test_hreflang_conflict_fails_with_bounded_evidence():
    missing = [
        f"https://x.example/fr/missing-{i}" for i in range(_MAX_EVIDENCE_URLS + 1)
    ]
    ev = evaluate_hreflang_conflict(
        alternate_count=15,
        checked_count=12,
        unchecked_count=3,
        missing_return_tags=missing,
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.rule_id == "technical.hreflang_conflict"
    assert len(ev.evidence["missing_return_tags"]) == _MAX_EVIDENCE_URLS
    assert ev.evidence["alternate_count"] == 15
    assert ev.evidence["checked_count"] == 12
    assert ev.evidence["unchecked_count"] == 3
