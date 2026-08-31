"""Unit tests for the crawl_finalize evaluators (v2 P2 — spec §5.3).

The cross-page rules are evaluated in a second pass at crawl terminalization,
owned by the finalize-writer. Their normalized observations participate in
Web Fundamentals, so a displayed issue can never coexist with an unaffected
100 score. Pure, offline.
"""

from __future__ import annotations

import pytest

from app.analysis.site_health.finalize import (
    _MAX_EVIDENCE_URLS,
    evaluate_broken_internal_links,
    evaluate_canonical_resolvable,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
    evaluate_sitemap_url_unreachable,
)
from app.core.config.site_health_contracts import (
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_GRAPH,
    RULE_SCOPE_PAGE,
    SCORE_ROLE_WEB_FUNDAMENTALS,
)


def test_finalize_rules_carry_scored_catalog_provenance():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=1, orphan_urls=[], coverage_state="complete"
    )
    assert ev.rule_id == "technical.sitemap_orphan"
    assert ev.rule_version == RULE_CATALOG_VERSION
    assert ev.dimension == DIMENSION_TECHNICAL
    assert ev.weight == 1.0
    assert ev.score_roles == (SCORE_ROLE_WEB_FUNDAMENTALS,)
    assert ev.remediation


def _assert_technical_score_metadata(ev, *, scope: str) -> None:
    assert ev.dimension == DIMENSION_TECHNICAL
    assert ev.scope == scope
    assert ev.weight == 3.0
    assert ev.score_roles == (SCORE_ROLE_WEB_FUNDAMENTALS,)
    assert ev.score_applicability is True
    assert ev.expected_profile_membership is True


# --- Technical crawl-finalize reachability ----------------------------------


def test_broken_internal_links_are_satisfied_when_no_links_need_checking():
    ev = evaluate_broken_internal_links(total_count=0, checked_count=0, broken_urls=[])
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence == {
        "total_count": 0,
        "checked_count": 0,
        "normalized_score": 1.0,
        "normalized_coverage": 1.0,
    }
    _assert_technical_score_metadata(ev, scope=RULE_SCOPE_GRAPH)


def test_broken_internal_links_report_partial_health_and_coverage():
    ev = evaluate_broken_internal_links(
        total_count=4,
        checked_count=2,
        broken_urls=["https://example.test/broken"],
    )
    assert ev.outcome == RULE_OUTCOME_PARTIAL
    assert ev.evidence["failure_count"] == 1
    assert ev.evidence["normalized_score"] == 0.5
    assert ev.evidence["normalized_coverage"] == 0.5
    _assert_technical_score_metadata(ev, scope=RULE_SCOPE_GRAPH)


def test_broken_internal_links_fail_when_every_checked_target_is_broken():
    ev = evaluate_broken_internal_links(
        total_count=2,
        checked_count=2,
        broken_urls=["https://example.test/a", "https://example.test/b"],
    )
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.evidence["normalized_score"] == 0.0
    assert ev.evidence["normalized_coverage"] == 1.0


def test_broken_internal_link_evidence_deduplicates_weighted_targets():
    ev = evaluate_broken_internal_links(
        total_count=3,
        checked_count=3,
        broken_urls=[
            "https://example.test/broken",
            "https://example.test/broken",
        ],
    )

    assert ev.evidence["failure_count"] == 1
    assert ev.evidence["failing_urls"] == ["https://example.test/broken"]
    assert ev.evidence["normalized_score"] == pytest.approx(2 / 3)


def test_broken_internal_links_remain_unknown_without_checked_targets():
    ev = evaluate_broken_internal_links(total_count=2, checked_count=0, broken_urls=[])
    assert ev.outcome == RULE_OUTCOME_UNKNOWN
    assert ev.evidence == {
        "reason": "insufficient_evidence",
        "total_count": 2,
        "checked_count": 0,
    }
    _assert_technical_score_metadata(ev, scope=RULE_SCOPE_GRAPH)


def test_sitemap_url_unreachable_is_not_applicable_without_a_sitemap():
    ev = evaluate_sitemap_url_unreachable(
        total_count=0, checked_count=0, unreachable_urls=[]
    )
    assert ev.outcome == RULE_OUTCOME_NOT_APPLICABLE
    assert ev.evidence == {"reason": "no_sitemap"}
    assert ev.score_roles == ()
    assert ev.score_applicability is False
    assert ev.expected_profile_membership is False
    assert ev.scope == RULE_SCOPE_PAGE


