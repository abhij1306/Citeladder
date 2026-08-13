"""Component tests for the GA4 sync path (I11).

Runs the real ``IntegrationWorker`` against a live Postgres schema with an
injected fake Google OAuth + GA4 Data API (``httpx.MockTransport``;
recorded ``runReport`` fixtures). Covers the full worker contract for a
GA4 connection riding the ONE shared Google grant (no new OAuth):

  - claim -> serialized refresh (shared grant) -> paged ``runReport``
    import (one immutable artifact per page) -> derivation metric rows
    with the full provenance triple + C1-packed ``dimension_key``.
  - The runReport -> GSC-shaped row mapping (``keys`` in declared
    template order incl. the compact GA4 date; metric strings coerced to
    numbers).
  - Empty result pages, and a 401 marking the grant ``needs_reauth``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
    ANALYTICS_TASK_KIND_INGEST_REFERRALS,
    ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH,
)
from app.core.config.integrations import (
    DATASET_GA4_CHANNEL_DAILY,
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_LANDING_DAILY,
    DATASET_GA4_REFERRER_DAILY,
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
    ERROR_GA4_DIMENSION_INCOMPATIBLE,
    ERROR_GRANT_AUTH_FAILED,
    ERROR_PROVIDER_API,
    EVENT_INTEGRATION_REAUTH_REQUIRED,
    EVENT_INTEGRATION_SYNC_FINISHED,
    EVENT_INTEGRATION_SYNC_STARTED,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
    GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    GRANT_STATUS_CONNECTED,
    GRANT_STATUS_NEEDS_REAUTH,
    INTEGRATION_IMPORTER_VERSION,
    INTEGRATION_PROVIDER_GA4,
    INTEGRATION_TRANSPORT_GOOGLE,
    integration_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.integrations.sync import enqueue_sync_run
from app.models.analytics import AnalyticsTask
from app.models.brand import OwnedDomain
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationImportArtifact,
    IntegrationMetricRow,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
)
from app.models.project import Project
from app.models.workspace import Workspace
from app.workers.integration_worker import IntegrationWorker

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integrations"
_WINDOW = (date(2026, 7, 20), date(2026, 7, 22))
_PROPERTY_REF = "123456789"

# The datasets a GA4 run pages by default (no persisted capability): the
# four session datasets, ecommerce source/medium, and the primary item report.
# The channel-group item template runs only as the recorded
# fallback (exactly one item template per run).
_GA4_DATASETS = (
    DATASET_GA4_CHANNEL_DAILY,
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_REFERRER_DAILY,
    DATASET_GA4_LANDING_DAILY,
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
)

# GA4's realistic dimension-incompatibility 400 detail (carries the
# config-owned "incompatib" classifier marker).
_INCOMPATIBLE_DETAIL = (
    "The selected dimensions and metrics are incompatible and can not be "
    "queried together."
)


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _fast_pacing_and_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep request pacing out of the test timing budget and give the OAuth
    # refresh path env-injected client credentials (never logged).
    monkeypatch.setattr(integration_settings, "ga4_requests_per_minute", 60000)
    monkeypatch.setattr(settings, "integration_google_client_id", "test-client-id")
    monkeypatch.setattr(
        settings, "integration_google_client_secret", "test-client-secret"
    )


class _ProviderFake:
    """The fake Google OAuth + GA4 Data API, routing by request host.

    ``drop_row`` swaps the channel dataset's first page for a variant whose
    second row is malformed (a non-numeric metric): the raw page is FULL
    (2 rows) but normalization keeps only 1 — the paging-termination
    regression fixture. ``item_incompatible`` makes the PRIMARY item
    source/medium report reject with the realistic incompatible-dimension
    HTTP 400 (the narrow fallback trigger); ``item_generic_400`` makes it
    reject with a 400 whose detail carries NO incompatibility marker (no
    fallback).
    """

    def __init__(
        self,
        *,
        ga4_status: int = 200,
        empty: bool = False,
        drop_row: bool = False,
        item_incompatible: bool = False,
        item_generic_400: bool = False,
    ) -> None:
        self.token_calls: list[httpx.Request] = []
        self.ga4_auth: list[str] = []
        self.ga4_urls: list[str] = []
        self.ga4_requests: list[dict] = []
        self._ga4_status = ga4_status
        self._empty = empty
        self._drop_row = drop_row
        self._item_incompatible = item_incompatible
        self._item_generic_400 = item_generic_400

    def _ga4_response(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.ga4_auth.append(request.headers.get("authorization", ""))
        self.ga4_urls.append(str(request.url))
        self.ga4_requests.append(body)
        if self._ga4_status != 200:
            return httpx.Response(
                self._ga4_status, json={"error": {"message": "ga4 boom"}}
            )
        if self._empty:
            return httpx.Response(200, json={"rowCount": 0})
        dimensions = tuple(entry.get("name") for entry in body.get("dimensions") or ())
        metrics = tuple(entry.get("name") for entry in body.get("metrics") or ())
        offset = int(body.get("offset") or 0)
        if "itemId" in dimensions:
            if "sessionDefaultChannelGroup" in dimensions:
                if offset:
                    return httpx.Response(200, json={"rows": [], "rowCount": 2})
                payload = _fixture("ga4_run_report_item_channel_group.json")
            else:
                # The PRIMARY item source/medium report.
                if self._item_incompatible:
                    return httpx.Response(
                        400, json={"error": {"message": _INCOMPATIBLE_DETAIL}}
                    )
                if self._item_generic_400:
                    return httpx.Response(
                        400,
                        json={"error": {"message": "Invalid JSON payload received."}},
                    )
                if offset:
                    return httpx.Response(200, json={"rows": [], "rowCount": 2})
                payload = _fixture("ga4_run_report_item_source_medium.json")
        elif "transactions" in metrics:
            # The ecommerce source/medium report (order-level A1 measures).
            if offset:
                return httpx.Response(200, json={"rows": [], "rowCount": 2})
            payload = _fixture("ga4_run_report_ecommerce_source_medium.json")
        elif "sessionDefaultChannelGroup" in dimensions:
            if offset:
                payload = _fixture("ga4_run_report_page2.json")
            elif self._drop_row:
                payload = _fixture("ga4_run_report_page1_dropped_row.json")
            else:
                payload = _fixture("ga4_run_report_page1.json")
        elif "sessionSource" in dimensions and "landingPage" in dimensions:
            payload = _fixture("ga4_run_report_landing.json")
        elif "sessionSource" in dimensions:
            payload = _fixture("ga4_run_report_source_medium.json")
        else:
            payload = _fixture("ga4_run_report_referrer.json")
        return httpx.Response(200, json=payload)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_calls.append(request)
            return httpx.Response(
                200,
                json={
                    "access_token": "fresh-access-token",
                    "expires_in": 3600,
                    "scope": "scope-a scope-b",
                },
            )
        if request.url.host == "analyticsdata.googleapis.com":
            return self._ga4_response(request)
        raise AssertionError(f"unexpected request: {request.url}")

    def mock_transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


async def _seed_graph(
    db_session,
    *,
    grant_status: str = GRANT_STATUS_CONNECTED,
    token_expires_at: datetime | None = None,
    account_ref: str = _PROPERTY_REF,
    mapping_ref: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    workspace = Workspace(name="Acme")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme Site")
    db_session.add(project)
    await db_session.flush()
    db_session.add(OwnedDomain(project_id=project.id, domain="example.com"))
    grant = IntegrationOAuthGrant(
        workspace_id=workspace.id,
        transport=INTEGRATION_TRANSPORT_GOOGLE,
        access_token_encrypted=encrypt_secret("access-token-1"),
        refresh_token_encrypted=encrypt_secret("refresh-token-1"),
        token_expires_at=token_expires_at or (datetime.now(UTC) + timedelta(hours=1)),
        granted_scopes=["scope-a"],
        status=grant_status,
    )
    db_session.add(grant)
    await db_session.flush()
    connection = IntegrationConnection(
        workspace_id=workspace.id,
        grant_id=grant.id,
        provider=INTEGRATION_PROVIDER_GA4,
        label="ga4 connection",
        account_ref=account_ref,
    )
    db_session.add(connection)
    await db_session.flush()
    db_session.add(
        IntegrationPropertyMapping(
            workspace_id=workspace.id,
            connection_id=connection.id,
            provider=INTEGRATION_PROVIDER_GA4,
            property_ref=mapping_ref if mapping_ref is not None else account_ref,
            project_id=project.id,
            status="active",
        )
    )
    await db_session.commit()
    return workspace.id, project.id, grant.id, connection.id


def _worker(
    session_factory: async_sessionmaker[AsyncSession],
    transport: httpx.AsyncBaseTransport,
) -> IntegrationWorker:
    return IntegrationWorker(
        session_factory=session_factory, owner="ga4-test", transport=transport
    )


async def _artifacts(db_session, run_id: uuid.UUID) -> list[IntegrationImportArtifact]:
    result = await db_session.scalars(
        select(IntegrationImportArtifact)
        .where(IntegrationImportArtifact.sync_run_id == run_id)
        .order_by(
            IntegrationImportArtifact.dataset.asc(),
            IntegrationImportArtifact.created_at.asc(),
            IntegrationImportArtifact.id.asc(),
        )
    )
    return list(result)


async def _metric_rows(db_session, run_id: uuid.UUID) -> list[IntegrationMetricRow]:
    artifact_ids = select(IntegrationImportArtifact.id).where(
        IntegrationImportArtifact.sync_run_id == run_id
    )
    result = await db_session.scalars(
        select(IntegrationMetricRow).where(
            IntegrationMetricRow.source_artifact_id.in_(artifact_ids)
        )
    )
    return list(result)


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _channel_requests(fake: _ProviderFake) -> list[dict]:
    """The channel-dataset runReport request bodies, in request order."""
    return [
        body
        for body in fake.ga4_requests
        if any(
            entry.get("name") == "sessionDefaultChannelGroup"
            for entry in body["dimensions"]
        )
        and not any(entry.get("name") == "itemId" for entry in body["dimensions"])
    ]


def _item_requests(fake: _ProviderFake) -> list[dict]:
    """The item-scoped runReport request bodies (either item template)."""
    return [
        body
        for body in fake.ga4_requests
        if any(entry.get("name") == "itemId" for entry in body["dimensions"])
    ]


@pytest.mark.asyncio
async def test_fixture_import_refresh_artifacts_derivation(
    session_factory, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claim -> refresh (shared grant) -> artifacts -> derivation rows."""
    monkeypatch.setattr(integration_settings, "sync_page_size", 2)
    # Near-expiry token: the worker performs the serialized refresh first.
    near_expiry = datetime.now(UTC) + timedelta(seconds=5)
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(
        db_session, token_expires_at=near_expiry
    )
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake()

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    assert run.error_code == ""

    # Exactly ONE serialized refresh on the shared grant, then every GA4
    # call carried the fresh Bearer token (never the expired one).
    (token_call,) = fake.token_calls
    form = parse_qs(token_call.content.decode("utf-8"))
    assert form["grant_type"] == ["refresh_token"]
    grant = await db_session.get(IntegrationOAuthGrant, grant_id)
    assert decrypt_secret(grant.access_token_encrypted) == "fresh-access-token"
    assert len(fake.ga4_auth) == 9
    assert set(fake.ga4_auth) == {"Bearer fresh-access-token"}

    # The runReport requests carried the template dimensions/metrics and
    # the limit/offset paging (channel dataset paged 0 -> 2).
    channel_requests = _channel_requests(fake)
    assert [body["offset"] for body in channel_requests] == [0, 2]
    assert [body["limit"] for body in channel_requests] == [2, 2]
    assert channel_requests[0]["dateRanges"] == [
        {"startDate": "2026-07-20", "endDate": "2026-07-22"}
    ]
    assert [m["name"] for m in channel_requests[0]["metrics"]] == [
        "sessions",
        "engagedSessions",
        "keyEvents",
    ]
    # Every call hit the pinned runReport path for the connection's
    # property ref (SSRF allow-listed host).
    assert (
        fake.ga4_urls
        == [
            f"https://analyticsdata.googleapis.com/v1beta/properties/{_PROPERTY_REF}:runReport"
        ]
        * 9
    )

    artifacts = await _artifacts(db_session, run.id)
    by_dataset: dict[str, list[IntegrationImportArtifact]] = {}
    for artifact in artifacts:
        by_dataset.setdefault(artifact.dataset, []).append(artifact)
    assert sorted(by_dataset) == sorted(_GA4_DATASETS)
    # Channel dataset paged (2 rows + 1 row); the ecommerce + primary item
    # fixtures carry EXACTLY one full page (2 rows == page_size), so an
    # EMPTY second page terminates paging; the other session datasets are
    # one page each.
    channel = by_dataset[DATASET_GA4_CHANNEL_DAILY]
    assert [a.query_snapshot["startRow"] for a in channel] == [0, 2]
    assert [a.row_count for a in channel] == [2, 1]
    for dataset in (
        DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    ):
        assert [a.query_snapshot["startRow"] for a in by_dataset[dataset]] == [0, 2]
        assert [a.row_count for a in by_dataset[dataset]] == [2, 0]
    for dataset in (
        DATASET_GA4_SOURCE_MEDIUM_DAILY,
        DATASET_GA4_REFERRER_DAILY,
        DATASET_GA4_LANDING_DAILY,
    ):
        assert [a.row_count for a in by_dataset[dataset]] == [1]

    for artifact in artifacts:
        # Immutable evidence: sha256 of the normalized payload + the
        # credential-free query snapshot (invariant 6).
        assert artifact.payload_hash == _canonical_hash(artifact.payload)
        assert artifact.provider == INTEGRATION_PROVIDER_GA4
        assert artifact.query_snapshot["api_method"] == "runReport"
        snapshot_text = json.dumps(artifact.query_snapshot).lower()
        assert "token" not in snapshot_text
        assert "authorization" not in snapshot_text
        # Normalized row shape: keys in declared template order + metrics.
        if artifact.dataset == DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY:
            expected_keys = {"keys", "transactions", "purchaseRevenue", "sessions"}
        elif artifact.dataset == DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY:
            expected_keys = {"keys", "itemRevenue", "itemsPurchased"}
        else:
            expected_keys = {"keys", "sessions", "engagedSessions", "keyEvents"}
        for row in artifact.payload["rows"]:
            assert set(row) == expected_keys
            assert all(isinstance(v, str) for v in row["keys"])
            if "sessions" in row:
                assert isinstance(row["sessions"], int)
        # A1 currency evidence: only the ecommerce datasets persist the
        # property's ISO currency (runReport metadata) — and only on pages
        # that carried rows (the empty terminator page has no metadata).
        if (
            artifact.dataset
            in (
                DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
                DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
            )
            and artifact.row_count
        ):
            assert artifact.payload["currency_code"] == "USD"
        else:
            assert "currency_code" not in artifact.payload

    # Derivation: one metric row per artifact row, full provenance (inv. 4).
    rows = await _metric_rows(db_session, run.id)
    # 3 channel + 1 source/medium + 1 referrer + 1 landing + 2 ecommerce
    # source/medium + 2 primary item (empty pages derive zero rows).
    assert len(rows) == 10
    artifact_ids = {artifact.id for artifact in artifacts}
    for row in rows:
        assert row.source_artifact_id in artifact_ids
        assert row.importer_version == INTEGRATION_IMPORTER_VERSION
        assert row.resync_seq == run.resync_seq == 0
        assert row.project_id == project_id
        assert row.provider == INTEGRATION_PROVIDER_GA4
        assert row.property_ref == _PROPERTY_REF

    by_key = {(row.dataset, row.dimension_key): row for row in rows}
    organic = by_key[(DATASET_GA4_CHANNEL_DAILY, "Organic Search | 20260720")]
    assert organic.dataset == DATASET_GA4_CHANNEL_DAILY
    assert organic.date == date(2026, 7, 20)
    assert organic.metrics == {"sessions": 41, "engagedSessions": 30, "keyEvents": 2}
    referral = by_key[(DATASET_GA4_REFERRER_DAILY, "https://chatgpt.com/ | 20260721")]
    assert referral.dataset == DATASET_GA4_REFERRER_DAILY
    assert referral.metrics["sessions"] == 6
    landing = by_key[
        (DATASET_GA4_LANDING_DAILY, "/pricing | google | organic | 20260720")
    ]
    assert landing.dataset == DATASET_GA4_LANDING_DAILY
    source_medium = by_key[
        (DATASET_GA4_SOURCE_MEDIUM_DAILY, "google | organic | 20260720")
    ]
    assert source_medium.dataset == DATASET_GA4_SOURCE_MEDIUM_DAILY
    ecommerce = by_key[
        (DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY, "chatgpt.com | referral | 20260720")
    ]
    assert ecommerce.dataset == DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY
    assert ecommerce.metrics == {
        "transactions": 2,
        "purchaseRevenue": 120.5,
        "sessions": 10,
    }
    item = by_key[
        (
            DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
            "SKU-1 | chatgpt.com | referral | 20260720",
        )
    ]
    assert item.dataset == DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY
    assert item.metrics == {"itemRevenue": 80.0, "itemsPurchased": 1}
    # Sync lifecycle: started/finished events + last_synced_at + the C5
    # projection chain enqueued — dataset-aware routing: one referral
    # ingest per source/medium + referrer ARTIFACT (the two referral
    # datasets), one traffic snapshot refresh for the window (channel /
    # source-medium / landing artifacts), one attribution snapshot refresh
    # for the window (ecommerce + item artifacts).
    connection = await db_session.get(IntegrationConnection, connection_id)
    assert connection.last_synced_at is not None
    events = list(
        (
            await db_session.scalars(
                select(IntegrationEvent).where(
                    IntegrationEvent.workspace_id == workspace_id
                )
            )
        ).all()
    )
    assert [event.event_type for event in events] == [
        EVENT_INTEGRATION_SYNC_STARTED,
        EVENT_INTEGRATION_SYNC_FINISHED,
    ]
    tasks = list((await db_session.scalars(select(AnalyticsTask))).all())
    ingest_tasks = [
        task for task in tasks if task.task_kind == ANALYTICS_TASK_KIND_INGEST_REFERRALS
    ]
    refresh_tasks = [
        task
        for task in tasks
        if task.task_kind == ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH
    ]
    attribution_tasks = [
        task
        for task in tasks
        if task.task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT
    ]
    assert len(ingest_tasks) == 2
    assert len(refresh_tasks) == 1
    assert refresh_tasks[0].payload == {
        "window_start": _WINDOW[0].isoformat(),
        "window_end": _WINDOW[1].isoformat(),
        "source_revision": str(run.id),
    }
    assert len(attribution_tasks) == 1
    assert attribution_tasks[0].payload == {
        "window_start": _WINDOW[0].isoformat(),
        "window_end": _WINDOW[1].isoformat(),
        "resync_seq": 0,
    }


