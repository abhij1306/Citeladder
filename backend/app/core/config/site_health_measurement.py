"""Version-1 Site Health measurement, checkpoint, and presentation policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from app.core.config.site_health_taxonomy import (
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_ARTICLE,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_CATEGORY,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_DOCS,
    PAGE_KIND_FAQ,
    PAGE_KIND_GUIDE,
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_LOCAL,
    PAGE_KIND_OTHER,
    PAGE_KIND_PRICING,
    PAGE_KIND_PRODUCT,
    PAGE_KIND_SERVICE,
    PAGE_KIND_TRUST_POLICY,
    PAGE_KINDS,
)

PROFILE_VERSION: Final = "sh-profiles-1"
SCHEMA_CONTRACT_VERSION: Final = "sh-schema-1"
PRESENTATION_VERSION: Final = "sh-presentation-1"
SITE_HEALTH_OVERVIEW_TREND_POINT_LIMIT: Final = 12

MEASUREMENT_STATE_MEASURED: Final = "measured"
MEASUREMENT_STATE_LIMITED: Final = "limited_evidence"
MEASUREMENT_STATE_NOT_MEASURED: Final = "not_measured"
MEASUREMENT_STATE_EXCLUDED: Final = "excluded"

DIMENSION_APPLICABLE: Final = "applicable"
DIMENSION_NOT_APPLICABLE: Final = "not_applicable"
MEASURED_AT_SITE_SCOPE_REASON: Final = "measured_at_site_scope"

AEO_MEASURED_MIN_COVERAGE: Final = 0.80
AEO_MEASURED_MIN_CHECKPOINTS: Final = 4
AEO_MEASURED_MIN_FAMILIES: Final = 3
AEO_MEASURED_MIN_DIMENSIONS: Final = 3
TECHNICAL_MEASURED_MIN_COVERAGE: Final = 0.80

READINESS_DIMENSION_WEIGHTS: Final[dict[str, float]] = {
    "answerability": 0.20,
    "structure": 0.15,
    "evidence": 0.15,
    "machine-readability": 0.20,
    "authority": 0.10,
    "freshness": 0.05,
    "crawlability": 0.15,
}

# Site rollups are invariant to the page mix found by a crawl. Each relevant
# page kind has one fixed vote within a page-scoped rule unless product policy
# explicitly assigns a different config-owned weight later.
PAGE_KIND_ROLLUP_WEIGHTS: Final[dict[str, float]] = {
    page_kind: 1.0 for page_kind in PAGE_KINDS
}


# Search eligibility intentionally uses only the two determinate checks below.
# Crawler and snippet observations remain supplemental until a later explicit
# contract change supplies determinate healthy and blocker evidence.
SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1: Final[tuple[str, ...]] = (
    "acquisition.public_representation",
    "search.indexability",
)

WEB_FUNDAMENTALS_AREAS: Final[tuple[str, ...]] = (
    "accessibility",
    "mobile",
    "security",
    "lab",
)

_UNIVERSAL_READINESS: Final[tuple[str, ...]] = (
    "technical.indexable",
    "aeo.server_rendered_content",
    "aeo.no_expand_gating",
    "search.snippet_access",
    "search.crawler_access",
)
_SCHEMA_READINESS: Final[tuple[str, ...]] = (
    "aeo.schema_expected_for_type",
    "aeo.schema_required_valid",
    "aeo.schema_recommended_present",
    "aeo.schema_matches_content",
)
_EDITORIAL_READINESS: Final[tuple[str, ...]] = (
    "aeo.content_date_present",
    "aeo.outbound_citations",
    "aeo.editorial_lead_present",
)
_ORGANIZATION_IDENTITY_CHECKPOINT: Final = "aeo.organization_identity"

# The complete page-kind expectation authority. Services never manufacture a
# second profile from evaluator outcomes; ``other`` deliberately stays on the
# universal contract.
_PAGE_KIND_READINESS_CHECKPOINTS: Final[dict[str, tuple[str, ...]]] = {
    kind: _UNIVERSAL_READINESS + (() if kind == PAGE_KIND_OTHER else _SCHEMA_READINESS)
    for kind in PAGE_KINDS
}
for _classified_kind in PAGE_KINDS:
    if _classified_kind != PAGE_KIND_OTHER:
        _PAGE_KIND_READINESS_CHECKPOINTS[_classified_kind] += ("aeo.heading_hierarchy",)

_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_HOMEPAGE] += (
    _ORGANIZATION_IDENTITY_CHECKPOINT,
    "aeo.trust_path_present",
    "aeo.entity_value_proposition",
)
for _entity_kind in (
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_PRICING,
    PAGE_KIND_SERVICE,
    PAGE_KIND_LOCAL,
):
    _PAGE_KIND_READINESS_CHECKPOINTS[_entity_kind] += (
        _ORGANIZATION_IDENTITY_CHECKPOINT,
        "aeo.entity_value_proposition",
    )
for _editorial_kind in (
    PAGE_KIND_ARTICLE,
    PAGE_KIND_GUIDE,
    PAGE_KIND_COMPARISON,
):
    _PAGE_KIND_READINESS_CHECKPOINTS[_editorial_kind] += (
        *_EDITORIAL_READINESS,
        "aeo.author_present",
    )
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_DOCS] += (
    *_EDITORIAL_READINESS,
    _ORGANIZATION_IDENTITY_CHECKPOINT,
)
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_CASE_STUDY_REVIEW] += (
    "aeo.content_date_present",
    "aeo.outbound_citations",
    "aeo.editorial_lead_present",
    _ORGANIZATION_IDENTITY_CHECKPOINT,
)
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_FAQ] += (
    "aeo.answer_first",
    "aeo.question_headings",
    _ORGANIZATION_IDENTITY_CHECKPOINT,
)
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_PRODUCT] += (
    "aeo.product_answer_facts",
    "aeo.product_evidence_facts",
    "aeo.product_brand_identity",
    "aeo.offer_freshness_signal",
)
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_CATEGORY] += (
    "aeo.listing_answer_set",
    "aeo.listing_item_facts",
    "aeo.assortment_freshness_signal",
    _ORGANIZATION_IDENTITY_CHECKPOINT,
)
_PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_TRUST_POLICY] += (
    _ORGANIZATION_IDENTITY_CHECKPOINT,
)

_UNIVERSAL_RELEVANT_DIMENSIONS: Final = (
    "structure",
    "machine-readability",
    "crawlability",
)
_ALL_RELEVANT_DIMENSIONS: Final = tuple(READINESS_DIMENSION_WEIGHTS)
_ENTITY_RELEVANT_DIMENSIONS: Final = tuple(
    key for key in _ALL_RELEVANT_DIMENSIONS if key != "freshness"
)
_FAQ_RELEVANT_DIMENSIONS: Final = tuple(
    key for key in _ALL_RELEVANT_DIMENSIONS if key not in {"evidence", "freshness"}
)

# These dimensions are semantically relevant, but the approved deterministic
# catalog has no honest evaluator for them yet. Keeping the gap config-owned
# prevents evaluator absence from silently becoming semantic N/A.
KNOWN_MEASUREMENT_GAPS: Final[dict[tuple[str, str], str]] = {
    (PAGE_KIND_HOMEPAGE, "evidence"): "claim_support_attachment_unavailable",
    (PAGE_KIND_ABOUT_CONTACT, "evidence"): "claim_support_attachment_unavailable",
    (PAGE_KIND_PRICING, "evidence"): "claim_support_attachment_unavailable",
    (PAGE_KIND_SERVICE, "evidence"): "claim_support_attachment_unavailable",
    (PAGE_KIND_LOCAL, "evidence"): "claim_support_attachment_unavailable",
}

# Dimension relevance is independent from checkpoint availability. An empty
# expression therefore remains applicable + unmeasured instead of disappearing
# as semantic N/A. ``other`` is the deliberate abstention baseline.
_PAGE_KIND_RELEVANT_DIMENSIONS: Final[dict[str, tuple[str, ...]]] = {
    kind: _UNIVERSAL_RELEVANT_DIMENSIONS for kind in PAGE_KINDS
}
for _fully_measured_kind in (
    PAGE_KIND_ARTICLE,
    PAGE_KIND_GUIDE,
    PAGE_KIND_DOCS,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_PRODUCT,
    PAGE_KIND_CATEGORY,
):
    _PAGE_KIND_RELEVANT_DIMENSIONS[_fully_measured_kind] = _ALL_RELEVANT_DIMENSIONS
for _entity_kind in (
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_PRICING,
    PAGE_KIND_SERVICE,
    PAGE_KIND_LOCAL,
):
    _PAGE_KIND_RELEVANT_DIMENSIONS[_entity_kind] = _ENTITY_RELEVANT_DIMENSIONS
_PAGE_KIND_RELEVANT_DIMENSIONS[PAGE_KIND_FAQ] = _FAQ_RELEVANT_DIMENSIONS
_PAGE_KIND_RELEVANT_DIMENSIONS[PAGE_KIND_TRUST_POLICY] = (
    "structure",
    "machine-readability",
    "authority",
    "crawlability",
)


def expected_checkpoints(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Return checkpoint expectations from structural context only."""
    effective_kind = page_kind if page_kind in PAGE_KINDS else PAGE_KIND_OTHER
    expected = set(_PAGE_KIND_READINESS_CHECKPOINTS[effective_kind])
    del page_traits
    if not bool((crawl_context or {}).get("is_site_root")):
        expected.discard("search.crawler_access")
    return tuple(sorted(expected))


