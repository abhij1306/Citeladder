"""Site Health phase controls, bulk analysis, and discovery resume."""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    CODE_ADVANCED_CONTROLS_UNAVAILABLE,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    INITIAL_TASK_GENERATION,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    MANUAL_PHASE_LIFECYCLE_KEY,
    PHASE_ANALYSIS,
    PHASE_RUN_RUNNING,
    PHASE_RUN_STOPPED,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.phase_control import start_discovery
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from tests.component.site_health_api_helpers import (
    _hash,
    _register,
    _seed_scenario,
)
from tests.component.site_health_helpers import seed_monitored_urls_allowance

pytestmark = pytest.mark.asyncio


async def test_stop_phase_endpoints_require_advanced_controls(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "advanced_controls_enabled", False)
    await _register(client, "phase-stop-gate@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="phase-stop-gate@example.com")

    headers = {"X-Workspace-Id": str(scenario.workspace_id)}
    for phase in ("discovery", "analysis"):
        response = await client.post(
            f"/api/v1/site-crawls/{scenario.crawl_id}/{phase}/stop",
            headers=headers,
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == CODE_ADVANCED_CONTROLS_UNAVAILABLE


async def test_stop_analysis_cancels_its_work_and_is_idempotent(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "advanced_controls_enabled", True)
    await _register(client, "phase-stop-analysis@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(
            session, email="phase-stop-analysis@example.com"
        )
        await seed_monitored_urls_allowance(
            session,
            workspace_id=scenario.workspace_id,
            monitored_urls=50,
        )
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_RUNNING
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        crawl.completed_at = None
        crawl.configuration = {
            **(crawl.configuration or {}),
            "advanced_controls_enabled": True,
        }
        phase_run = SiteCrawlPhaseRun(
            workspace_id=scenario.workspace_id,
            crawl_id=crawl.id,
            phase=PHASE_ANALYSIS,
            ordinal=1,
            status=PHASE_RUN_RUNNING,
            requested_count=2,
        )
        session.add(phase_run)
        await session.flush()
        for index, status in enumerate((TASK_STATUS_RUNNING, TASK_STATUS_QUEUED)):
            url = f"https://acme.test/stop-analysis-{index}"
            session.add(
                SiteCrawlTask(
                    crawl_id=crawl.id,
                    workspace_id=scenario.workspace_id,
                    phase_run_id=phase_run.id,
                    site_url_id=scenario.monitored_url_id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url=url,
                    url_hash=_hash(url),
                    idempotency_key=f"{crawl.id}:analyze:stop:{index}",
                    status=status,
                    lease_owner="worker-1" if status == TASK_STATUS_RUNNING else None,
                )
            )
        initial_url = "https://acme.test/initial-analysis-without-phase-run"
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=scenario.workspace_id,
                phase_run_id=None,
                site_url_id=scenario.monitored_url_id,
                task_kind=TASK_KIND_ANALYZE,
                requested_url=initial_url,
                url_hash=_hash(initial_url),
                idempotency_key=f"{crawl.id}:analyze:initial",
                status=TASK_STATUS_QUEUED,
            )
        )
        discovery_url = "https://acme.test/discovery-continues"
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=scenario.workspace_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=discovery_url,
                url_hash=_hash(discovery_url),
                idempotency_key=f"{crawl.id}:discover:continues",
                status=TASK_STATUS_QUEUED,
            )
        )
        await session.commit()

    headers = {"X-Workspace-Id": str(scenario.workspace_id)}
    first = await client.post(
        f"/api/v1/site-crawls/{scenario.crawl_id}/analysis/stop", headers=headers
    )
    assert first.status_code == 200
    assert first.json()["crawl"]["analysis_status"] == ANALYSIS_STATUS_STOPPED
    assert first.json()["phase_run"]["status"] == PHASE_RUN_STOPPED

    second = await client.post(
        f"/api/v1/site-crawls/{scenario.crawl_id}/analysis/stop", headers=headers
    )
    assert second.status_code == 200
    assert second.json()["crawl"]["analysis_status"] == ANALYSIS_STATUS_STOPPED
    assert second.json()["phase_run"] is None

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        phase_run = await session.scalar(
            select(SiteCrawlPhaseRun).where(
                SiteCrawlPhaseRun.crawl_id == scenario.crawl_id,
                SiteCrawlPhaseRun.phase == PHASE_ANALYSIS,
            )
        )
        live_analysis = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == scenario.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.status.not_in(
                    [TASK_STATUS_CANCELLED, TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED]
                ),
            )
        )
        stopped_analysis = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == scenario.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.status == TASK_STATUS_CANCELLED,
                SiteCrawlTask.error_code == "stopped",
            )
        )
        assert crawl is not None and crawl.status == CRAWL_STATUS_RUNNING
        assert crawl.analysis_status == ANALYSIS_STATUS_STOPPED
        assert phase_run is not None and phase_run.status == PHASE_RUN_STOPPED
        assert live_analysis == 0
        assert stopped_analysis == 3


