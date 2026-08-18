# Site Health workspace runtime row domain service (neutral, projection-only).
#
# A workspace's Site Health behavior lives on a single
# ``WorkspaceSiteHealthRuntime`` row. The row is NOT a commercial source of
# truth: it is the projection of the account's resolved ``monitored_urls``
# entitlement allowance onto the neutral crawl policy (see
# ``app.core.config.site_health_crawl_policy.runtime_policy_for_allowance``),
# plus the row
# locked ``FOR UPDATE`` to serialize the workspace-wide monitored-URL quota.
#
# This module owns the row mechanics:
#
#   - ``resolve_runtime`` — read the workspace's row, seeding the fail-closed
#     zero-allowance sample row on first use. The seeded row is flushed so it
#     can be locked ``FOR UPDATE`` in the same transaction; callers own commit.
#   - ``lock_runtime`` — resolve then lock the row (THE quota serialization
#     point).
#   - ``apply_runtime_policy`` — project a policy + resolver provenance onto
#     the row (in-place projection update, never a commercial edit).
#   - ``runtime_allows_monitored_analysis`` — the pure guard shared by the
#     selection mutation and the worker analyze guard.
#
# Entitlement resolution itself lives in ``app.domain.entitlements.service``;
# this module never knows about grants, plans, or billing providers.
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_BOOTSTRAP,
    SELECTION_SOURCE_FREE_SAMPLE,
    SELECTION_SOURCE_USER,
    SiteHealthRuntimePolicy,
)
from app.core.config.site_health_runtime import (
    runtime_policy_for_allowance,
)
from app.models.site_health import WorkspaceSiteHealthRuntime


async def _load_runtime(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceSiteHealthRuntime | None:
    result = await session.execute(
        select(WorkspaceSiteHealthRuntime).where(
            WorkspaceSiteHealthRuntime.workspace_id == workspace_id
        )
    )
    return result.scalar_one_or_none()


def apply_runtime_policy(
    row: WorkspaceSiteHealthRuntime,
    policy: SiteHealthRuntimePolicy,
    *,
    resolved_registry_revision: str,
    resolved_entitlement_lifecycle_version: int,
    resolved_valid_until: datetime | None,
) -> WorkspaceSiteHealthRuntime:
    """Project the neutral policy + resolver provenance onto the row."""
    row.discovery_mode = policy.discovery_mode
    row.discovery_url_cap = policy.discovery_url_cap
    row.sample_url_limit = policy.sample_url_limit
    row.monitored_url_limit = policy.monitored_url_limit
    row.count_disclosure = policy.count_disclosure
    row.resolved_registry_revision = resolved_registry_revision
    row.resolved_entitlement_lifecycle_version = resolved_entitlement_lifecycle_version
    row.resolved_valid_until = resolved_valid_until
    return row


def runtime_policy_is_current(
    row: WorkspaceSiteHealthRuntime, policy: SiteHealthRuntimePolicy
) -> bool:
    """True when the row already projects exactly ``policy`` (no rewrite)."""
    return (
        row.discovery_mode == policy.discovery_mode
        and row.discovery_url_cap == policy.discovery_url_cap
        and row.sample_url_limit == policy.sample_url_limit
        and row.monitored_url_limit == policy.monitored_url_limit
        and bool(row.count_disclosure) == policy.count_disclosure
    )


async def resolve_runtime(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceSiteHealthRuntime:
    """Return the workspace's runtime row, seeding the fail-closed row if none.

    The seeded row projects the ZERO-allowance sample policy (sample discovery,
    zero selectable monitored URLs, no count disclosure). It is flushed — never
    committed — so it can be locked ``FOR UPDATE`` for a subsequent quota
    check in the caller's transaction.

    The seed uses a PostgreSQL upsert instead of a plain ORM INSERT+flush. A
    concurrent first-use request in another project of the same workspace can
    race to insert the unique ``workspace_id`` row; a plain INSERT would raise
    ``IntegrityError`` and force a ``session.rollback()``. Rolling back the
    whole session here is a correctness bug: this call can run inside the
    crawl-creation transaction that has already taken the project ``FOR
    UPDATE`` lock used to serialize active crawls, so a rollback would
    silently release that lock and defeat the serialization. ``ON CONFLICT DO
    NOTHING`` never errors, so the ambient transaction (and its locks)
    survives the race untouched. On a real conflict nothing is returned and we
    reload the winning row.
    """
    existing = await _load_runtime(session, workspace_id)
    if existing is not None:
        return existing

    policy = runtime_policy_for_allowance(0)
    stmt = (
        pg_insert(WorkspaceSiteHealthRuntime)
        .values(
            workspace_id=workspace_id,
            discovery_mode=policy.discovery_mode,
            discovery_url_cap=policy.discovery_url_cap,
            sample_url_limit=policy.sample_url_limit,
            monitored_url_limit=policy.monitored_url_limit,
            count_disclosure=policy.count_disclosure,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id"])
        .returning(WorkspaceSiteHealthRuntime.id)
    )
    inserted_id = await session.scalar(stmt)
    if inserted_id is None:
        # Lost the race: the concurrent inserter committed/flushed the row
        # first. Reload it without touching the ambient transaction.
        winner = await _load_runtime(session, workspace_id)
        if winner is None:  # pragma: no cover - unreachable under a real conflict
            raise RuntimeError("runtime upsert conflicted but no row was found")
        return winner

    # We inserted the row. Load the managed ORM instance so callers get a
    # tracked object (the upsert used Core, not the ORM identity map).
    seeded = await _load_runtime(session, workspace_id)
    if seeded is None:  # pragma: no cover - unreachable right after insert
        raise RuntimeError("runtime row was inserted but could not be reloaded")
    return seeded


async def lock_runtime(
    session: AsyncSession, workspace_id: uuid.UUID
) -> WorkspaceSiteHealthRuntime:
    """Resolve then lock the workspace runtime row ``FOR UPDATE``.

    This is THE quota serialization point (subplan Persistence contract):
    every monitored-set replacement across every project in the workspace must
    lock this single row before counting active rows, so two concurrent
    updates are ordered and neither can push the workspace above its
    ``monitored_url_limit``. Seeds the fail-closed row first if the workspace
    has none, then re-selects it ``with_for_update`` so the lock is held for
    the caller's transaction.
    """
    await resolve_runtime(session, workspace_id)
    result = await session.execute(
        select(WorkspaceSiteHealthRuntime)
        .where(WorkspaceSiteHealthRuntime.workspace_id == workspace_id)
        .with_for_update()
    )
    return result.scalar_one()


def runtime_allows_monitored_analysis(
    runtime: WorkspaceSiteHealthRuntime | None,
    *,
    selection_source: str = SELECTION_SOURCE_USER,
) -> bool:
    """Pure guard: may this runtime row analyze a row of ``selection_source``?

    Used both by the selection mutation (block selection with no allowance)
    and by the worker guard before I/O / before evidence persistence (a lost
    allowance blocks NEW user-managed analysis while preserving evidence).

    - A positive ``monitored_url_limit`` (full policy) may analyze any row.
    - A zero allowance (sample policy) may still analyze its own
      system-managed ``free_sample`` rows, but never a ``user`` row — so a
      lost allowance stops new user-source work without deleting anything.
    - A missing runtime row fails closed (no analysis).
    """
    if runtime is None:
        return False
    if runtime.monitored_url_limit > 0:
        return True
    return selection_source in {
        SELECTION_SOURCE_FREE_SAMPLE,
        SELECTION_SOURCE_BOOTSTRAP,
    }
