"""Component tests for topical binding + prompt bounds (slice23 Task 4 Part C).

Covers, against real Postgres (service level) and the API envelope:
  - off-domain free text rejected on all five paths: manual create, CSV
    import (atomic), text update, and generated acceptance (proposed -> active)
    — plus valid brand/domain/category text passing;
  - generated-output persistence drops off-domain model output;
  - empty vocabulary fails closed (complete identity / use generation);
  - the 300-char DTO bound (301 rejects, 300 accepts);
  - the funded/trial prompt-count policy: unset fails closed with
    ``prompt_count_policy_unconfigured``, a configured count is enforced,
    and BYOK audit creation is never gated by the knob;
  - the competitor negative pin: a competitor name never admits a prompt.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.prompts as prompts_api
from app.core.config.audits import (
    AUDIT_TRIGGER_MANUAL,
    AUDIT_TRIGGER_TRIAL,
    CODE_PROMPT_COUNT_EXCEEDED,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
    audit_settings,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_BYOK,
    CREDENTIAL_MODE_FUNDED,
    KEY_AUDIT_CREDITS,
)
from app.core.config.projects import PROMPT_ORIGIN_GENERATED
from app.core.config.prompts import (
    CODE_BINDING_VOCABULARY_EMPTY,
    CODE_PROMPT_OFF_TOPIC,
)
from app.core.config.provider_catalog import ENGINE_CLAUDE
from app.core.security import encrypt_secret
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import PromptCountPolicyError
from app.domain.entitlements.types import GrantSpec
from app.models.brand import Brand, OwnedDomain
from app.models.prompt import Prompt, Topic
from app.models.provider import ProviderConnection, ProviderRoute
from tests.component.audit_helpers import (
    _mark_connection_probed,
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.occupancy_helpers import seed_occupancy_grants

# ---------------------------------------------------------------------------
# Shared API seed helpers (project identity: Acme Corp / acme.com, competitor
# Globex — never part of the positive vocabulary).
# ---------------------------------------------------------------------------


async def _register(client: httpx.AsyncClient, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


def _project_payload() -> dict:
    return {
        "name": "Acme Visibility",
        "brand_name": "Acme Corp",
        "brand": {"aliases": ["Acme"]},
        "website_url": "https://acme.com",
        "owned_domains": ["acme.com"],
        "competitors": [
            {"name": "Globex", "aliases": ["Globex Co"], "domains": ["globex.com"]}
        ],
        "country_code": "AU",
        "language_code": "en-AU",
    }


async def _make_project_and_set(
    client: httpx.AsyncClient, email: str
) -> tuple[dict, str]:
    await _register(client, email)
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Default"},
        )
    ).json()["id"]
    return project, prompt_set_id


# ---------------------------------------------------------------------------
# Manual create
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_rejects_off_domain_and_accepts_on_domain(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "bind-create@example.com")

    off_domain = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "best laptops for programming"},
    )
    assert off_domain.status_code == 422
    body = off_domain.json()
    assert body["error"]["code"] == CODE_PROMPT_OFF_TOPIC
    assert body["detail"]["code"] == CODE_PROMPT_OFF_TOPIC

    # Brand token, owned-domain token, and domain-host label all bind.
    for text in (
        "best acme running shoes",
        "is acme corp shipping fast",
        "reviews for acme.com products",
    ):
        created = await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": text},
        )
        assert created.status_code == 201, text


@pytest.mark.asyncio
async def test_competitor_name_never_admits_a_prompt(
    client: httpx.AsyncClient,
) -> None:
    """Negative pin: the competitor list is not the positive vocabulary."""
    _, prompt_set_id = await _make_project_and_set(client, "bind-comp@example.com")
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "is globex the market leader in footwear"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == CODE_PROMPT_OFF_TOPIC


# ---------------------------------------------------------------------------
# CSV import (atomic)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_import_one_invalid_row_inserts_nothing_and_returns_row_errors(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "bind-import@example.com")

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        json={
            "prompts": [
                {"text": "best acme running shoes"},
                {"text": "best laptops for programming"},
            ]
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == CODE_PROMPT_OFF_TOPIC
    rows = body["error"]["details"]["rows"]
    assert rows == [
        {
            "row": 1,
            "code": CODE_PROMPT_OFF_TOPIC,
            "message": rows[0]["message"],
        }
    ]
    # Atomic: the valid sibling row was NOT inserted either.
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert listed["prompts"] == []

    valid = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        json={"prompts": [{"text": "best acme running shoes"}]},
    )
    assert valid.status_code == 201
    assert valid.json()["prompt_count"] == 1


# ---------------------------------------------------------------------------
# Text update + the proposed -> active human transition
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_update_rejects_off_domain_text_and_accepts_on_domain(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "bind-update@example.com")
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "best acme running shoes"},
        )
    ).json()

    off_domain = await client.patch(
        f"/api/v1/prompts/{prompt['id']}",
        json={"text": "best laptops for programming"},
    )
    assert off_domain.status_code == 422
    assert off_domain.json()["error"]["code"] == CODE_PROMPT_OFF_TOPIC
    # The edit did not persist.
    assert (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()["prompts"][
        0
    ]["text"] == "best acme running shoes"

    ok = await client.patch(
        f"/api/v1/prompts/{prompt['id']}",
        json={"text": "best acme trail shoes"},
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_activation_transition_rejects_off_domain_proposed_prompt(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Stale/bypassed proposed content can never be promoted to active."""
    _, prompt_set_id = await _make_project_and_set(client, "bind-accept@example.com")
    async with session_factory() as session:
        stale = Prompt(
            prompt_set_id=uuid.UUID(prompt_set_id),
            text="best laptops for programming",
            status="proposed",
            origin="generated",
        )
        fresh = Prompt(
            prompt_set_id=uuid.UUID(prompt_set_id),
            text="best acme running shoes",
            status="proposed",
            origin="generated",
        )
        session.add_all([stale, fresh])
        await session.commit()
        stale_id, fresh_id = str(stale.id), str(fresh.id)

    rejected = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts/bulk-status",
        json={"prompt_ids": [stale_id], "status": "active"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == CODE_PROMPT_OFF_TOPIC
    # Nothing transitioned.
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert {p["status"] for p in listed["prompts"]} == {"proposed"}

    accepted = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts/bulk-status",
        json={"prompt_ids": [fresh_id], "status": "active"},
    )
    assert accepted.status_code == 200


