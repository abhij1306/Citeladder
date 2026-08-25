"""Component tests for topic-bound AI prompt generation and review lifecycle.

The default agent is always faked at the API boundary
(``app.api.prompts.create_model_gateway``) so no test ever performs live
provider I/O, regardless of what keys exist in the developer's ``.env``.

Covers:
  - generate happy path: prompts reference existing canonical topics and retain
    provenance evidence (invariant 4);
  - automatic generation without a third decision gate + count cap (422);
  - unconfigured agent -> 503, but foreign set -> 404 first (invariant 5);
  - unparseable model output -> 502;
  - DB-level duplicate dropping across repeat runs (conflict-safe dedupe);
  - topics CRUD with per-status counts + duplicate-name 409;
  - bulk status review transitions + duplicate prompt text 409;
  - the audit planner never consumes ``proposed``/``archived`` prompts.
"""

from __future__ import annotations

import json
import uuid
from typing import cast

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.prompts as prompts_api
from app.connectors.agent.client import AgentNotConfiguredError, DefaultAgentClient
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.audits import AUDIT_TRIGGER_MANUAL
from app.core.config.entitlements import KEY_PROMPT_SLOTS
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import AuditValidationError
from app.domain.audits.reads import list_tasks
from app.domain.entitlements.types import GrantSpec
from app.models.prompt import Prompt
from tests.component.audit_helpers import seed_audit_fixtures
from tests.component.auth_helpers import register_and_login as _register
from tests.component.occupancy_helpers import seed_occupancy_grants

VALID_AGENT_RESPONSE = json.dumps(
    {
        "topics": [
            {
                "name": "Running Shoes",
                "prompts": [
                    {"text": "best running shoes in australia", "intent": "discovery"},
                    {
                        "text": (
                            "affordable running shoes for budget conscious families"
                        ),
                        "intent": "purchase",
                    },
                ],
            },
            {
                "name": "Running Shoes",
                "prompts": [
                    {
                        "text": "how to choose the right running shoe size",
                        "intent": "service",
                    },
                ],
            },
        ]
    }
)


class FakeAgent:
    """Stands in for DefaultAgentClient; records calls, returns a canned body."""

    model = "fake-model"
    base_url_host = "agent.test"

    def __init__(self, response: str = VALID_AGENT_RESPONSE) -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []
        self.schemas: list[tuple[str, dict[str, object]]] = []

    async def complete_json(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self._response_for(user)

    async def complete_structured_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, object],
    ) -> str:
        self.calls.append({"system": system, "user": user})
        self.schemas.append((schema_name, schema))
        return self._response_for(user)

    def _response_for(self, user: str) -> str:
        try:
            payload = json.loads(self.response)
        except json.JSONDecodeError:
            return self.response
        if "prompts" in payload:
            return self.response

        marker = "Canonical topics (copy one id exactly for every prompt): "
        topic_line = next(line for line in user.splitlines() if line.startswith(marker))
        canonical = json.loads(topic_line.removeprefix(marker))
        by_name = {str(topic["name"]).casefold(): topic for topic in canonical}
        flattened = []
        for suggested_topic in payload.get("topics", []):
            topic = by_name.get(str(suggested_topic.get("name", "")).casefold())
            topic = topic or canonical[0]
            flattened.extend(
                {"topic_id": topic["id"], **prompt}
                for prompt in suggested_topic.get("prompts", [])
            )
        return json.dumps({"prompts": flattened})


@pytest.fixture
def fake_agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    agent = FakeAgent()
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)
    return agent


def _project_payload(**overrides: object) -> dict:
    payload = {
        "name": "Acme Visibility",
        "brand_name": "Acme Corp",
        "brand": {"aliases": ["Acme", "ACME Inc"]},
        "website_url": "https://acme.com",
        "owned_domains": ["acme.com"],
        "unintended_domains": [],
        "competitors": [
            {"name": "Globex", "aliases": ["Globex Co"], "domains": ["globex.com"]}
        ],
        "country_code": "AU",
        "language_code": "en-AU",
        "benchmark_mode": "controlled_localized",
        "default_repetitions": 3,
    }
    payload.update(overrides)
    return payload


