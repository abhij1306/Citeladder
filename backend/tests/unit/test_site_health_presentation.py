"""Unit tests for the pure Site Health row projections (plan P3.3).

These shapers are the whole contract between persisted rows and the wire: model
aliases, the Free count redaction, the derived fact counts, and the "current
catalog title" rule. Until the service was split they were only reachable
through component tests with a database, so a projection bug had to be found by
a full API round trip. They are pure functions over already-loaded rows — this
file tests them as such.

``presentation_status_for`` / ``_score_summary`` / ``display_label_for`` are
covered in ``test_site_health_service_pure.py``; this file is the row shapers.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

from app.core.config.site_health_rules import (
    SITE_HEALTH_RULES_BY_ID,
)
from app.domain.site_health.service.facts_projection import project_page_facts
from app.domain.site_health.service.presentation import (
    _delivery_facts,
    _evaluation_row,
    _issue_row,
    _matches_page_status,
    _page_kind_matches,
    display_label_for,
    project_crawl,
)
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl

_page_facts = project_page_facts

_NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def _crawl(**overrides: object) -> SiteCrawl:
    row = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "profile_id": uuid.uuid4(),
        "status": "running",
        "discovery_status": "running",
        "analysis_status": "pending",
        "root_url": "https://example.com/",
        "sample_mode": False,
        "random_seed": "seed-1",
        "inventory_complete": False,
        "admitted_url_count": 7,
        "analyzed_url_count": 3,
        "failed_url_count": 1,
        "discovered_url_count": 42,
        "discovery_requested_count": 42,
        "analysis_requested_count": 7,
        "score_summary": None,
        "site_facts": None,
        "configuration": {"count_disclosure": True},
        "extractor_version": "e1",
        "analyzer_version": "a1",
        "rule_catalog_version": "r1",
        "scoring_version": "s1",
        "error_message": None,
        "created_at": _NOW,
        "updated_at": _NOW,
        "started_at": _NOW,
        "completed_at": None,
    }
    row.update(overrides)
    return cast(SiteCrawl, SimpleNamespace(**row))


# --------------------------------------------------------------------------
# project_crawl: model aliases + Free redaction
# --------------------------------------------------------------------------


def test_project_crawl_aliases_model_columns_to_the_contract() -> None:
    crawl = _crawl()
    out = project_crawl(crawl)

    assert out["seed"] == "seed-1"  # random_seed
    assert out["visible_url_count"] == 7  # admitted_url_count
    assert out["analyzed_count"] == 3  # analyzed_url_count
    assert out["failed_count"] == 1  # failed_url_count
    assert out["rule_version"] == "r1"  # rule_catalog_version
    # A null error message projects as "" (the contract has no null there).
    assert out["error_message"] == ""
    assert out["created_at"] == _NOW.isoformat()
    assert out["completed_at"] is None


def test_project_crawl_withholds_the_total_until_inventory_is_complete() -> None:
    # `discovered_count` is live; `total_url_count` is only a TOTAL once the
    # inventory is closed, and `has_more_site_urls` says so meanwhile.
    running = project_crawl(_crawl(inventory_complete=False))
    assert running["discovered_count"] == 42
    assert running["total_url_count"] is None
    assert running["has_more_site_urls"] is True

    done = project_crawl(_crawl(inventory_complete=True))
    assert done["total_url_count"] == 42
    assert done["has_more_site_urls"] is False


def test_project_crawl_never_reports_a_total_below_the_admitted_inventory() -> None:
    # `discovered_url_count` counts the pages discovery FETCHED, so a
    # sitemap-driven crawl (one root fetch, fifty URLs admitted from the
    # sitemap) leaves it at 1 while the crawl holds -- and analyzes -- fifty.
    # Publishing that as the site total rendered "49/1 analyzed".
    sitemap_driven = project_crawl(
        _crawl(
            inventory_complete=True,
            discovered_url_count=1,
            admitted_url_count=50,
            analyzed_url_count=49,
        )
    )

    assert sitemap_driven["total_url_count"] == 50
    assert sitemap_driven["discovered_count"] == 50
    assert sitemap_driven["total_url_count"] >= sitemap_driven["analyzed_count"]


def test_project_crawl_redacts_every_count_field_for_a_sample_crawl() -> None:
    # The frozen `count_disclosure` snapshot is the authority (a later
    # allowance change must not retroactively reveal a sample crawl's counts).
    out = project_crawl(
        _crawl(
            configuration={"count_disclosure": False},
            inventory_complete=True,
            sample_mode=True,
        )
    )
    assert out["discovered_count"] is None
    assert out["total_url_count"] is None
    assert out["has_more_site_urls"] is None
    # The visible (admitted) count is NOT a full-site total, so it survives.
    assert out["visible_url_count"] == 7


def test_project_crawl_fails_closed_without_a_frozen_disclosure() -> None:
    # A crawl whose configuration never froze `count_disclosure` redacts
    # (fail-closed); only an explicit frozen True discloses counts.
    unfrozen = project_crawl(_crawl(configuration={}))
    disclosed = project_crawl(_crawl(configuration={"count_disclosure": True}))
    assert unfrozen["discovered_count"] is None
    assert unfrozen["total_url_count"] is None
    assert disclosed["discovered_count"] == 42


# --------------------------------------------------------------------------
# _page_facts / _delivery_facts: derived counts over a normalized-facts blob
# --------------------------------------------------------------------------


def test_page_facts_derives_counts_from_the_normalized_blob() -> None:
    out = _page_facts(
        {
            "title": "Pricing",
            "meta_description": "",
            "canonical_url": "https://example.com/pricing",
            "robots": {"noindex": True, "nofollow": False},
            "headings": {"h1_count": 1, "counts": {"h1": 1, "h2": 3}},
            "images": {"count": 5, "missing_alt": 2},
            "body": {"word_count": 812},
            "structured_data": {"types": ["Product", "FAQPage"]},
            "links": {
                "anchors": [
                    {"is_internal": True},
                    {"is_internal": True},
                    {"is_internal": False},
                ]
            },
        }
    )

    assert out["title"] == "Pricing"
    # Empty strings normalize to null rather than rendering as blank copy.
    assert out["meta_description"] is None
    assert out["robots_directives"] == ["noindex"]
    assert out["h1_count"] == 1
    assert out["heading_count"] == 4  # summed over every level
    assert out["image_count"] == 5
    assert out["image_missing_alt_count"] == 2
    assert out["word_count"] == 812
    assert out["internal_link_count"] == 2
    assert out["external_link_count"] == 1  # anchors - internal
    assert out["structured_data_types"] == ["Product", "FAQPage"]


def test_page_facts_of_a_missing_blob_is_zeros_not_nulls() -> None:
    # A not-yet-analyzed page still renders the facts panel; the counts are
    # genuinely zero and must not come back as None (or blow up).
    out = _page_facts(None)
    assert out["title"] is None
    assert out["robots_directives"] == []
    assert out["heading_count"] == 0
    assert out["internal_link_count"] == 0
    assert out["structured_data_types"] == []


def test_delivery_facts_never_claims_field_cwv() -> None:
    out = _delivery_facts(
        {
            "delivery": {
                "status_code": 200,
                "ttfb_ms": 120.5,
                "wire_bytes": 4096,
                "decoded_bytes": 8192,
                "http_version": "HTTP/2",
                "content_encoding": "gzip",
                "cache_control": "public, max-age=60",
            },
            "blocking_resources": {"total": 3},
        },
        html_bytes=8192,
    )

    # These are static HTTP measurements, never browser-rendered vitals.
    assert out["field_cwv_available"] is False
    assert out["status_code"] == 200
    assert out["ttfb_ms"] == 120.5
    assert out["compression"] == "gzip"  # content_encoding alias
    assert out["cache_control"] == "public, max-age=60"
    assert out["blocking_resource_count"] == 3
    assert out["html_bytes"] == 8192


def test_delivery_facts_distinguishes_unknown_from_zero() -> None:
    # No blocking-resource evidence is None ("we did not measure"), which the
    # UI renders as the placeholder — never as a reassuring 0.
    out = _delivery_facts({}, html_bytes=None)
    assert out["blocking_resource_count"] is None
    assert out["status_code"] is None
    assert out["compression"] is None
    assert out["html_bytes"] is None


# --------------------------------------------------------------------------
# Row projections: evaluations, links, issues
# --------------------------------------------------------------------------


def test_evaluation_row_titles_from_the_CURRENT_catalog() -> None:
    evaluation_id = uuid.uuid4()
    rule_id = "technical.title_present"
    row = _evaluation_row(
        cast(
            SiteRuleEvaluation,
            SimpleNamespace(
                id=evaluation_id,
                rule_id=rule_id,
                dimension="technical",
                category="metadata",
                severity="high",
                finding_class="defect",
                outcome="missing",
                display_applicability=True,
                score_applicability=True,
                expected_profile_membership=True,
                reason_code="",
                score_roles=["web_fundamentals"],
                checkpoint_family="",
                readiness_dimension="",
                readiness_weight=0.0,
                weight=1.0,
                evidence=None,
                analyzer_version="a1",
                rule_version="r1",
                created_at=_NOW,
            ),
        )
    )

    assert row["id"] == evaluation_id
    # The persisted row carries no title: it is read from the live catalog so a
    # relabelled rule reads correctly on old evidence. Asserted against the
    # catalog entry itself — this test is about the LOOKUP, so relabelling a
    # rule must not have to touch it (the exact copy is pinned by the literal
    # in ``test_issue_row_carries_the_affected_count_passed_by_the_caller``).
    assert row["title"] == SITE_HEALTH_RULES_BY_ID[rule_id].display_label
    assert row["evidence"] == {}  # null evidence projects as an empty object
    assert row["created_at"] == _NOW.isoformat()


def test_single_h1_title_names_which_side_of_the_rule_fired() -> None:
    """``h1_count != 1`` covers opposite failures; the row must say which.

    A shared title had to read "Multiple or missing H1", which tells a reader
    neither what happened nor what to do about it.
    """
    assert display_label_for("technical.single_h1", {"h1_count": 0}) == (
        "Missing H1 heading"
    )
    assert display_label_for("technical.single_h1", {"h1_count": 3}) == (
        "More than one H1 heading"
    )
    # No evidence (grouped rows span both directions) keeps the neutral title.
    neutral = SITE_HEALTH_RULES_BY_ID["technical.single_h1"].display_label
    assert display_label_for("technical.single_h1") == neutral
    assert display_label_for("technical.single_h1", {}) == neutral
    # The PASSING count has no failure to name. Evaluations are projected for
    # every outcome, so without this the healthy one-H1 row read "More than
    # one H1 heading".
    assert display_label_for("technical.single_h1", {"h1_count": 1}) == neutral


def test_display_label_ignores_evidence_for_rules_without_variants() -> None:
    rule_id = "technical.title_present"
    assert display_label_for(rule_id, {"h1_count": 0}) == (
        SITE_HEALTH_RULES_BY_ID[rule_id].display_label
    )
    assert display_label_for("nope.not_a_rule", {"h1_count": 0}) == "nope.not_a_rule"


def test_issue_row_projects_one_occurrence_with_its_evaluation_and_url() -> None:
    """Occurrence DTOs own page identity and evaluation context directly."""
    occurrence_id = uuid.uuid4()
    evaluation_id = uuid.uuid4()
    site_url_id = uuid.uuid4()
    row = _issue_row(
        cast(
            SiteIssue,
            SimpleNamespace(
                id=occurrence_id,
                evaluation_id=evaluation_id,
                crawl_id=uuid.uuid4(),
                rule_id="aeo.structured_data_present",
                dimension="aeo",
                category="structured_data",
                severity="medium",
                finding_class="defect",
                description="Structured data is missing.",
                remediation=None,
                evidence=None,
                analyzer_version="a1",
                rule_version="r1",
                created_at=_NOW,
            ),
        ),
        cast(SiteRuleEvaluation, SimpleNamespace(reason_code="missing_schema")),
        site_url_id=site_url_id,
        normalized_url="https://example.com/products/widget",
        display_url="https://example.com/products/widget",
        page_title="Widget",
        page_kind="product",
    )

    assert row["occurrence_id"] == occurrence_id
    assert row["evaluation_id"] == evaluation_id
    assert row["site_url_id"] == site_url_id
    assert row["normalized_url"] == "https://example.com/products/widget"
    assert row["title"] == "Widget"
    assert row["page_kind"] == "product"
    assert row["reason_code"] == "missing_schema"
    assert row["issue_title"] == "Missing structured data"
    assert row["remediation"] == ""


# --------------------------------------------------------------------------
# Filter predicates (shared by inventory and pages)
# --------------------------------------------------------------------------


def test_page_type_filter_requires_a_classified_analysis() -> None:
    analysis = cast(SitePageAnalysis, SimpleNamespace(page_kind="product"))
    assert _page_kind_matches(analysis, None) is True  # unfiltered
    assert _page_kind_matches(analysis, "product") is True
    assert _page_kind_matches(analysis, "article") is False
    # An unanalyzed URL has no type, so it never matches a filtered request.
    assert _page_kind_matches(None, "product") is False
    assert _page_kind_matches(None, None) is True


def test_error_or_blocked_is_one_combined_status_filter() -> None:
    assert _matches_page_status("error", "error_or_blocked") is True
    assert _matches_page_status("blocked", "error_or_blocked") is True
    assert _matches_page_status("completed", "error_or_blocked") is False
    assert _matches_page_status("completed", None) is True
    assert _matches_page_status("completed", "completed") is True