@pytest.mark.asyncio
async def test_prefixed_account_ref_normalizes_to_canonical_ref_and_url(
    session_factory, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``properties/``-prefixed account_ref still works end to end.

    Mappings persist the CANONICAL bare-numeric id (``create_mapping``
    normalizes) while a GA4 connection's ``account_ref`` may carry the
    provider's resource-name spelling: derivation resolves the canonical
    mapping through normalization, the runReport URL takes the bare id
    (never ``properties/properties%2F…``), and derived metric rows carry
    the canonical ref.
    """
    monkeypatch.setattr(integration_settings, "sync_page_size", 2)
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(
        db_session,
        account_ref=f"properties/{_PROPERTY_REF}",
        mapping_ref=_PROPERTY_REF,
    )
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake()

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    # Every runReport call hit the canonical bare-id path.
    assert fake.ga4_urls
    assert fake.ga4_urls == [
        f"https://analyticsdata.googleapis.com/v1beta/properties/{_PROPERTY_REF}:runReport"
    ] * len(fake.ga4_urls)
    # Derivation resolved the canonical mapping and wrote canonical refs.
    rows = await _metric_rows(db_session, run.id)
    assert rows
    assert {row.property_ref for row in rows} == {_PROPERTY_REF}


@pytest.mark.asyncio
async def test_full_raw_page_with_dropped_row_still_pages_on(
    session_factory, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A FULL raw page whose normalization dropped a row is NOT the last.

    Paging terminates on the provider's RAW row count, never the filtered
    count: the channel dataset's first page carries 2 raw rows, one with a
    non-numeric metric (dropped) — the worker must still request offset 2.
    """
    monkeypatch.setattr(integration_settings, "sync_page_size", 2)
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake(drop_row=True)

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1
    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED

    channel_requests = _channel_requests(fake)
    # Offset 2 WAS requested — the short normalized page (1 row) did not
    # terminate paging early.
    assert [body["offset"] for body in channel_requests] == [0, 2]

    artifacts = await _artifacts(db_session, run.id)
    channel = [
        artifact
        for artifact in artifacts
        if artifact.dataset == DATASET_GA4_CHANNEL_DAILY
    ]
    # row_count is the RAW provider count (the resume path's measure)...
    assert [a.row_count for a in channel] == [2, 1]
    # ...while the persisted payload keeps only the rows that normalized.
    assert [len(a.payload["rows"]) for a in channel] == [1, 1]


@pytest.mark.asyncio
async def test_retry_resumes_past_durable_page_with_dropped_row(
    session_factory, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resume path reads the same RAW count the live loop uses.

    A durable first page with raw ``row_count == page_size`` but fewer
    normalized payload rows (a dropped malformed row) resumes at the next
    offset instead of being mistaken for a complete short page.
    """
    monkeypatch.setattr(integration_settings, "sync_page_size", 2)
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    # Simulate a crashed first attempt: channel page 0 is already durable
    # with the raw count (2) vs one normalized payload row.
    normalized_page1 = {
        "rows": [
            {
                "keys": ["Organic Search", "20260720"],
                "sessions": 41,
                "engagedSessions": 30,
                "conversions": 2,
            }
        ],
        "rowCount": 3,
    }
    db_session.add(
        IntegrationImportArtifact(
            sync_run_id=run.id,
            connection_id=connection_id,
            workspace_id=workspace_id,
            provider=INTEGRATION_PROVIDER_GA4,
            dataset=DATASET_GA4_CHANNEL_DAILY,
            query_snapshot={
                "api_method": "runReport",
                "dataset": DATASET_GA4_CHANNEL_DAILY,
                "property_ref": _PROPERTY_REF,
                "startDate": _WINDOW[0].isoformat(),
                "endDate": _WINDOW[1].isoformat(),
                "dimensions": ["sessionDefaultChannelGroup", "date"],
                "metrics": ["sessions", "engagedSessions", "conversions"],
                "rowLimit": 2,
                "startRow": 0,
            },
            payload_hash=_canonical_hash(normalized_page1),
            row_count=2,
            payload=normalized_page1,
        )
    )
    await db_session.commit()
    fake = _ProviderFake(drop_row=True)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    channel_requests = _channel_requests(fake)
    # Page 0 was NOT refetched and the dataset was NOT declared complete:
    # exactly one channel request, at the resumed offset.
    assert [body["offset"] for body in channel_requests] == [2]


@pytest.mark.asyncio
async def test_empty_report_pages_write_empty_artifacts(
    session_factory, db_session
) -> None:
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake(empty=True)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    artifacts = await _artifacts(db_session, run.id)
    assert len(artifacts) == len(_GA4_DATASETS)
    assert all(artifact.row_count == 0 for artifact in artifacts)
    assert await _metric_rows(db_session, run.id) == []
    # A fresh (non-expired) grant token was used; no refresh happened.
    assert fake.token_calls == []
    assert fake.ga4_auth == ["Bearer access-token-1"] * len(_GA4_DATASETS)


@pytest.mark.asyncio
async def test_ga4_auth_failure_marks_grant_needs_reauth(
    session_factory, db_session
) -> None:
    workspace_id, _project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake(ga4_status=401)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_GRANT_AUTH_FAILED
    grant = await db_session.get(IntegrationOAuthGrant, grant_id)
    assert grant.status == GRANT_STATUS_NEEDS_REAUTH
    events = list(
        (
            await db_session.scalars(
                select(IntegrationEvent).where(
                    IntegrationEvent.workspace_id == workspace_id
                )
            )
        ).all()
    )
    assert EVENT_INTEGRATION_REAUTH_REQUIRED in [e.event_type for e in events]
    # Nothing derived, nothing projected downstream.
    assert await _metric_rows(db_session, run.id) == []
    assert list((await db_session.scalars(select(AnalyticsTask))).all()) == []


_FALLBACK_CAPABILITY = {
    "selected_dataset": DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    "source_granularity": GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    "reason": ERROR_GA4_DIMENSION_INCOMPATIBLE,
    "version": GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
}


def _dimension_names(body: dict) -> list[str]:
    return [entry.get("name") for entry in body["dimensions"]]


@pytest.mark.asyncio
async def test_item_dimension_incompatibility_falls_back_to_channel_group(
    session_factory, db_session
) -> None:
    """The NARROW item fallback: a 400 whose detail carries the GA4
    dimension-incompatibility marker on the PRIMARY item dataset switches
    the run to the channel-group item template and records the selection.

    The fallback pages in the SAME run (primary item evidence did not
    exist yet), the capability is stamped with the CURRENT version, and
    the A1 attribution chain fires off the fallback artifact.
    """
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake(item_incompatible=True)

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    assert run.error_code == ""

    # Two item-scoped calls: the rejected PRIMARY request (session
    # source/medium) then the channel-group FALLBACK request.
    item_requests = _item_requests(fake)
    assert len(item_requests) == 2
    assert "sessionSource" in _dimension_names(item_requests[0])
    assert "sessionDefaultChannelGroup" in _dimension_names(item_requests[1])

    # Exactly one item template produced artifacts: the FALLBACK one.
    artifacts = await _artifacts(db_session, run.id)
    item_datasets = {
        artifact.dataset
        for artifact in artifacts
        if artifact.dataset
        in (DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY, DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY)
    }
    assert item_datasets == {DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY}

    # The reduced-granularity selection is durable on the connection.
    connection = await db_session.get(IntegrationConnection, connection_id)
    assert connection.dataset_capabilities[GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY] == (
        _FALLBACK_CAPABILITY
    )

    # Fallback rows derive with the channel-group dimension packed (the
    # date is the LAST key part; the channel group takes the source slot).
    rows = await _metric_rows(db_session, run.id)
    by_key = {row.dimension_key: row for row in rows}
    fallback_row = by_key["SKU-1 | Referral | 20260720"]
    assert fallback_row.dataset == DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY
    assert fallback_row.metrics == {"itemRevenue": 80.0, "itemsPurchased": 1}

    # The attribution chain fired once for the window (ecommerce + item
    # artifacts share the window).
    tasks = list((await db_session.scalars(select(AnalyticsTask))).all())
    attribution_tasks = [
        task
        for task in tasks
        if task.task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT
    ]
    assert len(attribution_tasks) == 1


@pytest.mark.asyncio
async def test_persisted_capability_selects_fallback_item_template(
    session_factory, db_session
) -> None:
    """A recorded selection sticks: the NEXT run pages ONLY the fallback.

    Even with a healthy provider (the primary would now succeed), the
    persisted capability keeps the run on the channel-group item template
    so item evidence never flips granularity run over run.
    """
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    first = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    incompatible = _ProviderFake(item_incompatible=True)
    await _worker(session_factory, incompatible.mock_transport()).run_until_idle()
    await db_session.refresh(first)
    assert first.status == TASK_STATUS_SUCCEEDED

    # Second sync of the same window (resync_seq=1), provider now healthy.
    second = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    assert second.resync_seq == 1
    healthy = _ProviderFake()
    ran = await _worker(session_factory, healthy.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(second)
    assert second.status == TASK_STATUS_SUCCEEDED
    # The PRIMARY item report was never re-probed; exactly one item call,
    # carrying the channel-group dimensions.
    item_requests = _item_requests(healthy)
    assert len(item_requests) == 1
    assert _dimension_names(item_requests[0]) == [
        "itemId",
        "sessionDefaultChannelGroup",
        "date",
    ]
    artifacts = await _artifacts(db_session, second.id)
    item_datasets = {
        artifact.dataset
        for artifact in artifacts
        if artifact.dataset
        in (DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY, DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY)
    }
    assert item_datasets == {DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY}


@pytest.mark.asyncio
async def test_stale_capability_version_reprobes_primary_item_template(
    session_factory, db_session
) -> None:
    """A capability stamped with an OLDER version is NOT trusted: the run
    re-probes the primary item template (a version bump re-runs the
    primary mix, e.g. after GA4 adds the dimension combination).
    """
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    connection = await db_session.get(IntegrationConnection, connection_id)
    connection.dataset_capabilities = {
        GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY: {
            **_FALLBACK_CAPABILITY,
            "version": "ga4-item-attribution-0",  # stale
        }
    }
    await db_session.commit()
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake()

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    # The primary item report WAS paged again and produced artifacts; the
    # fallback template did not run.
    item_requests = _item_requests(fake)
    assert item_requests
    assert all("sessionSource" in _dimension_names(body) for body in item_requests)
    artifacts = await _artifacts(db_session, run.id)
    item_datasets = {
        artifact.dataset
        for artifact in artifacts
        if artifact.dataset
        in (DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY, DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY)
    }
    assert item_datasets == {DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY}


@pytest.mark.asyncio
async def test_generic_400_on_item_dataset_does_not_fall_back(
    session_factory, db_session
) -> None:
    """A 400 WITHOUT the incompatibility marker is NOT the fallback
    trigger: the run fails through the standard provider-API taxonomy and
    NO capability selection is recorded.
    """
    workspace_id, _project_id, _grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ProviderFake(item_generic_400=True)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    # No selection recorded, no fallback artifact written.
    connection = await db_session.get(IntegrationConnection, connection_id)
    assert GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY not in connection.dataset_capabilities
    artifacts = await _artifacts(db_session, run.id)
    assert {
        artifact.dataset
        for artifact in artifacts
        if artifact.dataset
        in (DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY, DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY)
    } == set()
