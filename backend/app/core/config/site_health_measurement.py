"""Version-1 Site Health measurement, checkpoint, and presentation policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final

from app.core.config.site_health_family_profile import (
    CAPABILITY_FAMILIES_BY_ID as CAPABILITY_FAMILIES_BY_ID,
)
from app.core.config.site_health_family_profile import (
    CAPABILITY_FAMILY_MANIFEST as CAPABILITY_FAMILY_MANIFEST,
)
from app.core.config.site_health_family_profile import (
    CHECKPOINT_DIMENSION_BY_ID as CHECKPOINT_DIMENSION_BY_ID,
)
from app.core.config.site_health_family_profile import (
    CHECKPOINT_FAMILY_BY_ID as CHECKPOINT_FAMILY_BY_ID,
)
from app.core.config.site_health_family_profile import (
    CLASSIFIED_KIND_FAMILY_PROFILE as CLASSIFIED_KIND_FAMILY_PROFILE,
)
from app.core.config.site_health_family_profile import (
    PROFILE_STATUS_MEASURED as PROFILE_STATUS_MEASURED,
)
from app.core.config.site_health_family_profile import (
    PROFILE_STATUS_NOT_APPLICABLE as PROFILE_STATUS_NOT_APPLICABLE,
)
from app.core.config.site_health_family_profile import (
    CapabilityFamily as CapabilityFamily,
)
from app.core.config.site_health_family_profile import (
    CheckpointExpression as CheckpointExpression,
)
from app.core.config.site_health_family_profile import (
    FamilyProfileRow as FamilyProfileRow,
)
from app.core.config.site_health_family_profile import (
    expected_checkpoint_expressions as _expected_checkpoint_expressions,
)
from app.core.config.site_health_family_profile import (
    expected_checkpoints as _expected_checkpoints,
)
from app.core.config.site_health_family_profile import (
    expected_families as _expected_families,
)
from app.core.config.site_health_family_profile import (
    profile_rows as profile_rows,
)
from app.core.config.site_health_family_profile import (
    relevant_dimensions as _relevant_dimensions,
)
from app.core.config.site_health_family_profile import (
    site_checkpoint_expressions as _site_checkpoint_expressions,
)
from app.core.config.site_health_family_profile import (
    validate_measurement_profile as validate_measurement_profile,
)
from app.core.config.site_health_family_profile_projection import (
    measurement_gap_reasons as _measurement_gap_reasons,
)
from app.core.config.site_health_family_profile_projection import (
    serialized_family_profile as serialized_family_profile,
)
from app.core.config.site_health_taxonomy import PAGE_KINDS

PROFILE_VERSION: Final = "sh-profiles-1"
SCHEMA_CONTRACT_VERSION: Final = "sh-schema-1"
PRESENTATION_VERSION: Final = "sh-presentation-1"
SITE_HEALTH_OVERVIEW_TREND_POINT_LIMIT: Final = 12
CLASSIFICATION_FORMULA_VERSION: Final = "sh-classification-1"
CLASSIFICATION_STATE_COMPLETE: Final = "complete"
CLASSIFICATION_STATE_PARTIAL: Final = "partial"
CLASSIFICATION_STATE_NOT_MEASURED: Final = "not_measured"
SOURCE_SUPPORT_MAX_ITEMS: Final = 24
SOURCE_SUPPORT_SECTION_HEADINGS: Final[frozenset[str]] = frozenset(
    {"methodology", "references", "sources"}
)
SOURCE_SUPPORT_ATTRIBUTION_PATTERN: Final = (
    r"(?:\b(?:according to|data from|reported by|research from)\b|\bsource\s*:)"
)
SOURCE_SUPPORT_CITATION_MARKER_PATTERN: Final = (
    r"(?:\[[0-9]{1,3}\]|\([A-Z][A-Za-z& .'-]{1,80},?\s+[12][0-9]{3}\)|"
    r"\b(?:cite|citation|reference)\b)"
)
FRESHNESS_ROUTE_SEGMENTS: Final[frozenset[str]] = frozenset(
    {"changelog", "news", "release", "releases"}
)
FRESHNESS_IDENTITY_PATTERN: Final = (
    r"\b(?:v(?:ersion)?\s*\d+(?:\.\d+)*|(?:19|20)\d{2})\b"
)
FRESHNESS_PURPOSE_PATTERN: Final = (
    r"\b(?:annual report|changelog|current event|news|quarterly report|"
    r"release notes|state of|what(?:'|’)s new)\b"
)

MEASUREMENT_STATE_MEASURED: Final = "measured"
MEASUREMENT_STATE_LIMITED: Final = "limited_evidence"
MEASUREMENT_STATE_NOT_MEASURED: Final = "not_measured"
MEASUREMENT_STATE_EXCLUDED: Final = "excluded"

DIMENSION_APPLICABLE: Final = "applicable"
DIMENSION_NOT_APPLICABLE: Final = "not_applicable"
MEASURED_AT_SITE_SCOPE_REASON: Final = "measured_at_site_scope"

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
PAGE_KIND_ROLLUP_WEIGHTS: Final[dict[str, float]] = dict.fromkeys(PAGE_KINDS, 1.0)


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


def expected_checkpoint_expressions(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[tuple[str, str, float], ...]:
    return _expected_checkpoint_expressions(page_kind, page_traits, crawl_context)


def site_checkpoint_expressions() -> tuple[tuple[str, str, float], ...]:
    return _site_checkpoint_expressions()


def expected_checkpoints(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    return _expected_checkpoints(page_kind, page_traits, crawl_context)


def expected_families(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    return _expected_families(page_kind, page_traits, crawl_context)


def relevant_dimensions(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    return _relevant_dimensions(page_kind, page_traits, crawl_context)


def measurement_gap_reasons(
    page_kind: str,
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> dict[str, str]:
    return _measurement_gap_reasons(page_kind, page_traits, crawl_context)


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
        "insufficient_evidence",
        "robots_not_fetched",
        "unknown_applicability",
    }
)
