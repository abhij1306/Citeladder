# Site Health monitored-set lifecycle domain logic (Task 4).
#
# Owns the atomic, versioned full-set replacement of a project's monitored
# selection and the shared locking/enqueue primitives the per-page rerun
# (``rerun``) and the recrawl seeding (``monitored_seeding``) reuse. The pure
# worker-side guard functions live in ``task_guards``.
#
# The monitored set is a persistent, project-level projection
# (``MonitoredSiteUrl``) whose active rows are counted WORKSPACE-WIDE against
# the runtime row's ``monitored_url_limit``. Every active row is
# counted regardless of ``selection_source`` (``user`` | ``free_sample``).
#
# Concurrency contract (subplan Acceptance criteria 2): two simultaneous
# selection updates — even across different projects in the same workspace —
# cannot push the workspace above the limit. This is serialized by locking the
# single ``WorkspaceSiteHealthRuntime`` row ``FOR UPDATE`` before counting,
# so the two updaters are ordered and each sees the other's committed rows.
#
# Nothing here is ever deleted on downgrade: rows are DEACTIVATED (``active``
# flipped, ``deselected_at`` stamped) so evidence/history survives capability
# changes (plan §4). Re-adding a removed URL in the same crawl allocates the
# NEXT ``generation`` so it never collides with the cancelled task's slot.
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    CODE_MONITORING_NOT_ALLOWED,
    CODE_QUOTA_EXCEEDED,
    CODE_STALE_SELECTION_VERSION,
    CRAWL_ACTIVE_STATUSES,
    INITIAL_TASK_GENERATION,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_USER,
)
from app.core.config.task_queue import (
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_QUEUED,
)
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_workspace,
)
from app.domain.site_health.entitlements import (
    lock_runtime,
    runtime_allows_monitored_analysis,
)
from app.domain.site_health.inventory_scope import inventory_site_url_subquery
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


def utcnow() -> datetime:
    return datetime.now(UTC)


class SelectionError(Exception):
    """Base class for a monitored-selection failure carrying a stable code."""

    code: str = ""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MonitoringNotAllowedError(SelectionError):
    """No monitored-URL allowance attempted a user-managed mutation (403)."""

    code = CODE_MONITORING_NOT_ALLOWED


class StaleSelectionVersionError(SelectionError):
    """``expected_selection_version`` did not match the current version (409)."""

    code = CODE_STALE_SELECTION_VERSION

    def __init__(self, message: str, *, current_version: int) -> None:
        super().__init__(message)
        self.current_version = current_version


class QuotaExceededError(SelectionError):
    """A valid selection would exceed the workspace monitored limit (403).

    Carries the workspace ``limit`` and the currently-used active count so the
    API/UI can render "N of 50" feedback. Never exposes other projects' URLs.
    """

    code = CODE_QUOTA_EXCEEDED

    def __init__(self, message: str, *, limit: int, currently_used: int) -> None:
        super().__init__(message)
        self.limit = limit
        self.currently_used = currently_used


class SelectionValidationError(SelectionError):
    """A requested id is foreign / not a discovered project URL (422)."""

    code = "invalid_selection"


@dataclass(frozen=True)
class SelectionResult:
    """The outcome of a monitored-set replacement (projection-only)."""

    selection_version: int
    active_ids: tuple[uuid.UUID, ...]
    added_ids: tuple[uuid.UUID, ...]
    removed_ids: tuple[uuid.UUID, ...]
    workspace_used: int
    enqueued_task_ids: tuple[uuid.UUID, ...]
    cancelled_task_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class _MembershipDelta:
    """The in-transaction result of applying one full-set membership change."""

    by_url_id: dict[uuid.UUID, MonitoredSiteUrl]
    new_memberships: tuple[MonitoredSiteUrl, ...]
    added_ids: tuple[uuid.UUID, ...]
    removed_ids: tuple[uuid.UUID, ...]


