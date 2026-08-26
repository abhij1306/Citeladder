"""GA4 integration retains Demand/Traffic datasets after attribution retirement."""

from app.core.config.integrations_datasets import (
    DATASET_GA4_CHANNEL_DAILY,
    DATASET_GA4_LANDING_DAILY,
    DATASET_GA4_REFERRER_DAILY,
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
    INTEGRATION_DATASET_TEMPLATES,
)


def test_ga4_demand_and_traffic_datasets_remain_registered() -> None:
    expected = {
        DATASET_GA4_CHANNEL_DAILY,
        DATASET_GA4_LANDING_DAILY,
        DATASET_GA4_REFERRER_DAILY,
        DATASET_GA4_SOURCE_MEDIUM_DAILY,
    }
    assert expected <= set(INTEGRATION_DATASET_TEMPLATES)
