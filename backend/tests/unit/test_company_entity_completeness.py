from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analysis.site_health.company_entity_rules import (
    evaluate_company_entity_facts,
    extract_company_entity_facts,
)
from app.analysis.site_health.page_traits import derive_traits

_CORPUS = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "site_health"
    / "company_entity_calibration.json"
)


def test_offline_calibration_corpus_uses_only_bounded_normalized_facts() -> None:
    cases = json.loads(_CORPUS.read_text(encoding="utf-8"))
    for case in cases:
        outcome, evidence = evaluate_company_entity_facts(case["facts"])
        assert outcome == case["expected"], case["case"]
        assert {atom["name"]: atom["outcome"] for atom in evidence["atoms"]} == case[
            "expected_atoms"
        ], case["case"]
        assert "body" not in case["facts"]
        assert all(len(str(value)) <= 256 for value in case["facts"].values())
        assert evidence.get("normalized_score", 0.0) <= 1.0


@pytest.mark.parametrize(
    ("missing", "expected_credit"),
    [
        ("company_and_offering_definition", 0.60),
        ("audience_or_use_case", 0.75),
        ("concrete_value_proposition", 0.80),
        ("durable_first_party_proof", 0.85),
    ],
)
def test_atoms_receive_unequal_weighted_credit(
    missing: str, expected_credit: float
) -> None:
    facts = {
        "readable": True,
        "company_identity": "Acme",
        "offering": "workflow software",
        "audience_or_use_case": "operations teams",
        "concrete_value_proposition": "a purpose-built operating workflow",
        "durable_first_party_proof": "founded in 2012",
    }
    if missing == "company_and_offering_definition":
        facts["offering"] = ""
    else:
        facts[missing] = ""
    outcome, evidence = evaluate_company_entity_facts(facts)
    expected_outcome = (
        "missing" if missing == "company_and_offering_definition" else "partial"
    )
    assert outcome == expected_outcome
    assert evidence["normalized_score"] == expected_credit


def test_unreadable_content_is_unknown() -> None:
    outcome, evidence = evaluate_company_entity_facts({"readable": False})
    assert outcome == "unknown"
    assert evidence["normalized_coverage"] == 0.0


def test_campaign_award_and_testimonial_statistics_do_not_become_proof() -> None:
    facts = {
        "body": {
            "text": (
                "Acme provides workflow software for operations teams. "
                "Our platform combines planning and reporting. Our campaign "
                "raised 2 million votes and won 12 awards. A testimonial says "
                "99 customers love it."
            )
        },
        "primary_content_text": (
            "Acme provides workflow software for operations teams. "
            "Our platform combines planning and reporting. Our campaign "
            "raised 2 million votes and won 12 awards. A testimonial says "
            "99 customers love it."
        ),
        "entity_proposition": {
            "provider": "Acme",
            "named_capability": "workflow software",
            "audience_or_outcome": "operations teams",
            "proposition": "Acme provides workflow software for operations teams.",
        },
        "structured_data": {"blocks": []},
    }
    normalized = extract_company_entity_facts(facts)
    assert normalized["durable_first_party_proof"] == ""


def test_company_proof_reads_only_primary_content() -> None:
    normalized = extract_company_entity_facts(
        {
            "body": {"text": "A footer partner was founded in 1999."},
            "primary_content_text": "Acme provides workflow software.",
            "entity_proposition": {
                "provider": "Acme",
                "named_capability": "workflow software",
            },
            "structured_data": {"blocks": []},
        }
    )
    assert normalized["durable_first_party_proof"] == ""


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        ("https://example.com/about-us", "About Us", True),
        ("https://example.com/our-company", "Our Company", True),
        ("https://example.com/company-history", "Company History", False),
        ("https://example.com/contact", "Contact Us", False),
        ("https://example.com/team", "Our Team", False),
        ("https://example.com/about-us", "About TeamSnap", True),
        ("https://example.com/", "HTC Global", False),
    ],
)
def test_canonical_profile_applicability_boundaries(
    url: str, title: str, expected: bool
) -> None:
    facts = {"title": title, "headings": {"h1_texts": [title]}}
    observed = "company_profile_intent" in derive_traits(url, facts)
    assert observed is expected
