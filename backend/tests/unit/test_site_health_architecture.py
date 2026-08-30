"""Deterministic observed-architecture derivation and safety guards."""

from __future__ import annotations

import uuid

from app.analysis.site_health.architecture import (
    ArchitecturePage,
    build_observed_architecture,
    common_structure_observations,
    evaluate_architecture_rules,
    resolve_archetype,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_UNAVAILABLE,
)
from app.core.config.site_health_link_metrics import (
    COVERAGE_STATE_COMPLETE,
    COVERAGE_STATE_PARTIAL,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_CATEGORY,
    PAGE_KIND_DOCS,
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_PRODUCT,
)


def _page(
    path: str,
    page_kind: str,
    *,
    depth: int | None = 1,
    inbound: int = 1,
    outbound: int = 1,
    title: str = "",
    description: str = "",
    facts: dict | None = None,
) -> ArchitecturePage:
    return ArchitecturePage(
        site_url_id=uuid.uuid5(uuid.NAMESPACE_URL, path),
        analysis_id=uuid.uuid5(uuid.NAMESPACE_OID, f"analysis:{path}"),
        artifact_id=uuid.uuid5(uuid.NAMESPACE_OID, f"artifact:{path}"),
        link_metric_id=uuid.uuid5(uuid.NAMESPACE_OID, f"metric:{path}"),
        url=f"https://example.com{path}",
        title=title,
        meta_description=description,
        page_kind=page_kind,
        depth_from_home=depth,
        inbound_count=inbound,
        outbound_count=outbound,
        indexable=True,
        facts=facts or {},
    )


def _context(**overrides) -> dict:
    context = {
        "business_model": "retail",
        "market_scope": "national",
        "knowledge_strength": "strong",
        "field_confidence": {"business_model": 0.9},
    }
    context.update(overrides)
    return context


def test_page_kinds_and_link_summaries_freeze_metrics_and_guard_absence() -> None:
    pages = [_page("/", PAGE_KIND_HOMEPAGE, depth=0, title="Home")]
    pages.extend(
        _page(
            f"/products/item-{index}",
            PAGE_KIND_PRODUCT,
            depth=index + 1,
            inbound=0 if index == 0 else 1,
            title="Same product",
            description="Same description",
        )
        for index in range(3)
    )
    complete = build_observed_architecture(
        pages=pages,
        coverage_state=COVERAGE_STATE_COMPLETE,
        business_context=_context(),
    )
    page_kind = next(
        row for row in complete.page_kinds if row["page_kind"] == "product"
    )
    assert page_kind["page_count"] == 3
    assert page_kind["median_depth"] == 2.0
    assert page_kind["duplicate_metadata_count"] == 3
    assert page_kind["orphan_count"] == 1
    assert complete.internal_linking == {
        "internal_link_count": 4,
        "pages_with_incoming_count": 3,
        "pages_with_incoming_percentage": 0.75,
        "orphan_page_count": 1,
    }
    assert complete.structure_depth["measured_page_count"] == 4
    assert [row["page_count"] for row in complete.structure_depth["buckets"]] == [
        1,
        1,
        1,
        1,
    ]

    partial = build_observed_architecture(
        pages=pages,
        coverage_state=COVERAGE_STATE_PARTIAL,
        business_context=_context(),
    )
    page_kind = next(row for row in partial.page_kinds if row["page_kind"] == "product")
    assert page_kind["orphan_count"] is None
    assert partial.internal_linking["orphan_page_count"] is None


