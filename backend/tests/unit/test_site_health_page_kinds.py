"""Unit tests for the deterministic page-type classifier.

Covers each evidence tier (structural primary entity, route family, semantic
fallback), the deliberate conflict semantics (structured data sits in the
weakest tier and can never self-certify), abstention to ``other``, homepage
path equivalents, bounded evidence contents, and determinism. Pure, offline.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest

from app.analysis.site_health.page_analysis import analyze_page
from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.page_traits import derive_traits
from app.analysis.site_health.parser import extract_page_facts
from app.core.config import site_health_contracts
from app.core.config import site_health_taxonomy as config
from app.core.config.site_health_contracts import (
    CLASSIFIER_VERSION,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_CONFIDENCE_HIGH,
    PAGE_KIND_CONFIDENCE_LOW,
    PAGE_KIND_CONFIDENCE_MEDIUM,
    PAGE_KIND_CONFIDENCE_UNKNOWN,
    PAGE_KIND_PATH_PATTERNS,
    PAGE_KIND_PROFILES,
    PAGE_KIND_SCHEMA_TYPE_MAP,
    PAGE_KIND_SIGNAL_CONTENT_HEURISTIC,
    PAGE_KIND_SIGNAL_NONE,
    PAGE_KIND_SIGNAL_PATH_PATTERN,
    PAGE_KIND_SIGNAL_PRIMARY_LISTING,
    PAGE_KIND_SIGNAL_PRIMARY_PRODUCT,
    PAGE_KIND_SIGNAL_ROOT_PATH,
    PAGE_KIND_SIGNAL_SEMANTIC_TITLE,
    PAGE_KIND_SIGNAL_TIERS,
    PAGE_KINDS,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site_health"
_CALIBRATION_MANIFEST = json.loads(
    (_FIXTURES / "classifier_calibration.json").read_text(encoding="utf-8")
)
_CALIBRATION_CASES = _CALIBRATION_MANIFEST["cases"]
_EMPTY_COLLECTION_EVIDENCE = {
    "container": {
        "tag": "",
        "label": "",
        "item_count": 0,
        "distinct_targets": 0,
    },
    "affordances": [],
}


def _fixture_facts(name: str, url: str) -> dict:
    return extract_page_facts(
        (_FIXTURES / name).read_bytes(), final_url=url, content_type="text/html"
    )


def _facts(
    *,
    h2_texts: list[str] | None = None,
    body_text: str = "",
    schema_types: list[str] | None = None,
    title: str = "",
    entity: dict | None = None,
    authorship: dict[str, str] | None = None,
) -> dict:
    """A bounded parser-facts-shaped dict with only what classify() reads."""
    return {
        "title": title,
        "headings": {"h2_texts": h2_texts or [], "h1_texts": []},
        "body": {"text": body_text, "word_count": len(body_text.split())},
        "structured_data": {"types": schema_types or [], "blocks": []},
        "entity": entity or {},
        "authorship": authorship or {},
    }


def _buy_box() -> dict:
    """Entity facts for a page whose OWN region holds a working buy box."""
    return {
        "product": {
            "has_primary_price": True,
            "has_product_detail_heading": False,
            "has_purchase_control": True,
            "has_variant_control": True,
            "has_sku_marker": False,
        }
    }


def _listing_grid(size: int = 24) -> dict:
    """Entity facts for a page whose OWN region holds a real listing grid."""
    return {
        "listing": {
            "largest_card_list_size": size,
            "distinct_card_list_targets": size,
            "has_result_count": True,
            "has_sort_control": True,
            "has_filter_control": False,
            "collection_evidence": {
                "container": {
                    "tag": "section",
                    "label": "Results",
                    "item_count": size,
                    "distinct_targets": size,
                },
                "affordances": [
                    {
                        "class": "result_count",
                        "relation": "contained",
                        "text": f"{size} results",
                    }
                ],
            },
        }
    }


def _single_location() -> dict:
    return {
        "location": {
            "address_entity_count": 1,
            "has_phone": True,
            "has_hours": False,
        }
    }


def _question_h2s(count: int, *, total: int | None = None) -> list[str]:
    """``total`` h2 texts of which ``count`` are question-form."""
    total = total if total is not None else count
    return [f"What is topic {i}?" for i in range(count)] + [
        f"Statement heading {i}" for i in range(total - count)
    ]


_PRODUCT_TEXT = "This durable water bottle costs $19.99. Add to cart today."
_ARTICLE_AUTHORSHIP = {
    "visible_byline": "By Jane Doe",
    "visible_date": "March 3, 2026",
}


# --- Signal 1: root path -> homepage ---------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com",
        "https://example.com/index.html",
        "https://example.com/INDEX.HTML",
        "https://example.com/en/",
        "https://example.com/en",
        "https://example.com/en-us/",
        "https://example.com/?utm_source=x",
    ],
)
def test_root_path_equivalents_classify_homepage(url: str) -> None:
    assessment = classify(url, _facts())
    assert assessment.page_kind == "homepage"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_ROOT_PATH
    assert assessment.confidence == PAGE_KIND_CONFIDENCE_HIGH


def test_unlisted_locale_root_falls_through_to_other() -> None:
    # "/uk/" is deliberately NOT in HOMEPAGE_PATH_EQUIVALENTS.
    assessment = classify("https://example.com/uk/", _facts())
    assert assessment.page_kind == "other"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_NONE
    assert assessment.confidence == PAGE_KIND_CONFIDENCE_UNKNOWN


def test_homepage_outranks_conflicting_schema_and_records_suggestion() -> None:
    assessment = classify("https://example.com/", _facts(schema_types=["FAQPage"]))
    assert assessment.page_kind == "homepage"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_ROOT_PATH
    # The schema claim is recorded even though it lost.
    assert assessment.schema_suggested_type == "faq"


# --- Signal 2: ordered URL path patterns ------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/blog/my-post", "article"),
        ("https://example.com/news/story", "article"),
        # Both spellings reach PAGE_KIND_GUIDE. Listing "guides" under the
        # earlier article pattern made the plural an article and left the guide
        # entry unreachable for it, so /guide and /guides classified differently.
        ("https://example.com/guide/how-to", "guide"),
        ("https://example.com/guides/how-to", "guide"),
        ("https://example.com/product/123", "product"),
        ("https://example.com/products/123", "product"),
        ("https://example.com/p/abc", "product"),
        ("https://example.com/shop/item", "category"),
        ("https://example.com/category/shoes", "category"),
        ("https://example.com/collections/summer", "category"),
        ("https://example.com/pricing", "pricing"),
        ("https://example.com/pricing/teams", "pricing"),
        ("https://example.com/docs/getting-started", "docs"),
        ("https://example.com/reference/api", "docs"),
        ("https://example.com/faq", "faq"),
        # Help/support paths are documentation. FAQ requires the explicit FAQ
        # route or independent structural classification evidence.
        ("https://example.com/help/article", "docs"),
        ("https://example.com/about", "about_contact"),
        ("https://example.com/contact", "about_contact"),
    ],
)
def test_path_patterns_classify_each_type(url: str, expected: str) -> None:
    assessment = classify(url, _facts())
    assert assessment.page_kind == expected
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/blog/pricing", "article"),
        ("/pricing/blog", "pricing"),
        ("/resources/guides/getting-started", "guide"),
        ("/company/contact-us", "about_contact"),
        ("/legal/privacy-policy", "trust_policy"),
    ],
)
def test_path_pattern_uses_nearest_semantic_segment(path: str, expected: str) -> None:
    assessment = classify(f"https://example.com{path}", _facts())
    assert assessment.page_kind == expected


def test_path_pattern_requires_a_complete_semantic_segment() -> None:
    assessment = classify("https://example.com/x/blog-post", _facts())
    assert assessment.page_kind == "other"


def test_semantic_title_requires_a_complete_phrase() -> None:
    assessment = classify(
        "https://example.com/contactless-payments",
        _facts(title="Contactless payments"),
    )
    assert assessment.page_kind == "other"


def test_glossary_title_does_not_classify_as_terms_policy() -> None:
    assessment = classify(
        "https://example.com/glossary/ai-search-glossary-2026",
        _facts(title="AI Search Glossary: Essential Technical Terms for Marketers"),
    )

    assert assessment.page_kind == "other"


def test_path_pattern_outranks_schema_on_conflict() -> None:
    assessment = classify(
        "https://example.com/product/123",
        _facts(schema_types=["Article"]),
    )
    assert assessment.page_kind == "product"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN
    assert assessment.schema_suggested_type == "article"


def test_primary_buy_box_overrides_ancestor_category_path() -> None:
    # A real PDP living under a /categories/ route: its own region holds the
    # buy box, which outranks the ancestor route segment.
    assessment = classify(
        "https://example.com/categories/women/dresses/red-dress/ABC123",
        _facts(entity=_buy_box()),
    )

    assert assessment.page_kind == "product"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PRIMARY_PRODUCT
    assert assessment.confidence == PAGE_KIND_CONFIDENCE_MEDIUM


def test_primary_price_and_product_heading_classify_without_purchase_control() -> None:
    assessment = classify(
        "https://example.com/catalogue/a-light-in-the-attic_1000/index.html",
        _facts(
            entity={
                "product": {
                    "has_primary_price": True,
                    "has_product_detail_heading": True,
                    "has_purchase_control": False,
                    "has_variant_control": False,
                    "has_sku_marker": False,
                }
            },
        ),
    )

    assert assessment.page_kind == "product"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PRIMARY_PRODUCT
    assert assessment.signals[0]["detail"] == "primary_price+product_heading"


def test_recommendation_carousel_cannot_make_a_policy_page_a_product() -> None:
    # The whole-body "price + cart marker anywhere" heuristic used to fire
    # here: a returns-policy page carrying a "You May Also Like" strip has
    # both. Product evidence is now scoped outside every repeated card list,
    # so the carousel contributes nothing and the page keeps its own type.
    facts = _facts(
        title="Returns",
        body_text="30 day return window. Add to cart $99.00 Add to cart $88.00",
        entity={
            "product": {
                "has_primary_price": False,
                "has_purchase_control": False,
                "has_variant_control": False,
                "has_sku_marker": False,
            },
            "listing": {"largest_card_list_size": 4, "has_result_count": False},
        },
    )
    assessment = classify("https://example.com/pages/refund-policy", facts)
    assert assessment.page_kind == "trust_policy"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_SEMANTIC_TITLE


def test_product_schema_alone_cannot_override_category_path() -> None:
    assessment = classify(
        "https://example.com/categories/women/dresses/red-dress/ABC123",
        _facts(schema_types=["Product"]),
    )

    assert assessment.page_kind == "category"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN


# --- Signal 3: content/heading heuristics -----------------------------------


def test_question_heading_ratio_classifies_faq() -> None:
    facts = _facts(h2_texts=_question_h2s(4, total=5))
    assessment = classify("https://example.com/answers", facts)
    assert assessment.page_kind == "faq"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_CONTENT_HEURISTIC


def test_faq_requires_minimum_heading_count() -> None:
    # 2/2 question headings is a perfect ratio but below the minimum count.
    facts = _facts(h2_texts=_question_h2s(2, total=2))
    assert classify("https://example.com/answers", facts).page_kind == "other"


def test_faq_requires_question_ratio() -> None:
    # 1 question of 4 headings is below the config ratio.
    facts = _facts(h2_texts=_question_h2s(1, total=4))
    assert classify("https://example.com/answers", facts).page_kind == "other"


def test_question_word_prefix_counts_as_question_form() -> None:
    facts = _facts(h2_texts=["How it works", "Why choose us", "What you get"])
    assert classify("https://example.com/answers", facts).page_kind == "faq"


def test_body_text_price_and_cart_marker_alone_do_not_classify_product() -> None:
    # Body text says nothing about WHERE the price and button are. Any page
    # carrying a product carousel has both, so this can only be read from the
    # page's own region -- see the entity-scoped test above.
    assessment = classify("https://example.com/item", _facts(body_text=_PRODUCT_TEXT))
    assert assessment.page_kind == "other"


def test_listing_grid_classifies_category_without_a_route_token() -> None:
    # A flat ecommerce slug with no /category/ or /collections/ segment.
    assessment = classify(
        "https://example.com/womens-dresses", _facts(entity=_listing_grid())
    )
    assert assessment.page_kind == "category"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PRIMARY_LISTING


def test_single_address_requires_a_local_route() -> None:
    arbitrary = classify(
        "https://example.com/team/member", _facts(entity=_single_location())
    )
    local = classify(
        "https://example.com/stores/gosford", _facts(entity=_single_location())
    )
    assert arbitrary.page_kind == "other"
    assert local.page_kind == "local"


def test_small_card_strip_is_not_a_listing() -> None:
    # Four related products is a module, not a listing page.
    assessment = classify(
        "https://example.com/some/page", _facts(entity=_listing_grid(size=4))
    )
    assert assessment.page_kind == "other"


def test_price_without_cart_marker_does_not_classify_product() -> None:
    facts = _facts(body_text="Everything here costs $19.99, shipping included.")
    assert classify("https://example.com/item", facts).page_kind == "other"


def test_cart_marker_without_price_does_not_classify_product() -> None:
    facts = _facts(body_text="Click add to cart whenever you are ready.")
    assert classify("https://example.com/item", facts).page_kind == "other"


def test_byline_and_date_classify_article() -> None:
    assessment = classify(
        "https://example.com/post", _facts(authorship=_ARTICLE_AUTHORSHIP)
    )
    assert assessment.page_kind == "article"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_CONTENT_HEURISTIC


def test_byline_without_date_does_not_classify_article() -> None:
    facts = _facts(authorship={"visible_byline": "By Jane Doe"})
    assert classify("https://example.com/post", facts).page_kind == "other"


def test_content_heuristics_have_fixed_sub_order() -> None:
    # FAQ outranks product within signal 3 when both match.
    facts = _facts(h2_texts=_question_h2s(3), body_text=_PRODUCT_TEXT)
    assert classify("https://example.com/x", facts).page_kind == "faq"


def test_conflicting_semantic_evidence_uses_priority_and_records_conflict() -> None:
    facts = _facts(
        h2_texts=_question_h2s(3),
        title="Shipping policy questions and answers",
    )
    assessment = classify("https://example.com/x", facts)
    assert assessment.page_kind == "faq"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_CONTENT_HEURISTIC
    assert any(
        conflict["conflicting_page_kind"] == "trust_policy"
        for conflict in assessment.conflicts
    )


def test_content_heuristic_outranks_schema_on_conflict() -> None:
    facts = _facts(h2_texts=_question_h2s(3), schema_types=["Article"])
    assessment = classify("https://example.com/item", facts)
    assert assessment.page_kind == "faq"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_CONTENT_HEURISTIC
    assert assessment.schema_suggested_type == "article"


def test_article_with_related_item_list_stays_article() -> None:
    facts = _facts(
        schema_types=["Article", "ItemList"],
        entity={
            "listing": {
                "largest_card_list_size": 20,
                "distinct_card_list_targets": 20,
                "has_result_count": False,
                "has_sort_control": False,
                "has_filter_control": False,
            }
        },
    )

    assessment = classify("https://example.com/blog/what-is-aeo", facts)

    assert assessment.page_kind == "article"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN


@pytest.mark.parametrize(
    ("fixture", "url"),
    [
        ("allbirds_news_archive.html", "https://www.allbirds.com/blogs/news"),
        ("allbirds_news_archive.html", "https://www.allbirds.com/blogs/stories"),
        ("allbirds_news_archive.html", "https://www.allbirds.com/news"),
        (
            "asian_school_education_archive.html",
            "https://www.theasianschool.net/blog/category/education/",
        ),
    ],
)
def test_blog_archives_with_page_owned_card_lists_are_categories(
    fixture: str, url: str
) -> None:
    facts = _fixture_facts(fixture, url)
    assessment = classify(url, facts)

    assert assessment.page_kind == "category"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PRIMARY_LISTING
    assert "listing" in derive_traits(url, facts)


def test_individual_blog_post_with_related_cards_stays_article() -> None:
    url = "https://www.allbirds.com/blogs/news/story-1"
    facts = _fixture_facts("allbirds_news_archive.html", url)

    assert classify(url, facts).page_kind == "article"


def test_generic_single_depth_blog_post_is_not_an_archive() -> None:
    url = "https://www.allbirds.com/blogs/my-post"
    facts = _fixture_facts("allbirds_news_archive.html", url)

    assert classify(url, facts).page_kind == "article"


# --- Signal 4: structured-data types -----------------------------------------


@pytest.mark.parametrize(
    ("schema_type", "expected"),
    [
        ("Article", "article"),
        ("BlogPosting", "article"),
        ("NewsArticle", "article"),
        ("Product", "product"),
        ("FAQPage", "faq"),
        ("TechArticle", "docs"),
        ("CollectionPage", "category"),
        ("ContactPage", "about_contact"),
    ],
)
def test_schema_types_are_suggestions_not_page_type_verdicts(
    schema_type: str, expected: str
) -> None:
    assessment = classify(
        "https://example.com/anything", _facts(schema_types=[schema_type])
    )
    assert assessment.page_kind == "other"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_NONE
    assert assessment.schema_suggested_type == expected
    assert assessment.other_reason == "schema_only"


def test_unmapped_schema_type_does_not_classify() -> None:
    assessment = classify(
        "https://example.com/anything", _facts(schema_types=["Organization"])
    )
    assert assessment.page_kind == "other"
    assert assessment.schema_suggested_type is None


def test_multiple_schema_types_use_explicit_specificity_order() -> None:
    assessment = classify(
        "https://example.com/anything",
        _facts(schema_types=["Product", "Article"]),
    )
    assert assessment.page_kind == "other"
    assert assessment.schema_suggested_type == "product"


# --- Confidence, threshold, evidence, determinism ----------------------------


def test_confidence_reports_the_deciding_tier_not_a_score() -> None:
    # Confidence must describe the evidence that DECIDED the type. Summing
    # every matched weight let agreeing and disagreeing signals inflate the
    # same number, so a page classified from a route signal could report a
    # confidence higher than that signal was ever worth.
    facts = _facts(schema_types=["BlogPosting"])
    assessment = classify("https://example.com/blog/x", facts)
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN
    assert assessment.confidence == PAGE_KIND_CONFIDENCE_MEDIUM

    structural = classify("https://example.com/blog/x", _facts(entity=_buy_box()))
    assert structural.confidence == PAGE_KIND_CONFIDENCE_MEDIUM

    # A slug with no route family at all: only the page's own stated purpose
    # is left, which is the weakest evidence the classifier accepts.
    semantic = classify("https://example.com/pages/care-cleaning", _facts())
    assert semantic.page_kind == "guide"
    assert semantic.classified_by == PAGE_KIND_SIGNAL_SEMANTIC_TITLE
    assert semantic.confidence == PAGE_KIND_CONFIDENCE_LOW


def test_structural_evidence_outranks_a_conflicting_route_family() -> None:
    # The route says category; the page's own region holds a buy box. The
    # stronger tier wins and the disagreement stays on the record.
    facts = _facts(entity=_buy_box())
    assessment = classify("https://example.com/collections/red-dress", facts)
    assert assessment.page_kind == "product"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PRIMARY_PRODUCT
    assert any(
        conflict["conflicting_page_kind"] == "category"
        for conflict in assessment.conflicts
    )


def test_no_signals_classifies_other_with_none_classifier() -> None:
    assessment = classify("https://example.com/some/random-page", _facts())
    assert assessment.page_kind == "other"
    assert assessment.confidence == PAGE_KIND_CONFIDENCE_UNKNOWN
    assert assessment.classified_by == PAGE_KIND_SIGNAL_NONE
    assert assessment.signals == ()


def test_evidence_is_bounded_and_explainable() -> None:
    facts = _facts(schema_types=["Article"])
    assessment = classify("https://example.com/product/123", facts)
    evidence = assessment.to_evidence()
    assert evidence["classifier_version"] == CLASSIFIER_VERSION
    assert evidence["classified_by"] == PAGE_KIND_SIGNAL_PATH_PATTERN
    assert evidence["schema_suggested_type"] == "article"
    assert evidence["confidence"] == assessment.confidence
    assert evidence["tier"] == assessment.tier
    # At most one signal record per signal source, each small + JSON-safe.
    assert len(evidence["signals"]) <= len(PAGE_KIND_SIGNAL_TIERS)
    for signal in evidence["signals"]:
        assert set(signal) == {"signal", "page_kind", "tier", "detail"}
        assert signal["page_kind"] in PAGE_KINDS
        assert signal["tier"] in config.PAGE_KIND_TIERS
        assert len(signal["detail"]) <= 256


def test_classification_is_deterministic() -> None:
    facts = _facts(
        h2_texts=_question_h2s(3),
        body_text=_PRODUCT_TEXT,
        authorship=_ARTICLE_AUTHORSHIP,
        schema_types=["Product"],
    )
    first = classify("https://example.com/page", facts)
    second = classify("https://example.com/page", facts)
    assert first == second
    assert first.to_evidence() == second.to_evidence()


def test_malformed_inputs_never_raise() -> None:
    # A URL we cannot locate a page from contributes NO signals. It used to
    # normalize to the root path and so reported a confident "homepage" for a
    # page that was never identified — a fabricated classification.
    assert classify("", {}).page_kind == "other"
    assert classify("http://", {}).page_kind == "other"
    assert classify("not a url at all", {}).page_kind == "other"
    # Missing/partial facts dicts simply match fewer signals.
    assert classify("https://example.com/blog/x", {}).page_kind == "article"
    assessment = classify("https://example.com/blog/x", None)  # type: ignore[arg-type]
    assert assessment.page_kind == "article"


def test_classifier_version_stamped_from_config() -> None:
    assessment = classify("https://example.com/", {})
    assert assessment.classifier_version == CLASSIFIER_VERSION


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/offers-list/summer", config.PAGE_KIND_CATEGORY),
        ("/q/running-shoes", config.PAGE_KIND_CATEGORY),
        ("/search", config.PAGE_KIND_CATEGORY),
        ("/shop", config.PAGE_KIND_CATEGORY),
        ("/company", config.PAGE_KIND_ABOUT_CONTACT),
        ("/request-demo", config.PAGE_KIND_ABOUT_CONTACT),
        ("/customers/acme", config.PAGE_KIND_CASE_STUDY_REVIEW),
        ("/cookies", config.PAGE_KIND_TRUST_POLICY),
        ("/support/faq/", config.PAGE_KIND_FAQ),
        ("/help/faqs/", config.PAGE_KIND_FAQ),
    ],
)
def test_clear_route_aliases_map_to_stable_page_kinds(path: str, expected: str) -> None:
    assessment = classify(f"https://example.com{path}", {})
    assert assessment.page_kind == expected
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN


# --- Config table integrity (static frozen tables — a plain test, not an
# import-time check) --------------------------------------------------------


def test_page_type_config_tables_are_internally_consistent() -> None:
    # Every taxonomy member has a profile: the table doubles as the registry
    # of kinds the evaluator will accept, so a missing entry silently makes
    # every page-kind-scoped rule inapplicable.
    for page_kind in PAGE_KINDS:
        profile = PAGE_KIND_PROFILES.get(page_kind)
        assert profile is not None, f"missing PAGE_KIND_PROFILES entry: {page_kind}"
        assert profile.page_kind == page_kind
    # Path patterns and the schema map only reference taxonomy members.
    for page_kind, _pattern in PAGE_KIND_PATH_PATTERNS:
        assert page_kind in PAGE_KINDS, f"path pattern type unknown: {page_kind}"
    for page_kind in PAGE_KIND_SCHEMA_TYPE_MAP.values():
        assert page_kind in PAGE_KINDS, f"schema map type unknown: {page_kind}"
    # Every signal name the classifier records is placed in a known tier.
    for signal in (
        config.PAGE_KIND_SIGNAL_ROOT_PATH,
        config.PAGE_KIND_SIGNAL_PATH_PATTERN,
        config.PAGE_KIND_SIGNAL_CONTENT_HEURISTIC,
        config.PAGE_KIND_SIGNAL_STRUCTURED_DATA,
        config.PAGE_KIND_SIGNAL_PRIMARY_PRODUCT,
        config.PAGE_KIND_SIGNAL_PRIMARY_LISTING,
        config.PAGE_KIND_SIGNAL_PRIMARY_LOCATION,
        config.PAGE_KIND_SIGNAL_SEMANTIC_TITLE,
    ):
        assert PAGE_KIND_SIGNAL_TIERS[signal] in config.PAGE_KIND_TIERS
    # The semantic fallback only ever proposes types the taxonomy already has.
    for page_kind, phrase in config.PAGE_KIND_TITLE_KEYWORDS:
        assert page_kind in PAGE_KINDS, f"title keyword type unknown: {page_kind}"
        assert phrase == phrase.lower().strip()


@pytest.mark.parametrize(
    "facts",
    [
        # Top-level facts of the wrong shape entirely.
        "not-a-dict",
        None,
        [],
        # Nested fields of the wrong shape (an older extractor version, or a
        # hand-edited/corrupt persisted artifact).
        {"headings": "oops"},
        {"body": ["not", "a", "mapping"]},
        {"structured_data": "nope"},
        {"headings": {"h2_texts": "a-string-not-a-list"}},
        {"headings": {"h2_texts": None, "h3_texts": 7}},
        {"body": {"text": ["list", "not", "str"]}},
        {"structured_data": {"types": "Article"}},
    ],
)
def test_classify_never_raises_on_malformed_facts(facts) -> None:
    """Malformed facts must match fewer signals, never crash the analysis.

    The facts dict is also read back from persisted JSON written by an earlier
    extractor version, so a wrongly-shaped field has to degrade rather than
    take down the whole page analysis.
    """
    assessment = classify("https://example.com/some/page", facts)
    assert assessment.page_kind == config.PAGE_KIND_OTHER
    assert assessment.classifier_version == site_health_contracts.CLASSIFIER_VERSION


def test_a_bare_string_field_never_fabricates_signals() -> None:
    """Iterating a string would yield characters and invent evidence."""
    assessment = classify(
        "https://example.com/x",
        {"structured_data": {"types": "FAQPage"}},
    )
    # No schema signal is derived from the malformed value.
    assert assessment.schema_suggested_type is None
    assert assessment.signals == ()


@pytest.mark.parametrize("breadcrumbs", [[], None, "API", ["Rapid start"]])
def test_documentation_breadcrumb_requires_complete_list_tokens(breadcrumbs) -> None:
    assessment = classify(
        "https://docs.example.com/start",
        {"commerce": {"breadcrumbs": breadcrumbs}},
    )

    assert assessment.page_kind == config.PAGE_KIND_OTHER


def test_documentation_breadcrumb_matches_normalized_list_token() -> None:
    assessment = classify(
        "https://docs.example.com/start",
        {"commerce": {"breadcrumbs": ["Home", "API Reference"]}},
    )

    assert assessment.page_kind == config.PAGE_KIND_DOCS


# --- PR4 labelled classifier calibration ------------------------------------


def test_html_mime_with_space_before_charset_remains_classifiable() -> None:
    facts = _facts()
    facts["content_type"] = "text/html ; charset=UTF-8"

    assessment = classify("https://example.com/pricing", facts)

    assert assessment.page_kind == "pricing"
    assert assessment.classified_by == PAGE_KIND_SIGNAL_PATH_PATTERN


def _calibration_facts(case: dict) -> dict:
    fixture = case["fixture"]
    if fixture["kind"] == "html":
        return extract_page_facts(
            fixture["html"].encode(),
            final_url=case["url"],
            content_type=case["content_type"],
        )
    facts = deepcopy(fixture["facts"])
    facts["has_html"] = case["content_type"].startswith("text/html")
    facts["delivery"] = {
        **facts.get("delivery", {}),
        "final_url": case["url"],
        "content_type": case["content_type"],
    }
    return facts


def _calibration_outcome(case: dict, *, facts: dict | None = None) -> dict:
    result = analyze_page(facts if facts is not None else _calibration_facts(case))
    assessment = result.assessment
    return {
        "page_kind": assessment.page_kind,
        "traits": list(result.traits),
        "deciding_signal": assessment.classified_by,
        "deciding_tier": assessment.tier,
        "confidence": assessment.confidence,
        "other_reason": assessment.other_reason,
        "evidence": assessment.to_evidence(),
    }


def test_classifier_calibration_manifest_is_bounded_and_complete() -> None:
    limits = _CALIBRATION_MANIFEST["limits"]
    ids = [case["id"] for case in _CALIBRATION_CASES]
    represented_kinds = {case["expected"]["page_kind"] for case in _CALIBRATION_CASES}

    assert len(ids) == len(set(ids))
    assert represented_kinds == set(PAGE_KINDS)
    assert {
        "healthy",
        "broken",
        "ambiguous",
        "conflicting",
        "js_shell",
        "non_html",
    } <= {case["condition"] for case in _CALIBRATION_CASES}
    searchable_details = [
        case
        for case in _CALIBRATION_CASES
        if case["id"].startswith("searchable_blog_detail_")
    ]
    assert len(searchable_details) == 6
    assert any("Flourist" in case["source_label"] for case in _CALIBRATION_CASES)

    for case in _CALIBRATION_CASES:
        expected = case["expected"]
        assert date.fromisoformat(case["observation_date"])
        assert case["source_label"].strip()
        assert ".test/" in case["url"]
        assert 0 < len(case["structural_reason"]) <= limits["max_reason_chars"]
        assert expected["page_kind"] in PAGE_KINDS
        assert set(expected["rejected_kinds"]) <= set(PAGE_KINDS)
        assert expected["page_kind"] not in expected["rejected_kinds"]
        assert expected["allowed_deciding_tiers"]
        assert expected["allowed_confidence"]
        if case["deliberate_abstention"]:
            assert expected["page_kind"] == "other"
            assert expected["other_reason"] in {
                "no_classification_signals",
                "schema_only",
                "conflicting_top_tier_evidence",
            }
        fixture = case["fixture"]
        if fixture["kind"] == "html":
            assert len(fixture["html"]) <= limits["max_html_chars"]
        else:
            serialized = json.dumps(fixture["facts"], sort_keys=True)
            assert len(serialized) <= limits["max_fact_chars"]
            assert "selector" not in serialized.casefold()


@pytest.mark.parametrize(
    "case",
    _CALIBRATION_CASES,
    ids=[case["id"] for case in _CALIBRATION_CASES],
)
def test_classifier_calibration_exact_outcome(case: dict) -> None:
    facts = _calibration_facts(case)
    outcome = _calibration_outcome(case, facts=facts)
    expected = case["expected"]

    assert outcome["page_kind"] == expected["page_kind"]
    assert outcome["traits"] == expected["traits"]
    assert outcome["deciding_signal"] == expected["deciding_signal"]
    assert outcome["deciding_tier"] in expected["allowed_deciding_tiers"]
    assert outcome["confidence"] in expected["allowed_confidence"]
    assert outcome["other_reason"] == expected["other_reason"]
    assert outcome["page_kind"] not in expected["rejected_kinds"]
    assert len(json.dumps(outcome["evidence"], sort_keys=True)) <= 4096
    if case["id"].startswith("searchable_blog_detail_"):
        assert case["fixture"]["kind"] == "html"
        assert (
            facts["entity"]["listing"]["collection_evidence"]
            == _EMPTY_COLLECTION_EVIDENCE
        )
        assert outcome["page_kind"] == "article"
    if case["id"] == "searchable_blog_root_without_collection":
        assert (
            facts["entity"]["listing"]["collection_evidence"]
            == _EMPTY_COLLECTION_EVIDENCE
        )
        assert outcome["page_kind"] != "category"


def test_classifier_calibration_reports_exact_metrics_and_abstention() -> None:
    outcomes = [
        (
            case["expected"]["page_kind"],
            _calibration_outcome(case)["page_kind"],
            case["deliberate_abstention"],
        )
        for case in _CALIBRATION_CASES
    ]
    per_kind: dict[str, dict[str, float | int]] = {}
    confusion = {
        kind: {predicted: 0 for predicted in PAGE_KINDS} for kind in PAGE_KINDS
    }
    for expected, predicted, _deliberate in outcomes:
        confusion[expected][predicted] += 1
    for kind in PAGE_KINDS:
        true_positive = confusion[kind][kind]
        false_positive = sum(
            confusion[expected][kind] for expected in PAGE_KINDS if expected != kind
        )
        false_negative = sum(
            confusion[kind][predicted] for predicted in PAGE_KINDS if predicted != kind
        )
        per_kind[kind] = {
            "support": sum(confusion[kind].values()),
            "precision": (
                true_positive / (true_positive + false_positive)
                if true_positive + false_positive
                else 0.0
            ),
            "recall": (
                true_positive / (true_positive + false_negative)
                if true_positive + false_negative
                else 0.0
            ),
        }

    observed_abstentions = sum(predicted == "other" for _, predicted, _ in outcomes)
    expected_abstentions = sum(deliberate for _, _, deliberate in outcomes)
    correct_deliberate_abstentions = sum(
        expected == predicted == "other" and deliberate
        for expected, predicted, deliberate in outcomes
    )
    report = {
        "per_kind": per_kind,
        "confusion": confusion,
        "observed_abstentions": observed_abstentions,
        "expected_deliberate_abstentions": expected_abstentions,
        "correct_deliberate_abstentions": correct_deliberate_abstentions,
    }

    assert all(row["support"] > 0 for row in per_kind.values()), report
    assert all(
        row["precision"] == 1.0 and row["recall"] == 1.0 for row in per_kind.values()
    ), report
    assert observed_abstentions == expected_abstentions, report
    assert correct_deliberate_abstentions == expected_abstentions, report
