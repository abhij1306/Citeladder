"""Focused fixtures for page-type evidence, Product/Offer rules, and history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.analysis.opportunities.detectors import _site_opportunity_rule_id
from app.analysis.site_health.page_analysis import analyze_page
from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.page_traits import derive_traits
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.rules import evaluate_all, rule_for
from app.core.config.opportunities import SITE_ISSUE_TO_OPPORTUNITY_RULE_ID
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_CONFLICTING,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    KNOWN_MEASUREMENT_GAPS,
    expected_checkpoints,
    relevant_dimensions,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_PROFILES,
    PAGE_KINDS,
)
from app.domain.site_health.service.issue_history import (
    _group_issue_history,
    _HistoryObservation,
)


def _outcome(facts: dict, rule_id: str):
    return next(item for item in evaluate_all(facts) if item.rule_id == rule_id)


def test_page_analysis_is_the_immutable_evaluation_interface() -> None:
    facts = {
        "has_html": True,
        "title": "Acme",
        "body": {"word_count": 40, "text": "word " * 40},
        "delivery": {"final_url": "https://x.example/", "is_https": True},
        "headings": {"h1_count": 1, "counts": {"h1": 1}, "h1_texts": ["Acme"]},
        "structured_data": {"count": 0, "blocks": [], "types": []},
    }

    result = analyze_page(facts)

    assert result.assessment.page_kind == "homepage"
    assert result.assessment.tier
    assert result.evaluations
    assert all(row.reason_code != "crawl_finalize_scope" for row in result.evaluations)
    assert {"page_kind", "page_kind_evidence", "page_traits"}.isdisjoint(facts)


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


def test_every_relevant_dimension_has_a_checkpoint_or_named_gap() -> None:
    missing_paths: set[tuple[str, str]] = set()
    for page_kind in PAGE_KINDS:
        expected = expected_checkpoints(
            page_kind,
            crawl_context={"is_site_root": page_kind == "homepage"},
        )
        dimensions = {
            rule.readiness_dimension
            for rule_id in expected
            if (rule := rule_for(rule_id)) is not None
        }
        missing_paths.update(
            (page_kind, dimension)
            for dimension in relevant_dimensions(page_kind)
            if dimension not in dimensions
        )

    assert missing_paths == set(KNOWN_MEASUREMENT_GAPS)
    assert all(KNOWN_MEASUREMENT_GAPS.values())


def test_product_offer_facts_fixture() -> None:
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
        <label for="finish">Finish</label><select id="finish"><option>Oak</option>
        <option>Walnut</option></select>
        <p>Acme Widget Pro, SKU W-100, GTIN 1234567890123, is in stock
        for 19.99 USD.</p>
        </body></html>""",
        final_url="https://example.test/products/widget-pro",
    )
    facts["page_kind"] = "product"
    facts["page_traits"] = list(
        derive_traits("https://example.test/products/widget-pro", facts)
    )

    product = facts["structured_data"]["product"]
    assert product["sku"] == ["W-100"]
    assert product["gtin"] == ["1234567890123"]
    assert product["brand"] == ["Acme"]
    assert product["price"] == ["19.99"]
    assert product["price_currency"] == ["USD"]
    assert product["ratings"] == ["4.8"]
    assert product["shipping"] is True and product["returns"] is True
    answer = _outcome(facts, "aeo.product_answer_facts")
    assert answer.outcome == RULE_OUTCOME_SATISFIED
    assert [atom["outcome"] for atom in answer.evidence["atoms"]] == [
        "satisfied",
        "satisfied",
        "satisfied",
        "satisfied",
    ]


def test_product_answer_requires_availability() -> None:
    facts = extract_page_facts(
        b"""<html><head><script type="application/ld+json">{
        "@context":"https://schema.org", "@type":"Product", "name":"Widget",
        "sku":"W-100", "brand":"Acme",
        "offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD"}
        }</script></head><body><h1>Widget</h1></body></html>""",
        final_url="https://example.test/products/widget",
    )
    facts["page_kind"] = "product"

    outcome = _outcome(facts, "aeo.product_answer_facts")
    assert outcome.outcome == RULE_OUTCOME_MISSING
    availability = next(
        atom for atom in outcome.evidence["atoms"] if atom["name"] == "availability"
    )
    assert availability["outcome"] == RULE_OUTCOME_MISSING


