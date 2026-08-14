"""Validation and removal contracts for the focused AI Referrals API."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config.analytics import ANALYTICS_MAX_WINDOW_DAYS
from tests.component import test_llm_analytics_api as analytics_tests


@pytest.mark.asyncio
async def test_query_validation_422(client) -> None:
    await analytics_tests._register(client, "ai-referrals-validation@example.com")
    project_id, _ = await analytics_tests._create_project(client)
    base = f"/api/v1/projects/{project_id}/ai-referrals"
    too_wide = analytics_tests.WINDOW[1] - timedelta(days=ANALYTICS_MAX_WINDOW_DAYS)
    max_from = analytics_tests.WINDOW[1] - timedelta(days=ANALYTICS_MAX_WINDOW_DAYS - 1)
    invalid = (
        (base, {"granularity": "hourly"}),
        (base, {"from": "2026-07-22", "to": "2026-07-20"}),
        (base, {"from": "2026-07-20"}),
        (
            base,
            {"from": too_wide.isoformat(), "to": analytics_tests.WINDOW[1].isoformat()},
        ),
        (base, {"from": "not-a-date", "to": "2026-07-22"}),
    )
    for url, params in invalid:
        assert (await client.get(url, params=params)).status_code == 422
    assert (
        await client.get(
            base,
            params={
                "from": max_from.isoformat(),
                "to": analytics_tests.WINDOW[1].isoformat(),
            },
        )
    ).status_code == 200


@pytest.mark.asyncio
async def test_removed_llm_analytics_drilldowns_are_not_routable(client) -> None:
    """AI Referrals deliberately contains no event, theme, or visibility drill-down."""
    await analytics_tests._register(client, "ai-referrals-removed@example.com")
    project_id, _ = await analytics_tests._create_project(client)
    legacy = f"/api/v1/projects/{project_id}/llm-analytics"

    assert (await client.get(legacy)).status_code == 404
    assert (await client.get(f"{legacy}/referrals")).status_code == 404
    assert (await client.get(f"{legacy}/themes")).status_code == 404
