"""Analytics worker registration for the Commerce replacement task kinds."""

from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_COMMERCE_CATALOG_PROJECTION,
    ANALYTICS_TASK_KIND_COMMERCE_COMPETITOR_DISCOVERY,
    ANALYTICS_TASK_KINDS,
)
from app.workers.analytics_worker import EXECUTORS


def test_commerce_replacement_tasks_are_registered() -> None:
    expected = {
        ANALYTICS_TASK_KIND_COMMERCE_CATALOG_PROJECTION,
        ANALYTICS_TASK_KIND_COMMERCE_COMPETITOR_DISCOVERY,
    }
    assert expected <= ANALYTICS_TASK_KINDS
    assert expected <= set(EXECUTORS)
