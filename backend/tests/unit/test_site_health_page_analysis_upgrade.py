"""Focused fixtures for page-type evidence, Product/Offer rules, and history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.analysis.opportunities.detectors import _site_opportunity_rule_id
from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.rules import evaluate_all, rule_for
from app.core.config.opportunities import SITE_ISSUE_TO_OPPORTUNITY_RULE_ID
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_PROFILES,
)
from app.domain.site_health.service.issue_history import (
    _group_issue_history,
    _HistoryObservation,
)


def _outcome(facts: dict, rule_id: str):
    return next(item for item in evaluate_all(facts) if item.rule_id == rule_id)


def test_classification_evidence_has_alternatives_conflicts_and_other_reason() -> None:
    assessment = classify(
        "https://example.test/products/widget",
        {"structured_data": {"types": ["Article"]}},
    )

    evidence = assessment.to_evidence()
    assert assessment.page_kind == "product"
    assert evidence["alternatives"] == [
        {
            "page_kind": "article",
            "tier": "semantic",
            "signals": ["structured_data"],
        }
    ]
    assert evidence["conflicts"][0]["conflicting_page_kind"] == "article"
    assert (
        classify("https://example.test/unclassified", {}).to_evidence()["other_reason"]
        == "no_classification_signals"
    )


def test_all_configured_page_types_have_profile_and_schema_contract() -> None:
    assert set(PAGE_KIND_PROFILES) == set(PAGE_KIND_EXPECTED_SCHEMA)
    assert set(PAGE_KIND_PROFILES) >= {
        "homepage",
        "product",
        "category",
        "service",
        "local",
        "article",
        "guide",
        "comparison",
        "faq",
        "docs",
        "pricing",
        "about_contact",
        "case_study_review",
        "trust_policy",
        "other",
    }


def test_product_offer_facts_and_visible_schema_parity_fixture() -> None:
    facts = extract_page_facts(
        b"""<html><head><title>Widget Pro</title>
        <script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Product", "name":"Widget Pro",
          "sku":"W-100", "gtin13":"1234567890123",
          "brand":{"@type":"Brand","name":"Acme"},
          "aggregateRating":{"@type":"AggregateRating","ratingValue":"4.8"},
          "hasVariant":{"@type":"Product","name":"Widget Pro Blue"},
          "offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD",
          "availability":"https://schema.org/InStock",
          "shippingDetails":{"@type":"OfferShippingDetails"},
          "hasMerchantReturnPolicy":{"@type":"MerchantReturnPolicy"}}
        }</script></head><body><h1>Widget Pro</h1>
        <p>Acme Widget Pro, SKU W-100, GTIN 1234567890123, is in stock
        for 19.99 USD.</p>
        </body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"

    product = facts["structured_data"]["product"]
    assert product["sku"] == ["W-100"]
    assert product["gtin"] == ["1234567890123"]
    assert product["brand"] == ["Acme"]
    assert product["price"] == ["19.99"]
    assert product["price_currency"] == ["USD"]
    assert product["ratings"] == ["4.8"]
    assert product["shipping"] is True and product["returns"] is True
    assert _outcome(facts, "aeo.product_offer_details").outcome == "pass"
    assert _outcome(facts, "aeo.product_visible_schema_parity").outcome == "pass"


def test_declared_product_offer_requires_all_offer_fields() -> None:
    facts = extract_page_facts(
        b"""<html><head><script type="application/ld+json">{
        "@context":"https://schema.org", "@type":"Product", "name":"Widget",
        "sku":"W-100", "brand":"Acme",
        "offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD"}
        }</script></head><body><h1>Widget</h1></body></html>""",
        final_url="https://example.test/products/widget",
    )
    facts["page_kind"] = "product"

    outcome = _outcome(facts, "aeo.product_offer_details")
    assert outcome.outcome == "fail"
    assert outcome.evidence["offer_declared"] is True
    assert outcome.evidence["missing"] == ["offers.availability"]