def test_hierarchy_uses_breadcrumb_then_explicit_then_safe_path_or_unknown() -> None:
    home = _page("/", PAGE_KIND_HOMEPAGE, depth=0)
    category = _page("/products", PAGE_KIND_CATEGORY)
    breadcrumb = _page(
        "/products/breadcrumb",
        PAGE_KIND_PRODUCT,
        facts={
            "commerce": {
                "breadcrumb_links": [
                    {"url": home.url},
                    {"url": category.url},
                ]
            },
            "structured_data": [{"is_part_of_url": home.url}],
        },
    )
    explicit = _page(
        "/elsewhere/explicit",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": category.url}]},
    )
    path_parent = _page("/products/path-parent", PAGE_KIND_PRODUCT)
    unknown = _page("/missing/unknown", PAGE_KIND_PRODUCT)
    model = build_observed_architecture(
        pages=[home, category, breadcrumb, explicit, path_parent, unknown],
        coverage_state=COVERAGE_STATE_COMPLETE,
        business_context=_context(),
    )
    by_url = {row["url"]: row for row in model.pages}
    assert by_url[breadcrumb.url]["parent_source"] == "breadcrumb"
    assert by_url[breadcrumb.url]["parent_site_url_id"] == str(category.site_url_id)
    assert by_url[explicit.url]["parent_source"] == "explicit_structure"
    assert by_url[explicit.url]["parent_site_url_id"] == str(category.site_url_id)
    assert by_url[path_parent.url]["parent_source"] == "url_parent"
    assert by_url[path_parent.url]["parent_site_url_id"] == str(category.site_url_id)
    assert by_url[unknown.url]["parent_source"] == "unknown"
    assert by_url[unknown.url]["parent_site_url_id"] is None


def test_hierarchy_suppresses_explicit_parent_cycles() -> None:
    first_url = "https://example.com/first"
    second_url = "https://example.com/second"
    first = _page(
        "/first",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": second_url}]},
    )
    second = _page(
        "/second",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": first_url}]},
    )
    model = build_observed_architecture(
        pages=[first, second],
        coverage_state=COVERAGE_STATE_COMPLETE,
        business_context=_context(),
    )
    assert any(row["cycle_suppressed"] for row in model.pages)
    assert not all(row["parent_site_url_id"] for row in model.pages)


def test_hierarchy_preserves_page_that_only_points_into_parent_cycle() -> None:
    outside = _page(
        "/a",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": "https://example.com/b"}]},
    )
    first = _page(
        "/b",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": "https://example.com/c"}]},
    )
    second = _page(
        "/c",
        PAGE_KIND_PRODUCT,
        facts={"structured_data": [{"is_part_of_url": "https://example.com/b"}]},
    )
    model = build_observed_architecture(
        pages=[outside, first, second],
        coverage_state=COVERAGE_STATE_COMPLETE,
        business_context=_context(),
    )
    by_url = {row["url"]: row for row in model.pages}

    assert by_url[outside.url]["parent_site_url_id"] == str(first.site_url_id)
    assert not by_url[outside.url]["cycle_suppressed"]
    assert sum(bool(row["cycle_suppressed"]) for row in model.pages) == 1


def test_archetype_resolution_abstains_on_every_unsafe_profile_path() -> None:
    commerce_pages = [_page("/products/widget", PAGE_KIND_PRODUCT)]
    cases = (
        ({}, "profile_absent"),
        (_context(knowledge_strength="none"), "knowledge_strength_none"),
        (
            _context(field_confidence={"business_model": 0.2}),
            "business_model_confidence_below_floor",
        ),
    )
    for context, reason in cases:
        assessment = resolve_archetype(
            business_context=context,
            pages=commerce_pages,
            coverage_state=COVERAGE_STATE_COMPLETE,
        )
        assert assessment.archetype == "other"
        assert assessment.reason == reason

    contradictory = [_page(f"/docs/{index}", PAGE_KIND_DOCS) for index in range(5)]
    assessment = resolve_archetype(
        business_context=_context(),
        pages=contradictory,
        coverage_state=COVERAGE_STATE_COMPLETE,
    )
    assert assessment.archetype == "other"
    assert assessment.reason == "crawl_materially_contradicts_profile"

    pricing_pages = [_page(f"/pricing/{index}", "pricing") for index in range(5)]
    assessment = resolve_archetype(
        business_context=_context(),
        pages=pricing_pages,
        coverage_state=COVERAGE_STATE_COMPLETE,
    )
    assert assessment.archetype == "commerce"
    assert assessment.reason == "profile_supported"