# ---------------------------------------------------------------------------
# Generated-output persistence (model output is not trusted)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generation_drops_off_domain_model_output(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, prompt_set_id = await _make_project_and_set(client, "bind-gen@example.com")
    profile = await client.put(
        f"/api/v1/projects/{project['id']}/brand-profile",
        json={"products_services": ["running shoes"]},
    )
    assert profile.status_code == 200
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics",
            json={"name": "Running Shoes"},
        )
    ).json()

    class _MixedAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        async def complete_json(self, *, system: str, user: str) -> str:
            return (
                '{"prompts": ['
                f'{{"topic_id": "{topic["id"]}", '
                '"text": "best running shoes for daily training", '
                '"intent": "discovery"},'
                f'{{"topic_id": "{topic["id"]}", '
                '"text": "best laptops for programming", "intent": "discovery"}'
                "]}"
            )

    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: _MixedAgent())
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 2, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    generated = resp.json()["generated"]
    assert [p["text"] for p in generated] == ["best running shoes for daily training"]
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert [p["text"] for p in listed["prompts"]] == [
        "best running shoes for daily training"
    ]


# ---------------------------------------------------------------------------
# Audit admission
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_audit_launch_does_not_revalidate_active_prompt_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Launch consumes the persisted active portfolio admission decision."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        session.add(Topic(project_id=seed.project_id, name="Digital marketing"))
        session.add(
            Prompt(
                prompt_set_id=seed.prompt_set_id,
                text="Which agencies improve experimentation outcomes?",
                status="active",
                origin=PROMPT_ORIGIN_GENERATED,
            )
        )
        await session.commit()

    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        assert audit.id is not None


@pytest.mark.asyncio
async def test_audit_admission_honors_persisted_generated_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A generated neutral synonym is not rejected by a second lexical gate."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=0)
        # Activates the lexical project gate. The generated prompt is a valid
        # neutral synonym but intentionally shares no literal category token.
        session.add(Topic(project_id=seed.project_id, name="Digital marketing"))
        session.add(
            Prompt(
                prompt_set_id=seed.prompt_set_id,
                text="Which agencies improve experimentation outcomes?",
                status="active",
                origin=PROMPT_ORIGIN_GENERATED,
            )
        )
        await session.commit()

    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        assert audit.id is not None


