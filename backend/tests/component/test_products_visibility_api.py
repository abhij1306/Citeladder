"""M2a product visibility contract tests over persisted evidence only.

These tests deliberately do not build an answer-engine adapter. They seed immutable raw
artifacts, invoke the deterministic product analyzer/finalizer, and then exercise the
HTTP projection. That keeps provider execution out of projection tests (invariant 7).
"""

from __future__ import annotations

import copy
import csv
import io
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.product_service import (
    analyze_task_products,
    build_product_scoring_config,
    finalize_audit_product_analysis,
)
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.core.config.provider_catalog import ENGINE_GEMINI
from app.domain.audits.creation import create_audit
from app.models.audit import Audit, AuditTask, RawResponseArtifact
from app.models.brand import Competitor
from app.models.product import (
    CompetitorProduct,
    MerchantMention,
    Product,
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)
from app.models.user import User
from app.models.workspace import WorkspaceMember
from tests.component.audit_helpers import Seed, seed_audit_fixtures

_FIXTURE_SURFACE = "fixture-shopping"
_V1_ANALYZER = "product-analysis-1"
_V1_RULE = "product-scoring-v1"
_ANSWER = (
    "1. Acme VoltBike 500 — true to size, $2,499.00, "
    "https://acme.com/p/voltbike?utm_source=answer\n"
    "2. Globex CityBike 450 — $2,199.00, https://www.amazon.com/dp/BIKE?tag=x"
)


async def _seed_catalog_user_and_audit(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Seed, Product, CompetitorProduct, Audit]:
    email = f"commerce-v2-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        competitor = await session.scalar(
            select(Competitor).where(Competitor.project_id == seed.project_id)
        )
        user = await session.scalar(select(User).where(User.email == email))
        assert competitor is not None and user is not None
        product = Product(
            project_id=seed.project_id,
            sku="AC-VB500",
            name="Acme VoltBike 500",
            aliases=["VoltBike 500"],
            price=Decimal("2499.00"),
            currency="USD",
            url="https://acme.com/p/voltbike",
            attributes={"category": "footwear"},
        )
        competitor_product = CompetitorProduct(
            project_id=seed.project_id,
            competitor_id=competitor.id,
            name="Globex CityBike 450",
            price=Decimal("2399.00"),
            currency="USD",
        )
        session.add_all(
            [
                product,
                competitor_product,
                WorkspaceMember(
                    workspace_id=seed.workspace_id, user_id=user.id, role="owner"
                ),
            ]
        )
        await session.commit()
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=[ENGINE_GEMINI],
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="7",
        )
    return seed, product, competitor_product, audit


async def _persist_answer(
    session: AsyncSession,
    task: AuditTask,
    *,
    answer: str = _ANSWER,
) -> RawResponseArtifact:
    artifact = RawResponseArtifact(
        audit_id=task.audit_id,
        task_id=task.id,
        logical_engine=task.logical_engine,
        transport_provider=task.transport_provider,
        transport_model=task.transport_model,
        answer_text=answer,
        search_used=False,
        search_events=[],
        citations=[],
    )
    session.add(artifact)
    await session.flush()
    task.result_artifact_id = artifact.id
    task.answer_text = answer
    task.status = TASK_STATUS_SUCCEEDED
    task.completed_at = datetime.now(UTC)
    return artifact


def _clone_surface_task(source: AuditTask, *, surface: str, repetition: int = 0):
    return AuditTask(
        audit_id=source.audit_id,
        workspace_id=source.workspace_id,
        prompt_snapshot_id=source.prompt_snapshot_id,
        engine_snapshot_id=source.engine_snapshot_id,
        prompt_index=source.prompt_index,
        repetition=repetition,
        randomized_position=source.randomized_position + 1,
        logical_engine=source.logical_engine,
        transport_provider=source.transport_provider,
        transport_model=source.transport_model,
        shopping_surface=surface,
        prompt_text=source.prompt_text,
        provider_route_snapshot=source.provider_route_snapshot,
        idempotency_key=(
            f"{source.audit_id}:{source.prompt_index}:{repetition}:"
            f"{source.logical_engine}:{surface}"
        ),
    )