async def _make_project_and_set(
    client: httpx.AsyncClient, email: str, *, create_default_topic: bool = True
) -> tuple[dict, str]:
    await _register(client, email)
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Default"},
        )
    ).json()["id"]
    # Category identity for topical binding: unbranded generated/manual texts
    # bind through the products_services vocabulary (a partial upsert, so
    # later per-test brand-profile PUTs keep it).
    profile = await client.put(
        f"/api/v1/projects/{project['id']}/brand-profile",
        json={"products_services": ["running shoes"]},
    )
    assert profile.status_code == 200
    if create_default_topic:
        topic = await client.post(
            f"/api/v1/projects/{project['id']}/topics",
            json={"name": "Running Shoes"},
        )
        assert topic.status_code == 201
    return project, prompt_set_id


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_generate_creates_prompts_under_existing_topic(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    project, prompt_set_id = await _make_project_and_set(client, "gen1@example.com")
    profile = await client.put(
        f"/api/v1/projects/{project['id']}/brand-profile",
        json={
            "positioning": "Value-priced family footwear.",
            "target_audience": "Budget-conscious Australian families.",
        },
    )
    assert profile.status_code == 200

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    body = resp.json()

    assert body["dropped_duplicates"] == 0
    assert len(body["generated"]) == 3
    by_status = {p["text"]: p["status"] for p in body["generated"]}
    # Fresh core set, 3 < the 20-active pool -> all unbranded prompts activate.
    assert by_status["best running shoes in australia"] == "active"
    assert by_status["how to choose the right running shoe size"] == "active"
    assert (
        by_status["affordable running shoes for budget conscious families"] == "active"
    )
    for prompt in body["generated"]:
        assert prompt["origin"] == "generated"
        assert prompt["topic_id"] is not None
    assert {t["name"] for t in body["topics"]} == {"Running Shoes"}
    running_shoes = body["topics"][0]
    assert running_shoes["origin"] == "manual"
    assert running_shoes["active_count"] == 3
    assert running_shoes["proposed_count"] == 0

    # The brand evidence went to the agent (confirmed above), and the
    # request embedded identity + count instructions.
    assert len(fake_agent.calls) == 1
    assert fake_agent.schemas[0][0] == "prompt_generation"
    assert fake_agent.schemas[0][1]["additionalProperties"] is False
    sent = fake_agent.calls[0]["user"]
    assert "Acme Corp" in sent
    assert "Globex" in sent
    assert "Value-priced family footwear" in sent
    assert "exactly 3 prompts" in sent
    assert "Canonical topics" in sent
    assert '["running shoes"]' in sent

    # Provenance evidence is persisted but the API response never includes
    # any credential material — only host + model identity.
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert len(listed["prompts"]) == 3
    # Core generation excludes tracked and competitor names.
    branded = {p["text"]: p["branded"] for p in listed["prompts"]}
    assert branded["affordable running shoes for budget conscious families"] is False
    assert branded["how to choose the right running shoe size"] is False


@pytest.mark.asyncio
async def test_generate_persists_provenance_evidence(
    client: httpx.AsyncClient,
    fake_agent: FakeAgent,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen2@example.com")
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201

    async with session_factory() as session:
        prompts = (
            (
                await session.execute(
                    select(Prompt).where(
                        Prompt.prompt_set_id == uuid.UUID(prompt_set_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(prompts) == 3
    run_ids = set()
    for prompt in prompts:
        evidence = prompt.generation_evidence
        assert evidence is not None
        assert evidence["generator_version"] == "prompt-gen-v15"
        assert evidence["generation_mode"] == "model"
        assert evidence["model_identity"] == {
            "transport_host": "agent.test",
            "transport_model": "fake-model",
        }
        assert evidence["requested_count"] == 3
        run_ids.add(evidence["generation_run_id"])
    assert len(run_ids) == 1  # one run id for the whole batch


@pytest.mark.asyncio
async def test_commerce_generation_is_catalog_derived_without_an_agent(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "gen-commerce-script@example.com", create_default_topic=False
    )
    topic_response = await client.post(
        f"/api/v1/projects/{project['id']}/topics",
        json={"name": "Headphones"},
    )
    assert topic_response.status_code == 201
    topic_id = topic_response.json()["id"]
    for sku, name in (
        ("BOSE-QCU", "Bose QuietComfort Ultra"),
        ("SONY-XM6", "Sony WH-1000XM6"),
    ):
        product_response = await client.post(
            f"/api/v1/projects/{project['id']}/products",
            json={
                "sku": sku,
                "name": name,
                "price": 299.0,
                "currency": "USD",
                "url": f"https://shop.example/products/{sku.casefold()}",
                "attributes": {"category": "Headphones"},
            },
        )
        assert product_response.status_code == 201

    def _unexpected_agent() -> DefaultAgentClient:
        raise AssertionError("Commerce generation must not configure an agent")

    async def _unexpected_rate_limit(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Commerce generation must not consume provider quota")

    monkeypatch.setattr(prompts_api, "create_model_gateway", _unexpected_agent)
    monkeypatch.setattr(
        prompts_api, "enforce_workspace_request", _unexpected_rate_limit
    )

    response = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={
            "count": 2,
            "topic_id": topic_id,
            "intents": ["discovery", "comparison"],
            "cohort": "commerce",
        },
    )

    assert response.status_code == 201
    generated = response.json()["generated"]
    assert [(row["text"], row["intent"]) for row in generated] == [
        (
            "Which headphones should I buy for the best overall value?",
            "discovery",
        ),
        (
            "Which headphones should I buy: Bose QuietComfort Ultra or "
            "Sony WH-1000XM6?",
            "comparison",
        ),
    ]

    async with session_factory() as session:
        prompts = (
            (
                await session.execute(
                    select(Prompt).where(
                        Prompt.prompt_set_id == uuid.UUID(prompt_set_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {prompt.generation_evidence["generation_mode"] for prompt in prompts} == {
        "deterministic"
    }
    assert all(
        prompt.generation_evidence["model_identity"] is None for prompt in prompts
    )


@pytest.mark.asyncio
async def test_generate_rejects_count_over_cap(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen4@example.com")
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 9999, "confirm_send_evidence": True},
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "generation_invalid"
    assert fake_agent.calls == []


@pytest.mark.asyncio
async def test_generate_requires_an_existing_topic(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "gen-products@example.com", create_default_topic=False
    )

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "generation_invalid"
    assert "at least one topic" in resp.json()["detail"]["message"]
    assert fake_agent.calls == []


@pytest.mark.asyncio
async def test_generate_rejects_foreign_topic_id(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen5@example.com")
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={
            "count": 3,
            "confirm_send_evidence": True,
            "topic_id": str(uuid.uuid4()),
        },
    )
    assert resp.status_code == 422
    assert fake_agent.calls == []


@pytest.mark.asyncio
async def test_generate_unconfigured_agent_returns_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen6@example.com")

    def _unconfigured() -> None:
        raise AgentNotConfiguredError("no key")

    monkeypatch.setattr(prompts_api, "create_model_gateway", _unconfigured)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail["code"] == "agent_not_configured"
    assert "configured provider's API key" in detail["message"]


@pytest.mark.asyncio
async def test_generate_reports_upstream_rate_limits_as_retryable(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen-rate-limit@example.com")

    class RateLimitedAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        async def complete_structured_json(
            self,
            *,
            system: str,
            user: str,
            schema_name: str,
            schema: dict[str, object],
        ) -> str:
            raise ProviderError(
                "Default agent returned HTTP 429",
                error_code="rate_limit",
                retryable=True,
                retry_after_seconds=4,
            )

    monkeypatch.setattr(prompts_api, "create_model_gateway", RateLimitedAgent)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )

    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "4"
    assert resp.json()["detail"] == {
        "code": "rate_limited",
        "message": "The AI provider is rate limited. Please try again shortly.",
    }


@pytest.mark.asyncio
async def test_generate_foreign_set_is_404_even_when_unconfigured(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scope check wins over configuration state (no existence oracle)."""
    _, prompt_set_id = await _make_project_and_set(client, "gen7a@example.com")
    client.cookies.clear()
    await _register(client, "gen7b@example.com")

    def _unconfigured() -> None:
        raise AgentNotConfiguredError("no key")

    monkeypatch.setattr(prompts_api, "create_model_gateway", _unconfigured)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_generate_unparseable_output_returns_502(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "gen8@example.com")
    agent = FakeAgent(response="this is not json")
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "generation_unparseable"


@pytest.mark.asyncio
async def test_generate_twice_drops_duplicates(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    """Same model output twice: run 2 inserts nothing, reports drops."""
    _, prompt_set_id = await _make_project_and_set(client, "gen9@example.com")

    first = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert first.status_code == 201
    assert len(first.json()["generated"]) == 3

    second = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert second.status_code == 201
    assert second.json()["generated"] == []
    assert second.json()["dropped_duplicates"] == 3

    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert len(listed["prompts"]) == 3  # no dupes, and no reused topics broke


@pytest.mark.asyncio
async def test_generate_into_target_topic(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, prompt_set_id = await _make_project_and_set(client, "gen10@example.com")
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics",
            json={"name": "Pricing"},
        )
    ).json()

    # The fake converts its fixture to the only canonical topic ID supplied to
    # a scoped generation call.
    agent = FakeAgent(
        response=json.dumps(
            {
                "topics": [
                    {
                        "name": "Whatever The Model Said",
                        "prompts": [
                            {
                                "text": "how much do running shoe plans cost",
                                "intent": "purchase",
                            }
                        ],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={
            "count": 1,
            "confirm_send_evidence": True,
            "topic_id": topic["id"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert [t["id"] for t in body["topics"]] == [topic["id"]]
    assert body["generated"][0]["topic_id"] == topic["id"]
    assert '"name":"Pricing"' in agent.calls[0]["user"]

    # No new topic was created from the model's invented name.
    topics = (await client.get(f"/api/v1/projects/{project['id']}/topics")).json()
    assert {t["name"] for t in topics} == {"Pricing", "Running Shoes"}


@pytest.mark.asyncio
async def test_generation_reuses_existing_topic_with_description(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "gen-topic-description@example.com"
    )
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics",
            json={
                "name": "Footwear",
                "description": "Running and everyday shoes for families.",
            },
        )
    ).json()
    agent = FakeAgent(
        response=json.dumps(
            {
                "topics": [
                    {
                        "name": "Footwear",
                        "prompts": [
                            {"text": "best family running shoes", "intent": "discovery"}
                        ],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)

    response = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 1, "confirm_send_evidence": True},
    )

    assert response.status_code == 201
    body = response.json()
    assert [item["id"] for item in body["topics"]] == [topic["id"]]
    assert body["generated"][0]["topic_id"] == topic["id"]
    assert '"name":"Footwear"' in agent.calls[0]["user"]
    assert (
        '"description":"Running and everyday shoes for families."'
        in agent.calls[0]["user"]
    )
    topics = (await client.get(f"/api/v1/projects/{project['id']}/topics")).json()
    assert {item["name"] for item in topics} == {"Footwear", "Running Shoes"}


def _agent_response_with_n_prompts(
    n: int, *, topic: str = "Running Shoes", discriminator: str = ""
) -> str:
    """A single-topic response carrying ``n`` distinct prompts.

    Texts embed the topic so responses from different runs never collide on
    the per-set dedupe hash (letting a test insert fresh rows each run), and
    each opens with a different token: generation caps how many prompts may
    share their first three words, so a stub that repeats one opening is
    rejected as templated rather than accepted as a batch.
    """
    text_prefix = discriminator or topic
    return json.dumps(
        {
            "topics": [
                {
                    "name": topic,
                    "prompts": [
                        {
                            "text": (
                                f"{chr(97 + i) * 20} {text_prefix} running "
                                "shoes for buyers"
                            ),
                            "intent": "discovery",
                        }
                        for i in range(n)
                    ],
                }
            ]
        }
    )


@pytest.mark.asyncio
async def test_generate_activates_validated_requested_count(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The requested, validated portfolio becomes active without measuring it."""
    _, prompt_set_id = await _make_project_and_set(client, "pool1@example.com")
    agent = FakeAgent(response=_agent_response_with_n_prompts(25))
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 20, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Model returned 25 but only 20 were requested -> output trimmed to 20.
    assert len(body["generated"]) == 20
    statuses = [p["status"] for p in body["generated"]]
    assert statuses == ["active"] * 20


@pytest.mark.asyncio
async def test_generate_comparison_cohort_is_active_and_branded(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validated comparison prompts retain their cohort signal and are active."""
    _, prompt_set_id = await _make_project_and_set(client, "brandcap@example.com")
    # Ten existing core prompts plus ten named comparisons settle at 12 active:
    # 10 core + 2 comparison, because int(12 * 0.2) == 2.
    for i in range(10):
        created = await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": f"best Acme running shoes for terrain {i}"},
        )
        assert created.status_code == 201
    comparison_prompts = [
        {"text": text, "intent": "comparison"}
        for text in (
            "Acme Corp or Globex for wet trail running",
            "Should I choose Globex over Acme Corp for marathon shoes",
            "Compare Acme Corp and Globex shoes for flat feet",
            "Is Globex better than Acme Corp for school trainers",
            "Acme Corp versus Globex when buying wide running shoes",
            "Would Globex or Acme Corp suit daily walking",
            "How do Acme Corp and Globex compare on hiking footwear",
            "Which lasts longer, Acme Corp or Globex running shoes",
            "For gym training, is Acme Corp better than Globex",
            "Between Globex and Acme Corp, who makes lighter shoes",
        )
    ]
    agent = FakeAgent(
        response=json.dumps(
            {"topics": [{"name": "Running Shoes", "prompts": comparison_prompts}]}
        )
    )
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 10, "cohort": "comparison", "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["generated"]) == 10

    active_branded = [
        p for p in body["generated"] if p["branded"] and p["status"] == "active"
    ]
    assert len(active_branded) == 10


@pytest.mark.asyncio
async def test_generate_brand_diagnostic_uses_named_cohort_rules(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "diagnostic@example.com")
    agent = FakeAgent(
        response=json.dumps(
            {
                "topics": [
                    {
                        "name": "Running Shoes",
                        "prompts": [
                            {
                                "text": (
                                    "Is Acme Corp reliable for long distance "
                                    "running shoes"
                                ),
                                "intent": "discovery",
                            }
                        ],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)

    response = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={
            "count": 1,
            "cohort": "brand_diagnostic",
            "confirm_send_evidence": True,
        },
    )

    assert response.status_code == 201
    assert [item["cohort"] for item in response.json()["generated"]] == [
        "brand_diagnostic"
    ]
    assert "Every prompt must name the tracked brand" in agent.calls[0]["system"]


@pytest.mark.asyncio
async def test_generate_counts_intra_response_duplicates(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Duplicate texts within one model response are counted as dropped."""
    _, prompt_set_id = await _make_project_and_set(client, "dup1@example.com")
    agent = FakeAgent(
        response=json.dumps(
            {
                "topics": [
                    {
                        "name": "Running Shoes",
                        "prompts": [
                            {
                                "text": "Best running shoes for flat feet?",
                                "intent": "discovery",
                            },
                            {
                                "text": "best  running shoes for flat feet",
                                "intent": "discovery",
                            },
                            {
                                "text": "hiking shoes for wet weather trails",
                                "intent": "discovery",
                            },
                        ],
                    }
                ]
            }
        )
    )
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 5, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["generated"]) == 2  # the collapsed duplicate is gone
    # The bounded replacement call receives the same fake response: one
    # duplicate is collapsed in each model batch, then its two surviving
    # rows duplicate the first batch at persistence time.
    assert body["dropped_duplicates"] == 4


@pytest.mark.asyncio
async def test_generate_bounds_existing_prompt_context(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The existing-prompt list sent to the model is capped by config."""
    from app.core.config.prompts import prompt_generation_settings

    _, prompt_set_id = await _make_project_and_set(client, "ctx1@example.com")
    monkeypatch.setattr(prompt_generation_settings, "existing_prompt_context_limit", 3)
    for i in range(6):
        created = await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": f"existing acme context prompt {i}"},
        )
        assert created.status_code == 201

    agent = FakeAgent(response=_agent_response_with_n_prompts(2, topic="New"))
    monkeypatch.setattr(prompts_api, "create_model_gateway", lambda: agent)
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 2, "confirm_send_evidence": True},
    )
    assert resp.status_code == 201
    sent = agent.calls[0]["user"]
    # Only the most recent 3 existing prompts appear in the "do NOT duplicate"
    # block: the context is the tail of the set, so 3, 4 and 5 are sent and the
    # older 0, 1 and 2 are left out.
    included = [i for i in range(6) if f"existing acme context prompt {i}" in sent]
    assert included == [3, 4, 5]


@pytest.mark.asyncio
async def test_concurrent_generation_keeps_all_validated_rows_active(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Concurrent generation preserves both active portfolios without duplicates."""
    import asyncio

    from app.domain.prompts.generation import generate_prompts
    from app.domain.prompts.schemas import PromptGenerateRequest

    project, prompt_set_id = await _make_project_and_set(client, "conc1@example.com")

    # Resolve the workspace id from the project's owning workspace.
    from app.models.project import Project

    async with session_factory() as session:
        proj = await session.get(Project, uuid.UUID(project["id"]))
        assert proj is not None
        workspace_id = proj.workspace_id

    class _CountingAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        def __init__(self, discriminator: str, n: int) -> None:
            self._response = _agent_response_with_n_prompts(
                n, discriminator=discriminator
            )

        async def complete_structured_json(
            self,
            *,
            system: str,
            user: str,
            schema_name: str,
            schema: dict[str, object],
        ) -> str:
            # Yield so both coroutines interleave before either persists.
            await asyncio.sleep(0)
            return await FakeAgent(response=self._response).complete_json(
                system=system, user=user
            )

    async def _run(topic: str, n: int) -> None:
        async with session_factory() as session:
            await generate_prompts(
                session,
                workspace_id=workspace_id,
                prompt_set_id=uuid.UUID(prompt_set_id),
                payload=PromptGenerateRequest(count=n, confirm_send_evidence=True),
                agent=cast(DefaultAgentClient, _CountingAgent(topic, n)),
            )

    await asyncio.gather(_run("Alpha", 15), _run("Beta", 15))

    async with session_factory() as session:
        active = (
            (
                await session.execute(
                    select(Prompt).where(
                        Prompt.prompt_set_id == uuid.UUID(prompt_set_id),
                        Prompt.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(active) == 30


@pytest.mark.asyncio
async def test_generation_racing_prompt_set_delete_is_scoped_not_found(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Delete the set mid-generation (provider paused) -> scoped 404, not 500."""
    import asyncio

    from app.domain.prompts.generation import generate_prompts
    from app.domain.prompts.schemas import PromptGenerateRequest
    from app.domain.prompts.service import (
        PromptSetNotFoundError,
        delete_prompt_set,
    )
    from app.models.project import Project

    project, prompt_set_id = await _make_project_and_set(client, "race1@example.com")
    async with session_factory() as session:
        proj = await session.get(Project, uuid.UUID(project["id"]))
        assert proj is not None
        workspace_id = proj.workspace_id

    provider_entered = asyncio.Event()
    delete_done = asyncio.Event()

    class _PausingAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        async def complete_structured_json(
            self,
            *,
            system: str,
            user: str,
            schema_name: str,
            schema: dict[str, object],
        ) -> str:
            # Signal that the read txn is committed, then wait until the set
            # has been deleted before returning (so generation re-resolves a
            # set that no longer exists).
            provider_entered.set()
            await delete_done.wait()
            return await FakeAgent(
                response=_agent_response_with_n_prompts(3, topic="Race")
            ).complete_json(system=system, user=user)

    async def _generate() -> BaseException | None:
        async with session_factory() as session:
            try:
                await generate_prompts(
                    session,
                    workspace_id=workspace_id,
                    prompt_set_id=uuid.UUID(prompt_set_id),
                    payload=PromptGenerateRequest(count=3, confirm_send_evidence=True),
                    agent=cast(DefaultAgentClient, _PausingAgent()),
                )
                return None
            except BaseException as exc:  # noqa: BLE001
                return exc

    async def _delete() -> None:
        await provider_entered.wait()
        async with session_factory() as session:
            await delete_prompt_set(
                session,
                workspace_id=workspace_id,
                prompt_set_id=uuid.UUID(prompt_set_id),
            )
        delete_done.set()

    gen_result, _ = await asyncio.gather(_generate(), _delete())
    # Disappearance surfaces as the scoped domain error the endpoint maps to
    # 404 — never an unhandled FK 500.
    assert isinstance(gen_result, PromptSetNotFoundError)


@pytest.mark.asyncio
async def test_generation_racing_topic_delete_is_scoped_validation_error(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Delete the target topic mid-generation (paused) -> scoped 422, not 500."""
    import asyncio

    from app.domain.prompts.generation import (
        GenerationValidationError,
        generate_prompts,
    )
    from app.domain.prompts.schemas import PromptGenerateRequest
    from app.domain.prompts.topics import delete_topic
    from app.models.project import Project

    project, prompt_set_id = await _make_project_and_set(client, "race2@example.com")
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics", json={"name": "Doomed"}
        )
    ).json()
    async with session_factory() as session:
        proj = await session.get(Project, uuid.UUID(project["id"]))
        assert proj is not None
        workspace_id = proj.workspace_id

    provider_entered = asyncio.Event()
    delete_done = asyncio.Event()

    class _PausingAgent:
        model = "fake-model"
        base_url_host = "agent.test"

        async def complete_structured_json(
            self,
            *,
            system: str,
            user: str,
            schema_name: str,
            schema: dict[str, object],
        ) -> str:
            provider_entered.set()
            await delete_done.wait()
            return await FakeAgent(
                response=_agent_response_with_n_prompts(2, topic="Whatever")
            ).complete_json(system=system, user=user)

    async def _generate() -> BaseException | None:
        async with session_factory() as session:
            try:
                await generate_prompts(
                    session,
                    workspace_id=workspace_id,
                    prompt_set_id=uuid.UUID(prompt_set_id),
                    payload=PromptGenerateRequest(
                        count=2,
                        confirm_send_evidence=True,
                        topic_id=uuid.UUID(topic["id"]),
                    ),
                    agent=cast(DefaultAgentClient, _PausingAgent()),
                )
                return None
            except BaseException as exc:  # noqa: BLE001
                return exc

    async def _delete() -> None:
        await provider_entered.wait()
        async with session_factory() as session:
            await delete_topic(
                session,
                workspace_id=workspace_id,
                topic_id=uuid.UUID(topic["id"]),
            )
        delete_done.set()

    gen_result, _ = await asyncio.gather(_generate(), _delete())
    # Target topic gone -> scoped validation error the endpoint maps to 422.
    assert isinstance(gen_result, GenerationValidationError)
    # No prompts were persisted into the vanished topic.
    async with session_factory() as session:
        remaining = (
            (
                await session.execute(
                    select(Prompt).where(
                        Prompt.prompt_set_id == uuid.UUID(prompt_set_id)
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == []


@pytest.mark.asyncio
async def test_generation_unrelated_integrity_error_is_not_remapped(
    client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An IntegrityError unrelated to a lost set/topic FK must NOT be masked.

    When the referenced set and (unscoped) topics are all still present, an
    insert-time integrity error is a genuine constraint bug, so it must
    re-raise as ``IntegrityError`` — never a phantom ``PromptSetNotFoundError``
    (404) or ``GenerationValidationError`` (422).
    """
    from sqlalchemy.exc import IntegrityError

    import app.domain.prompts.generation as generation
    from app.domain.prompts.generation import generate_prompts
    from app.domain.prompts.schemas import PromptGenerateRequest
    from app.models.project import Project

    project, prompt_set_id = await _make_project_and_set(client, "unrel1@example.com")
    async with session_factory() as session:
        proj = await session.get(Project, uuid.UUID(project["id"]))
        assert proj is not None
        workspace_id = proj.workspace_id

    async def _boom(*args: object, **kwargs: object) -> object:
        raise IntegrityError("boom", params=None, orig=Exception("unrelated"))

    monkeypatch.setattr(generation, "_insert_prompts_returning", _boom)

    with pytest.raises(IntegrityError):
        async with session_factory() as session:
            await generate_prompts(
                session,
                workspace_id=workspace_id,
                prompt_set_id=uuid.UUID(prompt_set_id),
                payload=PromptGenerateRequest(count=2, confirm_send_evidence=True),
                agent=cast(
                    DefaultAgentClient,
                    FakeAgent(response=_agent_response_with_n_prompts(2)),
                ),
            )


# --------------------------------------------------------------------------
# Topics CRUD
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_prompt_accepts_topic_id(client: httpx.AsyncClient) -> None:
    """Onboarding creates topics first, then files prompts under them directly.

    Without ``topic_id`` on create it would have to POST every prompt and then
    PATCH every prompt, doubling the write count on a first-run flow.
    """
    project, prompt_set_id = await _make_project_and_set(
        client, "ptopic1@example.com", create_default_topic=False
    )
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics", json={"name": "Everyday basics"}
        )
    ).json()

    created = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "best basics for kids", "topic_id": topic["id"]},
    )

    assert created.status_code == 201
    assert created.json()["topic_id"] == topic["id"]
    # And it counts toward the topic straight away.
    listing = (await client.get(f"/api/v1/projects/{project['id']}/topics")).json()
    assert listing[0]["active_count"] == 1


@pytest.mark.asyncio
async def test_create_prompt_rejects_foreign_topic_id(
    client: httpx.AsyncClient,
) -> None:
    """A topic from another project is a 404, not a cross-scope FK write."""
    project_a, set_a = await _make_project_and_set(client, "ptopic2@example.com")
    other = await client.post(
        "/api/v1/projects",
        json={
            "name": "Other",
            "brand_name": "Other",
            "website_url": "https://other.example",
            "country_code": "US",
            "language_code": "en",
        },
    )
    assert other.status_code == 201
    foreign_topic = (
        await client.post(
            f"/api/v1/projects/{other.json()['id']}/topics", json={"name": "Foreign"}
        )
    ).json()

    resp = await client.post(
        f"/api/v1/prompt-sets/{set_a}/prompts",
        json={"text": "scoped acme prompt", "topic_id": foreign_topic["id"]},
    )

    assert resp.status_code == 404
    assert project_a["id"] != other.json()["id"]


@pytest.mark.asyncio
async def test_topics_crud_with_counts(client: httpx.AsyncClient) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "top1@example.com", create_default_topic=False
    )
    project_id = project["id"]

    created = await client.post(
        f"/api/v1/projects/{project_id}/topics",
        json={"name": "Footwear", "description": "Shoes and boots"},
    )
    assert created.status_code == 201
    topic = created.json()
    assert topic["origin"] == "manual"
    assert topic["active_count"] == 0 and topic["proposed_count"] == 0

    # Duplicate name (same project) -> 409.
    dup = await client.post(
        f"/api/v1/projects/{project_id}/topics", json={"name": "Footwear"}
    )
    assert dup.status_code == 409

    # A prompt assigned to the topic shows up in the counts.
    prompt = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "best hiking boots"},
    )
    assert prompt.status_code == 201
    patched = await client.patch(
        f"/api/v1/prompts/{prompt.json()['id']}",
        json={"topic_id": topic["id"]},
    )
    assert patched.status_code == 200
    assert patched.json()["topic_id"] == topic["id"]

    listing = await client.get(f"/api/v1/projects/{project_id}/topics")
    assert listing.status_code == 200
    assert listing.json()[0]["active_count"] == 1

    renamed = await client.patch(
        f"/api/v1/topics/{topic['id']}", json={"name": "Boots"}
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Boots"

    deleted = await client.delete(f"/api/v1/topics/{topic['id']}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/projects/{project_id}/topics")).json() == []

    # Topic delete detaches (SET NULL), never deletes prompts.
    survivor = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert len(survivor["prompts"]) == 1
    assert survivor["prompts"][0]["topic_id"] is None


@pytest.mark.asyncio
async def test_prompt_topic_assignment_same_project_succeeds(
    client: httpx.AsyncClient,
) -> None:
    """A prompt can be filed under a topic of its own project."""
    project, prompt_set_id = await _make_project_and_set(client, "tscope1@example.com")
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics", json={"name": "Footwear"}
        )
    ).json()
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "best hiking shoes"},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"topic_id": topic["id"]}
    )
    assert resp.status_code == 200
    assert resp.json()["topic_id"] == topic["id"]
    # Detaching (topic_id=null) is always allowed.
    detached = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"topic_id": None}
    )
    assert detached.status_code == 200
    assert detached.json()["topic_id"] is None


@pytest.mark.asyncio
async def test_prompt_topic_assignment_cross_project_rejected(
    client: httpx.AsyncClient,
) -> None:
    """A topic from a sibling project (same workspace) can't be attached."""
    await _register(client, "tscope2@example.com")
    project_a = (
        await client.post("/api/v1/projects", json=_project_payload(name="A"))
    ).json()
    prompt_set_a = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project_a["id"], "name": "SetA"},
        )
    ).json()["id"]
    project_b = (
        await client.post(
            "/api/v1/projects",
            json=_project_payload(
                name="B", brand_name="Beta", website_url="https://beta.example"
            ),
        )
    ).json()
    topic_b = (
        await client.post(
            f"/api/v1/projects/{project_b['id']}/topics", json={"name": "Other"}
        )
    ).json()

    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_a}/prompts",
            json={"text": "cross project acme prompt"},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"topic_id": topic_b["id"]}
    )
    assert resp.status_code == 404
    # The assignment did not persist.
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_a}")).json()
    assert listed["prompts"][0]["topic_id"] is None


@pytest.mark.asyncio
async def test_prompt_topic_assignment_cross_workspace_rejected(
    client: httpx.AsyncClient,
) -> None:
    """A topic from another workspace can't be attached to this prompt."""
    # Workspace 1 owns the topic.
    other_project, _ = await _make_project_and_set(client, "tscope3a@example.com")
    other_topic = (
        await client.post(
            f"/api/v1/projects/{other_project['id']}/topics", json={"name": "Theirs"}
        )
    ).json()

    # Workspace 2 owns the prompt.
    client.cookies.clear()
    _, prompt_set_id = await _make_project_and_set(client, "tscope3b@example.com")
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "my acme prompt"},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"topic_id": other_topic["id"]}
    )
    assert resp.status_code == 404
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert listed["prompts"][0]["topic_id"] is None


@pytest.mark.asyncio
async def test_prompt_topic_assignment_unknown_topic_rejected(
    client: httpx.AsyncClient,
) -> None:
    """A non-existent topic id is rejected (no cross-scope FK 500)."""
    _, prompt_set_id = await _make_project_and_set(client, "tscope4@example.com")
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "orphan acme prompt"},
        )
    ).json()
    resp = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"topic_id": str(uuid.uuid4())}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_topics_are_workspace_scoped(client: httpx.AsyncClient) -> None:
    project, _ = await _make_project_and_set(client, "top2a@example.com")
    topic = (
        await client.post(
            f"/api/v1/projects/{project['id']}/topics", json={"name": "Mine"}
        )
    ).json()

    client.cookies.clear()
    await _register(client, "top2b@example.com")
    assert (
        await client.get(f"/api/v1/projects/{project['id']}/topics")
    ).status_code == 404
    assert (
        await client.patch(f"/api/v1/topics/{topic['id']}", json={"name": "X"})
    ).status_code == 404
    assert (await client.delete(f"/api/v1/topics/{topic['id']}")).status_code == 404


# --------------------------------------------------------------------------
# Review lifecycle: status edits, bulk transitions, duplicate guard
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_prompt_status_update_and_duplicate_409(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "rev1@example.com")
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "best value shoes"},
        )
    ).json()
    assert prompt["status"] == "active"

    archived = await client.patch(
        f"/api/v1/prompts/{prompt['id']}", json={"status": "archived"}
    )
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"

    # Same concept ("Best value shoes?" normalizes identically) -> 409.
    dup = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "Best  value shoes?"},
    )
    assert dup.status_code == 409


@pytest.mark.asyncio
async def test_bulk_status_accepts_proposed_prompts(
    client: httpx.AsyncClient, fake_agent: FakeAgent
) -> None:
    _, prompt_set_id = await _make_project_and_set(client, "rev2@example.com")
    generated = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/generate",
            json={"count": 3, "confirm_send_evidence": True},
        )
    ).json()["generated"]
    ids = [p["id"] for p in generated]

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts/bulk-status",
        json={"prompt_ids": ids, "status": "active"},
    )
    assert resp.status_code == 200
    assert {p["status"] for p in resp.json()["prompts"]} == {"active"}


