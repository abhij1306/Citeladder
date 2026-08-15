"""Demand Intelligence policy, vocabulary, and version ownership."""

from typing import Final

DEMAND_ANALYZER_VERSION: Final = "demand-analyzer-2"
DEMAND_FORMULA_VERSION: Final = "demand-priority-1"
DEMAND_RULE_VERSION: Final = "demand-rules-2"

DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR: Final = "high_impression_low_ctr"
DEMAND_SIGNAL_TYPES: Final[frozenset[str]] = frozenset(
    {DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR}
)

DEMAND_SIGNAL_STATE_ACTIVE: Final = "active"
DEMAND_SIGNAL_STATE_RESOLVED: Final = "resolved"

DEMAND_MIN_IMPRESSIONS: Final = 10
DEMAND_LOW_CTR_THRESHOLD: Final = 0.02
DEMAND_SEARCH_GAP_WEIGHT: Final = 1.0
DEMAND_LIST_MAX_LIMIT: Final = 200

# Cross-source owned-page equivalence is deliberately separate from crawler
# identity. Bump whenever evidence precedence or candidate construction changes.
PAGE_EQUIVALENCE_RESOLVER_VERSION: Final = "owned-page-resolver-1"
PAGE_EQUIVALENCE_MAX_CANDIDATES: Final = 16

BRANDED_QUERY_CLASSIFIER_VERSION: Final = "branded-query-1"
BRANDED_QUERY_CLASSES: Final[frozenset[str]] = frozenset(
    {"branded", "non_branded", "ambiguous"}
)
