"""Focused pure contracts for the Commerce discovery worker."""

from __future__ import annotations

import contextlib
import hashlib
import json
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

import app.workers.commerce_discovery_worker as worker_module
from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    FetchCallTrace,
    FetchResult,
)
from app.core.config.commerce import (
    COMMERCE_CANDIDATE_KIND_COMPETITOR,
    COMMERCE_CANDIDATE_KIND_OWN,
    COMMERCE_EVIDENCE_KIND_CRAWLED,
    COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING,
    COMMERCE_EVIDENCE_KIND_STRUCTURED,
    commerce_intelligence_settings,
)
from app.models.commerce import CommerceDiscoveryRun
from app.workers.commerce_discovery_worker import (
    CommerceDiscoveryWorker,
    _candidate_conflict_identity,
    _configured_candidate_target,
    _evidence_kind,
    _safe_acquisition,
)


def _hash(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _result(*, url: str, content_type: str = "text/html") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=200,
        redacted_headers={"content-type": content_type},
        content_type=content_type,
        http_version="HTTP/2",
        body=b"<html>raw-html-contains-super-secret</html>",
        wire_bytes=42,
        decoded_bytes=42,
        ttfb_ms=5,
        latency_ms=9,
        attempts=(
            FetchCallTrace(
                request_ordinal=0,
                url=url,
                method="GET",
                status_code=200,
                error_code=None,
                wire_bytes=42,
                decoded_bytes=42,
                ttfb_ms=5,
                latency_ms=9,
                acquisition=AcquisitionProvenance(
                    transport="patchright",
                    rung=3,
                    options={"max_captured_responses": 16},
                ),
            ),
        ),
        acquisition=AcquisitionProvenance(transport="patchright", rung=3),
    )


def test_candidate_conflict_identity_separates_own_and_competitor() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    competitor_id = uuid.uuid4()
    identity = {"name": "Widget", "sku": "W-1", "attributes": {"brand": "Acme"}}
    own = _candidate_conflict_identity(
        identity,
        candidate_kind=COMMERCE_CANDIDATE_KIND_OWN,
        competitor_id=None,
        run_id=run_id,
        task_id=task_id,
        source_url="https://example.com/widget#details",
    )
    competitor = _candidate_conflict_identity(
        identity,
        candidate_kind=COMMERCE_CANDIDATE_KIND_COMPETITOR,
        competitor_id=competitor_id,
        run_id=run_id,
        task_id=task_id,
        source_url="https://example.com/widget#details",
    )

    assert _hash(own) != _hash(competitor)
    assert own["name"] == competitor["name"] == "Widget"


def test_candidate_conflict_identity_keeps_a_true_retry_idempotent() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    kwargs = {
        "candidate_kind": COMMERCE_CANDIDATE_KIND_OWN,
        "competitor_id": None,
        "run_id": run_id,
        "task_id": task_id,
        "source_url": "https://example.com/widget#fragment",
    }

    first = _candidate_conflict_identity({"name": "Widget", "sku": "W-1"}, **kwargs)
    retry = _candidate_conflict_identity({"sku": "W-1", "name": "Widget"}, **kwargs)

    assert first == retry
    assert _hash(first) == _hash(retry)
    assert first["_commerce_discovery_conflict_context"]["source_url"].endswith(
        "/widget"
    )


def test_safe_acquisition_is_bounded_and_excludes_raw_html_and_secrets() -> None:
    persisted = _safe_acquisition(_result(url="https://example.com/widget"))
    serialized = json.dumps(persisted)

    assert persisted["attempts"] == persisted["attempts"][:1]
    assert "raw-html-contains-super-secret" not in serialized
    assert "authorization" not in serialized
    assert "body" not in persisted
    assert persisted["provenance"]["transport"] == "patchright"


