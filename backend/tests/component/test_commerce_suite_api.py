from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.commerce.prompts import (
    _project_with_brand,
    _target_context,
    _target_vocabulary,
    add_manual_buyer_prompt,
)
from app.domain.commerce.schemas import CommerceTarget
from app.domain.commerce.service import CommerceNotFoundError
from app.domain.prompts.topical_binding import binding_tokens
from app.models.commerce import CommerceCategory
from app.models.project import Project


async def _register(client: httpx.AsyncClient, email: str) -> None:
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 202
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 200


async def _project(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Commerce", "brand_name": "Acme", "competitors": []},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_catalog_import_is_idempotent_with_row_outcomes(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-import@example.com")
    project = await _project(client)
    url = f"/api/v1/projects/{project['id']}/commerce/catalog/import"
    content = (
        "canonical_url,name,brand,price,currency,sku,category\n"
        "https://shop.example/products/one,Acme One,Acme,19.00,USD,A-1,Shoes\n"
    )
    payload = {
        "filename": "catalog.csv",
        "content_type": "text/csv",
        "content": content,
    }
    first = await client.post(url, json=payload)
    assert first.status_code == 201
    assert first.json()["created"] == 1
    assert first.json()["row_outcomes"][0]["status"] == "created"
    repeated = await client.post(url, json=payload)
    assert repeated.status_code == 201
    assert repeated.json() == first.json()

    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["products"][0]["canonical_url"] == (
        "https://shop.example/products/one"
    )
    assert catalog.json()["products"][0]["field_sources"]["name"]["kind"] == "csv"


@pytest.mark.asyncio
async def test_catalog_orders_categories_by_product_count_descending(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-category-order@example.com")
    project = await _project(client)
    response = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,category\n"
                "https://shop.example/products/one,One,Small\n"
                "https://shop.example/products/two,Two,Large\n"
                "https://shop.example/products/three,Three,Large\n"
            ),
        },
    )
    assert response.status_code == 201

    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")

    assert catalog.status_code == 200
    assert [
        (row["name"], row["product_count"]) for row in catalog.json()["categories"]
    ] == [("Large", 2), ("Small", 1)]


@pytest.mark.asyncio
async def test_commerce_catalog_is_workspace_isolated(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-owner@example.com")
    project = await _project(client)
    await _register(client, "commerce-outsider@example.com")
    response = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_competitor_discovery_deduplicates_only_within_one_request(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-discovery@example.com")
    project = await _project(client)
    import_response = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,brand\n"
                "https://shop.example/products/one,Acme One,Acme\n"
            ),
        },
    )
    assert import_response.status_code == 201
    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    product_id = catalog.json()["products"][0]["id"]
    url = f"/api/v1/projects/{project['id']}/commerce/competitors/discover"
    target = {"kind": "product", "id": product_id}

    first = await client.post(url, json={"targets": [target, target]})
    second = await client.post(url, json={"targets": [target]})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["task_ids"][0] == first.json()["task_ids"][1]
    assert second.json()["task_ids"][0] != first.json()["task_ids"][0]
    status_response = await client.get(
        f"/api/v1/projects/{project['id']}/commerce/competitors/discoveries",
        params=[("task_ids", first.json()["task_ids"][0])],
    )
    assert status_response.status_code == 200
    assert status_response.json() == [
        {
            "id": first.json()["task_ids"][0],
            "target": target,
            "status": "queued",
            "error_code": "",
            "terminal": False,
        }
    ]

    # Omitting task_ids asks for whatever is in flight for the project. The
    # client used to hold the ids in component state alone, so a reload lost
    # track of a running discovery entirely.
    active_response = await client.get(
        f"/api/v1/projects/{project['id']}/commerce/competitors/discoveries",
    )
    assert active_response.status_code == 200
    active_ids = {row["id"] for row in active_response.json()}
    assert active_ids == {
        first.json()["task_ids"][0],
        second.json()["task_ids"][0],
    }
    assert all(row["terminal"] is False for row in active_response.json())


@pytest.mark.asyncio
async def test_catalog_edit_clears_optional_identifiers_to_null(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-edit@example.com")
    project = await _project(client)
    await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,sku,gtin,mpn\n"
                "https://shop.example/products/one,Acme One,A-1,1234567890123,M-1\n"
            ),
        },
    )
    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    product_id = catalog.json()["products"][0]["id"]

    response = await client.patch(
        f"/api/v1/projects/{project['id']}/commerce/catalog/products/{product_id}",
        json={"sku": None, "gtin": None, "mpn": None},
    )

    assert response.status_code == 200
    assert response.json()["sku"] is None
    assert response.json()["gtin"] is None
    assert response.json()["mpn"] is None


