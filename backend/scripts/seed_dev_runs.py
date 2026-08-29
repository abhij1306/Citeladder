"""Worker drains for the development seeder.

``seed_dev_data`` builds rows; this module runs the REAL workers over them:
the two audits, the Site Health crawl trio, and the opportunity/comparison
pass. Split out so row construction and worker orchestration are separately
readable, and so neither module carries the other's imports.

Nothing here is reachable from the API or a worker image (``setuptools`` ships
``app*`` only). It is gated exactly like ``app/`` -- ruff, mypy, the CC/LOC
policy, vulture -- because an operational script that silently rots is a
script nobody can run on the day they need it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import AUDIT_TRIGGER_SYSTEM, audit_settings
from app.core.config.entitlements import KEY_MONITORED_URLS
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_COMPLETED,
    CRAWL_TERMINAL_STATUSES,
)
from app.core.database import SessionLocal
from app.domain.audits.creation import create_audit
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.entitlements.grants import issue_override_bundle
from app.domain.entitlements.types import GrantSpec
from app.domain.opportunities import commands
from app.domain.opportunities.queries import list_opportunities
from app.domain.opportunities.recompute import recompute as recompute_opportunities
from app.domain.site_health.planner import create_crawl
from app.domain.site_health.selection import (
    BULK_SELECT_MODE_ALL,
    bulk_select_monitored_set,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.user import User
from app.workers.audit import execution as audit_execution
from app.workers.audit_worker import AuditWorker
from app.workers.site_health_worker import SiteHealthWorker
from scripts.seed_dev_support import (
    SEED_MONITORED_URL_ALLOWANCE,
    _build_seed_adapter,
    _FakeResolver,
    _site_transport,
    set_seed_audit_generation,
)

logger = logging.getLogger("seed_dev_data")

#: Every engine the primary project audits across.
ALL_ENGINES = [ENGINE_CHATGPT, ENGINE_CLAUDE, ENGINE_GEMINI]


@contextlib.contextmanager
def seeded_adapter() -> Iterator[None]:
    """Swap in the deterministic adapter and un-throttle the audit worker.

    All three knobs are module singletons, so every exit path has to restore
    them. The two audit stages each carried a hand-written ``try``/``finally``
    doing this, which is two copies of one invariant that can drift apart.

    The patch target is ``app.workers.audit.execution``, which is where the
    factory is actually resolved. The seeder patched
    ``app.workers.audit_worker.build_adapter`` -- an attribute that stopped
    existing when the execution path was split out -- so the stub never took
    effect and seeded audits called real providers with fake dev keys.
    """
    original_build_adapter = audit_execution.build_adapter
    original_min_interval = audit_settings.min_request_interval_seconds
    original_heartbeat = audit_settings.heartbeat_interval_seconds
    audit_execution.build_adapter = _build_seed_adapter
    audit_settings.min_request_interval_seconds = 0.0
    audit_settings.heartbeat_interval_seconds = 3600.0
    try:
        yield
    finally:
        audit_execution.build_adapter = original_build_adapter
        audit_settings.min_request_interval_seconds = original_min_interval
        audit_settings.heartbeat_interval_seconds = original_heartbeat


async def seed_monitored_urls_grant(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Give the demo workspace a positive ``monitored_urls`` allowance.

    Uses the production grant path (billing bootstrap + operator override
    bundle) so the projected ``WorkspaceSiteHealthRuntime`` row is a true
    projection: full discovery, user selection, and count disclosure -- exactly
    what the seeded "discover -> select -> recrawl analyzes" flow needs.
    """
    owner = await session.get(User, owner_user_id)
    if owner is None:  # pragma: no cover - the seeder just created this user
        raise RuntimeError("demo user missing during entitlement seed")
    account = await ensure_user_billing(session, owner, workspace_ids=(workspace_id,))
    await issue_override_bundle(
        session,
        operator_user=owner,
        account_id=account.id,
        grants=(GrantSpec(key=KEY_MONITORED_URLS, value=SEED_MONITORED_URL_ALLOWANCE),),
        reason="dev seed monitored-URL allowance",
        valid_from=datetime.now(UTC) - timedelta(days=1),
        valid_until=None,
        idempotency_key=f"seed-dev-data:{workspace_id}",
    )


async def drain_site_crawl(
    worker: SiteHealthWorker, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> None:
    """Drain delayed host-gated tasks until the selected crawl terminalizes."""
    for _ in range(120):
        await worker.run_until_idle()
        async with SessionLocal() as session:
            status = await session.scalar(
                select(SiteCrawl.status).where(
                    SiteCrawl.id == crawl_id,
                    SiteCrawl.workspace_id == workspace_id,
                )
            )
        if status in CRAWL_TERMINAL_STATUSES:
            if status != CRAWL_STATUS_COMPLETED:
                raise RuntimeError(
                    f"seed Site Health crawl terminalized unsuccessfully: "
                    f"{crawl_id} ({status})"
                )
            return
        await asyncio.sleep(0.25)
    raise RuntimeError(f"seed Site Health crawl did not terminalize: {crawl_id}")


async def _run_audit(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    engines: list[str],
    owner: str,
    random_seed: str,
    repetitions: int,
    prompt_set_id: uuid.UUID | None = None,
    prompt_ids: list[uuid.UUID] | None = None,
) -> uuid.UUID:
    """Plan one audit through the real planner, then drain it to completion."""
    async with SessionLocal() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_SYSTEM,
            workspace_id=workspace_id,
            project_id=project_id,
            engines=engines,
            prompt_set_id=prompt_set_id,
            prompt_ids=prompt_ids,
            repetitions=repetitions,
            random_seed=random_seed,
        )
        audit_id = audit.id
    await AuditWorker(session_factory=SessionLocal, owner=owner).run_until_idle()
    logger.info("Completed audit %s for project %s", audit_id, project_id)
    return audit_id