@pytest.mark.asyncio
async def test_bulk_status_rejects_foreign_prompt_ids(
    client: httpx.AsyncClient,
) -> None:
    """One bad id rejects the whole batch — no partial transitions."""
    _, prompt_set_id = await _make_project_and_set(client, "rev3@example.com")
    prompt = (
        await client.post(
            f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
            json={"text": "real acme prompt"},
        )
    ).json()

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts/bulk-status",
        json={"prompt_ids": [prompt["id"], str(uuid.uuid4())], "status": "archived"},
    )
    assert resp.status_code == 404
    # The valid prompt was not transitioned.
    listed = (await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")).json()
    assert listed["prompts"][0]["status"] == "active"


# --------------------------------------------------------------------------
# Audits only consume active prompts (no auto-run of AI suggestions)
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_planner_excludes_proposed_and_archived_prompts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=3)
        for prompt_id, status in zip(
            seed.prompt_ids[:2], ("proposed", "archived"), strict=True
        ):
            prompt = await session.get(Prompt, prompt_id)
            assert prompt is not None
            prompt.status = status
        await session.commit()

    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        # Only the one still-active prompt produced a slot.
        assert len(tasks) == 1

    # Explicitly requesting a proposed prompt is a validation error.
    async with session_factory() as session:
        with pytest.raises(AuditValidationError):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                prompt_ids=[seed.prompt_ids[0]],
                repetitions=1,
            )


