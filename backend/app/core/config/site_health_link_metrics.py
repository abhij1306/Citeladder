"""Versioned policy for crawl coverage and internal-link projections."""

from __future__ import annotations

from typing import Final

COVERAGE_STATE_COMPLETE: Final = "complete"
COVERAGE_STATE_PARTIAL: Final = "partial"
COVERAGE_STATE_UNKNOWN: Final = "unknown"
COVERAGE_STATES: Final[frozenset[str]] = frozenset(
    {
        COVERAGE_STATE_COMPLETE,
        COVERAGE_STATE_PARTIAL,
        COVERAGE_STATE_UNKNOWN,
    }
)

# These tokens make post-terminal derivations replayable without pretending
# that a later formula is the same result over old evidence.
COVERAGE_FORMULA_VERSION: Final = "sh-coverage-1"
LINK_METRIC_FORMULA_VERSION: Final = "sh-link-metrics-1"

# URL detail needs useful neighbours, not an unbounded edge projection.
LINK_METRIC_TOP_NEIGHBOUR_LIMIT: Final = 10
