# Commerce attribution configuration (invariant 1: config lives here).
#
# Owns every vocabulary token + provenance version for the Commerce
# attribution surface (WS-B): the method vocabulary (A1 platform-attributed
# from GA4, A2 order-referrer), the deterministic/statistical metrics
# namespaces, the analyzer/formula version stamps, the data/delta/statistical
# state vocabularies served verbatim by the read API (the frontend zod
# contract pins them exactly), and the consumed-dataset read set.
#
# The confidence buckets are imported from
# ``config/analytics.py`` and the source-granularity literals from
# ``config/integrations.py`` — aliased here, never re-literalized
# (invariant 2). Attribution performs NO provider I/O, so no fetch knobs
# live here.
from __future__ import annotations

from typing import Final

# The deterministic confidence buckets are OWNED by the analytics config
# (the referral classifier's vocabulary) and reused here so an attribution
# confidence can never drift from the classifier's stamps (invariant 2).
from app.core.config.analytics import (
    CONFIDENCE_BUCKETS,
    CONFIDENCE_EXACT,
    CONFIDENCE_HEURISTIC,
)

# The dataset ids + item source-granularity literals are OWNED by the
# integrations config (cross-workstream contract C1; the granularity tokens
# live there to keep the config import graph acyclic) — imported, never
# re-literalized (invariant 2).
from app.core.config.integrations import (
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
)

# Re-exported, never duplicated (the classifier's confidence vocabulary is
# reused for attribution confidence stamps): CONFIDENCE_EXACT,
# CONFIDENCE_HEURISTIC, CONFIDENCE_BUCKETS.
__all__ = [
    "ATTRIBUTION_ANALYZER_VERSION",
    "ATTRIBUTION_ORDERS_PAGE_SIZE",
    "ATTRIBUTION_ORDER_STATE_ATTRIBUTED",
    "ATTRIBUTION_ORDER_STATE_UNATTRIBUTED",
    "ATTRIBUTION_ORDER_STATES",
    "ATTRIBUTION_CONSUMED_DATASETS",
    "ATTRIBUTION_DATA_STATE_AVAILABLE",
    "ATTRIBUTION_DATA_STATE_NO_DATA",
    "ATTRIBUTION_DATA_STATE_NOT_CONNECTED",
    "ATTRIBUTION_DATA_STATES",
    "ATTRIBUTION_DELTA_STATE_COMPARABLE",
    "ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE",
    "ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE",
    "ATTRIBUTION_DELTA_STATES",
    "ATTRIBUTION_FORMULA_VERSION",
    "ATTRIBUTION_METHOD_GA4_PLATFORM",
    "ATTRIBUTION_METHOD_ORDER_REFERRER",
    "ATTRIBUTION_METHODS",
    "ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC",
    "ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL",
    "ATTRIBUTION_SOURCE_GRANULARITIES",
    "ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP",
    "ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM",
    "ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED",
    "CONFIDENCE_BUCKETS",
    "CONFIDENCE_EXACT",
    "CONFIDENCE_HEURISTIC",
]

# --- Attribution methods (the frontend attributionMethodSchema) --------------
# A1: platform-attributed revenue read from the GA4 ecommerce reports.
# A2: order-referrer attribution over Shopify order facts (Task 4).
ATTRIBUTION_METHOD_ORDER_REFERRER: Final = "order_referrer"
ATTRIBUTION_METHOD_GA4_PLATFORM: Final = "ga4_platform_attributed"
ATTRIBUTION_METHODS: Final[frozenset[str]] = frozenset(
    {ATTRIBUTION_METHOD_ORDER_REFERRER, ATTRIBUTION_METHOD_GA4_PLATFORM}
)

# --- Provenance versions (invariant 4) ---------------------------------------
# Stamped on every ``AttributionSnapshot`` row so a served projection traces
# to the exact projection code + formula set that produced it.
ATTRIBUTION_ANALYZER_VERSION: Final = "attribution-analysis-1"
ATTRIBUTION_FORMULA_VERSION: Final = "attribution-formula-1"
ATTRIBUTION_ORDERS_PAGE_SIZE: Final = 50
ATTRIBUTION_ORDER_STATE_ATTRIBUTED: Final = "attributed"
ATTRIBUTION_ORDER_STATE_UNATTRIBUTED: Final = "unattributed"
ATTRIBUTION_ORDER_STATES: Final[frozenset[str]] = frozenset(
    {ATTRIBUTION_ORDER_STATE_ATTRIBUTED, ATTRIBUTION_ORDER_STATE_UNATTRIBUTED}
)
# --- Metrics namespaces (the persisted metrics document's top level) ---------
ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC: Final = "deterministic"
ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL: Final = "statistical"

# --- Source granularity (A1's GA4 source dimension) ---------------------------
# ``session_source_medium`` is the primary item report's granularity;
# ``default_channel_group`` is the reduced granularity of the fallback item
# report (labelled, never guessed back into an AI source). Aliased from the
# integrations config (the owning module).
ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM: Final = (
    GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM
)
ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP: Final = (
    GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP
)
ATTRIBUTION_SOURCE_GRANULARITIES: Final[frozenset[str]] = frozenset(
    {
        ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
        ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    }
)

# --- Data states (per-method row state; attributionDataStateSchema) ----------
# ``available``: measured values served; ``no_data``: the provider is
# connected but the window has no rows; ``not_connected``: no connection
# ever produced rows for the method. An unavailable method reports null
# metrics — NEVER a fabricated zero.
ATTRIBUTION_DATA_STATE_AVAILABLE: Final = "available"
ATTRIBUTION_DATA_STATE_NO_DATA: Final = "no_data"
ATTRIBUTION_DATA_STATE_NOT_CONNECTED: Final = "not_connected"
ATTRIBUTION_DATA_STATES: Final[frozenset[str]] = frozenset(
    {
        ATTRIBUTION_DATA_STATE_AVAILABLE,
        ATTRIBUTION_DATA_STATE_NO_DATA,
        ATTRIBUTION_DATA_STATE_NOT_CONNECTED,
    }
)

# --- Delta states (attributionDeltaStateSchema; exactly these three) ---------
# A within-currency A1-vs-A2 delta is ``comparable``; it is
# ``currency_unavailable`` when the two sides cannot be compared safely and
# ``method_unavailable`` when one side has no available row. Non-comparable
# rows carry null metric values.
ATTRIBUTION_DELTA_STATE_COMPARABLE: Final = "comparable"
ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE: Final = "currency_unavailable"
ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE: Final = "method_unavailable"
ATTRIBUTION_DELTA_STATES: Final[frozenset[str]] = frozenset(
    {
        ATTRIBUTION_DELTA_STATE_COMPARABLE,
        ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE,
        ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE,
    }
)

# --- Statistical namespace state ----------------------------------------------
# No statistical allocation is offered in this scope (never a fabricated
# estimate); the namespace persists exactly this state with empty
# allocations.
ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED: Final = "not_offered"

# --- Consumed datasets (the A1 projection's read set, contract C1) ------------
# The dataset ids the ``attribution_snapshot`` executor reads from
# ``IntegrationMetricRow``: the GA4 source/medium ecommerce report (order-
# level A1 totals) and BOTH item ecommerce reports (per-product A1 rows —
# exactly one of the two item datasets has rows per connection, selected by
# the capability fallback). These datasets feed NOTHING else (not referral
# ingest, not the traffic projection).
ATTRIBUTION_CONSUMED_DATASETS: Final[frozenset[str]] = frozenset(
    {
        DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
        DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    }
)