@pytest.mark.asyncio
async def test_audit_launch_api_passes_active_prompt_to_later_admission_gates(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """POST /audits does not reject active text at the lexical gate."""
    project, prompt_set_id = await _make_project_and_set(
        client, "bind-audit@example.com"
    )
    workspace_id = uuid.UUID(project["workspace_id"])
    async with session_factory() as session:
        # Persisted generated prompt whose neutral synonym has no lexical
        # overlap with the project's current category vocabulary.
        session.add(
            Topic(project_id=uuid.UUID(project["id"]), name="Digital marketing")
        )
        prompt = Prompt(
            prompt_set_id=uuid.UUID(prompt_set_id),
            text="Which agencies improve experimentation outcomes?",
            status="active",
            origin=PROMPT_ORIGIN_GENERATED,
        )
        session.add(prompt)
        await session.flush()
        # One approved BYOK route so audit creation can complete.
        connection = ProviderConnection(
            workspace_id=workspace_id,
            label="gemini key",
            transport_provider="google",
            api_key_encrypted=encrypt_secret("secret-test-key"),
            active=True,
        )
        session.add(connection)
        await session.flush()
        session.add(
            ProviderRoute(
                workspace_id=workspace_id,
                connection_id=connection.id,
                logical_engine="gemini",
                transport_provider="google",
                transport_model="gemini-flash-latest",
                is_default=True,
            )
        )
        await session.commit()
        prompt_id = str(prompt.id)

    resp = await client.post(
        "/api/v1/audits",
        json={
            "project_id": project["id"],
            "engines": ["gemini"],
            "prompt_ids": [prompt_id],
            "repetitions": 1,
        },
    )
    # This API fixture has no funded platform credential, so execution is
    # denied later. Reaching that gate proves prompt_off_topic no longer makes
    # the already-active prompt impossible to launch.
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "execution_credentials_unavailable"


# ---------------------------------------------------------------------------
# Empty vocabulary fails closed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_vocabulary_fails_closed_on_mutation_but_not_audit(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A project with no brand identity/topics yet cannot take free text."""
    await _register(client, "bind-empty@example.com")
    project = (
        await client.post(
            "/api/v1/projects",
            json={"name": "No Identity", "website_url": "", "brand_name": ""},
        )
    ).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Default"},
        )
    ).json()["id"]

    created = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "anything at all"},
    )
    assert created.status_code == 422
    body = created.json()
    assert body["error"]["code"] == CODE_BINDING_VOCABULARY_EMPTY
    # The guidance directs the caller to complete identity / use generation.
    assert "identity" in body["error"]["message"]

    imported = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        json={"prompts": [{"text": "anything at all"}]},
    )
    assert imported.status_code == 422
    assert imported.json()["error"]["code"] == CODE_BINDING_VOCABULARY_EMPTY

    # An already-persisted prompt can still be measured: setup should nudge the
    # user to add identity, not make the visibility run unreachable.
    async with session_factory() as session:
        workspace_id = uuid.UUID(project["workspace_id"])
        session.add(
            Prompt(
                prompt_set_id=uuid.UUID(prompt_set_id),
                text="anything at all",
                status="active",
                origin="manual",
            )
        )
        # One approved BYOK route so admission reaches the binding gate.
        connection = ProviderConnection(
            workspace_id=workspace_id,
            label="gemini key",
            transport_provider="google",
            api_key_encrypted=encrypt_secret("secret-test-key"),
            active=True,
        )
        session.add(connection)
        await session.flush()
        _mark_connection_probed(session, connection=connection, engine="gemini")
        session.add(
            ProviderRoute(
                workspace_id=workspace_id,
                connection_id=connection.id,
                logical_engine="gemini",
                transport_provider="google",
                transport_model="gemini-flash-latest",
                is_default=True,
            )
        )
        await session.commit()
    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=uuid.UUID(project["workspace_id"]),
            project_id=uuid.UUID(project["id"]),
            engines=["gemini"],
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=uuid.UUID(prompt_set_id),
            repetitions=1,
        )
        assert audit.id is not None