async def run_seed_audits(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    active_prompt_ids: list[uuid.UUID],
    agency_workspace_id: uuid.UUID,
    project2_id: uuid.UUID,
    prompt_set2_id: uuid.UUID,
) -> uuid.UUID:
    """Run both seeded audits against the stubbed adapter (no network calls).

    Returns the primary project's audit id, which the action set is built from.
    """
    with seeded_adapter():
        audit1_id = await _run_audit(
            workspace_id=workspace_id,
            project_id=project_id,
            engines=ALL_ENGINES,
            owner="seed-worker-1",
            random_seed="42",
            repetitions=2,
            prompt_ids=active_prompt_ids,
        )
        await _run_audit(
            workspace_id=agency_workspace_id,
            project_id=project2_id,
            engines=[ENGINE_GEMINI],
            owner="seed-worker-2",
            random_seed="7",
            repetitions=1,
            prompt_set_id=prompt_set2_id,
        )
    return audit1_id


async def _plan_and_drain_crawl(
    worker: SiteHealthWorker,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    random_seed: str,
    label: str,
) -> uuid.UUID:
    async with SessionLocal() as session:
        crawl = await create_crawl(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            random_seed=random_seed,
        )
        crawl_id = crawl.id
    await drain_site_crawl(worker, workspace_id=workspace_id, crawl_id=crawl_id)
    logger.info("Completed %s %s", label, crawl_id)
    return crawl_id


async def run_site_health_crawls(
    *, workspace_id: uuid.UUID, project_id: uuid.UUID, demo_user_id: uuid.UUID
) -> uuid.UUID:
    """Discover, select every URL as monitored, then run two analysis crawls.

    Runs the REAL crawl planner (``create_crawl``) and the REAL
    ``SiteHealthWorker`` (against a mocked transport), mirroring the production
    "discover -> select monitored URLs -> recrawl analyzes" flow; a hand-built
    crawl/task never goes through that selection gate.

    The second analysis crawl supplies the immediate comparable A/B pair the
    Website Changes projection needs. The deterministic transport is unchanged
    between the two, so it is also the clean-stack zero-false-regression proof.
    Returns that crawl's id.
    """
    async with SessionLocal() as session:
        await seed_monitored_urls_grant(session, demo_user_id, workspace_id)

    worker = SiteHealthWorker(
        session_factory=SessionLocal,
        owner="seed-site-worker",
        resolver=_FakeResolver(),
        transport=_site_transport(),
    )
    discovery_crawl_id = await _plan_and_drain_crawl(
        worker,
        workspace_id=workspace_id,
        project_id=project_id,
        random_seed="99",
        label="site health discovery crawl",
    )
    async with SessionLocal() as session:
        await bulk_select_monitored_set(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            crawl_id=discovery_crawl_id,
            mode=BULK_SELECT_MODE_ALL,
            expected_selection_version=0,
        )
        await session.commit()

    await _plan_and_drain_crawl(
        worker,
        workspace_id=workspace_id,
        project_id=project_id,
        random_seed="100",
        label="site health analysis crawl",
    )
    return await _plan_and_drain_crawl(
        worker,
        workspace_id=workspace_id,
        project_id=project_id,
        random_seed="101",
        label="comparable site health crawl",
    )


async def _resolve_first_opportunity(
    *, workspace_id: uuid.UUID, project_id: uuid.UUID, demo_user_id: uuid.UUID
) -> None:
    async with SessionLocal() as session:
        actions = await list_opportunities(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if not actions["items"]:
            return
        await commands.update_status(
            session,
            workspace_id=workspace_id,
            opportunity_id=actions["items"][0]["id"],
            status="resolved",
            changed_by_user_id=demo_user_id,
        )


async def run_actions_and_comparison(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    demo_user_id: uuid.UUID,
    active_prompt_ids: list[uuid.UUID],
    audit_id: uuid.UUID,
    site_crawl_id: uuid.UUID,
) -> None:
    """Materialize the first action set, then give it comparable history.

    One item is resolved between two comparable Wanderlust audits. The later
    deterministic adapter generations improve the evidence mix without changing
    prompt or engine identity, which is what keeps the pair comparable.
    """
    async with SessionLocal() as session:
        await recompute_opportunities(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=audit_id,
            site_crawl_id=site_crawl_id,
        )
    await _resolve_first_opportunity(
        workspace_id=workspace_id, project_id=project_id, demo_user_id=demo_user_id
    )

    comparison_audit_id = audit_id
    with seeded_adapter():
        try:
            for generation, random_seed in ((1, "43"), (2, "44")):
                set_seed_audit_generation(generation)
                comparison_audit_id = await _run_audit(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    engines=ALL_ENGINES,
                    owner=f"seed-worker-comparison-{generation}",
                    random_seed=random_seed,
                    repetitions=2,
                    prompt_ids=active_prompt_ids,
                )
        finally:
            set_seed_audit_generation(0)

    async with SessionLocal() as session:
        await recompute_opportunities(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=comparison_audit_id,
            site_crawl_id=site_crawl_id,
        )
    logger.info(
        "Completed comparable audit %s with action history for project %s",
        comparison_audit_id,
        project_id,
    )
