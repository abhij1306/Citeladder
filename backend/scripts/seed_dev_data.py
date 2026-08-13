"""Seed realistic development data for CiteLadder.

Creates, through the real ORM/domain layer (never raw SQL), a full demo
dataset covering every major surface of the app:

  - A demo user (login: demo@citeladder.dev / DemoPass123!) with a personal
    workspace (auto-created via ``register_user``) plus a second workspace.
  - Two ``Project``s with normalized brand identity (Brand/BrandAlias/
    Competitor/OwnedDomain/UnintendedDomain), covering all three
    ``benchmark_mode`` values across the two projects.
  - A ``PromptSet`` per project with prompts covering every ``intent``
    (discovery/comparison/purchase/service/local) and every ``status``
    (active/proposed/archived).
  - BYOK ``ProviderConnection`` + ``ProviderRoute`` rows for all three
    approved engines (chatgpt/gemini/claude) using fake encrypted keys
    (invariant 6 - no real secrets required).
  - A fully completed ``Audit`` (with frozen snapshots, tasks, raw response
    artifacts, response analyses, brand/competitor mentions, citations, and
    a metric snapshot) produced by running the REAL planner
    (``create_audit``) + the REAL ``AuditWorker`` against a stubbed
    answer-engine adapter (no network calls) - mirrors
    ``tests/component/test_analysis_api.py::_run_completed_audit``.
  - A second, smaller audit on the second project so the dashboard/audit
    list has more than one entry.
  - A completed Site Health crawl (via the real ``SiteHealthWorker`` against
    a mocked HTTP transport) with pages ranging from rich/healthy to thin/
    unhealthy, producing page analyses, rule evaluations, issues, and a
    crawl-level snapshot.
  - Products + a competitor product for the Agentic Commerce surface.

Idempotent: re-running deletes any previously-seeded demo workspaces (by a
well-known name prefix) before recreating them, so it is safe to run
repeatedly against the same database.

Usage (from backend/):
    uv run python -m scripts.seed_dev_data
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.audits import AUDIT_TRIGGER_SYSTEM, audit_settings
from app.core.config.entitlements import KEY_MONITORED_URLS
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
    measurement_route,
)
from app.core.database import SessionLocal
from app.core.security import encrypt_secret
from app.domain.audits.planner import create_audit
from app.domain.auth.service import register_user
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.entitlements.grants import issue_override_bundle
from app.domain.entitlements.types import GrantSpec
from app.domain.opportunities.service import (
    list_opportunities,
)
from app.domain.opportunities.service import (
    recompute as recompute_opportunities,
)
from app.domain.opportunities.service import (
    update_status as update_opportunity_status,
)
from app.domain.site_health.planner import create_crawl
from app.domain.site_health.selection import (
    BULK_SELECT_MODE_ALL,
    bulk_select_monitored_set,
)
from app.domain.workspaces.service import ensure_personal_workspace
from app.models.brand import (
    Brand,
    BrandAlias,
    Competitor,
    OwnedDomain,
    UnintendedDomain,
)
from app.models.product import CompetitorProduct, Product
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.provider import ProviderConnection, ProviderRoute
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.workers import audit_worker
from app.workers.audit_worker import AuditWorker
from app.workers.site_health_worker import SiteHealthWorker
from scripts.seed_dev_support import (
    DEMO_COMPETITOR_PRODUCT_SPEC,
    DEMO_PRODUCT_SPECS,
    PROMPT_SPECS,
    SEED_MONITORED_URL_ALLOWANCE,
    _build_seed_adapter,
    _FakeResolver,
    _prompt_bucket,
    _SeedStubAdapter,
    _site_transport,
    set_seed_audit_generation,
)

__all__ = [
    "DEMO_COMPETITOR_PRODUCT_SPEC",
    "DEMO_PRODUCT_SPECS",
    "PROMPT_SPECS",
    "_prompt_bucket",
    "_SeedStubAdapter",
]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_dev_data")

DEMO_EMAIL = "demo@citeladder.dev"
DEMO_PASSWORD = "DemoPass123!"
DEMO_WORKSPACE_NAMES = ("Wanderlust Gear Co.", "Wanderlust Gear Co. - Agency")

# ---------------------------------------------------------------------------
# Development-only guard (fail closed BEFORE any write)
# ---------------------------------------------------------------------------
# Environments this seeder is allowed to touch. Anything else — staging,
# production, or an unrecognized token — is refused.
_DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test", "testing"})


class SeedEnvironmentError(RuntimeError):
    """The configured target is not an approved development database."""


def _require_development_target() -> None:
    """Refuse to seed anything but a development database.

    This seeder DELETES the demo workspaces and the demo user, and creates a
    fixed, publicly-known credential (``DEMO_EMAIL`` / ``DEMO_PASSWORD``).
    Against a shared, staging, or production database that is destructive AND
    an account-takeover vector, so the check runs before the first delete or
    commit rather than trusting the operator's shell.

    ``APP_ENV`` is the gate. An empty/unset value is treated as production:
    the safe default for a destructive script is to refuse, not to assume.
    """
    env = str(settings.app_env or "").strip().lower()
    if env not in _DEVELOPMENT_ENVS:
        raise SeedEnvironmentError(
            f"Refusing to seed: APP_ENV is {env or '<unset>'!r}, not a development "
            f"environment ({', '.join(sorted(_DEVELOPMENT_ENVS))}). This script "
            "deletes the demo workspaces/user and creates a well-known demo "
            "login, so it must never run against a shared, staging, or "
            "production database. Set APP_ENV=development and point "
            "DATABASE_URL at a disposable local database."
        )
    logger.info("Environment check passed: APP_ENV=%s", env)


# ---------------------------------------------------------------------------
# Cleanup (idempotency)
# ---------------------------------------------------------------------------
async def _cleanup_previous_seed(session: AsyncSession) -> None:
    # Defense in depth: the guard also runs at the top of ``seed()``, but this
    # function performs the first deletes, so it re-asserts rather than
    # trusting every future caller to have checked.
    _require_development_target()
    existing = (
        (
            await session.execute(
                select(Workspace).where(Workspace.name.in_(DEMO_WORKSPACE_NAMES))
            )
        )
        .scalars()
        .all()
    )
    for ws in existing:
        await session.delete(ws)
    if existing:
        await session.commit()
        logger.info("Removed %d previously-seeded demo workspace(s)", len(existing))

    existing_user = (
        await session.execute(select(User).where(User.email == DEMO_EMAIL))
    ).scalar_one_or_none()
    if existing_user is not None:
        await session.delete(existing_user)
        await session.commit()
        logger.info("Removed previously-seeded demo user")


async def _seed_monitored_urls_grant(
    session: AsyncSession,
    owner_user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Give the demo workspace a positive ``monitored_urls`` allowance.

    Uses the production grant path (billing bootstrap + operator override
    bundle) so the projected ``WorkspaceSiteHealthRuntime`` row is a true
    projection: full discovery, user selection, and count disclosure — exactly
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


# ---------------------------------------------------------------------------
# Main seed
# ---------------------------------------------------------------------------
async def seed() -> None:
    # Fail closed BEFORE the first delete/commit or any credential creation.
    _require_development_target()
    async with SessionLocal() as session:
        await _cleanup_previous_seed(session)

    # 1. Demo user + personal workspace (via the real auth service).
    async with SessionLocal() as session:
        user = await register_user(session, DEMO_EMAIL, DEMO_PASSWORD)
        if user is None:
            user = (
                await session.execute(select(User).where(User.email == DEMO_EMAIL))
            ).scalar_one()
        # ensure_personal_workspace is idempotent; may already exist.
        personal_ws = await ensure_personal_workspace(session, user)
        if personal_ws is None:
            personal_ws = (
                (
                    await session.execute(
                        select(Workspace)
                        .join(
                            WorkspaceMember,
                            WorkspaceMember.workspace_id == Workspace.id,
                        )
                        .where(WorkspaceMember.user_id == user.id)
                        # Deterministic pick when the demo user belongs to
                        # several workspaces — otherwise a re-run could rename
                        # a different workspace each time.
                        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
                    )
                )
                .scalars()
                .first()
            )
        if personal_ws is None:
            # Neither path produced a workspace: fail with the cause rather
            # than an AttributeError on the rename below.
            raise SeedEnvironmentError(
                f"Could not resolve a personal workspace for {DEMO_EMAIL}: "
                "ensure_personal_workspace returned None and the user has no "
                "workspace membership. Re-run against a clean development "
                "database."
            )
        # Rename the auto-created personal workspace to our demo name so
        # cleanup/re-run can find it, and add a second agency workspace.
        personal_ws.name = DEMO_WORKSPACE_NAMES[0]
        agency_ws = Workspace(name=DEMO_WORKSPACE_NAMES[1])
        session.add(agency_ws)
        await session.flush()
        session.add(
            WorkspaceMember(workspace_id=agency_ws.id, user_id=user.id, role="owner")
        )
        await session.commit()
        workspace_id = personal_ws.id
        agency_workspace_id = agency_ws.id
        demo_user_id = user.id
        logger.info(
            "Seeded user %s workspaces=%s/%s",
            user.email,
            workspace_id,
            agency_workspace_id,
        )

    # 2. Provider connections + routes (BYOK, fake keys) on the main workspace.
    async with SessionLocal() as session:
        engines_transports = [
            (ENGINE_CHATGPT, TRANSPORT_OPENAI),
            (ENGINE_CLAUDE, TRANSPORT_ANTHROPIC),
            (ENGINE_GEMINI, TRANSPORT_GOOGLE),
        ]
        for engine, transport in engines_transports:
            connection = ProviderConnection(
                workspace_id=workspace_id,
                label=f"{engine.capitalize()} (dev key)",
                transport_provider=transport,
                api_key_encrypted=encrypt_secret(f"dev-fake-key-for-{engine}"),
                active=True,
                last_test_status="ok",
                last_tested_at=datetime.now(UTC),
            )
            session.add(connection)
            await session.flush()
            session.add(
                ProviderRoute(
                    workspace_id=workspace_id,
                    connection_id=connection.id,
                    logical_engine=engine,
                    transport_provider=transport,
                    transport_model=measurement_route(engine, "pulse").transport_model,
                    is_default=True,
                )
            )
        await session.commit()
        logger.info("Seeded 3 provider connections + routes")

    # 3. Project #1: Wanderlust Gear Co. (controlled_localized benchmark mode).
    async with SessionLocal() as session:
        project = Project(
            workspace_id=workspace_id,
            name="Wanderlust Gear - US Backpacks",
            brand_name="Wanderlust Gear Co.",
            website_url="https://wanderlustgear.com",
            country_code="US",
            language_code="en-US",
            benchmark_mode="controlled_localized",
            default_repetitions=2,
        )
        session.add(project)
        await session.flush()

        brand = Brand(project_id=project.id, name="Wanderlust Gear Co.")
        session.add(brand)
        await session.flush()
        session.add(BrandAlias(brand_id=brand.id, alias="Wanderlust"))
        session.add(BrandAlias(brand_id=brand.id, alias="Wanderlust Gear"))

        trailblaze = Competitor(
            project_id=project.id,
            name="TrailBlaze Packs",
            aliases=["TrailBlaze"],
            domains=["trailblazepacks.com"],
        )
        session.add(trailblaze)
        session.add(
            Competitor(
                project_id=project.id,
                name="Summit Gear",
                aliases=["Summit"],
                domains=["summitgear.com"],
            )
        )
        await session.flush()
        session.add(OwnedDomain(project_id=project.id, domain="wanderlustgear.com"))
        session.add(
            UnintendedDomain(
                project_id=project.id, domain="wanderlustgear.blogspot.com"
            )
        )

        # Prompts covering every intent + every status (module-level
        # PROMPT_SPECS so the fixture unit test can mirror them).
        prompt_set = PromptSet(project_id=project.id, name="Core Discovery Set")
        session.add(prompt_set)
        await session.flush()

        prompt_ids: list[uuid.UUID] = []
        for text, intent, status, origin in PROMPT_SPECS:
            prompt = Prompt(
                prompt_set_id=prompt_set.id,
                text=text,
                theme="backpacks",
                intent=intent,
                status=status,
                enabled=status != "archived",
                origin=origin,
            )
            session.add(prompt)
            await session.flush()
            prompt_ids.append(prompt.id)

        # Products (Agentic Commerce surface): the catalog the fixture
        # answers name (module-level specs; see the adapter comment).
        for spec in DEMO_PRODUCT_SPECS:
            session.add(
                Product(
                    project_id=project.id,
                    name=spec.name,
                    sku=spec.sku,
                    url=spec.url,
                    price=spec.price,
                    currency=spec.currency,
                )
            )
        session.add(
            CompetitorProduct(
                project_id=project.id,
                competitor_id=trailblaze.id,
                name=DEMO_COMPETITOR_PRODUCT_SPEC.name,
                url=DEMO_COMPETITOR_PRODUCT_SPEC.url,
                price=DEMO_COMPETITOR_PRODUCT_SPEC.price,
                currency=DEMO_COMPETITOR_PRODUCT_SPEC.currency,
            )
        )

        await session.commit()
        project_id = project.id
        active_prompt_ids = [
            pid
            for pid, (_t, _i, status, _o) in zip(prompt_ids, PROMPT_SPECS, strict=True)
            if status == "active"
        ]
        logger.info(
            "Seeded project %s with %d prompts (%d active)",
            project_id,
            len(prompt_ids),
            len(active_prompt_ids),
        )

    # 4. Project #2: a second, smaller project on the agency workspace
    #    (forced_grounded benchmark mode) to exercise multi-project / cross-
    #    workspace surfaces.
    async with SessionLocal() as session:
        project2 = Project(
            workspace_id=agency_workspace_id,
            name="CamperCo Awnings",
            brand_name="CamperCo",
            website_url="https://camperco.example.com",
            country_code="AU",
            language_code="en-AU",
            benchmark_mode="forced_grounded",
            default_repetitions=1,
        )
        session.add(project2)
        await session.flush()
        brand2 = Brand(project_id=project2.id, name="CamperCo")
        session.add(brand2)
        await session.flush()
        session.add(BrandAlias(brand_id=brand2.id, alias="Camper Co"))
        session.add(
            Competitor(
                project_id=project2.id,
                name="OutbackShade",
                aliases=[],
                domains=["outbackshade.example.com"],
            )
        )
        session.add(OwnedDomain(project_id=project2.id, domain="camperco.example.com"))
        await session.commit()
        project2_id = project2.id
        logger.info("Seeded project %s (agency workspace)", project2_id)

    async with SessionLocal() as session:
        prompt_set2 = PromptSet(project_id=project2_id, name="Awning Prompts")
        session.add(prompt_set2)
        await session.flush()
        for text, intent in [
            ("best RV awning for hot climates", "discovery"),
            ("CamperCo vs OutbackShade awnings", "comparison"),
            ("where to buy a retractable camper awning", "purchase"),
        ]:
            session.add(
                Prompt(
                    prompt_set_id=prompt_set2.id,
                    text=text,
                    theme="awnings",
                    intent=intent,
                    status="active",
                    enabled=True,
                    origin="manual",
                )
            )
        await session.commit()
        prompt_set2_id = prompt_set2.id

    # Provider connection for the agency workspace (gemini only - smaller audit).
    async with SessionLocal() as session:
        connection2 = ProviderConnection(
            workspace_id=agency_workspace_id,
            label="Gemini (dev key)",
            transport_provider=TRANSPORT_GOOGLE,
            api_key_encrypted=encrypt_secret("dev-fake-key-for-gemini-agency"),
            active=True,
            last_test_status="ok",
            last_tested_at=datetime.now(UTC),
        )
        session.add(connection2)
        await session.flush()
        session.add(
            ProviderRoute(
                workspace_id=agency_workspace_id,
                connection_id=connection2.id,
                logical_engine=ENGINE_GEMINI,
                transport_provider=TRANSPORT_GOOGLE,
                transport_model=measurement_route(
                    ENGINE_GEMINI, "pulse"
                ).transport_model,
                is_default=True,
            )
        )
        await session.commit()

    # 5. Run a REAL completed audit for project #1 across all 3 engines,
    #    using the stubbed adapter (no network calls) - patches build_adapter
    #    for the duration of this run only, then restores it.
    _original_build_adapter = audit_worker.build_adapter
    _original_min_interval = audit_settings.min_request_interval_seconds
    _original_heartbeat = audit_settings.heartbeat_interval_seconds
    audit_worker.build_adapter = _build_seed_adapter
    audit_settings.min_request_interval_seconds = 0.0
    audit_settings.heartbeat_interval_seconds = 3600.0
    try:
        async with SessionLocal() as session:
            audit1 = await create_audit(
                session,
                trigger=AUDIT_TRIGGER_SYSTEM,
                workspace_id=workspace_id,
                project_id=project_id,
                engines=[ENGINE_CHATGPT, ENGINE_CLAUDE, ENGINE_GEMINI],
                prompt_set_id=None,
                prompt_ids=active_prompt_ids,
                repetitions=2,
                random_seed="42",
                measurement_mode="pulse",
            )
            audit1_id = audit1.id
        worker1 = AuditWorker(session_factory=SessionLocal, owner="seed-worker-1")
        await worker1.run_until_idle()
        logger.info("Completed audit %s for project %s", audit1_id, project_id)

        async with SessionLocal() as session:
            audit2 = await create_audit(
                session,
                trigger=AUDIT_TRIGGER_SYSTEM,
                workspace_id=agency_workspace_id,
                project_id=project2_id,
                engines=[ENGINE_GEMINI],
                prompt_set_id=prompt_set2_id,
                repetitions=1,
                random_seed="7",
                measurement_mode="pulse",
            )
            audit2_id = audit2.id
        worker2 = AuditWorker(session_factory=SessionLocal, owner="seed-worker-2")
        await worker2.run_until_idle()
        logger.info("Completed audit %s for project %s", audit2_id, project2_id)
    finally:
        audit_worker.build_adapter = _original_build_adapter
        audit_settings.min_request_interval_seconds = _original_min_interval
        audit_settings.heartbeat_interval_seconds = _original_heartbeat

    # 6. Site Health: run the REAL crawl planner (`create_crawl`) + REAL
    #    SiteHealthWorker (with a mocked transport) to drain discovery, then
    #    select every discovered URL as "monitored" and recrawl so the
    #    analyze tasks get seeded for them (mirrors the production
    #    "discover -> select monitored URLs -> recrawl analyzes" flow; a
    #    hand-built crawl/task never goes through that selection gate).
    async with SessionLocal() as session:
        await _seed_monitored_urls_grant(session, demo_user_id, workspace_id)
        crawl1 = await create_crawl(
            session, workspace_id=workspace_id, project_id=project_id, random_seed="99"
        )
        crawl1_id = crawl1.id

    worker3 = SiteHealthWorker(
        session_factory=SessionLocal,
        owner="seed-site-worker",
        resolver=_FakeResolver(),
        transport=_site_transport(),
    )
    await worker3.run_until_idle()
    logger.info("Completed site health discovery crawl %s", crawl1_id)

    async with SessionLocal() as session:
        await bulk_select_monitored_set(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            crawl_id=crawl1_id,
            mode=BULK_SELECT_MODE_ALL,
            expected_selection_version=0,
        )
        await session.commit()

    # Recrawl: `create_crawl` re-seeds `analyze` tasks for every active
    # monitored URL (`seed_monitored_targets`), which is how Starter's
    # per-page analyses actually get produced.
    async with SessionLocal() as session:
        crawl2 = await create_crawl(
            session, workspace_id=workspace_id, project_id=project_id, random_seed="100"
        )
        crawl2_id = crawl2.id
    await worker3.run_until_idle()
    logger.info("Completed site health analysis crawl %s", crawl2_id)

    # 7. Materialize the first action set and resolve one item between two
    # comparable Wanderlust audits. The second deterministic adapter generation
    # improves the evidence mix without changing prompt or engine identity.
    async with SessionLocal() as session:
        await recompute_opportunities(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=audit1_id,
            site_crawl_id=crawl2_id,
        )
        actions = await list_opportunities(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if actions["items"]:
            await update_opportunity_status(
                session,
                workspace_id=workspace_id,
                opportunity_id=actions["items"][0]["id"],
                status="resolved",
                changed_by_user_id=demo_user_id,
            )

    set_seed_audit_generation(1)
    audit_worker.build_adapter = _build_seed_adapter
    audit_settings.min_request_interval_seconds = 0.0
    audit_settings.heartbeat_interval_seconds = 3600.0
    try:
        async with SessionLocal() as session:
            comparison_audit = await create_audit(
                session,
                trigger=AUDIT_TRIGGER_SYSTEM,
                workspace_id=workspace_id,
                project_id=project_id,
                engines=[ENGINE_CHATGPT, ENGINE_CLAUDE, ENGINE_GEMINI],
                prompt_set_id=None,
                prompt_ids=active_prompt_ids,
                repetitions=2,
                random_seed="43",
                measurement_mode="pulse",
            )
            comparison_audit_id = comparison_audit.id
        comparison_worker = AuditWorker(
            session_factory=SessionLocal, owner="seed-worker-comparison"
        )
        await comparison_worker.run_until_idle()
    finally:
        set_seed_audit_generation(0)
        audit_worker.build_adapter = _original_build_adapter
        audit_settings.min_request_interval_seconds = _original_min_interval
        audit_settings.heartbeat_interval_seconds = _original_heartbeat

    async with SessionLocal() as session:
        await recompute_opportunities(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=comparison_audit_id,
            site_crawl_id=crawl2_id,
        )
    logger.info(
        "Completed comparable audit %s with action history for project %s",
        comparison_audit_id,
        project_id,
    )

    # The password is deliberately NOT logged (CodeQL: clear-text logging of
    # sensitive information). It is a fixed dev-seed constant defined at the top
    # of this module, so anyone who can run the seeder can already read it —
    # writing it into log output only risks it leaking into captured CI logs.
    logger.info(
        "Seed complete. Demo login: %s / see DEMO_PASSWORD in "
        "scripts/seed_dev_data.py (workspace=%s, agency_workspace=%s)",
        DEMO_EMAIL,
        workspace_id,
        agency_workspace_id,
    )


if __name__ == "__main__":
    asyncio.run(seed())