# =========================================================================
# Account occupancy enforcement (slice23 Task 4): the route maps the
# domain denial to the coded 403; the quota check lives in the service.
# =========================================================================
@pytest.mark.asyncio
async def test_generate_over_occupancy_returns_coded_403(
    client: httpx.AsyncClient,
    fake_agent: FakeAgent,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "occ-gen-403@example.com"
    )
    # A zero-slot grant provisions the capability with no headroom: every
    # generated row that could actually insert is over the allowance.
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=uuid.UUID(project["workspace_id"]),
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=0),),
        )
        await session.commit()

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/generate",
        json={"count": 3, "confirm_send_evidence": True},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "occupancy_limit_exceeded"
    assert body["error"]["retryable"] is False
    assert body["error"]["details"]["key"] == "prompt_slots"
    assert body["detail"]["code"] == "occupancy_limit_exceeded"

    # The denial is atomic: nothing persisted from the rejected generation.
    got = await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")
    assert got.json()["prompts"] == []


@pytest.mark.asyncio
async def test_import_over_occupancy_returns_coded_403(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project, prompt_set_id = await _make_project_and_set(
        client, "occ-import-403@example.com"
    )
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=uuid.UUID(project["workspace_id"]),
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=2),),
        )
        await session.commit()

    # 3 distinct rows against an allowance of 2: the whole import is denied
    # atomically (duplicates would be filtered before charging; there are
    # none here).
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        json={
            "prompts": [
                {"text": "first acme import"},
                {"text": "second acme import"},
                {"text": "third acme import"},
            ]
        },
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "occupancy_limit_exceeded"
    assert body["error"]["details"] == {
        "key": "prompt_slots",
        "allowance": 2,
        "current": 0,
        "requested": 3,
    }
    got = await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")
    assert got.json()["prompts"] == []


@pytest.mark.asyncio
async def test_import_validation_does_not_echo_parser_details(
    client: httpx.AsyncClient,
) -> None:
    _, prompt_set_id = await _make_project_and_set(
        client, "import-safe-validation@example.com"
    )

    response = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        content=b'{"prompts": [',
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Invalid prompt import payload"
