"""Structural region scoping and primary-entity signals.

Every fixture here reproduces a shape observed on a real crawled storefront,
and each assertion pins a defect that shape actually produced: an inline
script's regex replacement string read as the page's visible price, a
recommendation carousel speaking for a policy page, a navigation menu drowning
every link-derived signal, and a flat ecommerce slug with no route family.

Pure and offline: fixtures are parsed from disk, nothing touches the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import html as lxml_html

from app.analysis.site_health.fact_entity import (
    empty_entity_signals,
    extract_entity_signals,
)
from app.analysis.site_health.fact_regions import (
    card_list_containers,
    element_region,
    primary_region,
    primary_region_text,
)
from app.analysis.site_health.page_kinds import classify
from app.analysis.site_health.parser import extract_page_facts
from app.core.config import site_health_taxonomy as config

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "site_health"


def _tree(name: str):
    return lxml_html.fromstring((_FIXTURES / name).read_text(encoding="utf-8"))


def _facts(name: str, url: str) -> dict:
    return extract_page_facts(
        (_FIXTURES / name).read_bytes(), final_url=url, content_type="text/html"
    )


# --- the primary region ------------------------------------------------------


def test_primary_region_prefers_main_over_body() -> None:
    _node, source = primary_region(_tree("pdp_with_recommendations.html"))
    assert source == "main"


def test_region_text_excludes_inline_script_bodies() -> None:
    # The defect this pins: ``commerce.visible_price`` was "$1" on all 99 pages
    # of the reference crawl, matched inside a JavaScript replacement string.
    text = primary_region_text(_tree("pdp_with_recommendations.html"))
    assert "replace" not in text
    assert "\\$1" not in text
    assert "Dillen Letter Carrier" in text


def test_region_text_excludes_navigation_and_footer() -> None:
    text = primary_region_text(_tree("flat_category_listing.html"))
    assert "Sleepwear" not in text  # nav
    assert "Privacy" not in text  # footer
    assert "56 results" in text


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("/collections/bags", "nav"),
        ("/products/rec-a", "main"),
        ("/products/promo-one", "footer"),
    ],
)
def test_anchor_region_comes_from_the_dom(href: str, expected: str) -> None:
    # Chrome is identified structurally. Inferring it later from how often a
    # link repeats across a crawl would depend on crawl coverage and would
    # mistake a genuinely popular hub for boilerplate.
    tree = _tree("pdp_with_recommendations.html")
    anchor = next(a for a in tree.iter("a") if (a.get("href") or "") == href)
    assert element_region(anchor) == expected


def test_parser_records_the_region_of_every_anchor() -> None:
    facts = _facts("pdp_with_recommendations.html", "https://example.test/products/x")
    regions = {anchor["region"] for anchor in facts["links"]["anchors"]}
    assert regions == {"nav", "main", "footer"}


# --- repeated card lists -----------------------------------------------------


def test_recommendation_carousel_is_detected_as_a_card_list() -> None:
    region, _source = primary_region(_tree("pdp_with_recommendations.html"))
    assert len(card_list_containers(region)) == 1


def test_unrelated_linked_sections_are_not_a_card_list() -> None:
    tree = lxml_html.fromstring(
        """<html><body><main>
        <div><a href='/a'>A</a></div>
        <div><p><a href='/b'>B</a></p></div>
        <div><section><a href='/c'>C</a></section></div>
        </main></body></html>"""
    )
    region, _source = primary_region(tree)
    assert card_list_containers(region) == []


def test_card_list_tolerates_optional_child_markup() -> None:
    tree = lxml_html.fromstring(
        """<html><body><main><ul>
        <li><a href='/a'>A</a><span>$10</span></li>
        <li><a href='/b'>B</a><span>$20</span><em>Sale</em></li>
        <li><a href='/c'>C</a><span>$30</span></li>
        </ul></main></body></html>"""
    )
    region, _source = primary_region(tree)
    assert len(card_list_containers(region)) == 1


def test_product_signals_ignore_the_recommendation_carousel() -> None:
    # The carousel carries four prices and four "Add to cart" buttons. None of
    # them describe this page, so none of them may speak for it.
    signals = extract_entity_signals(_tree("policy_with_recommendations.html"))
    assert signals["product"] == {
        "has_primary_price": False,
        "has_product_detail_heading": False,
        "has_purchase_control": False,
        "has_variant_control": False,
        "has_sku_marker": False,
    }


def test_product_signals_read_the_pages_own_buy_box() -> None:
    signals = extract_entity_signals(_tree("pdp_with_recommendations.html"))
    assert signals["product"]["has_primary_price"] is True
    assert signals["product"]["has_purchase_control"] is True
    assert signals["product"]["has_variant_control"] is True
    assert signals["product"]["has_sku_marker"] is True


def test_product_detail_heading_is_scoped_to_primary_content() -> None:
    primary = lxml_html.fromstring(
        "<html><body><main><p>$19.00</p><h2>Product Information</h2></main>"
        "</body></html>"
    )
    chrome_only = lxml_html.fromstring(
        "<html><body><nav><h2>Product Information</h2></nav>"
        "<main><p>$19.00</p></main></body></html>"
    )

    assert extract_entity_signals(primary)["product"]["has_product_detail_heading"]
    assert not extract_entity_signals(chrome_only)["product"][
        "has_product_detail_heading"
    ]


@pytest.mark.parametrize("tag", ["script", "style", "noscript", "template"])
def test_product_price_ignores_non_rendered_subtrees(tag: str) -> None:
    tree = lxml_html.fromstring(
        f"<html><body><main><{tag}>$195.00</{tag}><p>No visible price</p></main>"
        "</body></html>"
    )
    signals = extract_entity_signals(tree)
    assert signals["product"]["has_primary_price"] is False


def test_entity_controls_ignore_non_rendered_template() -> None:
    tree = lxml_html.fromstring(
        """<html><body><main><p>$195.00</p><template>
        <button>Add to cart</button><select name='size'>
        <option>S</option><option>M</option></select>
        <address itemprop='address'>Hidden address</address>
        </template></main></body></html>"""
    )
    signals = extract_entity_signals(tree)
    assert signals["product"]["has_primary_price"] is True
    assert signals["product"]["has_purchase_control"] is False
    assert signals["product"]["has_variant_control"] is False
    assert signals["location"]["address_entity_count"] == 0


# --- listing structure -------------------------------------------------------


def test_listing_signals_describe_a_real_grid() -> None:
    signals = extract_entity_signals(_tree("flat_category_listing.html"))["listing"]
    assert signals["largest_card_list_size"] >= config.LISTING_MIN_CARD_ITEMS
    assert signals["has_result_count"] is True
    assert signals["has_sort_control"] is True
    assert signals["has_filter_control"] is True


def test_sort_dropdown_is_not_read_as_a_variant_picker() -> None:
    # A "Sort by" control is a multi-option <select>, structurally identical to
    # a size picker. Counting it as a variant control would let every category
    # page corroborate a product reading of itself.
    signals = extract_entity_signals(_tree("flat_category_listing.html"))
    assert signals["product"]["has_variant_control"] is False


def test_javascript_rendered_grid_yields_no_listing_evidence() -> None:
    signals = extract_entity_signals(_tree("hydrated_collection_shell.html"))["listing"]
    assert signals["largest_card_list_size"] == 0
    assert signals["has_result_count"] is False


# --- location ----------------------------------------------------------------


def test_single_store_page_has_exactly_one_address_entity() -> None:
    location = extract_entity_signals(_tree("single_store_page.html"))["location"]
    assert location["address_entity_count"] == 1
    assert location["has_phone"] is True


def test_store_locator_lists_many_addresses() -> None:
    location = extract_entity_signals(_tree("store_locator_index.html"))["location"]
    assert location["address_entity_count"] > 1


# --- end to end through the parser and classifier ----------------------------


@pytest.mark.parametrize(
    ("fixture", "url", "expected_kind", "expected_confidence"),
    [
        # A PDP keeps its type even though a carousel sits inside its main
        # region, and even though its route says nothing about products.
        (
            "pdp_with_recommendations.html",
            "https://example.test/Categories/Bags/Dillen/BDILL1725",
            "product",
            "medium",
        ),
        # The same carousel on a policy page must not make it a product. The
        # page's own stated purpose carries it instead, at low confidence.
        (
            "policy_with_recommendations.html",
            "https://example.test/pages/refund-policy",
            "trust_policy",
            "low",
        ),
        # A flat slug with no route family, identified by its listing structure.
        (
            "flat_category_listing.html",
            "https://example.test/womens-dresses",
            "category",
            "high",
        ),
        # No listing evidence exists, so the route family carries the page and
        # says so by reporting a weaker confidence.
        (
            "hydrated_collection_shell.html",
            "https://example.test/collections/new-arrivals",
            "category",
            "medium",
        ),
        (
            "single_store_page.html",
            "https://example.test/store/Gosford",
            "local",
            "high",
        ),
    ],
)
def test_fixture_classifies_end_to_end(
    fixture: str, url: str, expected_kind: str, expected_confidence: str
) -> None:
    assessment = classify(url, _facts(fixture, url))
    assert assessment.page_kind == expected_kind
    assert assessment.confidence == expected_confidence


def test_store_locator_is_not_treated_as_one_local_business() -> None:
    url = "https://example.test/pages/store-locator"
    assessment = classify(url, _facts("store_locator_index.html", url))
    assert assessment.page_kind == "service"


def test_visible_price_is_read_from_the_page_not_from_a_script() -> None:
    facts = _facts("pdp_with_recommendations.html", "https://example.test/products/x")
    assert facts["commerce"]["visible_price"] == "$195.00"


def test_visible_price_excludes_repeated_recommendation_cards() -> None:
    facts = _facts(
        "policy_with_recommendations.html",
        "https://example.test/pages/refund-policy",
    )
    assert facts["commerce"]["visible_price"] == ""


def test_body_without_content_carries_the_zero_entity_shape() -> None:
    # A page with nothing to observe reports the zero value rather than an
    # absent key, so a downstream reader never has to guess whether the
    # extractor ran.
    facts = extract_page_facts(
        b"<html><body></body></html>",
        final_url="https://example.test/empty",
        content_type="text/html",
    )
    zero = empty_entity_signals()
    assert set(facts["entity"]) == set(zero)
    for group in ("product", "listing", "location"):
        assert facts["entity"][group] == zero[group]


def test_extraction_is_deterministic() -> None:
    tree_a = _tree("pdp_with_recommendations.html")
    tree_b = _tree("pdp_with_recommendations.html")
    assert extract_entity_signals(tree_a) == extract_entity_signals(tree_b)