def test_archetype_absence_advice_requires_complete_coverage() -> None:
    pages = [_page("/products/widget", PAGE_KIND_PRODUCT)]
    complete = resolve_archetype(
        business_context=_context(),
        pages=pages,
        coverage_state=COVERAGE_STATE_COMPLETE,
    )
    assert complete.archetype == "commerce"
    assert {row["key"] for row in complete.observed} == {"products"}
    assert complete.not_observed

    partial = resolve_archetype(
        business_context=_context(),
        pages=pages,
        coverage_state=COVERAGE_STATE_PARTIAL,
    )
    assert partial.archetype == "commerce"
    assert partial.not_observed == ()


def test_structural_rules_fire_positive_observations_and_abstain_on_absence() -> None:
    pages = [_page("/", PAGE_KIND_HOMEPAGE, depth=0)]
    pages.extend(
        _page(
            f"/products/item-{index}",
            PAGE_KIND_PRODUCT,
            depth=5,
            inbound=0,
            title="Duplicate",
            description="Duplicate",
        )
        for index in range(3)
    )
    partial = build_observed_architecture(
        pages=pages,
        coverage_state=COVERAGE_STATE_PARTIAL,
        business_context=_context(),
    )
    outcomes = {
        evaluation.rule_id: evaluation.outcome
        for evaluation in evaluate_architecture_rules(
            model=partial,
            source_pages=pages,
            coverage_state=COVERAGE_STATE_PARTIAL,
        )
    }
    assert outcomes["architecture.excessive_depth"] == RULE_OUTCOME_MISSING
    assert (
        outcomes["architecture.duplicate_metadata_in_page_kind"] == RULE_OUTCOME_MISSING
    )
    assert outcomes["architecture.orphan_pages"] == RULE_OUTCOME_UNAVAILABLE
    assert outcomes["architecture.parentless_detail_pages"] == RULE_OUTCOME_UNAVAILABLE
    assert outcomes["architecture.unhubbed_page_kind"] == RULE_OUTCOME_UNAVAILABLE

    complete = build_observed_architecture(
        pages=pages,
        coverage_state=COVERAGE_STATE_COMPLETE,
        business_context=_context(),
    )
    outcomes = {
        evaluation.rule_id: evaluation.outcome
        for evaluation in evaluate_architecture_rules(
            model=complete,
            source_pages=pages,
            coverage_state=COVERAGE_STATE_COMPLETE,
        )
    }
    assert outcomes["architecture.orphan_pages"] == RULE_OUTCOME_MISSING
    assert outcomes["architecture.parentless_detail_pages"] == RULE_OUTCOME_MISSING
    assert outcomes["architecture.unhubbed_page_kind"] == RULE_OUTCOME_MISSING


def _structure_keys(result: tuple[list[dict], list[dict]]) -> set[str]:
    return {row["key"] for group in result for row in group}


def test_common_structures_are_matched_by_kind_or_path_and_gate_local() -> None:
    """The read path re-runs this policy on a correction, so it must be pure.

    It takes ``(page_kind, url)`` pairs rather than the analysis dataclass, and
    a location structure stays out of the comparison entirely unless the user
    confirmed a local/regional market.
    """
    pages = [
        (PAGE_KIND_PRODUCT, "https://x.test/p/widget"),
        ("trust_policy", "https://x.test/pages/refund-policy"),
    ]
    observed, not_observed = common_structure_observations(
        archetype="commerce", pages=pages, market_scope="national"
    )
    assert [row["key"] for row in observed] == ["products", "shipping_returns"]
    assert [row["key"] for row in not_observed] == [
        "categories",
        "contact",
        "help_hub",
        "editorial",
    ]

    national = common_structure_observations(
        archetype="services", pages=pages, market_scope="national"
    )
    local = common_structure_observations(
        archetype="services", pages=pages, market_scope="local"
    )
    assert "locations" not in _structure_keys(national)
    assert "locations" in _structure_keys(local)