@pytest.mark.asyncio
async def test_empty_vocabulary_after_identity_removal_keeps_audit_available(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Deleting identity rows does not strand an already-configured audit."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await session.execute(delete(Brand).where(Brand.project_id == seed.project_id))
        await session.execute(
            delete(OwnedDomain).where(OwnedDomain.project_id == seed.project_id)
        )
        await session.commit()

    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        assert audit.id is not None


# ---------------------------------------------------------------------------
# Prompt text bound (DTO boundary)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_prompt_text_bound_300_accepts_301_rejects(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "bind-300@example.com")

    exactly = "acme " + "x" * 295
    assert len(exactly) == 300
    ok = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts", json={"text": exactly}
    )
    assert ok.status_code == 201

    over = "acme " + "x" * 296
    assert len(over) == 301
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts", json={"text": over}
    )
    assert resp.status_code == 422

    # The update DTO shares the bound.
    patch = await client.patch(
        f"/api/v1/prompts/{ok.json()['id']}", json={"text": over}
    )
    assert patch.status_code == 422


# ---------------------------------------------------------------------------
# Funded/trial prompt-count policy
# ---------------------------------------------------------------------------
async def _seed_funded_workspace(
    session: AsyncSession, *, prompt_count: int
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, list[str]]:
    # Tenant connection stays unprobed (BYOK precedence must not claim funded
    # tasks); the platform credential backs funded credential resolution.
    seed = await seed_audit_fixtures(
        session, prompt_count=prompt_count, engines=["claude"], probed=False
    )
    await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
    await seed_occupancy_grants(
        session,
        workspace_id=seed.workspace_id,
        grants=(GrantSpec(key=KEY_AUDIT_CREDITS, value=100_000),),
    )
    await session.commit()
    return seed.workspace_id, seed.project_id, seed.prompt_set_id, seed.engines


@pytest.mark.asyncio
async def test_unset_prompt_count_policy_blocks_funded_and_trial(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_settings, "audit_prompt_count", None)
    async with session_factory() as session:
        workspace_id, project_id, prompt_set_id, engines = await _seed_funded_workspace(
            session, prompt_count=2
        )

    for trigger, credential_mode in (
        (AUDIT_TRIGGER_MANUAL, CREDENTIAL_MODE_FUNDED),
        (AUDIT_TRIGGER_TRIAL, CREDENTIAL_MODE_BYOK),
    ):
        async with session_factory() as session:
            with pytest.raises(PromptCountPolicyError) as exc_info:
                await create_audit(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    engines=engines,
                    trigger=trigger,
                    credential_mode=credential_mode,
                    prompt_set_id=prompt_set_id,
                    repetitions=1,
                )
            assert exc_info.value.code == CODE_PROMPT_COUNT_POLICY_UNCONFIGURED
            await session.rollback()


@pytest.mark.asyncio
async def test_unset_prompt_count_policy_does_not_gate_byok(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BYOK manual runs stay governed by their existing product limits."""
    monkeypatch.setattr(audit_settings, "audit_prompt_count", None)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)

    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            credential_mode=CREDENTIAL_MODE_BYOK,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        assert audit.id is not None


@pytest.mark.asyncio
async def test_configured_prompt_count_is_enforced(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_settings, "audit_prompt_count", 1)
    async with session_factory() as session:
        workspace_id, project_id, prompt_set_id, engines = await _seed_funded_workspace(
            session, prompt_count=2
        )

    # 2 selected active prompts > configured 1: funded and trial both stop.
    for trigger, credential_mode in (
        (AUDIT_TRIGGER_MANUAL, CREDENTIAL_MODE_FUNDED),
        (AUDIT_TRIGGER_TRIAL, CREDENTIAL_MODE_BYOK),
    ):
        async with session_factory() as session:
            with pytest.raises(PromptCountPolicyError) as exc_info:
                await create_audit(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    engines=engines,
                    trigger=trigger,
                    credential_mode=credential_mode,
                    prompt_set_id=prompt_set_id,
                    repetitions=1,
                )
            assert exc_info.value.code == CODE_PROMPT_COUNT_EXCEEDED
            assert exc_info.value.details == {"selected": 2, "limit": 1}
            await session.rollback()

    # At or under the configured count the funded run is admitted.
    monkeypatch.setattr(audit_settings, "audit_prompt_count", 2)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            engines=engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            credential_mode=CREDENTIAL_MODE_FUNDED,
            prompt_set_id=prompt_set_id,
            repetitions=1,
        )
        assert audit.id is not None
