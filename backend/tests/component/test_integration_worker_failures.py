"""Failure and resume contracts for the integration sync worker."""

from __future__ import annotations

import pytest

from app.core.config.integrations_contracts import (
    ERROR_GRANT_AUTH_FAILED,
    ERROR_PAYLOAD_TOO_LARGE,
    ERROR_PROVIDER_API,
    GRANT_STATUS_NEEDS_REAUTH,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_GSC,
)
from app.core.config.task_queue import TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED
from app.models.integrations import IntegrationImportArtifact
from tests.component import test_integration_worker as worker_tests


@pytest.mark.asyncio
async def test_payload_too_large_fails(
    session_factory, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(integration_settings, "max_inline_payload_bytes", 10)
    seed = await worker_tests._seed_graph(db_session)
    run = await worker_tests._enqueue_run(db_session, seed)
    fake = worker_tests._ProviderFake()

    await worker_tests._worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PAYLOAD_TOO_LARGE
    assert await worker_tests._artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_unsupported_provider_fails_clean(session_factory, db_session) -> None:
    seed = await worker_tests._seed_graph(db_session, provider="netscape")
    run = await worker_tests._enqueue_run(db_session, seed)
    fake = worker_tests._ProviderFake()

    await worker_tests._worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert run.attempt_count == 1
    assert fake.gsc_auth == [] and fake.token_calls == []


@pytest.mark.asyncio
async def test_grant_not_connected_fails_without_provider_calls(
    session_factory, db_session
) -> None:
    seed = await worker_tests._seed_graph(
        db_session, grant_status=GRANT_STATUS_NEEDS_REAUTH
    )
    run = await worker_tests._enqueue_run(db_session, seed)
    fake = worker_tests._ProviderFake()

    await worker_tests._worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_GRANT_AUTH_FAILED
    assert fake.gsc_auth == [] and fake.token_calls == []


@pytest.mark.asyncio
async def test_retry_resumes_from_durable_artifacts(
    session_factory, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(integration_settings, "sync_page_size", 2)
    seed = await worker_tests._seed_graph(db_session)
    run = await worker_tests._enqueue_run(db_session, seed)
    page1 = worker_tests._fixture("gsc_search_analytics_page1.json")
    db_session.add(
        IntegrationImportArtifact(
            sync_run_id=run.id,
            connection_id=seed.connection_id,
            workspace_id=seed.workspace_id,
            provider=INTEGRATION_PROVIDER_GSC,
            dataset=worker_tests.DATASET_GSC_PAGE_DAILY,
            query_snapshot={
                "api_method": "searchAnalytics.query",
                "dataset": worker_tests.DATASET_GSC_PAGE_DAILY,
                "property_ref": worker_tests._PROPERTY_REF,
                "startDate": worker_tests._WINDOW[0].isoformat(),
                "endDate": worker_tests._WINDOW[1].isoformat(),
                "dimensions": ["page", "date"],
                "metrics": ["clicks", "impressions", "ctr", "position"],
                "rowLimit": 2,
                "startRow": 0,
            },
            payload_hash=worker_tests._canonical_hash(page1),
            row_count=2,
            payload=page1,
        )
    )
    await db_session.commit()
    fake = worker_tests._ProviderFake()

    await worker_tests._worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    assert sorted(fake.gsc_pages) == sorted(
        [
            (("page", "date"), 2),
            (("query", "date"), 0),
            (("query", "page", "date"), 0),
            (("device", "date"), 0),
            (("country", "date"), 0),
        ]
    )
    artifacts = await worker_tests._artifacts(db_session, run.id)
    assert len(artifacts) == len({artifact.id for artifact in artifacts}) == 6
