"""Attribution config (WS-B Task 1): method/confidence/version/state
vocabularies, source-granularity aliasing, and the consumed-dataset read
set — pinned exactly (the frontend zod contract + cross-workstream C1
contract fail loud on drift)."""

from __future__ import annotations

from app.core.config import analytics as analytics_config
from app.core.config import attribution
from app.core.config import integrations_datasets as integration_datasets
from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_CONSUMED_DATASETS,
    ATTRIBUTION_DATA_STATE_AVAILABLE,
    ATTRIBUTION_DATA_STATE_NO_DATA,
    ATTRIBUTION_DATA_STATE_NOT_CONNECTED,
    ATTRIBUTION_DATA_STATES,
    ATTRIBUTION_DELTA_STATE_COMPARABLE,
    ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE,
    ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE,
    ATTRIBUTION_DELTA_STATES,
    ATTRIBUTION_FORMULA_VERSION,
    ATTRIBUTION_METHOD_GA4_PLATFORM,
    ATTRIBUTION_METHOD_ORDER_REFERRER,
    ATTRIBUTION_METHODS,
    ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC,
    ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL,
    ATTRIBUTION_SOURCE_GRANULARITIES,
    ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
    ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED,
    CONFIDENCE_BUCKETS,
    CONFIDENCE_EXACT,
    CONFIDENCE_HEURISTIC,
)
from app.core.config.integrations_transport import INTEGRATION_PROVIDER_GA4


def test_attribution_method_vocabulary() -> None:
    assert ATTRIBUTION_METHOD_ORDER_REFERRER == "order_referrer"
    assert ATTRIBUTION_METHOD_GA4_PLATFORM == "ga4_platform_attributed"
    assert ATTRIBUTION_METHODS == frozenset(
        {"order_referrer", "ga4_platform_attributed"}
    )


def test_confidence_buckets_are_aliased_never_duplicated() -> None:
    # The analytics config OWNS the classifier's confidence vocabulary;
    # attribution re-exports the SAME objects (invariant 2 — no drift).
    assert CONFIDENCE_EXACT is analytics_config.CONFIDENCE_EXACT
    assert CONFIDENCE_HEURISTIC is analytics_config.CONFIDENCE_HEURISTIC
    assert CONFIDENCE_BUCKETS is analytics_config.CONFIDENCE_BUCKETS


def test_provenance_versions_stamped_and_distinct() -> None:
    assert ATTRIBUTION_ANALYZER_VERSION
    assert ATTRIBUTION_FORMULA_VERSION
    assert ATTRIBUTION_ANALYZER_VERSION != ATTRIBUTION_FORMULA_VERSION
    # Never collide with the analytics/traffic provenance stamps.
    assert ATTRIBUTION_ANALYZER_VERSION != analytics_config.REFERRAL_SANITIZE_VERSION


def test_metrics_namespace_literals() -> None:
    assert ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC == "deterministic"
    assert ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL == "statistical"


def test_source_granularity_literals_aliased_from_integrations() -> None:
    # The integrations config owns the literals (acyclic import graph);
    # attribution aliases the SAME values, never re-literalizes.
    assert (
        ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM
        == integration_datasets.GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM
        == "session_source_medium"
    )
    assert (
        ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP
        == integration_datasets.GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP
        == "default_channel_group"
    )
    assert ATTRIBUTION_SOURCE_GRANULARITIES == frozenset(
        {"session_source_medium", "default_channel_group"}
    )


def test_data_state_vocabulary() -> None:
    assert ATTRIBUTION_DATA_STATE_AVAILABLE == "available"
    assert ATTRIBUTION_DATA_STATE_NO_DATA == "no_data"
    assert ATTRIBUTION_DATA_STATE_NOT_CONNECTED == "not_connected"
    assert ATTRIBUTION_DATA_STATES == frozenset(
        {"available", "no_data", "not_connected"}
    )


def test_delta_state_vocabulary_exactly_three() -> None:
    # The frontend attributionDeltaStateSchema pins EXACTLY these three.
    assert ATTRIBUTION_DELTA_STATE_COMPARABLE == "comparable"
    assert ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE == "currency_unavailable"
    assert ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE == "method_unavailable"
    assert ATTRIBUTION_DELTA_STATES == frozenset(
        {"comparable", "currency_unavailable", "method_unavailable"}
    )


def test_statistical_state_not_offered() -> None:
    assert ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED == "not_offered"


def test_consumed_datasets_are_owned_template_ids() -> None:
    # The A1 read set: the source/medium ecommerce report + BOTH item
    # ecommerce reports (exactly one item report has rows per connection).
    assert ATTRIBUTION_CONSUMED_DATASETS == frozenset(
        {
            integration_datasets.DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
            integration_datasets.DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
            integration_datasets.DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
        }
    )
    # No drift from the C1 owner: every consumed id is a registered
    # GA4 template — and the A1 datasets feed NOTHING else.
    for dataset in ATTRIBUTION_CONSUMED_DATASETS:
        template = integration_datasets.INTEGRATION_DATASET_TEMPLATES[dataset]
        assert template.provider == INTEGRATION_PROVIDER_GA4
    from app.core.config.traffic import (
        TRAFFIC_GA4_REFERRAL_DATASETS,
        TRAFFIC_REFRESH_TRIGGER_DATASETS,
    )

    assert ATTRIBUTION_CONSUMED_DATASETS.isdisjoint(TRAFFIC_GA4_REFERRAL_DATASETS)
    assert ATTRIBUTION_CONSUMED_DATASETS.isdisjoint(TRAFFIC_REFRESH_TRIGGER_DATASETS)


def test_config_module_exports_match_all() -> None:
    # The re-exported confidence names stay in __all__ (no silent drop).
    exported = set(attribution.__all__)
    assert {
        "CONFIDENCE_EXACT",
        "CONFIDENCE_HEURISTIC",
        "CONFIDENCE_BUCKETS",
        "ATTRIBUTION_METHODS",
        "ATTRIBUTION_CONSUMED_DATASETS",
        "ATTRIBUTION_DELTA_STATES",
    } <= exported