def relevant_dimensions(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Return semantically relevant dimensions from structural context only."""
    del crawl_context
    effective_kind = page_kind if page_kind in PAGE_KINDS else PAGE_KIND_OTHER
    relevant = set(_PAGE_KIND_RELEVANT_DIMENSIONS[effective_kind])
    del page_traits
    return tuple(key for key in READINESS_DIMENSION_WEIGHTS if key in relevant)


STRUCTURAL_NA_REASONS: Final[frozenset[str]] = frozenset(
    {
        "no_canonical",
        "empty_title",
        "empty_meta_description",
        "no_product_schema",
        "no_expected_type_block",
        "no_required_properties",
        "no_recommended_properties",
        "no_schema_names",
        "no_sitemap",
        "no_hreflang",
        "no_html",
        "format_has_no_html",
        "other_page_kind",
        "trait_not_observed",
        "not_site_root",
        "crawl_finalize_scope",
        "content_not_server_rendered",
        "intentional_non_indexing",
    }
)

UNAVAILABLE_REASONS: Final[frozenset[str]] = frozenset(
    {"coverage_not_complete", "no_checkable_alternates", "no_ttfb_measurement"}
)
UNKNOWN_REASONS: Final[frozenset[str]] = frozenset(
    {
        "currency_unavailable",
        "freshness_timestamp_unavailable",
        "insufficient_evidence",
        "robots_not_fetched",
        "unknown_applicability",
    }
)
