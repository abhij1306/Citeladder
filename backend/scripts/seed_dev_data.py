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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.brand_profile import (
    BRAND_PROFILE_FIELDS,
    BRAND_PROFILE_REVIEW_CONFIRMED,
    BRAND_PROFILE_SOURCE_MANUAL,
)
from app.core.config.integrations_transport import INTEGRATION_TRANSPORT_GOOGLE
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
from app.domain.auth.service import register_user
from app.domain.integrations.sync import enqueue_sync_run
from app.domain.workspaces.service import ensure_personal_workspace
from app.models.brand import (
    Brand,
    BrandAlias,
    BrandProfile,
    Competitor,
    OwnedDomain,
    UnintendedDomain,
)
from app.models.integrations import (
    IntegrationConnection,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.provider import ProviderConnection, ProviderRoute
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember
from app.workers.analytics_worker import AnalyticsWorker
from app.workers.integration_worker import IntegrationWorker
from scripts.seed_dev_runs import (
    run_actions_and_comparison,
    run_seed_audits,
    run_site_health_crawls,
)
from scripts.seed_dev_support import (
    PROMPT_SPECS,
    _integration_transport,
    _prompt_bucket,
    _SeedStubAdapter,
)

__all__ = [
    "PROMPT_SPECS",
    "_SeedStubAdapter",
    "_prompt_bucket",
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


# ---------------------------------------------------------------------------
# Main seed
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class _SeedWorkspaces:
    """Identity the later stages hang everything else off."""

    workspace_id: uuid.UUID
    agency_workspace_id: uuid.UUID
    demo_user_id: uuid.UUID


@dataclass(frozen=True)
class _SeedPrimaryProject:
    project_id: uuid.UUID
    active_prompt_ids: list[uuid.UUID]


@dataclass(frozen=True)
class _SeedAgencyProject:
    project_id: uuid.UUID
    prompt_set_id: uuid.UUID


async def _seed_user_and_workspaces() -> _SeedWorkspaces:
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

    return _SeedWorkspaces(
        workspace_id=workspace_id,
        agency_workspace_id=agency_workspace_id,
        demo_user_id=demo_user_id,
    )


async def _seed_provider_connections(workspace_id: uuid.UUID) -> None:
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
                    transport_model=measurement_route(engine).transport_model,
                    is_default=True,
                )
            )
        await session.commit()
        logger.info("Seeded 3 provider connections + routes")


async def _seed_primary_project(
    workspace_id: uuid.UUID, demo_user_id: uuid.UUID
) -> _SeedPrimaryProject:
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
        reviewed_at = datetime.now(UTC).isoformat()
        confirmed_source = {
            "origin": BRAND_PROFILE_SOURCE_MANUAL,
            "review_state": BRAND_PROFILE_REVIEW_CONFIRMED,
            "reviewed_by": str(demo_user_id),
            "reviewed_at": reviewed_at,
        }
        session.add(
            BrandProfile(
                workspace_id=workspace_id,
                project_id=project.id,
                brand_id=brand.id,
                description="Evidence-grounded outdoor packs and travel gear.",
                positioning="Durable mid-market packs for multi-day travel.",
                products_services=[
                    "Hiking backpacks",
                    "Travel backpacks",
                    "Waterproof backpack",
                ],
                target_audience="Travelers and hikers planning multi-day trips.",
                sources={
                    field: dict(confirmed_source) for field in BRAND_PROFILE_FIELDS
                },
            )
        )
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

    return _SeedPrimaryProject(
        project_id=project_id, active_prompt_ids=active_prompt_ids
    )