def test_product_answer_rejects_unqualified_visible_price() -> None:
    facts = {
        "has_html": True,
        "page_kind": "product",
        "headings": {"h1_texts": ["Widget"]},
        "structured_data": {"product": {}},
        "commerce": {
            "visible_price": "$100",
            "visible_price_context": "Free shipping over $100 on all orders",
            "visible_availability": "In stock",
        },
        "entity": {"product": {"has_primary_price": False}},
    }

    outcome = _outcome(facts, "aeo.product_answer_facts")
    offer = next(atom for atom in outcome.evidence["atoms"] if atom["name"] == "offer")

    assert offer["outcome"] == RULE_OUTCOME_MISSING


def test_product_variants_atom_uses_only_the_observed_trait() -> None:
    facts = extract_page_facts(
        b"""<html><head><script type="application/ld+json">{
        "@context":"https://schema.org", "@type":"Product", "name":"Widget",
        "hasVariant":{"@type":"Product","name":"Blue"},
        "offers":{"@type":"Offer","price":"19.99","availability":"InStock"}
        }</script></head><body><h1>Widget</h1></body></html>""",
        final_url="https://example.test/products/widget",
    )
    facts["page_kind"] = "product"
    facts["page_traits"] = list(
        derive_traits("https://example.test/products/widget", facts)
    )

    no_trait = _outcome(facts, "aeo.product_answer_facts")
    variants = next(
        atom for atom in no_trait.evidence["atoms"] if atom["name"] == "variants"
    )
    assert variants["outcome"] == RULE_OUTCOME_NOT_APPLICABLE
    assert variants["condition"] == "page_trait:has_variants"

    facts["form_fields"] = ["Finish"]
    facts["page_traits"] = list(
        derive_traits("https://example.test/products/widget", facts)
    )
    trait_present = _outcome(facts, "aeo.product_answer_facts")
    variants = next(
        atom for atom in trait_present.evidence["atoms"] if atom["name"] == "variants"
    )
    assert variants["outcome"] == RULE_OUTCOME_SATISFIED


def test_variant_selection_context_can_expose_missing_variant_evidence() -> None:
    facts = extract_page_facts(
        b"""<html><body><h1>Widget</h1><p>$19.99 In stock</p>
        <label for="finish">Finish</label><input id="finish"></body></html>""",
        final_url="https://example.test/products/widget",
    )
    facts["page_kind"] = "product"
    facts["page_traits"] = list(
        derive_traits("https://example.test/products/widget", facts)
    )

    outcome = _outcome(facts, "aeo.product_answer_facts")
    variants = next(
        atom for atom in outcome.evidence["atoms"] if atom["name"] == "variants"
    )
    assert facts["page_traits"] == ["has_variants"]
    assert variants["outcome"] == RULE_OUTCOME_MISSING
    assert outcome.outcome == RULE_OUTCOME_PARTIAL


def test_freshness_requires_timestamp_and_offer_currency() -> None:
    product = extract_page_facts(
        b"""<html><head><script type="application/ld+json">{
        "@context":"https://schema.org", "@type":"Product",
        "offers":{"@type":"Offer","price":"19.99","priceCurrency":"USD",
        "availability":"InStock"}}</script></head><body><h1>Widget</h1></body></html>""",
        final_url="https://example.test/products/widget",
    )
    product["page_kind"] = "product"
    product["dates"] = {"published": "", "modified": "2026-08-30"}
    current = _outcome(product, "aeo.offer_freshness_signal")
    assert current.outcome == RULE_OUTCOME_SATISFIED
    assert current.evidence == {
        "currency": ["USD"],
        "timestamp": "2026-08-30",
        "timestamp_source": "modified",
    }

    product["structured_data"]["product"]["price_currency"] = []
    unknown = _outcome(product, "aeo.offer_freshness_signal")
    assert unknown.outcome == RULE_OUTCOME_UNKNOWN
    assert unknown.evidence["reason"] == "currency_unavailable"


