"""Cursor and query-validation contracts for the LLM analytics API."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.config.analytics import (
    AI_SOURCE_CHATGPT,
    AI_SOURCE_GEMINI,
    ANALYTICS_MAX_WINDOW_DAYS,
)
from app.domain.analytics import service as analytics_service
from tests.component import test_llm_analytics_api as analytics_tests


@pytest.mark.asyncio
async def test_referrals_cursor_is_bound_to_filters(
    client, session_factory, monkeypatch
) -> None:
    await analytics_tests._register(client, "analytics-cursor@example.com")
    project_id, workspace_id = await analytics_tests._create_project(client)
    async with session_factory() as session:
        await analytics_tests._seed_referral_page_rows(
            session,
            workspace_id=analytics_tests.uuid.UUID(workspace_id),
            project_id=analytics_tests.uuid.UUID(project_id),
        )
    monkeypatch.setattr(analytics_service, "ANALYTICS_REFERRALS_PAGE_SIZE", 2)
    url = f"/api/v1/projects/{project_id}/llm-analytics/referrals"
    cursor = (await client.get(url, params={"source": AI_SOURCE_CHATGPT})).json()[
        "next_cursor"
    ]
    assert cursor is not None
    for params, status in (
        ({"source": AI_SOURCE_GEMINI, "cursor": cursor}, 400),
        ({"cursor": cursor}, 400),
        ({"source": AI_SOURCE_CHATGPT, "cursor": cursor}, 200),
        ({"cursor": "not-a-valid-cursor"}, 400),
    ):
        assert (await client.get(url, params=params)).status_code == status


@pytest.mark.asyncio
async def test_query_validation_422(client) -> None:
    await analytics_tests._register(client, "analytics-validation@example.com")
    project_id, _ = await analytics_tests._create_project(client)
    base = f"/api/v1/projects/{project_id}/llm-analytics"
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
        (f"{base}/referrals", {"source": "bogus"}),
        (f"{base}/referrals", {"to": "2026-07-22"}),
        (f"{base}/themes", {"from": "2026-07-22", "to": "2026-07-20"}),
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
