"""Component tests for the product-catalog API (httpx ASGITransport).

Covers the Task 1 acceptance:
  - product CRUD round-trip with the computed completeness badge;
  - CSV import via multipart file AND JSON rows (duplicates dropped, never a
    failure; headerless CSV -> 422);
  - cross-workspace access returns 404 (invariant 5);
  - per-project SKU uniqueness enforced as 409.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config.products import PRODUCT_COMPLETENESS_ATTRIBUTE_KEYS


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


async def _project(client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": "Voltaic Visibility",
            "brand_name": "Voltaic Supply",
            "competitors": [{"name": "RideCore", "aliases": [], "domains": []}],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _product_payload(**overrides: object) -> dict:
    payload = {
        "sku": "VC-EB500-GR",
        "name": "VoltCity Commuter 500",
        "aliases": ["VoltCity 500"],
        "variants": [
            {"name": "Graphite / Standard", "sku": "VC-EB500-GR", "price": 2499.0}
        ],
        "price": 2499.00,
        "currency": "usd",
        "url": "https://voltaic.example/products/voltcity-500",
        "attributes": {"brand": "Voltaic", "category": "E-Bikes"},
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_product_crud_round_trip(client: httpx.AsyncClient) -> None:
    await _register(client, "prod-crud@example.com")
    project = await _project(client)

    created = await client.post(
        f"/api/v1/projects/{project['id']}/products", json=_product_payload()
    )
    assert created.status_code == 201
    body = created.json()
    assert body["sku"] == "VC-EB500-GR"
    assert body["currency"] == "USD"  # normalized
    assert body["origin"] == "manual"
    assert body["variants"][0]["name"] == "Graphite / Standard"
    # Sync provenance fields are present and null for a manual product.
    assert body["connection_id"] is None
    assert body["external_item_ref"] is None
    assert body["last_seen_sync_run_id"] is None
    # Completeness badge is computed on read from the config matrix.
    completeness = body["completeness"]
    assert completeness["present"] < completeness["total"]
    assert set(completeness["missing"]) == {
        key
        for key in PRODUCT_COMPLETENESS_ATTRIBUTE_KEYS
        if key not in {"brand", "category"}
    }

    product_id = body["id"]
    got = await client.get(f"/api/v1/products/{product_id}")
    assert got.status_code == 200
    assert got.json()["sku"] == "VC-EB500-GR"

    patched = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"price": 2399.0, "attributes": {"brand": "Voltaic", "gtin": "0123"}},
    )
    assert patched.status_code == 200
    assert patched.json()["price"] == 2399.0
    assert "gtin" not in patched.json()["completeness"]["missing"]

    listed = await client.get(f"/api/v1/projects/{project['id']}/products")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [product_id]

    deleted = await client.delete(f"/api/v1/products/{product_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/products/{product_id}")).status_code == 404


@pytest.mark.asyncio
async def test_product_sku_uniqueness_conflict(client: httpx.AsyncClient) -> None:
    await _register(client, "prod-dupe@example.com")
    project = await _project(client)
    url = f"/api/v1/projects/{project['id']}/products"

    first = await client.post(url, json=_product_payload())
    assert first.status_code == 201
    dupe = await client.post(url, json=_product_payload(name="Other name"))
    assert dupe.status_code == 409

    other = await client.post(url, json=_product_payload(sku="SF-200W"))
    assert other.status_code == 201
    # PATCH onto the existing SKU also conflicts.
    patched = await client.patch(
        f"/api/v1/products/{other.json()['id']}", json={"sku": "VC-EB500-GR"}
    )
    assert patched.status_code == 409


@pytest.mark.asyncio
async def test_product_import_csv_file_and_json_rows(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prod-import@example.com")
    project = await _project(client)
    url = f"/api/v1/projects/{project['id']}/products/import"

    csv_text = (
        "sku,name,price,currency,category\n"
        "VC-500,VoltCity 500,2499.00,USD,E-Bikes\n"
        "SF-200W,SolarFold Panel 200W,499.00,USD,Power & Solar\n"
        "VC-500,Duplicate In File,1.00,USD,E-Bikes\n"
    )
    imported = await client.post(
        url, files={"file": ("catalog.csv", csv_text, "text/csv")}
    )
    assert imported.status_code == 201
    body = imported.json()
    # D1 response contract: the refreshed catalog + the per-row summary.
    assert set(body) == {"items", "summary"}
    assert set(body["summary"]) == {"created", "updated", "skipped", "errors"}
    rows = body["items"]
    # The in-file duplicate is dropped; both unique rows land as imported.
    assert {row["sku"] for row in rows} == {"VC-500", "SF-200W"}
    assert {row["origin"] for row in rows} == {"imported"}
    by_sku = {row["sku"]: row for row in rows}
    assert by_sku["VC-500"]["name"] == "VoltCity 500"
    assert by_sku["SF-200W"]["attributes"]["category"] == "Power & Solar"
    # Summary: 2 created, the in-file duplicate skipped with its row number.
    assert body["summary"]["created"] == 2
    assert body["summary"]["updated"] == 0
    assert body["summary"]["skipped"] == 1
    assert body["summary"]["errors"] == [
        {
            "row": 3,
            "field": "sku",
            "message": "Duplicate sku 'VC-500' in this import — "
            "the first occurrence was kept",
        }
    ]

    # JSON rows path converges on the same logic; the existing sku is a
    # skipped row (left unchanged), never a failure.
    json_import = await client.post(
        url,
        json={
            "products": [
                {"sku": "VC-500", "name": "Ignored duplicate"},
                {"sku": "CG-S2-GR", "name": "CityGlide Scooter S2", "price": 899.0},
            ]
        },
    )
    assert json_import.status_code == 201
    body = json_import.json()
    rows = body["items"]
    assert {row["sku"] for row in rows} == {"VC-500", "SF-200W", "CG-S2-GR"}
    assert {row["name"] for row in rows if row["sku"] == "VC-500"} == {"VoltCity 500"}
    assert body["summary"]["created"] == 1
    assert body["summary"]["skipped"] == 1
    assert body["summary"]["errors"] == [
        {
            "row": 1,
            "field": "sku",
            "message": "A product with sku 'VC-500' already exists — "
            "it was left unchanged",
        }
    ]


@pytest.mark.asyncio
async def test_product_import_summary_reports_missing_sku_rows(
    client: httpx.AsyncClient,
) -> None:
    """COM-4: sku-less CSV rows surface as numbered row errors, not silence."""
    await _register(client, "prod-import-skips@example.com")
    project = await _project(client)
    csv_text = (
        "sku,name\nVC-500,VoltCity 500\n,No SKU row\nSF-200W,SolarFold Panel 200W\n"
    )
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        files={"file": ("catalog.csv", csv_text, "text/csv")},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert [row["sku"] for row in body["items"]] == ["VC-500", "SF-200W"]
    assert body["summary"]["created"] == 2
    assert body["summary"]["skipped"] == 1
    errors = body["summary"]["errors"]
    assert len(errors) == 1
    assert errors[0]["row"] == 2
    assert errors[0]["field"] == "sku"
    assert "Missing sku" in errors[0]["message"]


@pytest.mark.asyncio
async def test_product_import_json_rows_report_blank_sku_and_duplicates(
    client: httpx.AsyncClient,
) -> None:
    """JSON rows that pass schema validation but cannot be imported (blank
    sku, in-payload duplicates) land in the summary, not in a 422."""
    await _register(client, "prod-import-json-skips@example.com")
    project = await _project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        json={
            "products": [
                {"sku": "   ", "name": "Whitespace-only sku"},
                {"sku": "DUP-1", "name": "First"},
                {"sku": "DUP-1", "name": "Second"},
            ]
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert [row["sku"] for row in body["items"]] == ["DUP-1"]
    assert body["items"][0]["name"] == "First"
    assert body["summary"]["created"] == 1
    assert body["summary"]["skipped"] == 2
    errors = body["summary"]["errors"]
    assert [error["row"] for error in errors] == [1, 3]
    assert "Missing sku" in errors[0]["message"]
    assert "Duplicate sku 'DUP-1'" in errors[1]["message"]


@pytest.mark.asyncio
async def test_product_import_bad_price_json_is_sanitized_422(
    client: httpx.AsyncClient,
) -> None:
    """COM-5: a schema-violating JSON row (negative price) is a sanitized
    422 — no Pydantic internals reach the client."""
    await _register(client, "prod-import-price-422@example.com")
    project = await _project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        json={"products": [{"sku": "VC-500", "name": "VoltCity", "price": -5}]},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "pydantic" not in resp.text
    assert "ProductImport" not in resp.text
    assert "errors.pydantic.dev" not in resp.text


@pytest.mark.asyncio
async def test_product_import_headerless_csv_rejected(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prod-import-422@example.com")
    project = await _project(client)
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        files={"file": ("catalog.csv", "VC-500,VoltCity 500\n", "text/csv")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_product_import_invalid_utf8_rejected(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prod-import-utf8@example.com")
    project = await _project(client)
    response = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        files={"file": ("catalog.csv", b"sku,name\nVC-500,Volt\xffCity\n", "text/csv")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "CSV must be valid UTF-8"


@pytest.mark.asyncio
async def test_product_import_malformed_json_is_422_not_500(
    client: httpx.AsyncClient,
) -> None:
    """Bad JSON import payloads are client errors, never unhandled 500s."""
    await _register(client, "prod-import-json-422@example.com")
    project = await _project(client)
    url = f"/api/v1/projects/{project['id']}/products/import"

    # Undecodable JSON body.
    broken = await client.post(
        url, content="{not json", headers={"content-type": "application/json"}
    )
    assert broken.status_code == 422

    # Well-formed JSON that violates the ProductImport schema.
    invalid = await client.post(
        url, json={"products": [{"name": "Missing the required sku"}]}
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_product_import_rejects_oversized_file_before_csv_parsing(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prod-import-limit@example.com")
    project = await _project(client)
    oversized = b"sku,name\n1," + (b"x" * (1024 * 1024))
    response = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        files={"file": ("catalog.csv", oversized, "text/csv")},
    )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_cross_workspace_isolation(client: httpx.AsyncClient) -> None:
    """User B cannot read/write user A's catalog (invariant 5)."""
    await _register(client, "prod-owner-a@example.com")
    project_a = await _project(client)
    product = (
        await client.post(
            f"/api/v1/projects/{project_a['id']}/products", json=_product_payload()
        )
    ).json()

    client.cookies.clear()
    await _register(client, "prod-owner-b@example.com")

    assert (
        await client.get(f"/api/v1/projects/{project_a['id']}/products")
    ).status_code == 404
    assert (await client.get(f"/api/v1/products/{product['id']}")).status_code == 404
    assert (
        await client.patch(f"/api/v1/products/{product['id']}", json={"name": "x"})
    ).status_code == 404
    assert (await client.delete(f"/api/v1/products/{product['id']}")).status_code == 404
    assert (
        await client.post(
            f"/api/v1/projects/{project_a['id']}/products",
            json=_product_payload(sku="NEW-1"),
        )
    ).status_code == 404