def test_product_visible_schema_parity_fails_on_persisted_conflict() -> None:
    facts = extract_page_facts(
        b"""<html><head><title>Widget Pro</title><script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Widget Pro",
        "sku":"W-100","brand":"Acme","offers":{"@type":"Offer","price":"19.99",
        "priceCurrency":"USD","availability":"InStock"}}</script></head>
        <body><h1>Widget Pro</h1><p>Acme Widget Pro is currently unavailable
        for 29.99 USD.</p></body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"
    parity = _outcome(facts, "aeo.product_visible_schema_parity")
    assert parity.outcome == "fail"
    assert parity.evidence["mismatch_count"] >= 1


def test_product_parity_does_not_match_inside_a_longer_field() -> None:
    facts = extract_page_facts(
        b"""<html><head><title>Widget Pro</title>
        <script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Product",
          "name":"Widget Pro", "sku":"W-10"
        }</script></head><body><h1>Widget Pro</h1>
        <p>SKU W-100</p></body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"

    parity = _outcome(facts, "aeo.product_visible_schema_parity")
    assert parity.outcome == "fail"
    assert any(
        check["field"] == "sku" and check["visible_match"] is False
        for check in parity.evidence["checks"]
    )


def test_in_stock_does_not_match_negated_available_phrase() -> None:
    facts = extract_page_facts(
        b"""<html><head><title>Widget Pro</title>
        <script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Product",
          "name":"Widget Pro", "offers":{"@type":"Offer","availability":"InStock"}
        }</script></head><body><h1>Widget Pro</h1>
        <p>This item is not available.</p></body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"
    assert _outcome(facts, "aeo.product_visible_schema_parity").outcome == "fail"


def test_out_of_stock_matches_negated_available_phrase() -> None:
    facts = extract_page_facts(
        b"""<html><head><title>Widget Pro</title>
        <script type="application/ld+json">{
          "@context":"https://schema.org", "@type":"Product",
          "name":"Widget Pro", "offers":{"@type":"Offer","availability":"OutOfStock"}
        }</script></head><body><h1>Widget Pro</h1>
        <p>This item is not available.</p></body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"
    assert _outcome(facts, "aeo.product_visible_schema_parity").outcome == "pass"


def test_site_opportunity_mapping_covers_schema_and_content_catalog() -> None:
    expected = {
        "aeo.structured_data_present",
        "aeo.schema_expected_for_type",
        "aeo.schema_required_valid",
        "aeo.schema_recommended_present",
        "aeo.schema_matches_content",
        "aeo.product_offer_details",
        "aeo.product_visible_schema_parity",
        "technical.thin_content",
        "aeo.answer_first",
        "aeo.question_headings",
        "aeo.author_present",
        "aeo.date_present",
        "aeo.outbound_citations",
        "aeo.organization_identity",
    }
    assert expected <= set(SITE_ISSUE_TO_OPPORTUNITY_RULE_ID)
    assert all(_site_opportunity_rule_id(rule_id) for rule_id in expected)
    assert rule_for("aeo.product_offer_details") is not None


def test_grouped_issue_history_tracks_new_continuing_and_resolved() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    crawl_ids = [uuid4(), uuid4(), uuid4()]
    observations = [
        _HistoryObservation(
            crawl_id=crawl_ids[index],
            observed_at=start + timedelta(days=index),
            rule_id="aeo.schema_required_valid",
            dimension="aeo",
            category="structured_data",
            severity="medium",
            finding_class="defect",
            outcome=outcome,
            analyzer_version="analyzer-1",
            rule_version="rule-1",
            description="Required schema properties are missing.",
            remediation="Add missing properties.",
        )
        for index, outcome in enumerate(("fail", "fail", "pass"))
    ]

    groups, summary = _group_issue_history(observations)
    assert len(groups) == 1
    group = groups[0]
    assert group["current_state"] == "resolved"
    assert group["occurrence_count"] == 2
    assert [entry["transition"] for entry in group["timeline"]] == [
        "new",
        "continuing",
        "resolved",
    ]
    assert summary == {
        "has_previous_crawl": True,
        "new": 0,
        "continuing": 0,
        "resolved": 1,
    }
