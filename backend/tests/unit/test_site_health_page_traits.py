"""Page-trait derivation: observations a page carries, not inferences.

Traits exist because ``page_kind`` is exclusive and was carrying two jobs. A
product page with an FAQ block had to become one or the other, and whichever it
became, the other checklist was lost. These tests hold the line that a trait is
read from evidence the page actually carries -- never guessed from its kind,
and never so loose that a page picks one up by accident.

Pure and offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.page_traits import derive_traits
from app.analysis.site_health.parser import extract_page_facts
from app.core.config import site_health_taxonomy as config

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site_health"


def _facts(name: str, url: str) -> dict:
    return extract_page_facts(
        (_FIXTURES / name).read_bytes(), final_url=url, content_type="text/html"
    )


def _traits(name: str, url: str) -> set[str]:
    return set(derive_traits(url, _facts(name, url)))


# --- fixtures, end to end -----------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "url", "expected"),
    [
        (
            "contact_page.html",
            "https://northgate.example/contact-us",
            {"contact_intent", "local_intent"},
        ),
        ("faq_accordion.html", "https://northgate.example/faq", {"has_faq"}),
        (
            "guide_no_howto.html",
            "https://northgate.example/guides/re-oiling-an-oak-table",
            {"procedural"},
        ),
        (
            "flat_category_listing.html",
            "https://northgate.example/womens-dresses",
            {"listing"},
        ),
        (
            "broken_pdp_schema_mismatch.html",
            "https://northgate.example/oak-dining-tables/ilkley",
            {"has_variants"},
        ),
        ("docs_reference.html", "https://northgate.example/docs/api/orders", set()),
    ],
)
def test_observed_traits_per_fixture(fixture, url, expected) -> None:
    assert _traits(fixture, url) == expected


def test_an_article_with_descriptive_headings_is_not_an_faq() -> None:
    """The false positive this trait was tightened to avoid.

    The classifier's FAQ signal counts any heading opening with what/why/how
    as a question, which is right where it competes with other signals and is
    resolved by tier precedence. A trait stands alone -- whatever keys on it
    fires with no second opinion -- so ``has_faq`` requires a literal question
    mark. "What drying actually removes" is a section, not a question.
    """
    url = "https://northgate.example/blog/kiln-dried-oak"
    facts = _facts("article_no_schema.html", url)
    headings = facts["headings"]["h2_texts"]
    assert len(headings) >= config.PAGE_KIND_FAQ_MIN_HEADINGS
    assert not any(text.strip().endswith("?") for text in headings)
    assert "has_faq" not in derive_traits(url, facts)


# --- traits are independent of the page kind ---------------------------------


def test_traits_never_read_the_page_kind() -> None:
    """A trait is derived from facts, never from the classification.

    This is what lets a product page with an FAQ answer both checklists, and
    what makes trait-scoped rules safe to run at any classification
    confidence.
    """
    url = "https://northgate.example/faq"
    facts = _facts("faq_accordion.html", url)
    baseline = derive_traits(url, facts)
    for page_kind in ("product", "article", "other", "trust_policy"):
        assert derive_traits(url, {**facts, "page_kind": page_kind}) == baseline


def test_a_product_page_carrying_an_faq_keeps_both() -> None:
    # The hybrid case the taxonomy could not express. Rather than inventing a
    # product_with_faq kind, the page stays a product and gains has_faq.
    url = "https://northgate.example/oak-dining-tables/ilkley"
    facts = _facts("broken_pdp_schema_mismatch.html", url)
    facts["headings"] = {
        **facts["headings"],
        "h2_texts": [
            "How long does delivery take?",
            "Can I return a made-to-measure piece?",
            "Do you deliver outside the UK?",
        ],
    }
    assessment = classify(url, facts)
    assert assessment.page_kind == "product"
    traits = derive_traits(url, facts)
    assert "has_faq" in traits
    assert "has_variants" in traits


# --- bounded, deterministic, total -------------------------------------------


def test_derive_traits_returns_config_order() -> None:
    url = "https://northgate.example/contact-us"
    traits = derive_traits(url, _facts("contact_page.html", url))
    assert list(traits) == [t for t in config.PAGE_TRAITS if t in traits]


def test_derive_traits_tolerates_malformed_facts() -> None:
    # Facts are replayed from persisted JSONB, so every reader is defensive.
    for facts in ({}, {"headings": "nope", "entity": 5, "structured_data": None}):
        assert derive_traits("https://x.example/", facts) == ()
    assert derive_traits("", {}) == ()
    assert derive_traits("not a url", {}) == ()


def test_route_segments_match_exactly() -> None:
    # /aboutery is not /about, the same discipline the page-kind route
    # patterns already use.
    facts = {"title": "", "headings": {"h1_texts": []}}
    assert "about_intent" in derive_traits("https://x.example/about/", facts)
    assert "about_intent" not in derive_traits("https://x.example/aboutery", facts)


def test_a_contact_route_alone_is_enough_but_so_is_a_mailto() -> None:
    """Either the page says what it is, or it hands over a way to reply."""
    bare = {"title": "", "headings": {"h1_texts": []}}
    assert "contact_intent" in derive_traits("https://x.example/contact-us", bare)
    with_mailto = {
        **bare,
        "contact_points": [{"channel": "email", "value": "a@x.example"}],
    }
    assert "contact_intent" in derive_traits("https://x.example/anything", with_mailto)


def test_procedural_needs_a_real_sequence() -> None:
    # Two list items are a pair of sentences, not a procedure.
    below = {"ordered_list_steps": config.PAGE_TRAIT_PROCEDURAL_MIN_STEPS - 1}
    at = {"ordered_list_steps": config.PAGE_TRAIT_PROCEDURAL_MIN_STEPS}
    assert "procedural" not in derive_traits("https://x.example/", below)
    assert "procedural" in derive_traits("https://x.example/", at)


def test_every_trait_is_declared_in_the_config_vocabulary() -> None:
    url = "https://northgate.example/contact-us"
    for fixture in sorted(path.name for path in _FIXTURES.glob("*.html")):
        for trait in derive_traits(url, _facts(fixture, url)):
            assert trait in config.PAGE_TRAITS, (fixture, trait)
