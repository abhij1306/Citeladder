"""Site Health model constraints + fail-closed runtime row (Task 1).

Verifies the uniqueness/FK/index contract that the queue, quota, and
idempotency logic depends on: duplicate URL identity, duplicate task slot
(including the ``generation`` discriminator), duplicate rule evaluation and
selection uniqueness, plus the workspace runtime row seeding the fail-closed
zero-allowance sample policy on first use. Requires a real Postgres
(Postgres UUID + partial index semantics).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.entitlements import (
    CAPABILITY_REGISTRY_REVISION,
)
from app.core.config.site_health_contracts import (
    INITIAL_TASK_GENERATION,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    DISCOVERY_MODE_FULL,
    DISCOVERY_MODE_SAMPLE,
    SAMPLE_DISCOVERY_URL_CAP,
    SAMPLE_URL_LIMIT,
    SELECTION_SOURCE_USER,
)
from app.core.config.site_health_runtime import (
    runtime_policy_for_allowance,
)
from app.domain.site_health.entitlements import (
    apply_runtime_policy,
    resolve_runtime,
)
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl
from tests.component.site_health_helpers import seed_site_crawl


@pytest.mark.asyncio
async def test_site_url_project_hash_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
    async with session_factory() as session:
        session.add(
            SiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                normalized_url="https://example.com/a",
                url_hash="hash-a",
            )
        )
        await session.commit()
    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                SiteUrl(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    normalized_url="https://example.com/a",
                    url_hash="hash-a",
                )
            )
            await session.commit()


def _task(seed, *, url_hash: str, generation: int, key: str) -> SiteCrawlTask:
    return SiteCrawlTask(
        crawl_id=seed.crawl_id,
        workspace_id=seed.workspace_id,
        task_kind=TASK_KIND_DISCOVER,
        requested_url="https://example.com/x",
        url_hash=url_hash,
        generation=generation,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_task_slot_unique_but_generation_disambiguates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)

    # Same (crawl, kind, url_hash, generation) must collide.
    async with session_factory() as session:
        session.add(
            _task(seed, url_hash="h1", generation=INITIAL_TASK_GENERATION, key="k1")
        )
        await session.commit()
    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                _task(
                    seed,
                    url_hash="h1",
                    generation=INITIAL_TASK_GENERATION,
                    key="k2",
                )
            )
            await session.commit()

    # Bumping the generation makes it a distinct slot — no collision.
    async with session_factory() as session:
        session.add(_task(seed, url_hash="h1", generation=1, key="k3"))
        await session.commit()


@pytest.mark.asyncio
async def test_task_idempotency_key_unique(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
    async with session_factory() as session:
        session.add(_task(seed, url_hash="a", generation=0, key="dup"))
        await session.commit()
    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_task(seed, url_hash="b", generation=0, key="dup"))
            await session.commit()


@pytest.mark.asyncio
async def test_monitored_url_unique_per_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url="https://example.com/m",
            url_hash="mhash",
        )
        session.add(site_url)
        await session.commit()
        site_url_id = site_url.id

    def _mon() -> MonitoredSiteUrl:
        return MonitoredSiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            profile_id=seed.profile_id,
            site_url_id=site_url_id,
            selection_source=SELECTION_SOURCE_USER,
        )

    async with session_factory() as session:
        session.add(_mon())
        await session.commit()
    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(_mon())
            await session.commit()


@pytest.mark.asyncio
async def test_resolve_runtime_seeds_zero_allowance_sample_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
    async with session_factory() as session:
        row = await resolve_runtime(session, seed.workspace_id)
        await session.commit()
        # Fail-closed: no resolved allowance -> sample policy, zero selectable
        # monitored URLs, no count disclosure.
        assert row.discovery_mode == DISCOVERY_MODE_SAMPLE
        assert row.sample_url_limit == SAMPLE_URL_LIMIT
        assert row.monitored_url_limit == 0
        assert row.count_disclosure is False
        # Inventory is DECOUPLED from the analysis budget: sample mode keeps
        # mapping the site to the discovery cap while only ``sample_url_limit``
        # URLs are ever analyzed.
        assert row.discovery_url_cap == SAMPLE_DISCOVERY_URL_CAP
        assert row.discovery_url_cap > row.sample_url_limit

    # Idempotent: a second resolve returns the same seeded row, no duplicate.
    async with session_factory() as session:
        again = await resolve_runtime(session, seed.workspace_id)
        assert again.id == row.id


@pytest.mark.asyncio
async def test_apply_runtime_policy_full_then_sample(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
    async with session_factory() as session:
        row = await resolve_runtime(session, seed.workspace_id)
        apply_runtime_policy(
            row,
            runtime_policy_for_allowance(50),
            resolved_registry_revision=CAPABILITY_REGISTRY_REVISION,
            resolved_entitlement_lifecycle_version=1,
            resolved_valid_until=None,
        )
        await session.commit()
        assert row.discovery_mode == DISCOVERY_MODE_FULL
        assert row.monitored_url_limit == 50
        assert row.count_disclosure is True
        row_id = row.id

    async with session_factory() as session:
        row = await resolve_runtime(session, seed.workspace_id)
        apply_runtime_policy(
            row,
            runtime_policy_for_allowance(0),
            resolved_registry_revision=CAPABILITY_REGISTRY_REVISION,
            resolved_entitlement_lifecycle_version=2,
            resolved_valid_until=None,
        )
        await session.commit()
        # In-place projection: same row, now the zero-allowance sample policy.
        assert row.id == row_id
        assert row.discovery_mode == DISCOVERY_MODE_SAMPLE
        assert row.monitored_url_limit == 0
        assert row.count_disclosure is False
        assert row.resolved_entitlement_lifecycle_version == 2


@pytest.mark.asyncio
async def test_runtime_policy_fail_closed_for_nonpositive_allowance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A zero/negative allowance always maps to the sample policy."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
    async with session_factory() as session:
        row = await resolve_runtime(session, seed.workspace_id)
        apply_runtime_policy(
            row,
            runtime_policy_for_allowance(-3),
            resolved_registry_revision=CAPABILITY_REGISTRY_REVISION,
            resolved_entitlement_lifecycle_version=0,
            resolved_valid_until=None,
        )
        await session.commit()
        assert row.discovery_mode == DISCOVERY_MODE_SAMPLE
        assert row.monitored_url_limit == 0
        assert row.count_disclosure is False


@pytest.mark.asyncio
async def test_resolve_runtime_conflict_preserves_ambient_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Handoff finding 3: an insert conflict must NOT roll back the caller.

    ``resolve_runtime`` runs inside the crawl-creation transaction that has
    already taken the project ``FOR UPDATE`` lock used to serialize active
    crawls. If a concurrent first-use request wins the race to insert the
    unique workspace runtime row, the loser must NOT ``session.rollback()``
    (which would release that lock and discard pending work) — it must resolve
    the conflict via an idempotent upsert and leave the ambient transaction
    (and any pending, un-flushed changes) intact.
    """
    from sqlalchemy import func as _func
    from sqlalchemy import select as _select

    from app.models.site_health.runtime import WorkspaceSiteHealthRuntime

    async with session_factory() as session:
        seed = await seed_site_crawl(session)

    # Winner: seed + COMMIT the runtime row first (a concurrent request).
    async with session_factory() as loser:
        winner_id = None
        async with session_factory() as winner:
            row = await resolve_runtime(winner, seed.workspace_id)
            await winner.commit()
            winner_id = row.id

        # Loser: stage other pending work in the SAME transaction, THEN resolve
        # the runtime row (which now conflicts). The pending work must survive.
        pending = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url="https://example.com/pending",
            url_hash="pending-hash",
        )
        loser.add(pending)
        await loser.flush()
        pending_id = pending.id

        resolved = await resolve_runtime(loser, seed.workspace_id)
        # Resolved to the winner's row (no duplicate, no error).
        assert resolved.id == winner_id
        await loser.commit()

        # The pending SiteUrl was NOT lost to a rollback — it committed.
        found = await loser.scalar(_select(SiteUrl.id).where(SiteUrl.id == pending_id))
        assert found == pending_id

        # Exactly one runtime row exists for the workspace.
        count = await loser.scalar(
            _select(_func.count()).where(
                WorkspaceSiteHealthRuntime.workspace_id == seed.workspace_id
            )
        )
        assert count == 1


