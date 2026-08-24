"""Shared seed helpers for the B5 audit-execution component tests.

Builds a workspace + project + brand identity + a prompt set with N prompts +
one approved provider route/connection per requested engine, directly through
the ORM (no HTTP), so the planner + worker + queue can be exercised against a
real Postgres schema.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_PLATFORM,
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    TEST_STATUS_OK,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
    measurement_route,
)
from app.core.security import encrypt_secret
from app.models.brand import Brand, BrandAlias, Competitor, OwnedDomain
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.provider import (
    ProviderConnection,
    ProviderConnectionTest,
    ProviderRoute,
)
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


@dataclass
class Seed:
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    prompt_set_id: uuid.UUID
    prompt_ids: list[uuid.UUID]
    engines: list[str]


async def seed_audit_fixtures(
    session: AsyncSession,
    *,
    prompt_count: int = 3,
    engines: list[str] | None = None,
    email: str | None = None,
    probed: bool = True,
) -> Seed:
    """Seed an auditable workspace; connections are probe-healthy by default.

    ``probed=True`` marks each BYOK connection successfully probed (the T11
    credential resolver only selects probed/healthy credentials). Funded-flow
    seeds pass ``probed=False`` so BYOK precedence cannot claim the task and
    the platform credential is exercised instead.
    """
    engines = engines or [ENGINE_GEMINI]
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"

    workspace = Workspace(name="Test WS")
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
        name="Acme Visibility",
        brand_name="Acme Corp",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=3,
    )
    session.add(project)
    await session.flush()

    brand = Brand(project_id=project.id, name="Acme Corp")
    session.add(brand)
    await session.flush()
    session.add(BrandAlias(brand_id=brand.id, alias="Acme"))
    session.add(
        Competitor(
            project_id=project.id,
            name="Globex",
            aliases=["Globex Co"],
            domains=["globex.com"],
        )
    )
    session.add(OwnedDomain(project_id=project.id, domain="acme.com"))

    prompt_set = PromptSet(project_id=project.id, name="Default")
    session.add(prompt_set)
    await session.flush()

    prompt_ids: list[uuid.UUID] = []
    for index in range(prompt_count):
        # The text names the seeded brand so it passes topical binding
        # (audit admission rejects off-domain prompts); "best option" leads
        # for tests asserting that prefix.
        prompt = Prompt(
            prompt_set_id=prompt_set.id,
            text=f"best option {index} for acme",
            theme="general",
            intent="category",
            enabled=True,
            origin="manual",
        )
        session.add(prompt)
        await session.flush()
        prompt_ids.append(prompt.id)

    # One approved connection + default route per requested engine. Gemini via
    # google is the simplest approved route; others resolve their catalog model.
    for engine in engines:
        transport = _transport_for(engine)
        connection = ProviderConnection(
            workspace_id=workspace.id,
            label=f"{engine} key",
            transport_provider=transport,
            api_key_encrypted=encrypt_secret("secret-test-key"),
            active=True,
        )
        session.add(connection)
        await session.flush()
        session.add(
            ProviderRoute(
                workspace_id=workspace.id,
                connection_id=connection.id,
                logical_engine=engine,
                transport_provider=transport,
                transport_model=measurement_route(engine).transport_model,
                is_default=True,
            )
        )
        if probed:
            _mark_connection_probed(session, connection=connection, engine=engine)

    await session.commit()
    return Seed(
        workspace_id=workspace.id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        prompt_ids=prompt_ids,
        engines=list(engines),
    )


def _mark_connection_probed(
    session: AsyncSession, *, connection: ProviderConnection, engine: str
) -> None:
    """Record one successful probe (append-only row + denormalized outcome).

    Mirrors what ``run_connection_test`` persists after a healthy probe; the
    T11 credential resolver only selects connections whose latest probe
    succeeded.
    """
    from datetime import UTC, datetime

    tested_at = datetime.now(UTC)
    session.add(
        ProviderConnectionTest(
            workspace_id=connection.workspace_id,
            connection_id=connection.id,
            status=TEST_STATUS_OK,
            error_code="",
            detail="Connection succeeded",
            latency_ms=12,
            logical_engine=engine,
            transport_provider=connection.transport_provider,
            transport_model=measurement_route(engine).transport_model,
            created_at=tested_at,
        )
    )
    connection.last_tested_at = tested_at
    connection.last_test_status = TEST_STATUS_OK


async def seed_platform_connection(
    session: AsyncSession,
    *,
    engines: list[str] | tuple[str, ...] = (ENGINE_CLAUDE,),
) -> Workspace:
    """Seed THE ONE system workspace with healthy platform connections (T11).

    Idempotent: an existing system workspace is reused (the partial unique
    index allows exactly one). Platform rows are ``credential_source=
    "platform"``, active, key-set, and successfully probed, with one default
    route per requested engine — what the provisioning script will own in
    stage D. Returns the system workspace.
    """
    from sqlalchemy import select

    system = await session.scalar(
        select(Workspace).where(Workspace.is_system.is_(True))
    )
    if system is None:
        system = Workspace(name="CiteLadder Platform (system)", is_system=True)
        session.add(system)
        await session.flush()
    for engine in engines:
        transport = _transport_for(engine)
        connection = ProviderConnection(
            workspace_id=system.id,
            label=f"platform {engine} key",
            transport_provider=transport,
            credential_source=CREDENTIAL_SOURCE_PLATFORM,
            api_key_encrypted=encrypt_secret("platform-secret-test-key"),
            active=True,
        )
        session.add(connection)
        await session.flush()
        session.add(
            ProviderRoute(
                workspace_id=system.id,
                connection_id=connection.id,
                logical_engine=engine,
                transport_provider=transport,
                transport_model=measurement_route(engine).transport_model,
                is_default=True,
            )
        )
        _mark_connection_probed(session, connection=connection, engine=engine)
    await session.flush()
    return system


def _transport_for(engine: str) -> str:
    transports = {
        ENGINE_CLAUDE: TRANSPORT_ANTHROPIC,
        ENGINE_CHATGPT: TRANSPORT_OPENAI,
        ENGINE_GEMINI: TRANSPORT_GOOGLE,
    }
    try:
        return transports[engine]
    except KeyError:
        raise ValueError(f"Unsupported engine: {engine!r}") from None
