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
