"""Commerce discovery/review/comparison API contracts."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.commerce import (
    COMMERCE_DISCOVERY_QUEUE_SPEC,
    COMMERCE_EVIDENCE_KIND_CRAWLED,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.models.commerce import (
    CommerceDiscoveryArtifact,
    CommerceDiscoveryRun,
    CommerceDiscoveryTask,
)
from app.models.project import Project
from app.models.workspace import Workspace
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.commerce_discovery_worker import CommerceDiscoveryWorker


async def _register(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "commerce-intelligence@example.com", "password": "password123"},
    )
    assert response.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": "commerce-intelligence@example.com", "password": "password123"},
    )
    assert login_response.status_code == 200


async def _project(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": "Commerce intelligence",
            "brand_name": "Northwind",
            "competitors": [{"name": "Contoso", "aliases": [], "domains": []}],
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_discovery_review_preserves_provenance_and_comparison(
    client: httpx.AsyncClient,
) -> None:
    await _register(client)
    project = await _project(client)
    own_run = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/discovery/runs",
        json={
            "input_kind": "upload",
            "rows": [
                {
                    "candidate_kind": "own",
                    "sku": "NW-1",
                    "name": "Northwind Trail Shoe",
                    "url": "https://northwind.example/trail-shoe",
                    "attributes": {"brand": "Northwind", "gtin": "0123456789012"},
                }
            ],
        },
    )
    assert own_run.status_code == 201
    own_candidate = own_run.json()["candidates"][0]
    runs = await client.get(f"/api/v1/projects/{project['id']}/commerce/discovery/runs")
    assert runs.status_code == 200
    assert runs.json()[0]["id"] == own_run.json()["id"]
    accepted = await client.post(
        f"/api/v1/projects/commerce/discovery/candidates/{own_candidate['id']}/accept",
        json={"status": "accepted"},
    )
    assert accepted.status_code == 200
    product_id = accepted.json()["product_id"]
    product = await client.get(f"/api/v1/products/{product_id}")
    assert product.status_code == 200
    assert product.json()["origin"] == "discovered"
    assert product.json()["source_candidate_id"] == own_candidate["id"]
    edited = await client.patch(
        f"/api/v1/products/{product_id}", json={"name": "Northwind Trail Shoe v2"}
    )
    assert edited.status_code == 200
    assert edited.json()["source_candidate_id"] == own_candidate["id"]

    competitor_id = project["competitors"][0]["id"]
    competitor_run = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/discovery/runs",
        json={
            "input_kind": "upload",
            "rows": [
                {
                    "candidate_kind": "competitor",
                    "competitor_id": competitor_id,
                    "name": "Contoso Trail Shoe",
                    "price": 120,
                    "currency": "USD",
                    "availability": "in_stock",
                    "attributes": {"brand": "Contoso", "mpn": "CT-1"},
                }
            ],
        },
    )
    assert competitor_run.status_code == 201
    competitor_candidate = competitor_run.json()["candidates"][0]
    reviewed = await client.post(
        f"/api/v1/projects/commerce/discovery/candidates/{competitor_candidate['id']}/accept",
        json={"status": "accepted"},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["competitor_product_id"]

    comparison = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/comparisons",
        json={"competitor_id": competitor_id},
    )
    assert comparison.status_code == 201
    body = comparison.json()
    assert body["source_catalog_ids"]["products"] == [product_id]
    assert body["comparison"]["coverage"]["competitor_total"] == 1
    assert body["comparison"]["items"][0]["evidence_kind"]["competitor"] == "discovery"

    history = await client.get(f"/api/v1/projects/{project['id']}/commerce/comparisons")
    assert history.status_code == 200
    assert history.json()[0]["id"] == body["id"]


@pytest.mark.asyncio
async def test_accept_rejects_an_explicit_target_outside_candidate_matches(
    client: httpx.AsyncClient,
) -> None:
    await _register(client)
    project = await _project(client)
    run = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/discovery/runs",
        json={
            "input_kind": "upload",
            "rows": [{"candidate_kind": "own", "name": "Unmatched product"}],
        },
    )
    candidate_id = run.json()["candidates"][0]["id"]

    response = await client.post(
        f"/api/v1/projects/commerce/discovery/candidates/{candidate_id}/accept",
        json={"status": "accepted", "target_id": str(uuid.uuid4())},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


@pytest.mark.asyncio
async def test_commerce_discovery_and_comparisons_are_workspace_scoped(
    client: httpx.AsyncClient,
) -> None:
    await _register(client)
    project = await _project(client)
    run = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/discovery/runs",
        json={
            "input_kind": "upload",
            "rows": [{"candidate_kind": "own", "name": "Scoped product"}],
        },
    )
    assert run.status_code == 201
    candidate_id = run.json()["candidates"][0]["id"]

    other_workspace = await client.post(
        "/api/v1/workspaces", json={"name": "Separate commerce workspace"}
    )
    assert other_workspace.status_code == 201
    headers = {"X-Workspace-Id": other_workspace.json()["id"]}

    candidates = await client.get(
        f"/api/v1/projects/{project['id']}/commerce/discovery/candidates",
        headers=headers,
    )
    assert candidates.status_code == 404
    comparison = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/comparisons",
        json={},
        headers=headers,
    )
    assert comparison.status_code == 404
    review = await client.post(
        f"/api/v1/projects/commerce/discovery/candidates/{candidate_id}/accept",
        json={"status": "accepted"},
        headers=headers,
    )
    assert review.status_code == 404


@pytest.mark.asyncio
async def test_discovery_task_uses_shared_postgres_queue_contract(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace = Workspace(name="Commerce queue workspace")
        session.add(workspace)
        await session.flush()
        project = Project(workspace_id=workspace.id, name="Commerce queue project")
        session.add(project)
        await session.flush()
        run = CommerceDiscoveryRun(
            workspace_id=workspace.id,
            project_id=project.id,
            input_kind="url",
        )
        session.add(run)
        await session.flush()
        task = CommerceDiscoveryTask(
            run_id=run.id,
            workspace_id=workspace.id,
            project_id=project.id,
            source_key="queue-contract",
            idempotency_key="commerce-queue-contract",
        )
        session.add(task)
        await session.commit()

    queue = PostgresTaskQueue(session_factory, COMMERCE_DISCOVERY_QUEUE_SPEC)
    claimed = await queue.claim(owner="commerce-worker", limit=1)
    assert [item.id for item in claimed] == [task.id]
    assert await queue.mark_running(task_id=task.id, owner="commerce-worker")
    assert await queue.heartbeat(task_id=task.id, owner="commerce-worker")
    assert await queue.succeed(task_id=task.id, owner="commerce-worker")


@pytest.mark.asyncio
async def test_reclaimed_crawl_task_with_an_artifact_succeeds_idempotently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second claim after the artifact was written must not fail the task.

    Lease expiry and redeploys re-claim a task whose acquisition already
    landed. Both input kinds answer the same question — is there already an
    artifact? — so a crawl-style rerun terminalizes on that artifact exactly
    like an upload, rather than burning a terminal failure and never
    reconciling the run.
    """
    async with session_factory() as session:
        workspace = Workspace(name="Commerce rerun workspace")
        session.add(workspace)
        await session.flush()
        project = Project(workspace_id=workspace.id, name="Commerce rerun project")
        session.add(project)
        await session.flush()
        run = CommerceDiscoveryRun(
            workspace_id=workspace.id,
            project_id=project.id,
            input_kind="url",
        )
        session.add(run)
        await session.flush()
        task = CommerceDiscoveryTask(
            run_id=run.id,
            workspace_id=workspace.id,
            project_id=project.id,
            source_key="https://example.com/p/1",
            idempotency_key="commerce-rerun-existing-artifact",
        )
        session.add(task)
        await session.flush()
        artifact = CommerceDiscoveryArtifact(
            task_id=task.id,
            run_id=run.id,
            workspace_id=workspace.id,
            project_id=project.id,
            evidence_kind=COMMERCE_EVIDENCE_KIND_CRAWLED,
            source_url="https://example.com/p/1",
            content_hash="a" * 64,
        )
        session.add(artifact)
        await session.commit()
        task_id, artifact_id = task.id, artifact.id

    worker = CommerceDiscoveryWorker(
        session_factory=session_factory, owner="commerce-rerun"
    )
    queue = PostgresTaskQueue(session_factory, COMMERCE_DISCOVERY_QUEUE_SPEC)
    claimed = await queue.claim(owner=worker.owner, limit=1)
    assert [item.id for item in claimed] == [task_id]

    assert await worker._ack_upload_or_existing(claimed[0]) is True

    async with session_factory() as session:
        settled = await session.get(CommerceDiscoveryTask, task_id)
        assert settled is not None
        assert settled.status == TASK_STATUS_SUCCEEDED
        assert settled.result_artifact_id == artifact_id
        assert settled.error_code == ""
