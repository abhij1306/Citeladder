"""Component coverage for the generation-receipt binding exemption.

A measurement prompt is brand-NEUTRAL by design: the same text is run for the
brand AND its competitors to compare who gets mentioned, so a prompt naming the
brand measures nothing. Correct prompts therefore share only CATEGORY wording
with the project, and topical binding (word-overlap against the project's
vocabulary) cannot judge them — a legitimate synonym shares no literal token.

So prompts the backend itself generated from verified website evidence are
exempt from binding. The exemption is proof-gated by an HMAC receipt, never by
the client's word, and free text is still gated exactly as before.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.domain.prompts.receipts import issue_prompt_receipt

# Real generated output for a brand whose category wording legitimately differs
# from its stored vocabulary (an abbreviation, and a synonym).
GENERATED = [
    (
        "Can you recommend agencies that offer experimentation and optimization "
        "services for digital marketing?",
        "digital_marketing_solutions",
    ),
    (
        "How can I create large-scale BI dashboards that provide real-time "
        "insights for my business?",
        "business_intelligence_and_analytics",
    ),
]

OFF_DOMAIN = "What are the best hiking boots for alpine trekking in winter?"


async def _project_and_set(
    client: httpx.AsyncClient, email: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    resp = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    assert resp.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200
    project = (
        await client.post(
            "/api/v1/projects",
            json={
                "name": "Cube27 visibility",
                "brand_name": "Cube27",
                "website_url": "https://www.cube27.com",
                "country_code": "IN",
                "language_code": "en",
            },
        )
    ).json()
    prompt_set = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Starting prompts"},
        )
    ).json()
    return (
        uuid.UUID(project["workspace_id"]),
        uuid.UUID(project["id"]),
        uuid.UUID(prompt_set["id"]),
    )


def _receipt(
    scope: tuple[uuid.UUID, uuid.UUID, uuid.UUID], text: str, cohort: str = "core"
) -> str:
    workspace_id, project_id, prompt_set_id = scope
    return issue_prompt_receipt(
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        cohort=cohort,
        text=text,
    )


@pytest.mark.asyncio
async def test_generated_prompts_bypass_binding_with_a_valid_receipt(
    client: httpx.AsyncClient,
) -> None:
    scope = await _project_and_set(client, "receipt-ok@example.com")
    set_id = scope[2]

    for text, theme in GENERATED:
        resp = await client.post(
            f"/api/v1/prompt-sets/{set_id}/prompts",
            json={
                "text": text,
                "theme": theme,
                "intent": "discovery",
                "cohort": "core",
                "enabled": True,
                "origin": "generated",
                "generation_receipt": _receipt(scope, text),
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["origin"] == "generated"


@pytest.mark.asyncio
async def test_forged_receipt_cannot_bypass_binding(
    client: httpx.AsyncClient,
) -> None:
    """The exemption is proof-gated: claiming ``generated`` is not enough."""
    set_id = (await _project_and_set(client, "receipt-forged@example.com"))[2]

    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/prompts",
        json={
            "text": OFF_DOMAIN,
            "theme": "",
            "intent": "discovery",
            "cohort": "core",
            "enabled": True,
            "origin": "generated",
            "generation_receipt": "deadbeef" * 8,
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "prompt_off_topic"


@pytest.mark.asyncio
async def test_receipt_does_not_transfer_to_different_text(
    client: httpx.AsyncClient,
) -> None:
    """A real receipt for one prompt cannot launder a different one."""
    scope = await _project_and_set(client, "receipt-swap@example.com")
    set_id = scope[2]

    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/prompts",
        json={
            "text": OFF_DOMAIN,
            "theme": "",
            "intent": "discovery",
            "cohort": "core",
            "enabled": True,
            "origin": "generated",
            # Valid receipt, but issued for a DIFFERENT prompt.
            "generation_receipt": _receipt(scope, GENERATED[0][0]),
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "prompt_off_topic"


@pytest.mark.asyncio
async def test_client_theme_cannot_widen_the_binding_vocabulary(
    client: httpx.AsyncClient,
) -> None:
    """``theme`` is free text from the request body, not project identity.

    Binding against it would let any caller echo their own prompt's wording
    back as the "category" and pass the gate unconditionally. Only a PERSISTED
    topic of the prompt's own project may widen the vocabulary.
    """
    set_id = (await _project_and_set(client, "receipt-theme@example.com"))[2]

    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/prompts",
        json={
            "text": OFF_DOMAIN,
            # Every significant token of the off-domain prompt.
            "theme": "hiking boots alpine trekking winter",
            "intent": "discovery",
            "cohort": "core",
            "enabled": True,
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "prompt_off_topic"


@pytest.mark.asyncio
async def test_manual_free_text_is_still_gated(client: httpx.AsyncClient) -> None:
    """The protection the gate was built for is unchanged."""
    set_id = (await _project_and_set(client, "receipt-manual@example.com"))[2]

    resp = await client.post(
        f"/api/v1/prompt-sets/{set_id}/prompts",
        json={
            "text": OFF_DOMAIN,
            "theme": "",
            "intent": "discovery",
            "cohort": "core",
            "enabled": True,
        },
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "prompt_off_topic"