@pytest.mark.asyncio
async def test_observation_cross_workspace_binding_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Handoff finding 4: an observation cannot bind a foreign workspace.

    The composite FKs pin ``(workspace_id, project_id, crawl_id)`` and
    ``(workspace_id, project_id, site_url_id)`` to the parent crawl/URL. An
    observation whose ``workspace_id`` differs from the crawl/URL workspace has
    no matching parent row, so the insert must raise ``IntegrityError``.
    """
    from app.models.site_health.urls import SiteUrlObservation

    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url="https://example.com/obs",
            url_hash="obs-hash",
        )
        session.add(site_url)
        await session.flush()
        site_url_id = site_url.id
        await session.commit()

    # A well-formed observation (same workspace as crawl + URL) inserts fine.
    async with session_factory() as session:
        session.add(
            SiteUrlObservation(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                source_kind="root",
            )
        )
        await session.commit()

    # A second distinct URL so the cross-workspace insert differs from the
    # valid row on ``(crawl_id, site_url_id)`` — isolating the composite FK as
    # the cause of rejection (not the uniqueness constraint).
    async with session_factory() as session:
        other_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url="https://example.com/obs2",
            url_hash="obs-hash-2",
        )
        session.add(other_url)
        await session.flush()
        other_url_id = other_url.id
        await session.commit()

    # A cross-workspace observation (foreign workspace_id) has no matching
    # composite parent and is rejected at the DB by the scoped FK.
    import uuid as _uuid

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            session.add(
                SiteUrlObservation(
                    workspace_id=_uuid.uuid4(),  # not the crawl/URL workspace
                    project_id=seed.project_id,
                    crawl_id=seed.crawl_id,
                    site_url_id=other_url_id,
                    source_kind="link",
                )
            )
            await session.commit()