async def lock_profile(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SiteHealthProfile | None:
    """Load + lock the project's Site Health profile ``FOR UPDATE``."""
    result = await session.execute(
        select(SiteHealthProfile)
        .where(
            SiteHealthProfile.workspace_id == workspace_id,
            SiteHealthProfile.project_id == project_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def _load_project_site_urls(
    session: AsyncSession, *, project_id: uuid.UUID, ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, SiteUrl]:
    """Load the ``SiteUrl`` rows for ``ids`` that belong to the project."""
    id_list = list(dict.fromkeys(ids))
    if not id_list:
        return {}
    result = await session.execute(
        select(SiteUrl).where(
            SiteUrl.project_id == project_id,
            SiteUrl.id.in_(id_list),
        )
    )
    return {row.id: row for row in result.scalars().all()}


async def _active_count_other_projects(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> int:
    """Count ACTIVE monitored rows in the workspace OUTSIDE this project.

    Counts every active row regardless of ``selection_source`` (plan §4: quota
    usage counts every active monitored row). Called while holding the
    runtime lock so the value reflects other updaters' committed state.
    """
    result = await session.execute(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.project_id != project_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    return int(result.scalar_one())


async def _active_count_in_project(
    session: AsyncSession, *, project_id: uuid.UUID
) -> int:
    """Count ACTIVE monitored rows currently in this project."""
    result = await session.execute(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    return int(result.scalar_one())


async def _load_project_memberships(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[MonitoredSiteUrl]:
    """Load + lock every monitored membership row for the project."""
    result = await session.execute(
        select(MonitoredSiteUrl)
        .where(MonitoredSiteUrl.project_id == project_id)
        .with_for_update()
    )
    return list(result.scalars().all())


async def active_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SiteCrawl | None:
    """Return the project's current active crawl, if any (most recent)."""
    result = await session.execute(
        select(SiteCrawl)
        .where(
            SiteCrawl.workspace_id == workspace_id,
            SiteCrawl.project_id == project_id,
            SiteCrawl.status.in_(list(CRAWL_ACTIVE_STATUSES)),
        )
        .order_by(SiteCrawl.created_at.desc())
    )
    return result.scalars().first()


async def next_generations(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    task_kind: str,
    url_hashes: Sequence[str],
) -> dict[str, int]:
    """Next ``generation`` per url_hash for a task kind within a crawl.

    A URL analyzed once (or removed+cancelled) already owns generation(s) in
    the crawl; re-adding it must allocate ``max(existing) + 1`` so the unique
    ``(crawl_id, task_kind, url_hash, generation)`` slot never collides with a
    cancelled task. A URL never seen in this crawl starts at generation 0.
    """
    wanted = set(url_hashes)
    if not wanted:
        return {}
    result = await session.execute(
        select(
            SiteCrawlTask.url_hash,
            func.max(SiteCrawlTask.generation),
        )
        .where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.task_kind == task_kind,
            SiteCrawlTask.url_hash.in_(list(wanted)),
        )
        .group_by(SiteCrawlTask.url_hash)
    )
    max_by_hash = {row[0]: int(row[1]) for row in result.all()}
    return {
        url_hash: (max_by_hash[url_hash] + 1)
        if url_hash in max_by_hash
        else INITIAL_TASK_GENERATION
        for url_hash in wanted
    }


def _analyze_idempotency_key(
    *, crawl_id: uuid.UUID, url_hash: str, generation: int
) -> str:
    return f"{crawl_id}:{TASK_KIND_ANALYZE}:{url_hash}:{generation}"


def enqueue_analyze_task(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url: SiteUrl,
    generation: int,
    position: int,
) -> SiteCrawlTask:
    """Create one queued ``analyze`` task for a newly monitored URL."""
    task = SiteCrawlTask(
        crawl_id=crawl.id,
        workspace_id=crawl.workspace_id,
        site_url_id=site_url.id,
        task_kind=TASK_KIND_ANALYZE,
        requested_url=site_url.normalized_url,
        url_hash=site_url.url_hash,
        generation=generation,
        randomized_position=position,
        idempotency_key=_analyze_idempotency_key(
            crawl_id=crawl.id,
            url_hash=site_url.url_hash,
            generation=generation,
        ),
        status=TASK_STATUS_QUEUED,
        available_at=utcnow(),
    )
    session.add(task)
    return task


async def _cancel_pending_analyze_tasks(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    url_hashes: Sequence[str],
) -> list[uuid.UUID]:
    """Cancel ONLY queued/retry ``analyze`` tasks for removed URLs.

    A running/leased task is NOT cancelled here — the worker's own guard
    (``evaluate_task_guard``) discards its result cooperatively before I/O and
    before persistence. Succeeded/failed tasks keep their immutable evidence.
    """
    hashes = list(dict.fromkeys(url_hashes))
    if not hashes:
        return []
    now = utcnow()
    result = await session.execute(
        update(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            SiteCrawlTask.url_hash.in_(hashes),
            SiteCrawlTask.status.in_(list(TASK_CLAIMABLE_STATUSES)),
        )
        .values(
            status=TASK_STATUS_CANCELLED,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=now,
            error_code="cancelled",
        )
        .returning(SiteCrawlTask.id)
    )
    return [row[0] for row in result.all()]


def _apply_membership_delta(
    *,
    memberships: list[MonitoredSiteUrl],
    requested: list[uuid.UUID],
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    profile_id: uuid.UUID,
    new_version: int,
    now: datetime,
) -> _MembershipDelta:
    """Apply the full-set membership delta without crossing the transaction boundary."""
    requested_set = set(requested)
    by_url_id = {membership.site_url_id: membership for membership in memberships}
    removed_ids: list[uuid.UUID] = []
    for membership in memberships:
        if membership.active and membership.site_url_id not in requested_set:
            membership.active = False
            membership.deselected_at = now
            removed_ids.append(membership.site_url_id)

    added_ids: list[uuid.UUID] = []
    new_memberships: list[MonitoredSiteUrl] = []
    for site_url_id in requested:
        existing = by_url_id.get(site_url_id)
        if existing is None:
            membership = MonitoredSiteUrl(
                workspace_id=workspace_id,
                project_id=project_id,
                profile_id=profile_id,
                site_url_id=site_url_id,
                active=True,
                selection_source=SELECTION_SOURCE_USER,
                selecting_membership_id=new_version,
                selected_at=now,
            )
            by_url_id[site_url_id] = membership
            new_memberships.append(membership)
            added_ids.append(site_url_id)
            continue

        was_active = existing.active
        existing.active = True
        existing.selection_source = SELECTION_SOURCE_USER
        existing.deselected_at = None
        if not was_active:
            existing.selected_at = now
            existing.selecting_membership_id = new_version
            added_ids.append(site_url_id)

    return _MembershipDelta(
        by_url_id=by_url_id,
        new_memberships=tuple(new_memberships),
        added_ids=tuple(added_ids),
        removed_ids=tuple(removed_ids),
    )


async def _reconcile_active_crawl_tasks(
    session: AsyncSession,
    *,
    crawl: SiteCrawl | None,
    project_id: uuid.UUID,
    site_urls: dict[uuid.UUID, SiteUrl],
    added_ids: Sequence[uuid.UUID],
    removed_ids: Sequence[uuid.UUID],
) -> tuple[tuple[uuid.UUID, ...], tuple[uuid.UUID, ...]]:
    """Enqueue additions and cooperatively cancel removals for the active crawl."""
    if crawl is None:
        return (), ()

    removed_site_urls = dict(site_urls)
    missing_removed_ids = [
        site_url_id for site_url_id in removed_ids if site_url_id not in site_urls
    ]
    if missing_removed_ids:
        removed_site_urls.update(
            await _load_project_site_urls(
                session, project_id=project_id, ids=missing_removed_ids
            )
        )
    removed_hashes = [
        removed_site_urls[site_url_id].url_hash
        for site_url_id in removed_ids
        if site_url_id in removed_site_urls
    ]
    cancelled_ids = await _cancel_pending_analyze_tasks(
        session, crawl_id=crawl.id, url_hashes=removed_hashes
    )

    added_hashes = [site_urls[site_url_id].url_hash for site_url_id in added_ids]
    generations = await next_generations(
        session,
        crawl_id=crawl.id,
        task_kind=TASK_KIND_ANALYZE,
        url_hashes=added_hashes,
    )
    enqueued_ids: list[uuid.UUID] = []
    for position, site_url_id in enumerate(added_ids):
        site_url = site_urls[site_url_id]
        task = enqueue_analyze_task(
            session,
            crawl=crawl,
            site_url=site_url,
            generation=generations[site_url.url_hash],
            position=position,
        )
        enqueued_ids.append(task.id)
    return tuple(enqueued_ids), tuple(cancelled_ids)


async def replace_monitored_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    site_url_ids: Sequence[uuid.UUID],
    expected_selection_version: int,
) -> SelectionResult:
    """Atomically replace the project's user-managed monitored set.

    In one locked transaction (subplan Users & flows step 3):

    1. Lock the workspace runtime row ``FOR UPDATE`` (serializes the
       workspace-wide quota across concurrent updates in ANY project).
    2. Reject the mutation for a capability that disallows user selection
       (zero allowance) with ``monitoring_not_allowed``.
    3. Lock the project profile and reject a stale
       ``expected_selection_version`` with ``stale_selection_version``.
    4. Validate every requested id is a discovered URL in this project.
    5. Enforce the workspace-wide active limit counting every active row
       regardless of source; over-limit raises ``site_health_quota_exceeded``.
    6. Apply the full-set delta: requested rows are activated or converted to
       user-managed (the sample-to-user conversion an allowance performs on
       rows it first selects), omitted active rows are deactivated and never
       deleted (evidence survives), and the version is bumped.
    7. Enqueue ``analyze`` tasks for additions into the active crawl (next
       generation) and cancel only queued/retry analyze tasks for removals.

    The caller owns the surrounding transaction boundary; this function flushes
    but does not commit, so the API layer can wrap it.
    """
    await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=utcnow()
    )
    runtime = await lock_runtime(session, workspace_id)
    profile = await lock_profile(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if profile is None:
        raise SelectionValidationError("Site Health profile not found")

    # Allowance gate: a zero monitored-URL allowance may not mutate a
    # user-managed selection.
    if not runtime_allows_monitored_analysis(
        runtime, selection_source=SELECTION_SOURCE_USER
    ):
        raise MonitoringNotAllowedError(
            "A monitored-URL allowance is required to select monitored URLs"
        )

    # Optimistic concurrency on the persistent selection version.
    if expected_selection_version != profile.selection_version:
        raise StaleSelectionVersionError(
            "The monitored selection changed since it was loaded",
            current_version=profile.selection_version,
        )

    requested = list(dict.fromkeys(site_url_ids))
    site_urls = await _load_project_site_urls(
        session, project_id=project_id, ids=requested
    )
    unknown = [rid for rid in requested if rid not in site_urls]
    if unknown:
        raise SelectionValidationError(
            "Selection contains ids that are not discovered project URLs"
        )

    # Workspace-wide quota: every active row outside this project + the full
    # requested set for this project (a full-set replacement). Counted under
    # the runtime lock so concurrent updaters are serialized.
    other_active = await _active_count_other_projects(
        session, workspace_id=workspace_id, project_id=project_id
    )
    limit = int(runtime.monitored_url_limit)
    new_workspace_total = other_active + len(set(requested))
    if new_workspace_total > limit:
        # The quota-check's ``currently_used`` reports the true workspace-
        # wide count of active rows (including this project's pre-existing
        # active memberships), not just the "other projects" count used for
        # the limit arithmetic above.
        current_project_active = await _active_count_in_project(
            session, project_id=project_id
        )
        raise QuotaExceededError(
            "The selection would exceed the workspace monitored-URL limit",
            limit=limit,
            currently_used=other_active + current_project_active,
        )

    # Apply the full-set delta against the project's memberships (locked).
    memberships = await _load_project_memberships(session, project_id=project_id)
    now = utcnow()
    new_version = profile.selection_version + 1
    delta = _apply_membership_delta(
        memberships=memberships,
        requested=requested,
        workspace_id=workspace_id,
        project_id=project_id,
        profile_id=profile.id,
        new_version=new_version,
        now=now,
    )
    session.add_all(delta.new_memberships)

    profile.selection_version = new_version
    await session.flush()

    # Active-crawl side effects: enqueue additions (next generation), cancel
    # only pending removals. If there is no active crawl, the selection still
    # persists — later crawls seed it via ``seed_monitored_targets``.
    crawl = await active_crawl(
        session, workspace_id=workspace_id, project_id=project_id
    )
    enqueued_task_ids, cancelled_task_ids = await _reconcile_active_crawl_tasks(
        session,
        crawl=crawl,
        project_id=project_id,
        site_urls=site_urls,
        added_ids=delta.added_ids,
        removed_ids=delta.removed_ids,
    )
    if crawl is not None:
        await session.flush()

    active_ids = tuple(
        membership.site_url_id
        for membership in delta.by_url_id.values()
        if membership.active
    )
    return SelectionResult(
        selection_version=new_version,
        active_ids=active_ids,
        added_ids=delta.added_ids,
        removed_ids=delta.removed_ids,
        workspace_used=new_workspace_total,
        enqueued_task_ids=enqueued_task_ids,
        cancelled_task_ids=cancelled_task_ids,
    )


BULK_SELECT_MODE_FIRST_N = "first_n"
BULK_SELECT_MODE_ALL = "all"
BULK_SELECT_MODE_NONE = "none"
BULK_SELECT_MODES = (
    BULK_SELECT_MODE_FIRST_N,
    BULK_SELECT_MODE_ALL,
    BULK_SELECT_MODE_NONE,
)


async def bulk_select_monitored_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID,
    mode: str,
    count: int | None = None,
    query: str | None = None,
    expected_selection_version: int,
) -> SelectionResult:
    """Resolve a bulk selection server-side, then replace the monitored set.

    Avoids shipping tens of thousands of ids through the client for "select
    the first N / all discovered URLs": the candidate ``site_url_id``s are
    resolved HERE, in the same deterministic ``(normalized_url, id)`` order
    the inventory endpoint pages in, so "first N" always matches the first N
    rows the user sees in the inventory (under the same ``query`` filter).

    Modes:

    - ``first_n`` — the first ``count`` admitted URLs (``count`` required).
    - ``all``     — every admitted URL (quota still enforced downstream).
    - ``none``    — clear the selection (empty set).

    Candidates use the exact same durable inventory scope as the listing:
    current observations plus the explicitly frozen earlier full-crawl lineage
    for a full-inventory recrawl. Sample crawls never inherit that lineage.

    The heavy lifting (capability gate, version check, workspace quota under
    the runtime lock, delta application, task enqueue/cancel) is delegated
    to ``replace_monitored_set`` — same locks, same coded errors. An ``all``
    selection larger than the workspace limit raises the SAME
    ``site_health_quota_exceeded`` a manual over-selection would — but it is
    raised HERE, before any lock is taken: candidate resolution is capped at
    ``limit + 1`` ids, so an unfiltered ``all`` over a huge inventory can
    never materialize tens of thousands of ids nor drag them through the
    runtime-locked replacement path. The under-lock quota check in
    ``replace_monitored_set`` remains the race-safe authority; this pre-check
    only bounds the work.
    """
    if mode not in BULK_SELECT_MODES:
        raise SelectionValidationError(f"Unknown bulk selection mode: {mode!r}")

    crawl = await session.scalar(
        select(SiteCrawl).where(
            SiteCrawl.id == crawl_id,
            SiteCrawl.workspace_id == workspace_id,
            SiteCrawl.project_id == project_id,
        )
    )
    if crawl is None:
        raise SelectionValidationError("Crawl not found in this project")

    site_url_ids: list[uuid.UUID] = []
    if mode != BULK_SELECT_MODE_NONE:
        if mode == BULK_SELECT_MODE_FIRST_N and (count is None or count < 1):
            raise SelectionValidationError(
                "A positive count is required for first_n bulk selection"
            )
        # Read (not lock) the refreshed runtime row to bound candidate
        # resolution: any set larger than the workspace limit is doomed to the
        # same quota error downstream, so cap the query at limit + 1 and fail
        # fast before the locked replacement path ever sees an oversized set.
        runtime = await refresh_site_health_runtime_for_workspace(
            session, workspace_id=workspace_id, at=utcnow()
        )
        limit = int(runtime.monitored_url_limit)
        fetch_cap = limit + 1 if count is None else min(count, limit + 1)
        stmt = select(SiteUrl.id).where(
            SiteUrl.project_id == project_id,
            SiteUrl.id.in_(inventory_site_url_subquery(crawl)),
        )
        if query:
            pattern = f"%{query.strip().lower()}%"
            stmt = stmt.where(
                func.lower(SiteUrl.normalized_url).like(pattern)
                | func.lower(SiteUrl.display_url).like(pattern)
            )
        stmt = stmt.order_by(SiteUrl.normalized_url.asc(), SiteUrl.id.asc()).limit(
            fetch_cap
        )
        site_url_ids = list((await session.scalars(stmt)).all())
        # Only pre-raise quota for runtimes that may select at all — a
        # zero-allowance workspace must still get its usual
        # MonitoringNotAllowedError from the locked path, not a misleading
        # quota error.
        if runtime_allows_monitored_analysis(runtime) and (len(site_url_ids) > limit):
            currently_used = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(MonitoredSiteUrl)
                        .where(
                            MonitoredSiteUrl.workspace_id == workspace_id,
                            MonitoredSiteUrl.active.is_(True),
                        )
                    )
                )
                or 0
            )
            raise QuotaExceededError(
                "The selection would exceed the workspace monitored-URL limit",
                limit=limit,
                currently_used=currently_used,
            )

    return await replace_monitored_set(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        site_url_ids=site_url_ids,
        expected_selection_version=expected_selection_version,
    )
