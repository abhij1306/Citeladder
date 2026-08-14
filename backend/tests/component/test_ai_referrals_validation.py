"""Validation contracts for the focused AI Referrals API."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config.analytics import ANALYTICS_MAX_WINDOW_DAYS
from tests.component import test_ai_referrals_api as ai_referrals_tests


@pytest.mark.asyncio
async def test_query_validation_422(client) -> None:
    await ai_referrals_tests._register(client, "ai-referrals-validation@example.com")
    project_id, _ = await ai_referrals_tests._create_project(client)
    base = f"/api/v1/projects/{project_id}/ai-referrals"
    too_wide = ai_referrals_tests.WINDOW[1] - timedelta(days=ANALYTICS_MAX_WINDOW_DAYS)
    max_from = ai_referrals_tests.WINDOW[1] - timedelta(
        days=ANALYTICS_MAX_WINDOW_DAYS - 1
    )
    invalid = (
        (base, {"granularity": "hourly"}),
        (base, {"from": "2026-07-22", "to": "2026-07-20"}),
        (base, {"from": "2026-07-20"}),
        (
            base,
            {
                "from": too_wide.isoformat(),
                "to": ai_referrals_tests.WINDOW[1].isoformat(),
            },
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
                "to": ai_referrals_tests.WINDOW[1].isoformat(),
            },
        )
    ).status_code == 200
