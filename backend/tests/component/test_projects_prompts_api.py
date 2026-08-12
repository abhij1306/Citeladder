"""Component tests for the projects + prompts API (B3, httpx ASGITransport).

Adapted from the reference ``tests/component/test_ai_visibility_api.py`` to
CiteLadder's UUID + workspace-scoped model. Covers the B3 acceptance:
  - project CRUD persists normalized brand identity + prompts, workspace-scoped;
  - prompt-intent + benchmark_mode validation;
  - CSV bulk-import persists prompts as ``imported``;
  - cross-workspace access is denied (reuses the B2 isolation pattern).

The ``/generate`` endpoint is covered in ``test_prompt_generation_api.py``.
"""

from __future__ import annotations

import hashlib
import io
import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.brand_logos import BRAND_LOGO_STATUS_READY
from app.core.config.entitlements import KEY_PROJECT_SLOTS, KEY_PROMPT_SLOTS
from app.domain.entitlements.types import GrantSpec
from app.models.brand import Brand, BrandLogoAsset, Competitor
from app.models.site_health import SiteCrawl
from tests.component.auth_helpers import register_and_login as _register
from tests.component.occupancy_helpers import seed_occupancy_grants


def _project_payload(**overrides: object) -> dict:
    payload = {
        "name": "Acme Visibility",
        "brand_name": "Acme Corp",
        "brand": {"aliases": ["Acme", "ACME Inc"]},
        "website_url": "https://acme.com",
        "owned_domains": ["acme.com"],
        "unintended_domains": ["support.acme.com"],
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


@pytest.mark.asyncio
async def test_create_project_persists_normalized_identity(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    await _register(client, "p1@example.com")
    resp = await client.post("/api/v1/projects", json=_project_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert "-" in body["id"] and "-" in body["workspace_id"]
    assert body["brand_name"] == "Acme Corp"
    assert body["brand"]["aliases"] == ["Acme", "ACME Inc"]
    assert body["brand"]["logo_url"] is None
    assert body["owned_domains"] == ["acme.com"]
    assert body["unintended_domains"] == ["support.acme.com"]
    assert len(body["competitors"]) == 1
    assert body["competitors"][0]["name"] == "Globex"
    assert body["competitors"][0]["logo_url"] is None
    assert "-" in body["competitors"][0]["id"]
    assert body["prompt_sets"] == []
    assert await db_session.scalar(select(SiteCrawl).limit(1)) is None

    # Round-trips on GET.
    got = await client.get(f"/api/v1/projects/{body['id']}")
    assert got.status_code == 200
    assert got.json()["brand"]["aliases"] == ["Acme", "ACME Inc"]


@pytest.mark.asyncio
async def test_project_logo_assets_are_workspace_scoped(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    await _register(client, "logo-owner@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    project_id = uuid.UUID(project["id"])
    brand = await db_session.scalar(select(Brand).where(Brand.project_id == project_id))
    competitor = await db_session.scalar(
        select(Competitor).where(Competitor.project_id == project_id)
    )
    assert brand is not None and competitor is not None
    png = b"\x89PNG\r\n\x1a\nasset"
    asset = BrandLogoAsset(
        domain="acme.com",
        status=BRAND_LOGO_STATUS_READY,
        source_url="https://acme.com/favicon.png",
        content_type="image/png",
        image_data=png,
        byte_size=len(png),
        sha256=hashlib.sha256(png).hexdigest(),
    )
    db_session.add(asset)
    await db_session.flush()
    brand.logo_asset_id = asset.id
    competitor.logo_asset_id = asset.id
    await db_session.commit()

    refreshed = await client.get(f"/api/v1/projects/{project['id']}")
    assert refreshed.json()["brand"]["logo_url"].endswith(
        f"/projects/{project['id']}/logo"
    )
    competitor_id = project["competitors"][0]["id"]
    own_logo = await client.get(f"/api/v1/projects/{project['id']}/logo")
    competitor_logo = await client.get(
        f"/api/v1/projects/{project['id']}/competitors/{competitor_id}/logo"
    )
    assert own_logo.status_code == 200 and own_logo.content == png
    assert competitor_logo.status_code == 200 and competitor_logo.content == png
    assert own_logo.headers["content-type"] == "image/png"
    assert own_logo.headers["cache-control"] == "private, max-age=86400"
    assert own_logo.headers["etag"] == f'"{hashlib.sha256(png).hexdigest()}"'
    assert own_logo.headers["x-content-type-options"] == "nosniff"
    not_modified = await client.get(
        f"/api/v1/projects/{project['id']}/logo",
        headers={"If-None-Match": own_logo.headers["etag"]},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert not_modified.headers["cache-control"] == own_logo.headers["cache-control"]
    assert not_modified.headers["etag"] == own_logo.headers["etag"]
    assert not_modified.headers["x-content-type-options"] == "nosniff"

    client.cookies.clear()
    await _register(client, "logo-outsider@example.com")
    assert (
        await client.get(f"/api/v1/projects/{project['id']}/logo")
    ).status_code == 404
    assert (
        await client.get(
            f"/api/v1/projects/{project['id']}/competitors/{competitor_id}/logo"
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_logo_is_served_without_the_active_workspace_header(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """A browser <img> cannot send X-Workspace-Id, so the path must be enough.

    The logo URLs are fetched directly by the browser, not through the API
    client, so no active-workspace header rides along. Scoping those routes to
    the caller's *earliest-joined* workspace 404s every logo in any other one —
    the "brand logos never appear" bug.
    """
    await _register(client, "logo-second-ws@example.com")
    # A second workspace, which is NOT the fallback the header-less request
    # would otherwise resolve to.
    second = (
        await client.post("/api/v1/workspaces", json={"name": "Second workspace"})
    ).json()
    project = (
        await client.post(
            "/api/v1/projects",
            json=_project_payload(),
            headers={"X-Workspace-Id": second["id"]},
        )
    ).json()
    project_id = uuid.UUID(project["id"])
    brand = await db_session.scalar(select(Brand).where(Brand.project_id == project_id))
    competitor = await db_session.scalar(
        select(Competitor).where(Competitor.project_id == project_id)
    )
    assert brand is not None and competitor is not None
    png = b"\x89PNG\r\n\x1a\nsecond"
    asset = BrandLogoAsset(
        domain="acme.com",
        status=BRAND_LOGO_STATUS_READY,
        source_url="https://acme.com/favicon.png",
        content_type="image/png",
        image_data=png,
        byte_size=len(png),
        sha256=hashlib.sha256(png).hexdigest(),
    )
    db_session.add(asset)
    await db_session.flush()
    brand.logo_asset_id = asset.id
    competitor.logo_asset_id = asset.id
    await db_session.commit()

    # No X-Workspace-Id — exactly what the <img> request looks like.
    served = await client.get(f"/api/v1/projects/{project['id']}/logo")
    assert served.status_code == 200
    assert served.content == png

    # The competitor route resolves the workspace independently of the brand
    # route, so it regresses on its own — a <img> for a competitor logo sends
    # no header either.
    competitor_id = project["competitors"][0]["id"]
    competitor_served = await client.get(
        f"/api/v1/projects/{project['id']}/competitors/{competitor_id}/logo"
    )
    assert competitor_served.status_code == 200
    assert competitor_served.content == png


@pytest.mark.asyncio
async def test_project_list_and_update_and_delete(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "p2@example.com")
    created = (await client.post("/api/v1/projects", json=_project_payload())).json()

    listing = await client.get("/api/v1/projects")
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    patched = await client.patch(
        f"/api/v1/projects/{created['id']}",
        json={
            "name": "Renamed",
            "brand": {"aliases": ["NewAlias"]},
            "benchmark_mode": "forced_grounded",
        },
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["brand"]["aliases"] == ["NewAlias"]
    assert patched.json()["benchmark_mode"] == "forced_grounded"

    deleted = await client.delete(f"/api/v1/projects/{created['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/projects")).json() == []


@pytest.mark.asyncio
async def test_benchmark_mode_validation(client: httpx.AsyncClient) -> None:
    await _register(client, "p3@example.com")
    resp = await client.post(
        "/api/v1/projects", json=_project_payload(benchmark_mode="warp_speed")
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_prompt_set_and_prompt_crud_and_intent_validation(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "p4@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()

    ps = await client.post(
        "/api/v1/prompt-sets",
        json={"project_id": project["id"], "name": "Launch set"},
    )
    assert ps.status_code == 201
    prompt_set_id = ps.json()["id"]
    assert ps.json()["prompts"] == []

    # Known intent is kept.
    created = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "best acme running shoes", "intent": "Discovery"},
    )
    assert created.status_code == 201
    assert created.json()["intent"] == "discovery"
    assert created.json()["origin"] == "manual"
    prompt_id = created.json()["id"]

    # Unknown intent normalizes to "".
    created2 = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "another acme prompt", "intent": "teleport"},
    )
    assert created2.status_code == 201
    assert created2.json()["intent"] == ""

    # Set now reports its prompts.
    got = await client.get(f"/api/v1/prompt-sets/{prompt_set_id}")
    assert got.json()["prompt_count"] == 2
    assert len(got.json()["prompts"]) == 2

    # Update + delete a prompt.
    upd = await client.patch(
        f"/api/v1/prompts/{prompt_id}",
        json={"enabled": False, "intent": "purchase"},
    )
    assert upd.status_code == 200
    assert upd.json()["enabled"] is False
    assert upd.json()["intent"] == "purchase"

    dele = await client.delete(f"/api/v1/prompts/{prompt_id}")
    assert dele.status_code == 204


@pytest.mark.asyncio
async def test_csv_import_bulk_creates_imported_prompts(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "p5@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Imported"},
        )
    ).json()["id"]

    csv_bytes = (
        b"text,theme,intent\n"
        b"cheap acme laptops,tech,discovery\n"
        b"Acme vs Globex,compare,comparison\n"
        b"   ,skip,discovery\n"
    )
    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        files={"file": ("prompts.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["prompt_count"] == 2  # blank-text row dropped
    assert {p["origin"] for p in body["prompts"]} == {"imported"}
    assert {p["intent"] for p in body["prompts"]} == {"discovery", "comparison"}


@pytest.mark.asyncio
async def test_csv_import_accepts_json_rows(client: httpx.AsyncClient) -> None:
    await _register(client, "p5b@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "JSON rows"},
        )
    ).json()["id"]

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        json={"prompts": [{"text": "acme row one"}, {"text": "acme row two"}]},
    )
    assert resp.status_code == 201
    assert resp.json()["prompt_count"] == 2
    assert {p["origin"] for p in resp.json()["prompts"]} == {"imported"}


@pytest.mark.asyncio
async def test_prompt_import_stops_oversized_file_before_csv_parsing(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "p5-limit@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Bounded import"},
        )
    ).json()["id"]
    oversized = b"text\n" + (b"x" * (1024 * 1024))
    response = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/import",
        files={"file": ("prompts.csv", io.BytesIO(oversized), "text/csv")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_projects_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/projects")).status_code == 401


@pytest.mark.asyncio
async def test_cross_workspace_project_isolation(
    client: httpx.AsyncClient,
) -> None:
    """User B cannot see or fetch user A's project (invariant 5)."""
    await _register(client, "owner-a@example.com")
    a_project = (await client.post("/api/v1/projects", json=_project_payload())).json()

    # Switch to user B (fresh session cookie in the same client).
    client.cookies.clear()
    await _register(client, "owner-b@example.com")

    # B's list is empty and B cannot fetch A's project by id.
    assert (await client.get("/api/v1/projects")).json() == []
    got = await client.get(f"/api/v1/projects/{a_project['id']}")
    assert got.status_code == 404

    # B also cannot create a prompt set against A's project.
    ps = await client.post(
        "/api/v1/prompt-sets",
        json={"project_id": a_project["id"], "name": "sneaky"},
    )
    assert ps.status_code == 404


# =========================================================================
# Account occupancy enforcement (slice23 Task 4): routes map the domain
# error to the coded 403 — the quota check itself lives in the services.
# =========================================================================
@pytest.mark.asyncio
async def test_create_project_over_occupancy_returns_coded_403(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "occ-proj@example.com")
    # Unprovisioned (no grants): the first project is not occupancy-gated.
    first = (await client.post("/api/v1/projects", json=_project_payload())).json()
    workspace_id = uuid.UUID(first["workspace_id"])
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_id,
            grants=(GrantSpec(key=KEY_PROJECT_SLOTS, value=1),),
        )
        await session.commit()

    resp = await client.post("/api/v1/projects", json=_project_payload(name="Second"))
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "occupancy_limit_exceeded"
    assert body["error"]["retryable"] is False
    assert body["error"]["details"]["key"] == "project_slots"
    assert body["error"]["details"]["allowance"] == 1
    # Legacy coded detail keeps its exact dialect (api-error-contract).
    assert body["detail"]["code"] == "occupancy_limit_exceeded"


@pytest.mark.asyncio
async def test_create_prompt_over_occupancy_returns_coded_403(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "occ-prompt@example.com")
    project = (await client.post("/api/v1/projects", json=_project_payload())).json()
    prompt_set_id = (
        await client.post(
            "/api/v1/prompt-sets",
            json={"project_id": project["id"], "name": "Launch set"},
        )
    ).json()["id"]
    async with session_factory() as session:
        await seed_occupancy_grants(
            session,
            workspace_id=uuid.UUID(project["workspace_id"]),
            grants=(GrantSpec(key=KEY_PROMPT_SLOTS, value=1),),
        )
        await session.commit()

    first = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "first acme prompt"},
    )
    assert first.status_code == 201

    resp = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": "second acme prompt"},
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["error"]["code"] == "occupancy_limit_exceeded"
    assert body["error"]["details"]["key"] == "prompt_slots"
    assert body["detail"]["code"] == "occupancy_limit_exceeded"

    # A duplicate of the persisted prompt stays a 409 even at full
    # capacity: duplicates never consume a slot, so no 403 pre-empts it.
    dup = await client.post(
        f"/api/v1/prompt-sets/{prompt_set_id}/prompts",
        json={"text": " First   Acme Prompt "},
    )
    assert dup.status_code == 409
