"""Shared seed helpers for the Task 1 Site Health component tests.

Builds a workspace + project + Site Health profile + crawl, and enqueues
``SiteCrawlTask`` queue rows directly through the ORM (no HTTP), so the generic
``PostgresTaskQueue`` (parameterized by ``SITE_CRAWL_QUEUE_SPEC``) can be
exercised against a real Postgres schema exactly like the audit queue.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    canonicalize,
    registrable_domain,
    split_host_port,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_RUNNING,
    INITIAL_TASK_GENERATION,
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.models.project import Project
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


@dataclass
class SiteSeed:
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    profile_id: uuid.UUID
    crawl_id: uuid.UUID
    task_ids: list[uuid.UUID] = field(default_factory=list)


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:64]


async def seed_site_crawl(
    session: AsyncSession,
    *,
    task_count: int = 0,
    email: str | None = None,
    root_url: str = "https://example.com/",
) -> SiteSeed:
    """Seed a workspace/project/profile/crawl and ``task_count`` queued tasks."""
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"

    # Derive the canonical root + registrable host through the production
    # URL-policy utilities (never hard-coded) so a custom-host root actually
    # produces a matching profile, and a root without a trailing slash still
    # joins task URLs safely (no "https://host page-0" malformed URL).
    canonical_root = canonicalize(root_url)
    root_host, _root_port = split_host_port(canonical_root)
    root_base = (
        canonical_root if canonical_root.endswith("/") else (canonical_root + "/")
    )

    workspace = Workspace(name="Site WS")
    session.add(workspace)
    await session.flush()

    user = User(email=email, hashed_password="x", is_active=True)
    session.add(user)
    await session.flush()
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    )

    project = Project(
        workspace_id=workspace.id,
        name="Acme Site",
        brand_name="Acme Corp",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=1,
        website_url=canonical_root,
    )
    session.add(project)
    await session.flush()

    profile = SiteHealthProfile(
        workspace_id=workspace.id,
        project_id=project.id,
        root_url=canonical_root,
        root_host=root_host,
        registrable_domain=registrable_domain(root_host),
    )
    session.add(profile)
    await session.flush()

    crawl = SiteCrawl(
        workspace_id=workspace.id,
        project_id=project.id,
        profile_id=profile.id,
        status=CRAWL_STATUS_RUNNING,
        root_url=canonical_root,
        random_seed="1",
    )
    session.add(crawl)
    await session.flush()

    tasks: list[SiteCrawlTask] = []
    for i in range(task_count):
        url = f"{root_base}page-{i}"
        task = SiteCrawlTask(
            crawl_id=crawl.id,
            workspace_id=workspace.id,
            task_kind=TASK_KIND_DISCOVER,
            requested_url=url,
            url_hash=_url_hash(url),
            generation=INITIAL_TASK_GENERATION,
            idempotency_key=f"{crawl.id}:{TASK_KIND_DISCOVER}:{i}:0",
            status=TASK_STATUS_QUEUED,
            randomized_position=i,
        )
        session.add(task)
        tasks.append(task)
    await session.flush()
    task_ids: list[uuid.UUID] = [task.id for task in tasks]
    await session.commit()

    return SiteSeed(
        workspace_id=workspace.id,
        project_id=project.id,
        profile_id=profile.id,
        crawl_id=crawl.id,
        task_ids=task_ids,
    )


async def seed_monitored_urls_allowance(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    monitored_urls: int,
) -> None:
    """Wire a billing account + workspace link + override grant so the
    workspace resolves to a ``monitored_urls`` allowance of exactly
    ``monitored_urls``.

    Uses the production grant path (``issue_override_bundle``), so the
    account lifecycle-version bump and the Site Health runtime-row refresh
    happen exactly as in production. When the workspace already has a
    billing link (e.g. API-seeded workspaces bootstrap one), the grant lands
    on the EXISTING account. Callers own the commit.
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.core.config.entitlements import KEY_MONITORED_URLS
    from app.domain.entitlements.grants import issue_override_bundle
    from app.domain.entitlements.types import GrantSpec
    from app.models.billing import BillingAccount, WorkspaceBillingLink

    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is not None:
        account = await session.get(BillingAccount, account_id)
        assert account is not None
        operator = await session.get(User, account.owner_user_id)
        assert operator is not None
    else:
        operator = User(
            email=f"billing-{uuid.uuid4().hex[:8]}@example.com",
            hashed_password="x",
            is_active=True,
        )
        session.add(operator)
        await session.flush()
        account = BillingAccount(owner_user_id=operator.id)
        session.add(account)
        await session.flush()
        session.add(
            WorkspaceBillingLink(
                workspace_id=workspace_id, billing_account_id=account.id
            )
        )
        await session.flush()
    await issue_override_bundle(
        session,
        operator_user=operator,
        account_id=account.id,
        grants=(GrantSpec(key=KEY_MONITORED_URLS, value=monitored_urls),),
        reason="test seed allowance",
        valid_from=datetime.now(UTC) - timedelta(days=1),
        valid_until=None,
        idempotency_key=f"test-seed:{workspace_id}:{uuid.uuid4().hex[:12]}",
    )
