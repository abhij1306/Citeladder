"""Version-1 Site Health measurement, checkpoint, and presentation policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

PROFILE_VERSION: Final = "sh-profiles-1"
SCHEMA_CONTRACT_VERSION: Final = "sh-schema-1"
PRESENTATION_VERSION: Final = "sh-presentation-1"

SCORE_ROLE_TECHNICAL: Final = "technical_integrity"
SCORE_ROLE_AEO: Final = "aeo_readiness"

MEASUREMENT_STATE_MEASURED: Final = "measured"
MEASUREMENT_STATE_LIMITED: Final = "limited_evidence"
MEASUREMENT_STATE_NOT_MEASURED: Final = "not_measured"
MEASUREMENT_STATE_EXCLUDED: Final = "excluded"

DIMENSION_APPLICABLE: Final = "applicable"
DIMENSION_NOT_APPLICABLE: Final = "not_applicable"
DIMENSION_UNRESOLVED: Final = "unresolved"

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


@dataclass(frozen=True)
class ReadinessCheckpoint:
    family: str
    dimension: str
    weight: float
    content_addressable: bool = False


READINESS_CHECKPOINTS: Final[dict[str, ReadinessCheckpoint]] = {
    "aeo.answer_first": ReadinessCheckpoint(
        "answer_content", "answerability", 1.0, True
    ),
    "aeo.question_headings": ReadinessCheckpoint(
        "semantic_structure", "structure", 1.0, True
    ),
    "aeo.schema_expected_for_type": ReadinessCheckpoint(
        "structured_representation", "machine-readability", 1.0
    ),
    "aeo.schema_required_valid": ReadinessCheckpoint(
        "structured_representation", "machine-readability", 1.0
    ),
    "aeo.schema_recommended_present": ReadinessCheckpoint(
        "structured_representation", "machine-readability", 0.5
    ),
    "aeo.schema_matches_content": ReadinessCheckpoint(
        "structured_representation", "machine-readability", 1.0
    ),
    "aeo.author_present": ReadinessCheckpoint("provenance", "authority", 1.0, True),
    "aeo.organization_identity": ReadinessCheckpoint(
        "provenance", "authority", 1.0, True
    ),
    "technical.indexable": ReadinessCheckpoint("indexability", "crawlability", 1.0),
}

# PR2 intentionally uses only the two determinate checks below. Crawler and
# snippet observations remain non-critical until their dedicated PR3 evaluators.
SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1: Final[tuple[str, ...]] = (
    "acquisition.public_representation",
    "search.indexability",
)

STRUCTURAL_NA_REASONS: Final[frozenset[str]] = frozenset(
    {
        "no_canonical",
        "empty_title",
        "empty_meta_description",
        "no_headings",
        "no_subheadings",
        "no_product_schema",
        "no_expected_type_block",
        "no_schema_names",
        "no_comparable_product_claims",
        "no_sitemap",
        "no_hreflang",
        "no_html",
        "format_has_no_html",
        "other_page_kind",
        "trait_not_observed",
        "not_site_root",
        "crawl_finalize_scope",
        "low_confidence_kind",
        "content_not_server_rendered",
    }
)

UNAVAILABLE_REASONS: Final[frozenset[str]] = frozenset(
    {"coverage_not_complete", "no_checkable_alternates", "no_ttfb_measurement"}
)
UNKNOWN_REASONS: Final[frozenset[str]] = frozenset(
    {"insufficient_evidence", "robots_not_fetched", "unknown_applicability"}
)