async def test_stop_discovery_cancels_unowned_tasks_without_stopping_analysis(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "advanced_controls_enabled", True)
    await _register(client, "phase-stop-discovery@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(
            session, email="phase-stop-discovery@example.com"
        )
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_RUNNING
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        crawl.completed_at = None
        crawl.configuration = {
            **(crawl.configuration or {}),
            "advanced_controls_enabled": True,
        }
        for index, status in enumerate((TASK_STATUS_RUNNING, TASK_STATUS_QUEUED)):
            url = f"https://acme.test/stop-discovery-{index}"
            session.add(
                SiteCrawlTask(
                    crawl_id=crawl.id,
                    workspace_id=scenario.workspace_id,
                    phase_run_id=None,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url=url,
                    url_hash=_hash(url),
                    idempotency_key=f"{crawl.id}:discover:stop:{index}",
                    status=status,
                    lease_owner="worker-1" if status == TASK_STATUS_RUNNING else None,
                )
            )
        analysis_url = "https://acme.test/analysis-continues"
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=scenario.workspace_id,
                site_url_id=scenario.monitored_url_id,
                task_kind=TASK_KIND_ANALYZE,
                requested_url=analysis_url,
                url_hash=_hash(analysis_url),
                idempotency_key=f"{crawl.id}:analyze:continues",
                status=TASK_STATUS_QUEUED,
            )
        )
        await session.commit()

    headers = {"X-Workspace-Id": str(scenario.workspace_id)}
    first = await client.post(
        f"/api/v1/site-crawls/{scenario.crawl_id}/discovery/stop", headers=headers
    )
    assert first.status_code == 200
    assert first.json()["crawl"]["discovery_status"] == DISCOVERY_STATUS_STOPPED
    assert first.json()["crawl"]["analysis_status"] == ANALYSIS_STATUS_RUNNING
    assert first.json()["crawl"]["status"] == CRAWL_STATUS_RUNNING
    assert first.json()["phase_run"] is None

    second = await client.post(
        f"/api/v1/site-crawls/{scenario.crawl_id}/discovery/stop", headers=headers
    )
    assert second.status_code == 200
    assert second.json()["crawl"]["discovery_status"] == DISCOVERY_STATUS_STOPPED

    async with session_factory() as session:
        cancelled_discovery = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == scenario.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                SiteCrawlTask.status == TASK_STATUS_CANCELLED,
                SiteCrawlTask.error_code == "stopped",
            )
        )
        live_analysis = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == scenario.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert cancelled_discovery == 2
        assert live_analysis == 1


async def test_terminal_bulk_analysis_creates_lineage_crawl(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "advanced_controls_enabled", True)
    await _register(client, "phase-rerun@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="phase-rerun@example.com")
        await seed_monitored_urls_allowance(
            session,
            workspace_id=scenario.workspace_id,
            monitored_urls=50,
        )
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        profile = await session.get(
            SiteHealthProfile, crawl.profile_id if crawl else None
        )
        assert crawl is not None and profile is not None
        crawl.configuration = {
            **(crawl.configuration or {}),
            "advanced_controls_enabled": True,
        }
        crawl.discovery_requested_count = 3
        selection_version = profile.selection_version
        await session.commit()

    response = await client.post(
        f"/api/v1/site-crawls/{scenario.crawl_id}/analysis/start",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        json={
            "requested_url_count": 1,
            "site_url_ids": [str(scenario.monitored_url_id)],
            "expected_selection_version": selection_version,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["created_new_crawl"] is True
    assert payload["crawl"]["id"] != str(scenario.crawl_id)
    assert payload["crawl"]["discovery_requested_count"] == 3
    assert payload["phase_run"]["requested_count"] == 1
    assert payload["scheduled_count"] == 1


async def test_discovery_resume_clones_only_the_requested_batch(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "phase-clone-limit@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="phase-clone-limit@example.com")
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_PAUSED
        crawl.discovery_status = DISCOVERY_STATUS_STOPPED
        crawl.configuration = {
            **(crawl.configuration or {}),
            "advanced_controls_enabled": True,
            "max_discovery_urls": 50,
        }
        for index in range(3):
            url_hash = _hash(f"https://acme.test/resume-{index}")
            session.add(
                SiteCrawlTask(
                    crawl_id=crawl.id,
                    workspace_id=crawl.workspace_id,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url=f"https://acme.test/resume-{index}",
                    url_hash=url_hash,
                    generation=INITIAL_TASK_GENERATION,
                    idempotency_key=f"{crawl.id}:discover:{url_hash}:0",
                    status=TASK_STATUS_CANCELLED,
                )
            )
        await session.commit()

    async with session_factory() as session:
        result = await start_discovery(
            session,
            workspace_id=scenario.workspace_id,
            crawl_id=scenario.crawl_id,
            additional_url_count=1,
        )
        assert result.phase_run is not None
        assert result.scheduled_count == 1
        assert result.crawl.configuration[MANUAL_PHASE_LIFECYCLE_KEY] is True
        queued = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.phase_run_id == result.phase_run.id,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert queued == 1
