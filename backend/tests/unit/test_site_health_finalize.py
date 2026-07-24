"""Unit tests for the crawl_finalize evaluators (v2 P2 — spec §5.3).

The three cross-page rules (``technical.broken_internal_link``,
``technical.sitemap_orphan``, ``technical.hreflang_conflict``) are evaluated
in a second pass at crawl terminalization, owned by the finalize-writer. The
evaluators are pure: they take pre-normalized, bounded inputs and produce
``RuleEvaluation`` values with weight 0.0 (issues, never score denominators)
and sh-rules-2 provenance. Pure, offline.
"""

from __future__ import annotations

from app.analysis.site_health.finalize import (
    _MAX_EVIDENCE_URLS,
    evaluate_broken_internal_link,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
)
from app.core.config.site_health import (
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)


def test_finalize_rules_carry_catalog_provenance_and_zero_weight():
    ev = evaluate_broken_internal_link(checked_count=1, broken_urls=[])
    assert ev.rule_id == "technical.broken_internal_link"
    assert ev.rule_version == RULE_CATALOG_VERSION
    assert ev.dimension == DIMENSION_TECHNICAL
    # Weight 0: finalize rules produce issues, never score denominators.
    assert ev.weight == 0.0
    assert ev.remediation


# --- technical.broken_internal_link -----------------------------------------


def test_broken_internal_link_not_applicable_without_checked_links():
    ev = evaluate_broken_internal_link(checked_count=0, broken_urls=[])
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_internal_links"}


def test_broken_internal_link_passes_when_all_reachable():
    ev = evaluate_broken_internal_link(checked_count=4, broken_urls=[])
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["checked_count"] == 4
    assert ev.evidence["broken_count"] == 0
    assert ev.evidence["broken_urls"] == []


def test_broken_internal_link_fails_with_bounded_evidence():
    broken = [f"https://x.example/dead-{i}" for i in range(_MAX_EVIDENCE_URLS + 5)]
    ev = evaluate_broken_internal_link(checked_count=20, broken_urls=broken)
    assert ev.outcome == RULE_OUTCOME_FAIL
    # The true count is preserved; the URL list is bounded.
    assert ev.evidence["broken_count"] == _MAX_EVIDENCE_URLS + 5
    assert len(ev.evidence["broken_urls"]) == _MAX_EVIDENCE_URLS
    assert ev.evidence["checked_count"] == 20


# --- technical.sitemap_orphan ------------------------------------------------


def test_sitemap_orphan_not_applicable_without_sitemap():
    ev = evaluate_sitemap_orphan(sitemap_url_count=0, orphan_urls=[])
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_sitemap"}


def test_sitemap_orphan_passes_when_all_linked():
    ev = evaluate_sitemap_orphan(sitemap_url_count=7, orphan_urls=[])
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["sitemap_url_count"] == 7
    assert ev.evidence["orphan_count"] == 0


def test_sitemap_orphan_fails_with_bounded_evidence():
    orphans = [f"https://x.example/orphan-{i}" for i in range(_MAX_EVIDENCE_URLS + 2)]
    ev = evaluate_sitemap_orphan(sitemap_url_count=50, orphan_urls=orphans)
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.rule_id == "technical.sitemap_orphan"
    assert ev.evidence["orphan_count"] == _MAX_EVIDENCE_URLS + 2
    assert len(ev.evidence["orphan_urls"]) == _MAX_EVIDENCE_URLS


# --- technical.hreflang_conflict ---------------------------------------------


def test_hreflang_conflict_not_applicable_without_hreflang():
    ev = evaluate_hreflang_conflict(
        alternate_count=0, checked_count=0, unchecked_count=0,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_hreflang"}


def test_hreflang_conflict_not_applicable_when_nothing_checkable():
    # Alternates exist but none were analyzed in this crawl: absence
    # fabricates nothing — N/A carrying the counts.
    ev = evaluate_hreflang_conflict(
        alternate_count=3, checked_count=0, unchecked_count=3,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence["reason"] == "no_checkable_alternates"
    assert ev.evidence["alternate_count"] == 3
    assert ev.evidence["unchecked_count"] == 3


def test_hreflang_conflict_passes_when_return_tags_complete():
    ev = evaluate_hreflang_conflict(
        alternate_count=2, checked_count=2, unchecked_count=0,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_PASS
    assert ev.evidence["checked_count"] == 2


def test_hreflang_conflict_fails_with_bounded_evidence():
    missing = [
        f"https://x.example/fr/missing-{i}" for i in range(_MAX_EVIDENCE_URLS + 1)
    ]
    ev = evaluate_hreflang_conflict(
        alternate_count=15, checked_count=12, unchecked_count=3,
        missing_return_tags=missing,
    )
    assert ev.outcome == RULE_OUTCOME_FAIL
    assert ev.rule_id == "technical.hreflang_conflict"
    assert len(ev.evidence["missing_return_tags"]) == _MAX_EVIDENCE_URLS
    assert ev.evidence["alternate_count"] == 15
    assert ev.evidence["checked_count"] == 12
    assert ev.evidence["unchecked_count"] == 3
