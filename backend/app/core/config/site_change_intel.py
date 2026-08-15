"""Versioned policy for deterministic crawl-to-crawl change intelligence."""

from typing import Final

CHANGE_ANALYZER_VERSION: Final = "site-change-v1"
CHANGE_MAX_PAGES: Final = 5000
CHANGE_MAX_CRAWL_CANDIDATES: Final = 50
CHANGE_DEFAULT_LIMIT: Final = 50
CHANGE_MAX_LIMIT: Final = 200

CHANGE_STATE_AVAILABLE: Final = "available"
CHANGE_STATE_UNAVAILABLE: Final = "unavailable"
CHANGE_STATE_NON_COMPARABLE: Final = "non_comparable"

CHANGE_CLASS_IMPROVEMENT: Final = "improvement"
CHANGE_CLASS_NEUTRAL: Final = "neutral-change"
CHANGE_CLASS_REGRESSION: Final = "potential-regression"
CHANGE_CLASS_CRITICAL: Final = "critical-regression"
CHANGE_CLASSES: Final = frozenset(
    {
        CHANGE_CLASS_IMPROVEMENT,
        CHANGE_CLASS_NEUTRAL,
        CHANGE_CLASS_REGRESSION,
        CHANGE_CLASS_CRITICAL,
    }
)

CHANGE_FIELDS: Final = (
    "title",
    "meta_description",
    "h1",
    "canonical",
    "robots_noindex",
    "json_ld_present",
    "internal_link_count",
    "http_status",
    "redirect_target",
)
CHANGE_MAX_OBSERVATIONS: Final = CHANGE_MAX_PAGES * len(CHANGE_FIELDS)

CHANGE_FIELD_RULES: Final[dict[str, str]] = {
    "title": "technical.title_present",
    "meta_description": "technical.meta_description_present",
    "h1": "technical.single_h1",
    "canonical": "technical.canonical_present",
    "robots_noindex": "technical.indexable",
    "json_ld_present": "aeo.structured_data_present",
}

CHANGE_REASON_NO_PREVIOUS_CRAWL: Final = "no_previous_comparable_crawl"
CHANGE_REASON_SCOPE_MISMATCH: Final = "crawl_scope_mismatch"
CHANGE_REASON_VERSION_MISMATCH: Final = "analysis_version_mismatch"
CHANGE_REASON_NO_USABLE_EVIDENCE: Final = "no_usable_page_evidence"