def test_extract_product_preserves_late_node_from_final_schema_document() -> None:
    limit = commerce_intelligence_settings.discovery_max_schema_nodes
    first_document = {"@graph": [{"@type": "Thing"}] * (limit // 2)}
    second_document = {
        "@graph": [
            *([{"@type": "Thing"}] * (limit // 2)),
            {"@type": "Product", "name": "Late Widget", "sku": "LATE-1"},
        ]
    }
    body = (
        "<html><script type='application/ld+json'>"
        + json.dumps(first_document)
        + "</script><script type='application/ld+json'>"
        + json.dumps(second_document)
        + "</script></html>"
    ).encode()
    result = replace(
        _result(url="https://example.com/late-widget"),
        body=body,
        wire_bytes=len(body),
        decoded_bytes=len(body),
    )

    extracted = worker_module._extract_product(result)

    assert extracted is not None
    identity, _evidence = extracted
    assert identity["name"] == "Late Widget"
    assert identity["sku"] == "LATE-1"


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    [
        (
            "https://shop.google.test/product/1",
            "text/html",
            COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING,
        ),
        (
            "https://feed.example.test/product/1",
            "application/json",
            COMMERCE_EVIDENCE_KIND_STRUCTURED,
        ),
        (
            "https://www.example.test/product/1",
            "text/html",
            COMMERCE_EVIDENCE_KIND_CRAWLED,
        ),
    ],
)
def test_evidence_kind_classification(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    content_type: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        commerce_intelligence_settings,
        "discovery_google_shopping_source_hosts",
        ("shop.google.test",),
    )
    assert _evidence_kind(_result(url=url, content_type=content_type)) == expected


def test_invalid_configured_competitor_target_fails_closed_to_own() -> None:
    run = SimpleNamespace(
        configuration={
            "candidate_kind": COMMERCE_CANDIDATE_KIND_COMPETITOR,
            "competitor_id": "not-a-uuid",
        }
    )

    assert _configured_candidate_target(run) == (COMMERCE_CANDIDATE_KIND_OWN, None)


async def test_acquire_success_uses_configured_competitor_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    competitor_id = uuid.uuid4()
    run = SimpleNamespace(
        configuration={
            "candidate_kind": COMMERCE_CANDIDATE_KIND_COMPETITOR,
            "competitor_id": str(competitor_id),
        }
    )
    claimed = SimpleNamespace(
        id=task_id,
        run_id=run_id,
        source_url="https://competitor.example.test/widget",
    )
    calls: dict[str, object] = {}

    class Session:
        async def get(self, model: type, identifier: uuid.UUID):
            assert model is CommerceDiscoveryRun
            assert identifier == run_id
            return run

        async def commit(self) -> None:
            calls["committed"] = True

    class SessionFactory:
        def __call__(self):
            return self

        async def __aenter__(self) -> Session:
            return Session()

        async def __aexit__(self, *_: object) -> None:
            return None

    class Fetcher:
        async def __aenter__(self) -> Fetcher:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def fetch(self, _request: object) -> FetchResult:
            return _result(url="https://competitor.example.test/widget")

    @contextlib.asynccontextmanager
    async def leased(_task_id: uuid.UUID):
        yield

    async def finalize(_session: object, **kwargs: object) -> uuid.UUID:
        calls.update(kwargs)
        return uuid.uuid4()

    worker = CommerceDiscoveryWorker(session_factory=SessionFactory())
    monkeypatch.setattr(worker, "_leased", leased)
    monkeypatch.setattr(worker, "_new_fetcher", Fetcher)
    monkeypatch.setattr(
        worker_module,
        "_extract_product",
        lambda _result: ({"name": "Widget", "sku": "W-1"}, {"schema_types": []}),
    )
    monkeypatch.setattr(worker_module, "finalize_discovery_success", finalize)

    await worker._acquire_and_finalize(claimed)

    assert calls["candidate_kind"] == COMMERCE_CANDIDATE_KIND_COMPETITOR
    assert calls["competitor_id"] == competitor_id
    assert calls["committed"] is True