@pytest.mark.asyncio
async def test_category_correction_is_persisted_and_workspace_isolated(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-category-owner@example.com")
    project = await _project(client)
    await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,category\n"
                "https://shop.example/products/one,Acme One,Shoes\n"
            ),
        },
    )
    catalog_url = f"/api/v1/projects/{project['id']}/commerce/catalog"
    category_id = (await client.get(catalog_url)).json()["categories"][0]["id"]

    response = await client.patch(
        f"{catalog_url}/categories/{category_id}",
        json={"name": "Trail shoes", "role": "leaf"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Trail shoes"
    assert response.json()["role"] == "leaf"
    assert response.json()["field_sources"]["name"]["kind"] == "edit"
    assert (await client.get(catalog_url)).json()["categories"][0]["name"] == (
        "Trail shoes"
    )

    await _register(client, "commerce-category-outsider@example.com")
    outsider = await client.patch(
        f"{catalog_url}/categories/{category_id}", json={"name": "Stolen"}
    )
    assert outsider.status_code == 404


async def test_ai_shelf_requires_an_explicit_target(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-shelf-target@example.com")
    project = await _project(client)

    response = await client.get(f"/api/v1/projects/{project['id']}/commerce/ai-shelf")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "commerce_target_required"


@pytest.mark.asyncio
async def test_a_category_target_carries_the_shop_not_just_its_own_name(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A category used to be sent to the model as nothing but its name.

    Handed the bare word "ACCESORIES" -- no brand, no vertical, no products,
    not even the collection URL -- the model wrote what generic e-commerce
    training data says accessories are: phone cases, screen protectors, laptop
    sleeves. For a linen-fashion label. It was not leaking examples; it had no
    way to know what the shop sold, and the topicality gate now has nothing to
    judge against either unless this context is populated.
    """
    await _register(client, "commerce-context@example.com")
    project = await _project(client)
    project_id = uuid.UUID(project["id"])

    imported = await client.post(
        f"/api/v1/projects/{project_id}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,brand,price,currency,sku,category\n"
                "https://shop.example/products/midi,"
                "Bubble Linen Dress,Acme,240.00,USD,L-1,ACCESORIES\n"
                "https://shop.example/products/scarf,"
                "Silk Linen Scarf,Acme,90.00,USD,L-2,ACCESORIES\n"
            ),
        },
    )
    assert imported.status_code in {200, 201}, imported.text

    async with session_factory() as session:
        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.project_id == project_id,
                CommerceCategory.normalized_name == "accesories",
            )
        )
        assert category is not None
        loaded = await _project_with_brand(
            session, workspace_id=category.workspace_id, project_id=project_id
        )
        context = await _target_context(
            session,
            workspace_id=category.workspace_id,
            project_id=project_id,
            target=CommerceTarget(kind="category", id=category.id),
            project=loaded,
        )

    assert context["brand"] == "Acme"
    assert set(context["products_on_this_shelf"]) == {
        "Bubble Linen Dress",
        "Silk Linen Scarf",
    }
    # And that context is what the topicality gate judges against, so an
    # off-vertical prompt for this shelf is now rejectable.
    vocabulary = _target_vocabulary(context)
    assert "linen" in vocabulary
    assert not (vocabulary & binding_tokens("phone case with magsafe for iphone"))


@pytest.mark.asyncio
async def test_a_manual_buyer_prompt_can_be_added_to_a_category(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The manual path shares the target lookup with generation.

    It calls `_target_context` purely to 404 an unknown target before writing,
    so when that helper grew a required `project` argument this raised
    TypeError on every manual prompt -- a path with no test to catch it.
    """
    await _register(client, "commerce-manual@example.com")
    project = await _project(client)
    project_id = uuid.UUID(project["id"])

    imported = await client.post(
        f"/api/v1/projects/{project_id}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,brand,price,currency,sku,category\n"
                "https://shop.example/products/midi,"
                "Bubble Linen Dress,Acme,240.00,USD,L-1,DRESSES\n"
            ),
        },
    )
    assert imported.status_code in {200, 201}, imported.text

    async with session_factory() as session:
        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.project_id == project_id,
                CommerceCategory.normalized_name == "dresses",
            )
        )
        assert category is not None
        workspace_id, category_id = category.workspace_id, category.id

        created = await add_manual_buyer_prompt(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            target=CommerceTarget(kind="category", id=category_id),
            text="  linen midi dress for a beach wedding  ",
        )

    assert created.text == "linen midi dress for a beach wedding"
    assert created.enabled is False
    assert created.target.id == category_id


@pytest.mark.asyncio
async def test_a_manual_buyer_prompt_rejects_an_unknown_target(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "commerce-manual-404@example.com")
    project = await _project(client)
    project_id = uuid.UUID(project["id"])

    async with session_factory() as session:
        workspace_id = await session.scalar(
            select(Project.workspace_id).where(Project.id == project_id)
        )
        assert workspace_id is not None
        with pytest.raises(CommerceNotFoundError):
            await add_manual_buyer_prompt(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                target=CommerceTarget(kind="category", id=uuid.uuid4()),
                text="linen midi dress for a beach wedding",
            )