async def _finish_with_two_surfaces(
    session_factory: async_sessionmaker[AsyncSession], audit_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    async with session_factory() as session:
        audit = await session.get(Audit, audit_id)
        measurement = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit_id)
        )
        assert audit is not None and measurement is not None
        probe = _clone_surface_task(measurement, surface=_FIXTURE_SURFACE)
        session.add(probe)
        await session.flush()
        await _persist_answer(session, measurement)
        await _persist_answer(session, probe)
        config = build_product_scoring_config(audit.configuration)
        measurement_analysis = await analyze_task_products(
            session, task=measurement, config=config
        )
        probe_analysis = await analyze_task_products(session, task=probe, config=config)
        assert measurement_analysis is not None and probe_analysis is not None
        await finalize_audit_product_analysis(session, audit=audit)
        audit.status = AUDIT_STATUS_COMPLETED
        audit.completed_at = datetime.now(UTC)
        audit.completed_count = 1
        await session.commit()
        return measurement.id, probe.id


def _headers(seed: Seed) -> dict[str, str]:
    return {"X-Workspace-Id": str(seed.workspace_id)}


@pytest.mark.asyncio
async def test_v1_graph_survives_rescore_and_current_projection_wins(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        stored_audit = await session.get(Audit, audit.id)
        assert task is not None and stored_audit is not None
        artifact = await _persist_answer(session, task)
        legacy = ProductResponseAnalysis(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            task_id=task.id,
            artifact_id=artifact.id,
            product_analyzer_version=_V1_ANALYZER,
            product_scoring_rule_version=_V1_RULE,
            logical_engine=task.logical_engine,
            transport_provider=task.transport_provider,
            transport_model=task.transport_model,
            prompt_index=0,
            repetition=0,
            shopping_surface="",
            own_product_mention_count=1,
            score={"products": [], "competitor_products": []},
        )
        session.add(legacy)
        await session.flush()
        legacy_mention = ProductMention(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            analysis_id=legacy.id,
            artifact_id=artifact.id,
            product_analyzer_version=_V1_ANALYZER,
            product_id=product.id,
            matched_name=product.name,
            matched_sku=product.sku,
            price_text="$2,499.00",
            price_value=Decimal("2499.00"),
            price_currency="USD",
            price_matches_catalog=True,
        )
        legacy_snapshot = ProductMetricSnapshot(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            project_id=seed.project_id,
            product_id=product.id,
            product_analyzer_version=_V1_ANALYZER,
            product_scoring_rule_version=_V1_RULE,
            mention_count=99,
            sov_share=1.0,
            metrics={"entry_id": str(product.id)},
            source_analysis_ids=[str(legacy.id)],
            source_artifact_ids=[str(artifact.id)],
        )
        session.add_all([legacy_mention, legacy_snapshot])
        await session.flush()
        legacy_ids = (legacy.id, legacy_mention.id, legacy_snapshot.id)

        current = await analyze_task_products(
            session,
            task=task,
            config=build_product_scoring_config(stored_audit.configuration),
        )
        assert current is not None and current.id != legacy.id
        await finalize_audit_product_analysis(session, audit=stored_audit)
        stored_audit.status = AUDIT_STATUS_COMPLETED
        stored_audit.completed_at = datetime.now(UTC)
        await session.commit()

    response = await client.get(
        f"/api/v1/projects/{seed.project_id}/products/visibility",
        params={"audit_id": str(audit.id)},
        headers=_headers(seed),
    )
    assert response.status_code == 200
    entry = response.json()["products"][0]
    assert entry["product_analyzer_version"] == PRODUCT_ANALYZER_VERSION
    assert entry["mention_count"] == 1
    async with session_factory() as session:
        for model, row_id in zip(
            (ProductResponseAnalysis, ProductMention, ProductMetricSnapshot),
            legacy_ids,
            strict=True,
        ):
            assert await session.get(model, row_id) is not None


@pytest.mark.asyncio
async def test_surface_slices_evidence_shapes_and_stable_ids(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import commerce as commerce_config

    monkeypatch.setattr(
        commerce_config, "SHOPPING_SURFACES", {_FIXTURE_SURFACE: {"label": "Fixture"}}
    )
    seed, product, competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    await _finish_with_two_surfaces(session_factory, audit.id)
    base = f"/api/v1/projects/{seed.project_id}/products/visibility"

    measurement = await client.get(
        base, params={"audit_id": str(audit.id)}, headers=_headers(seed)
    )
    probe = await client.get(
        base,
        params={"audit_id": str(audit.id), "surface": _FIXTURE_SURFACE},
        headers=_headers(seed),
    )
    intersected = await client.get(
        base,
        params={
            "audit_id": str(audit.id),
            "surface": _FIXTURE_SURFACE,
            "engine": ENGINE_GEMINI,
        },
        headers=_headers(seed),
    )
    assert (
        measurement.status_code == probe.status_code == intersected.status_code == 200
    )
    for body in (measurement.json(), probe.json(), intersected.json()):
        assert body["total_analyses"] == 1
        assert body["total_mentions"] == 2
        assert body["available_surfaces"] == ["", _FIXTURE_SURFACE]
        own = body["products"][0]
        assert own["price_relation_counts"] == {
            "match": 1,
            "higher": 0,
            "lower": 0,
            "mismatch": 0,
        }
        assert list(own["attribute_dimension_frequency"])
        assert own["buyer_destination_mix"]["total"] == 1
        assert (
            own["buyer_destination_mix"]["by_domain"][0]["merchant_domain"]
            == "acme.com"
        )
        assert own["competitor_co_placement"] == {
            "items": [
                {
                    "competitor_product_id": str(competitor.id),
                    "competitor_name": "Globex",
                    "product_name": "Globex CityBike 450",
                    "count": 1,
                }
            ],
            "truncated": False,
        }

    evidence_url = f"/api/v1/products/{product.id}/visibility/evidence"
    first = await client.get(
        evidence_url,
        params={"audit_id": str(audit.id), "surface": _FIXTURE_SURFACE},
        headers=_headers(seed),
    )
    second = await client.get(
        evidence_url,
        params={"audit_id": str(audit.id), "surface": _FIXTURE_SURFACE},
        headers=_headers(seed),
    )
    assert first.status_code == second.status_code == 200
    first_items, second_items = first.json()["items"], second.json()["items"]
    assert {item["evidence_kind"] for item in first_items} == {
        "product_mention",
        "attribute_mention",
        "buyer_destination",
    }
    assert [item["evidence_id"] for item in first_items] == [
        item["evidence_id"] for item in second_items
    ]
    async with session_factory() as session:
        mention_ids = set((await session.scalars(select(ProductMention.id))).all())
        merchant_ids = set((await session.scalars(select(MerchantMention.id))).all())
    for item in first_items:
        assert set(item) == {
            "evidence_id",
            "analysis_id",
            "evidence_kind",
            "audit_id",
            "task_id",
            "artifact_id",
            "logical_engine",
            "transport_model",
            "prompt_text",
            "prompt_index",
            "repetition",
            "product_analyzer_version",
            "shopping_surface",
            "matched_name",
            "matched_sku",
            "created_at",
            "first_offset",
            "rank_position",
            "price_text",
            "price_value",
            "price_currency",
            "price_matches_catalog",
            "price_relation",
            "attribute_dimension",
            "attribute_group",
            "attribute_text",
            "attribute_offset",
            "merchant_name",
            "merchant_domain",
            "merchant_kind",
            "destination_url",
        }
        if item["evidence_kind"] == "product_mention":
            assert uuid.UUID(item["evidence_id"]) in mention_ids
        elif item["evidence_kind"] == "buyer_destination":
            assert uuid.UUID(item["evidence_id"]) in merchant_ids

    assert (
        await client.get(base, params={"surface": "unknown"}, headers=_headers(seed))
    ).status_code == 422


@pytest.mark.asyncio
async def test_surface_csv_is_stable_exact_and_projection_only(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import commerce as commerce_config

    monkeypatch.setattr(
        commerce_config, "SHOPPING_SURFACES", {_FIXTURE_SURFACE: {"label": "Fixture"}}
    )
    seed, product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    # Formula-neutralization is an export concern, so freeze a hostile identity.
    async with session_factory() as session:
        stored = await session.get(Audit, audit.id)
        assert stored is not None
        configuration = copy.deepcopy(stored.configuration)
        configuration["products"][0]["name"] = '=WEBSERVICE("bad")'
        configuration["products"][0]["sku"] = "+CMD"
        stored.configuration = configuration
        await session.commit()
    await _finish_with_two_surfaces(session_factory, audit.id)
    url = f"/api/v1/projects/{seed.project_id}/products/visibility/export.csv"
    params = {"audit_id": str(audit.id), "surface": _FIXTURE_SURFACE}
    first = await client.get(url, params=params, headers=_headers(seed))
    second = await client.get(url, params=params, headers=_headers(seed))
    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    rows = list(csv.DictReader(io.StringIO(first.text)))
    assert rows and list(rows[0]) == [
        "audit_id",
        "product",
        "sku",
        "mentions",
        "sov",
        "avg_rank",
        "price_accuracy",
        "engine",
        "product_analyzer_version",
        "surface",
        "win_rate",
        "price_mismatch_rate",
        "price_relation_match_count",
        "price_relation_higher_count",
        "price_relation_lower_count",
        "price_relation_mismatch_count",
        "attribute_dimension_frequency",
        "buyer_destination_mix",
        "competitor_co_placement",
    ]
    own = next(row for row in rows if row["sku"])
    assert own["product"].startswith("'=") and own["sku"].startswith("'+")
    assert own["surface"] == _FIXTURE_SURFACE
    for key in (
        "attribute_dimension_frequency",
        "buyer_destination_mix",
        "competitor_co_placement",
    ):
        assert (
            json.dumps(json.loads(own[key]), sort_keys=True, separators=(",", ":"))
            == own[key]
        )

    # Every endpoint above is a persisted projection: deleting the live catalog
    # identity must not alter the frozen exported name/SKU or trigger re-analysis.
    async with session_factory() as session:
        await session.delete(await session.get(Product, product.id))
        await session.commit()
    assert (
        await client.get(url, params=params, headers=_headers(seed))
    ).status_code == 200


@pytest.mark.asyncio
async def test_mixed_v1_v2_evidence_projects_legacy_relation_fallback(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        stored = await session.get(Audit, audit.id)
        assert task is not None and stored is not None
        legacy_artifact = await _persist_answer(session, task)
        task.status = TASK_STATUS_FAILED  # finalize preserves this task as v1-only
        legacy = ProductResponseAnalysis(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            task_id=task.id,
            artifact_id=legacy_artifact.id,
            product_analyzer_version=_V1_ANALYZER,
            product_scoring_rule_version=_V1_RULE,
            logical_engine=task.logical_engine,
            transport_provider=task.transport_provider,
            transport_model=task.transport_model,
            prompt_index=0,
            repetition=0,
            shopping_surface="",
            score={
                "products": [],
                "competitor_products": [],
                "own_product_mention_count": 1,
                "competitor_product_mention_count": 0,
                "products_with_price_match": 0,
            },
        )
        session.add(legacy)
        await session.flush()
        session.add(
            ProductMention(
                workspace_id=seed.workspace_id,
                audit_id=audit.id,
                analysis_id=legacy.id,
                artifact_id=legacy_artifact.id,
                product_analyzer_version=_V1_ANALYZER,
                product_id=product.id,
                matched_name=product.name,
                matched_sku=product.sku,
                price_matches_catalog=False,
            )
        )
        current_task = _clone_surface_task(task, surface="", repetition=1)
        session.add(current_task)
        await session.flush()
        await _persist_answer(session, current_task)
        current = await analyze_task_products(
            session,
            task=current_task,
            config=build_product_scoring_config(stored.configuration),
        )
        assert current is not None
        await finalize_audit_product_analysis(session, audit=stored)
        stored.status = AUDIT_STATUS_COMPLETED
        stored.completed_at = datetime.now(UTC)
        await session.commit()

    response = await client.get(
        f"/api/v1/products/{product.id}/visibility/evidence",
        params={"audit_id": str(audit.id)},
        headers=_headers(seed),
    )
    assert response.status_code == 200
    mentions = [
        item
        for item in response.json()["items"]
        if item["evidence_kind"] == "product_mention"
    ]
    assert {
        (item["product_analyzer_version"], item["price_relation"]) for item in mentions
    } == {(_V1_ANALYZER, "mismatch"), (PRODUCT_ANALYZER_VERSION, "match")}
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductResponseAnalysis)
                .where(ProductResponseAnalysis.audit_id == audit.id)
            )
            == 2
        )
        assert PRODUCT_SCORING_RULE_VERSION