def test_assortment_freshness_does_not_treat_item_count_as_current() -> None:
    facts = {
        "has_html": True,
        "page_kind": "category",
        "headings": {"h1_texts": ["Widgets"]},
        "entity": {"listing": {"distinct_card_list_targets": 3}},
        "commerce": {"product_cards": [{"title": "Widget", "url": "/widget"}]},
        "dates": {"published": "", "modified": ""},
    }
    unknown = _outcome(facts, "aeo.assortment_freshness_signal")
    assert unknown.outcome == RULE_OUTCOME_UNKNOWN
    assert unknown.evidence["reason"] == "freshness_timestamp_unavailable"
    assert "crawlable_item_count" not in unknown.evidence

    facts["dates"]["published"] = "2026-08-01"
    current = _outcome(facts, "aeo.assortment_freshness_signal")
    assert current.outcome == RULE_OUTCOME_SATISFIED
    assert current.evidence == {
        "timestamp": "2026-08-01",
        "timestamp_source": "published",
    }


def test_composite_contracts_are_attached_to_every_composite_evaluator() -> None:
    expected = {
        "aeo.entity_value_proposition": {
            "entity_identity",
            "contact_path",
            "value_proposition",
        },
        "aeo.product_answer_facts": {"identity", "offer", "availability", "variants"},
        "aeo.listing_answer_set": {"collection_purpose", "item_set"},
    }
    for rule_id, atom_names in expected.items():
        rule = rule_for(rule_id)
        assert rule is not None
        contract = rule.composite_contract
        assert contract is not None
        assert {atom.name for atom in contract.atoms} == atom_names
        assert contract.threshold


def test_site_opportunity_mapping_covers_schema_and_content_catalog() -> None:
    expected = {
        "aeo.structured_data_present",
        "aeo.schema_expected_for_type",
        "aeo.schema_required_valid",
        "aeo.schema_recommended_present",
        "aeo.schema_matches_content",
        "aeo.product_answer_facts",
        "aeo.product_evidence_facts",
        "aeo.product_brand_identity",
        "aeo.offer_freshness_signal",
        "aeo.listing_answer_set",
        "aeo.listing_item_facts",
        "aeo.assortment_freshness_signal",
        "aeo.heading_hierarchy",
        "aeo.editorial_lead_present",
        "aeo.entity_value_proposition",
        "technical.thin_content",
        "aeo.answer_first",
        "aeo.question_headings",
        "aeo.author_present",
        "aeo.content_date_present",
        "aeo.outbound_citations",
        "aeo.organization_identity",
        "aeo.trust_path_present",
    }
    assert expected <= set(SITE_ISSUE_TO_OPPORTUNITY_RULE_ID)
    assert all(_site_opportunity_rule_id(rule_id) for rule_id in expected)
    assert rule_for("aeo.product_answer_facts") is not None


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
        for index, outcome in enumerate(
            (RULE_OUTCOME_MISSING, RULE_OUTCOME_MISSING, RULE_OUTCOME_SATISFIED)
        )
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


def test_grouped_issue_history_uses_latest_nonempty_guidance() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    observations = [
        _HistoryObservation(
            crawl_id=uuid4(),
            observed_at=start + timedelta(days=index),
            rule_id="aeo.answer_first",
            dimension="aeo",
            category="content",
            severity="medium",
            finding_class="defect",
            outcome=RULE_OUTCOME_MISSING,
            analyzer_version="analyzer-1",
            rule_version="rule-1",
            description=description,
            remediation=remediation,
        )
        for index, (description, remediation) in enumerate(
            (("Old description", "Old fix"), ("Current description", ""), ("", ""))
        )
    ]

    groups, _summary = _group_issue_history(observations)

    assert groups[0]["description"] == "Current description"
    assert groups[0]["remediation"] == "Old fix"


def test_grouped_issue_history_resolves_on_diagnostic_outcomes() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    outcomes = (
        RULE_OUTCOME_MISSING,
        RULE_OUTCOME_PARTIAL,
        RULE_OUTCOME_CONFLICTING,
        RULE_OUTCOME_ERROR,
    )
    observations = [
        _HistoryObservation(
            crawl_id=uuid4(),
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
        for index, outcome in enumerate(outcomes)
    ]

    groups, summary = _group_issue_history(observations)

    assert groups[0]["current_state"] == "resolved"
    assert groups[0]["occurrence_count"] == 2
    assert [entry["transition"] for entry in groups[0]["timeline"]] == [
        "new",
        "continuing",
        "resolved",
        "unchanged",
    ]
    assert summary["continuing"] == 0
    assert summary["resolved"] == 0
