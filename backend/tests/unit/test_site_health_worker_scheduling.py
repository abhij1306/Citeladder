"""Pure coverage for Site Health's capacity-sharing worker lanes."""

import pytest
from pydantic import ValidationError

from app.core.config.site_health_contracts import (
    SITE_TASK_KINDS,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_SITE_SETUP,
)
from app.core.config.site_health_runtime import SiteHealthSettings
from app.workers.site_health.scheduling import build_lane_plan


def test_lane_plan_reserves_acquisition_and_processing_capacity() -> None:
    lanes = build_lane_plan(concurrency=8, acquisition_reserve=2)

    acquisition_kinds = {TASK_KIND_DISCOVER, TASK_KIND_SITE_SETUP}
    acquisition = [
        lane for lane in lanes if set(lane.preferred_kinds) == acquisition_kinds
    ]
    processing = [lane for lane in lanes if TASK_KIND_ANALYZE in lane.preferred_kinds]

    assert len(acquisition) == 2
    assert len(processing) == 6
    assert all(
        set(lane.preferred_kinds) | set(lane.borrow_kinds) == SITE_TASK_KINDS
        for lane in lanes
    )


def test_lane_plan_retains_processing_capacity_when_reserve_is_oversized() -> None:
    lanes = build_lane_plan(concurrency=3, acquisition_reserve=20)

    assert (
        sum(
            set(lane.preferred_kinds) == {TASK_KIND_DISCOVER, TASK_KIND_SITE_SETUP}
            for lane in lanes
        )
        == 2
    )
    assert TASK_KIND_ANALYZE in lanes[-1].preferred_kinds


def test_single_slot_keeps_processing_priority_and_can_borrow_discovery() -> None:
    (lane,) = build_lane_plan(concurrency=1, acquisition_reserve=2)

    assert TASK_KIND_ANALYZE in lane.preferred_kinds
    assert set(lane.borrow_kinds) == {TASK_KIND_DISCOVER, TASK_KIND_SITE_SETUP}


def test_acquisition_lane_reserve_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="acquisition_lane_reserve"):
        SiteHealthSettings(acquisition_lane_reserve=0)
