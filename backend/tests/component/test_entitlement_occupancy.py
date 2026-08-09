"""Component tests for account occupancy enforcement (real Postgres).

Pins the slice23 Task 4 contract: every occupancy check runs in the SAME
transaction as the insert it guards, under the account-capacity advisory
lock, so concurrent mutations from INDEPENDENT sessions can never push the
committed count past the account grant — for project creates and for
manual/imported/generated prompt inserts alike. Also pins the charging
semantics: only rows that actually insert consume a slot (duplicates are
free), archived/proposed/generated rows count, deletion frees capacity,
and resolver allowance changes affect subsequent mutations immediately.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import cast

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.agent.client import DefaultAgentClient
from app.core.config.entitlements import KEY_PROJECT_SLOTS, KEY_PROMPT_SLOTS
from app.core.config.projects import PROMPT_ORIGIN_GENERATED, PROMPT_ORIGIN_MANUAL
from app.core.config.prompts import (
    PROMPT_STATUS_ACTIVE,
    PROMPT_STATUS_ARCHIVED,
)
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.enforcement import (
    OccupancyLimitExceededError,
    OccupancyUnresolvedError,
)
from app.domain.entitlements.types import GrantSpec
from app.domain.projects.schemas import ProjectCreate
from app.domain.projects.service import create_project
from app.domain.prompts.generation import generate_prompts
from app.domain.prompts.schemas import (
    PromptCreate,
    PromptGenerateRequest,
    PromptInput,
    PromptUpdate,
)
from app.domain.prompts.service import (
    create_prompt,
    delete_prompt,
    import_prompts,
    update_prompt,
)
from app.models.billing import WorkspaceBillingLink
from app.models.brand import Brand
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.workspace import Workspace
from tests.component.occupancy_helpers import (
    seed_account_workspace,
    seed_occupancy_grants,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _seed_project_set(
    session: AsyncSession, workspace_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """ORM-seed a project + prompt set (bypasses occupancy on purpose)."""
    project = Project(workspace_id=workspace_id, name="Seed Project")
    session.add(project)
    await session.flush()
    # Binding identity for topical admission: texts below name the brand.
    brand = Brand(project_id=project.id, name="Acme Corp")
    session.add(brand)
    await session.flush()
    prompt_set = PromptSet(project_id=project.id, name="Seed Set")
    session.add(prompt_set)
    await session.flush()
    project_id, prompt_set_id = project.id, prompt_set.id
    await session.commit()
    return project_id, prompt_set_id


async def _prompt_count(session: AsyncSession, prompt_set_id: uuid.UUID) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Prompt)
                .where(Prompt.prompt_set_id == prompt_set_id)
            )
        ).scalar_one()
    )


def _project_count_stmt(workspace_id: uuid.UUID):
    return (
        select(func.count())
        .select_from(Project)
        .where(Project.workspace_id == workspace_id)
    )


# =========================================================================
# Concurrent project creates never exceed the grant
# =========================================================================
@pytest.mark.asyncio
async def test_concurrent_project_creates_never_exceed_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROJECT_SLOTS, value=1),),
        )
        await session.commit()

    async def _create(name: str) -> str:
        async with session_factory() as session:
            try:
                await create_project(
                    session,
                    workspace_id=workspace.id,
                    payload=ProjectCreate(name=name),
                )
                return "ok"
            except OccupancyLimitExceededError:
                await session.rollback()
                return "denied"

    # The account advisory lock serializes the two mutations; the loser
    # recounts AFTER the winner commits and is denied.
    results = await asyncio.gather(_create("Alpha"), _create("Beta"))
    assert sorted(results) == ["denied", "ok"]

    async with session_factory() as session:
        count = int(
            (await session.execute(_project_count_stmt(workspace.id))).scalar_one()
        )
    assert count == 1


@pytest.mark.asyncio
async def test_project_slots_counts_every_linked_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace_a, _user = await seed_account_workspace(session)
        workspace_b = Workspace(name="Second WS")
        session.add(workspace_b)
        await session.flush()
        session.add(
            WorkspaceBillingLink(
                workspace_id=workspace_b.id, billing_account_id=account.id
            )
        )
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_a.id,
            grants=(GrantSpec(key=KEY_PROJECT_SLOTS, value=1),),
        )
        await session.commit()

    async with session_factory() as session:
        await create_project(
            session,
            workspace_id=workspace_a.id,
            payload=ProjectCreate(name="In A"),
        )
    # The project in workspace A consumes the account-wide slot, so a create
    # in the OTHER linked workspace is denied.
    async with session_factory() as session:
        with pytest.raises(OccupancyLimitExceededError):
            await create_project(
                session,
                workspace_id=workspace_b.id,
                payload=ProjectCreate(name="In B"),
            )
        await session.rollback()


# =========================================================================
# Concurrent prompt inserts (manual / import / generated) never exceed it
# =========================================================================
@pytest.mark.asyncio
async def test_concurrent_manual_prompt_inserts_never_exceed_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=2),),
        )
        await session.commit()

    async def _create(text: str) -> str:
        async with session_factory() as session:
            try:
                await create_prompt(
                    session,
                    workspace_id=workspace.id,
                    payload=PromptCreate(prompt_set_id=prompt_set_id, text=text),
                )
                return "ok"
            except OccupancyLimitExceededError:
                await session.rollback()
                return "denied"

    results = await asyncio.gather(
        _create("alpha acme question"),
        _create("beta acme question"),
        _create("gamma acme question"),
    )
    assert sorted(results) == ["denied", "ok", "ok"]

    async with session_factory() as session:
        assert await _prompt_count(session, prompt_set_id) == 2


@pytest.mark.asyncio
async def test_concurrent_imports_never_exceed_grant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=3),),
        )
        await session.commit()

    rows_a = [PromptInput(text=f"batch a acme {idx}") for idx in range(3)]
    rows_b = [PromptInput(text=f"batch b acme {idx}") for idx in range(3)]

    async def _import(rows: list[PromptInput]) -> str:
        async with session_factory() as session:
            try:
                await import_prompts(
                    session,
                    workspace_id=workspace.id,
                    prompt_set_id=prompt_set_id,
                    rows=rows,
                )
                return "ok"
            except OccupancyLimitExceededError:
                await session.rollback()
                return "denied"

    # Each import would fit alone (3 <= 3); together they would persist 6.
    # The account lock serializes them and the loser is denied atomically.
    results = await asyncio.gather(_import(rows_a), _import(rows_b))
    assert sorted(results) == ["denied", "ok"]

    async with session_factory() as session:
        assert await _prompt_count(session, prompt_set_id) == 3


@pytest.mark.asyncio
async def test_concurrent_generation_inserts_never_exceed_grant(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "occ-gen@example.com", "password": "password123"},
    )
    assert resp.status_code == 201
    project = (
        await client.post(
            "/api/v1/projects",
            json={
                "name": "Acme Visibility",
                "brand_name": "Acme Corp",
                "website_url": "https://acme.com",
                "benchmark_mode": "controlled_localized",
                "default_repetitions": 1,
            },
        )
    ).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Seed Set"},
        )
    ).json()["id"]
    profile = await client.put(
        f"/api/v1/projects/{project['id']}/brand-profile",
        json={"products_services": ["running shoes"]},
    )
    assert profile.status_code == 200
    workspace_id = uuid.UUID(project["workspace_id"])
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=5),),
        )
        await session.commit()

    # Both generations pause at the provider barrier so they hit the persist
    # phase together; the account lock serializes them at the mutation.
    barrier = asyncio.Barrier(2)

    def _agent_payload(topic: str) -> str:
        return json.dumps(
            {
                "topics": [
                    {
                        "name": topic,
                        "prompts": [
                            {
                                "text": (
                                    f"{topic} running shoes for {chr(97 + idx) * 20}"
                                ),
                                "intent": "discovery",
                            }
                            for idx in range(5)
                        ],
                    }
                ]
            }
        )

    class _BarrierAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        def __init__(self, topic: str) -> None:
            self._response = _agent_payload(topic)

        async def complete_json(self, *, system: str, user: str) -> str:
            await barrier.wait()
            return self._response

    async def _run(topic: str) -> str:
        async with session_factory() as session:
            try:
                await generate_prompts(
                    session,
                    workspace_id=workspace_id,
                    prompt_set_id=uuid.UUID(prompt_set_id),
                    payload=PromptGenerateRequest(count=5, confirm_send_evidence=True),
                    agent=cast(DefaultAgentClient, _BarrierAgent(topic)),
                )
                return "ok"
            except OccupancyLimitExceededError:
                await session.rollback()
                return "denied"

    results = await asyncio.gather(_run("Alpha"), _run("Beta"))
    assert sorted(results) == ["denied", "ok"]

    async with session_factory() as session:
        assert await _prompt_count(session, uuid.UUID(prompt_set_id)) == 5


# =========================================================================
# Charging semantics
# =========================================================================
@pytest.mark.asyncio
async def test_duplicate_filtering_charges_only_actual_inserts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=3),),
        )
        await session.commit()

    async with session_factory() as session:
        await create_prompt(
            session,
            workspace_id=workspace.id,
            payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme alpha"),
        )

    # "alpha" + an intra-upload repeat normalize to the persisted hash, so
    # only "beta"/"gamma" are charged: 1 in use + 2 actual inserts == 3.
    async with session_factory() as session:
        prompt_set = await import_prompts(
            session,
            workspace_id=workspace.id,
            prompt_set_id=prompt_set_id,
            rows=[
                PromptInput(text="acme alpha"),
                PromptInput(text=" ACME ALPHA "),
                PromptInput(text="acme beta"),
                PromptInput(text="acme gamma"),
            ],
        )
        assert len(prompt_set.prompts) == 3

    # At full capacity an all-duplicate upload inserts nothing and is NOT
    # denied — duplicates never consume a slot.
    async with session_factory() as session:
        prompt_set = await import_prompts(
            session,
            workspace_id=workspace.id,
            prompt_set_id=prompt_set_id,
            rows=[PromptInput(text="acme alpha"), PromptInput(text="acme beta")],
        )
        assert len(prompt_set.prompts) == 3

    async with session_factory() as session:
        assert await _prompt_count(session, prompt_set_id) == 3


@pytest.mark.asyncio
async def test_archived_and_generated_rows_count_and_update_is_free(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=3),),
        )
        archived = Prompt(
            prompt_set_id=prompt_set_id,
            text="archived row",
            status=PROMPT_STATUS_ARCHIVED,
            origin=PROMPT_ORIGIN_MANUAL,
        )
        generated_active_two = Prompt(
            prompt_set_id=prompt_set_id,
            text="second generated active row",
            status=PROMPT_STATUS_ACTIVE,
            origin=PROMPT_ORIGIN_GENERATED,
        )
        generated_active = Prompt(
            prompt_set_id=prompt_set_id,
            text="generated active row",
            status=PROMPT_STATUS_ACTIVE,
            origin=PROMPT_ORIGIN_GENERATED,
        )
        session.add_all([archived, generated_active_two, generated_active])
        await session.commit()
        archived_id = archived.id

    # Archived and generated rows all occupy slots: 3/3 used.
    async with session_factory() as session:
        with pytest.raises(OccupancyLimitExceededError):
            await create_prompt(
                session,
                workspace_id=workspace.id,
                payload=PromptCreate(prompt_set_id=prompt_set_id, text="new acme text"),
            )
        await session.rollback()

    # Updating text does NOT consume a slot, even at full capacity.
    async with session_factory() as session:
        updated = await update_prompt(
            session,
            workspace_id=workspace.id,
            prompt_id=archived_id,
            payload=PromptUpdate(text="rewritten acme archived row"),
        )
        assert updated.text == "rewritten acme archived row"

    async with session_factory() as session:
        assert await _prompt_count(session, prompt_set_id) == 3


@pytest.mark.asyncio
async def test_deletion_frees_capacity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=1),),
        )
        await session.commit()

    async with session_factory() as session:
        first = await create_prompt(
            session,
            workspace_id=workspace.id,
            payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme first"),
        )
        first_id = first.id

    async with session_factory() as session:
        with pytest.raises(OccupancyLimitExceededError):
            await create_prompt(
                session,
                workspace_id=workspace.id,
                payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme second"),
            )
        await session.rollback()

    async with session_factory() as session:
        await delete_prompt(session, workspace_id=workspace.id, prompt_id=first_id)

    async with session_factory() as session:
        await create_prompt(
            session,
            workspace_id=workspace.id,
            payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme second"),
        )
        assert await _prompt_count(session, prompt_set_id) == 1


@pytest.mark.asyncio
async def test_resolver_allowance_changes_immediately_affect_mutations(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROJECT_SLOTS, value=1),),
        )
        await session.commit()

    async with session_factory() as session:
        await create_project(
            session, workspace_id=workspace.id, payload=ProjectCreate(name="First")
        )
    async with session_factory() as session:
        with pytest.raises(OccupancyLimitExceededError):
            await create_project(
                session,
                workspace_id=workspace.id,
                payload=ProjectCreate(name="Second"),
            )
        await session.rollback()

    # A further grant bumps the account lifecycle version, so the very next
    # mutation resolves the NEW allowance (no cache staleness).
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=workspace.id,
            grants=(GrantSpec(key=KEY_PROJECT_SLOTS, value=1),),
        )
        await session.commit()
    async with session_factory() as session:
        await create_project(
            session, workspace_id=workspace.id, payload=ProjectCreate(name="Second")
        )
        count = int(
            (await session.execute(_project_count_stmt(workspace.id))).scalar_one()
        )
        assert count == 2


# =========================================================================
# Fail-closed / unprovisioned resolution semantics
# =========================================================================
@pytest.mark.asyncio
async def test_unresolved_entitlement_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # A workspace with NO billing link can never resolve an entitlement.
    async with session_factory() as session:
        workspace = Workspace(name="Unlinked WS")
        session.add(workspace)
        await session.flush()
        workspace_id = workspace.id
        _project_id, prompt_set_id = await _seed_project_set(session, workspace_id)

    async with session_factory() as session:
        with pytest.raises(OccupancyUnresolvedError):
            await create_project(
                session,
                workspace_id=workspace_id,
                payload=ProjectCreate(name="Denied"),
            )
        await session.rollback()

    async with session_factory() as session:
        with pytest.raises(OccupancyUnresolvedError):
            await create_prompt(
                session,
                workspace_id=workspace_id,
                payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme denied"),
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_unprovisioned_account_is_not_occupancy_gated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # A linked account with NO grants resolves but has no occupancy
    # capability provisioned: mutations stay ungated (the pre-commercial
    # contract) until any grant exists.
    async with session_factory() as session:
        _account, workspace, _user = await seed_account_workspace(session)
        _project_id, prompt_set_id = await _seed_project_set(session, workspace.id)

    async with session_factory() as session:
        await create_project(
            session, workspace_id=workspace.id, payload=ProjectCreate(name="One")
        )
        await create_project(
            session, workspace_id=workspace.id, payload=ProjectCreate(name="Two")
        )
    async with session_factory() as session:
        await create_prompt(
            session,
            workspace_id=workspace.id,
            payload=PromptCreate(prompt_set_id=prompt_set_id, text="acme free"),
        )
        assert await _prompt_count(session, prompt_set_id) == 1