def test_sitemap_url_unreachable_reports_partial_and_unknown_evidence():
    partial = evaluate_sitemap_url_unreachable(
        total_count=4,
        checked_count=2,
        unreachable_urls=["https://example.test/sitemap-broken"],
    )
    assert partial.outcome == RULE_OUTCOME_PARTIAL
    assert partial.evidence["normalized_score"] == 0.5
    assert partial.evidence["normalized_coverage"] == 0.5
    _assert_technical_score_metadata(partial, scope=RULE_SCOPE_PAGE)

    unknown = evaluate_sitemap_url_unreachable(
        total_count=2, checked_count=0, unreachable_urls=[]
    )
    assert unknown.outcome == RULE_OUTCOME_UNKNOWN
    assert unknown.evidence["reason"] == "insufficient_evidence"
    _assert_technical_score_metadata(unknown, scope=RULE_SCOPE_PAGE)


def test_canonical_resolvable_passes_fails_and_preserves_unknown():
    satisfied = evaluate_canonical_resolvable(
        target_url="https://example.test/canonical",
        checked=True,
        status_code=200,
        redirected=False,
    )
    assert satisfied.outcome == RULE_OUTCOME_SATISFIED
    assert satisfied.evidence["status_code"] == 200
    _assert_technical_score_metadata(satisfied, scope=RULE_SCOPE_PAGE)

    missing = evaluate_canonical_resolvable(
        target_url="https://example.test/missing",
        checked=True,
        status_code=404,
        redirected=False,
    )
    assert missing.outcome == RULE_OUTCOME_MISSING
    assert missing.evidence["status_code"] == 404

    redirected = evaluate_canonical_resolvable(
        target_url="https://example.test/redirecting",
        checked=True,
        status_code=200,
        redirected=True,
    )
    assert redirected.outcome == RULE_OUTCOME_MISSING
    assert redirected.evidence["redirected"] is True

    unknown = evaluate_canonical_resolvable(
        target_url="https://example.test/unverified",
        checked=False,
        status_code=None,
        redirected=False,
    )
    assert unknown.outcome == RULE_OUTCOME_UNKNOWN
    assert unknown.evidence == {
        "reason": "insufficient_evidence",
        "target_url": "https://example.test/unverified",
    }
    _assert_technical_score_metadata(unknown, scope=RULE_SCOPE_PAGE)


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
    assert ev.outcome == RULE_OUTCOME_SATISFIED
    assert ev.evidence["sitemap_url_count"] == 7
    assert ev.evidence["orphan_count"] == 0


def test_sitemap_orphan_fails_with_bounded_evidence():
    orphans = [f"https://x.example/orphan-{i}" for i in range(_MAX_EVIDENCE_URLS + 2)]
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=50, orphan_urls=orphans, coverage_state="complete"
    )
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.rule_id == "technical.sitemap_orphan"
    assert ev.evidence["orphan_count"] == _MAX_EVIDENCE_URLS + 2
    assert len(ev.evidence["orphan_urls"]) == _MAX_EVIDENCE_URLS


def test_sitemap_orphan_abstains_as_unknown_when_coverage_is_not_complete():
    ev = evaluate_sitemap_orphan(
        sitemap_url_count=50,
        orphan_urls=["https://x.example/orphan"],
        coverage_state="partial",
    )
    assert ev.outcome == RULE_OUTCOME_UNKNOWN
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


def test_hreflang_conflict_is_unknown_when_nothing_is_checkable():
    # Alternates exist but none were analyzed in this crawl: absence
    # fabricates nothing, and the exact reason retains the distinction.
    ev = evaluate_hreflang_conflict(
        alternate_count=3,
        checked_count=0,
        unchecked_count=3,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_UNKNOWN
    assert ev.reason_code == "no_checkable_alternates"
    assert ev.evidence == {
        "reason": "no_checkable_alternates",
        "alternate_count": 3,
        "unchecked_count": 3,
    }


def test_hreflang_conflict_passes_when_return_tags_complete():
    ev = evaluate_hreflang_conflict(
        alternate_count=2,
        checked_count=2,
        unchecked_count=0,
        missing_return_tags=[],
    )
    assert ev.outcome == RULE_OUTCOME_SATISFIED
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
    assert ev.outcome == RULE_OUTCOME_MISSING
    assert ev.rule_id == "technical.hreflang_conflict"
    assert len(ev.evidence["missing_return_tags"]) == _MAX_EVIDENCE_URLS
    assert ev.evidence["alternate_count"] == 15
    assert ev.evidence["checked_count"] == 12
    assert ev.evidence["unchecked_count"] == 3