async def _seed_google_integrations(
    workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    # 4. Persist one real Google consent graph (shared by GSC + GA4), map both
    # properties, and drain the real sync + analytics queues against a
    # deterministic provider transport. This yields immutable raw artifacts,
    # metric rows, Traffic/Demand projections, and honest connection history.
    metric_date = datetime.now(UTC).date() - timedelta(days=2)
    window = (metric_date - timedelta(days=27), metric_date)
    async with SessionLocal() as session:
        grant = IntegrationOAuthGrant(
            workspace_id=workspace_id,
            transport=INTEGRATION_TRANSPORT_GOOGLE,
            access_token_encrypted=encrypt_secret("dev-google-access-token"),
            refresh_token_encrypted=encrypt_secret("dev-google-refresh-token"),
            token_expires_at=datetime.now(UTC) + timedelta(days=1),
            granted_scopes=["gsc.readonly", "analytics.readonly"],
            status="connected",
        )
        session.add(grant)
        await session.flush()
        gsc = IntegrationConnection(
            workspace_id=workspace_id,
            grant_id=grant.id,
            provider="gsc",
            label="Wanderlust Search Console",
            account_ref="https://wanderlustgear.com",
        )
        ga4 = IntegrationConnection(
            workspace_id=workspace_id,
            grant_id=grant.id,
            provider="ga4",
            label="Wanderlust GA4",
            account_ref="123456789",
        )
        session.add_all([gsc, ga4])
        await session.flush()
        session.add_all(
            [
                IntegrationPropertyMapping(
                    workspace_id=workspace_id,
                    connection_id=gsc.id,
                    provider="gsc",
                    property_ref=gsc.account_ref,
                    project_id=project_id,
                    status="active",
                ),
                IntegrationPropertyMapping(
                    workspace_id=workspace_id,
                    connection_id=ga4.id,
                    provider="ga4",
                    property_ref=ga4.account_ref,
                    project_id=project_id,
                    status="active",
                ),
            ]
        )
        await enqueue_sync_run(
            session,
            workspace_id=workspace_id,
            connection_id=gsc.id,
            window_start=window[0],
            window_end=window[1],
        )
        await enqueue_sync_run(
            session,
            workspace_id=workspace_id,
            connection_id=ga4.id,
            window_start=window[0],
            window_end=window[1],
        )
    integration_worker = IntegrationWorker(
        session_factory=SessionLocal,
        owner="seed-integration-worker",
        transport=_integration_transport(metric_date),
    )
    await integration_worker.run_until_idle()
    await AnalyticsWorker(
        session_factory=SessionLocal, owner="seed-analytics-worker"
    ).run_until_idle()
    logger.info("Completed deterministic GSC/GA4 sync and analytics refresh")


async def _seed_agency_project(
    agency_workspace_id: uuid.UUID,
) -> _SeedAgencyProject:
    # 5. Project #2: a second, smaller project on the agency workspace
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
                transport_model=measurement_route(ENGINE_GEMINI).transport_model,
                is_default=True,
            )
        )
        await session.commit()

    return _SeedAgencyProject(project_id=project2_id, prompt_set_id=prompt_set2_id)


async def seed() -> None:
    """Build the demo dataset, then run the real workers over it.

    Each numbered stage owns one slice of the dataset and hands the next its
    identifiers; the worker drains live in ``scripts.seed_dev_runs``.
    """
    # Fail closed BEFORE the first delete/commit or any credential creation.
    _require_development_target()
    async with SessionLocal() as session:
        await _cleanup_previous_seed(session)

    workspaces = await _seed_user_and_workspaces()
    await _seed_provider_connections(workspaces.workspace_id)
    primary = await _seed_primary_project(
        workspaces.workspace_id, workspaces.demo_user_id
    )
    await _seed_google_integrations(workspaces.workspace_id, primary.project_id)
    agency = await _seed_agency_project(workspaces.agency_workspace_id)

    audit_id = await run_seed_audits(
        workspace_id=workspaces.workspace_id,
        project_id=primary.project_id,
        active_prompt_ids=primary.active_prompt_ids,
        agency_workspace_id=workspaces.agency_workspace_id,
        project2_id=agency.project_id,
        prompt_set2_id=agency.prompt_set_id,
    )
    site_crawl_id = await run_site_health_crawls(
        workspace_id=workspaces.workspace_id,
        project_id=primary.project_id,
        demo_user_id=workspaces.demo_user_id,
    )
    await run_actions_and_comparison(
        workspace_id=workspaces.workspace_id,
        project_id=primary.project_id,
        demo_user_id=workspaces.demo_user_id,
        active_prompt_ids=primary.active_prompt_ids,
        audit_id=audit_id,
        site_crawl_id=site_crawl_id,
    )

    # The password is deliberately NOT logged (CodeQL: clear-text logging of
    # sensitive information). It is a fixed dev-seed constant defined at the top
    # of this module, so anyone who can run the seeder can already read it -
    # writing it into log output only risks it leaking into captured CI logs.
    logger.info(
        "Seed complete. Demo login: %s / see DEMO_PASSWORD in "
        "scripts/seed_dev_data.py (workspace=%s, agency_workspace=%s)",
        DEMO_EMAIL,
        workspaces.workspace_id,
        workspaces.agency_workspace_id,
    )


if __name__ == "__main__":
    asyncio.run(seed())
