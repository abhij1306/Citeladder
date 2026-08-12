"""Resumable, discriminated audit SSE contract (slice1 section 8).

``GET /audits/{id}/events`` serves one discriminated contract in both modes —
the JSON list and the ``?stream=true`` SSE tail — through the DTO family in
``app/domain/audits/schemas.py``: common ``id`` / ``audit_id`` / ``event_type``
/ ``occurred_at`` plus a ``payload`` tagged on ``event_type``, every payload
schema closed (``extra="forbid"``) and secret-free.

Covered here:

- the initial stream replays persisted events in order;
- ``Last-Event-ID`` resumes strictly AFTER the cursor (never replays), a
  malformed cursor is a 422, and an unknown/foreign cursor gets the same safe
  404 a foreign audit gets;
- the terminal grace cutoff is driven by ``AuditSettings`` (monkeypatched the
  same way conftest pins settings), not by code constants;
- SSE ``event:``/``id:`` match the JSON ``event_type``/``id`` they wrap;
- every payload variant rejects unexpected fields;
- ``task.capacity_wait`` serializes through the SAME strict schema on the
  list and the stream.

The SSE loop opens its own sessions via ``SessionLocal``; stream tests point
it at the per-test schema (the ``client`` fixture only overrides the request
dependency) and shrink the poll cadence so a terminal audit's stream closes
immediately.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.audits as audits_api
import app.core.config.audits as audits_config
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    CAPACITY_CODE_CONCURRENCY,
    EVENT_AUDIT_COMPLETED,
    EVENT_TASK_CAPACITY_WAIT,
    POOL_KIND_TRANSPORT,
    AuditSettings,
    audit_settings,
)
from app.core.config.errors import CODE_NOT_FOUND, CODE_VALIDATION_ERROR
from app.domain.audits.planner import create_audit
from app.domain.audits.schemas import (
    EVENT_SCHEMA_BY_TYPE,
    AuditCompletedPayload,
    AuditCreatedPayload,
    AuditQueuedPayload,
    AuditStatusPayload,
    TaskCapacityWaitPayload,
    TaskFailedPayload,
    TaskRetryPayload,
    TaskSucceededPayload,
    audit_event_response,
)
from app.domain.audits.state_events import record_event
from app.models.audit import AuditEvent
from app.models.user import User
from app.models.workspace import WorkspaceMember
from tests.component.audit_helpers import Seed, seed_audit_fixtures


async def _register_and_seed(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> Seed:
    """Register a real user, seed an auditable workspace, attach them."""
    email = f"sse-{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        session.add(
            WorkspaceMember(
                workspace_id=seed.workspace_id, user_id=user.id, role="owner"
            )
        )
        await session.commit()
    return seed


def _headers(seed: Seed, **extra: str) -> dict[str, str]:
    return {"X-Workspace-Id": str(seed.workspace_id), **extra}


async def _create_terminal_audit(
    session_factory: async_sessionmaker[AsyncSession], seed: Seed
) -> uuid.UUID:
    """Plan a real audit (real planner events) and terminalize it.

    The terminal status is written directly — the state machine is covered
    elsewhere; what matters here is a stream that closes after the grace
    polls — and the terminal completion event is appended like the analysis
    stage records it.
    """
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
        audit.status = AUDIT_STATUS_COMPLETED
        audit.completed_at = datetime.now(UTC)
        record_event(
            session,
            audit_id=audit.id,
            event_type=EVENT_AUDIT_COMPLETED,
            message="audit completed",
            payload={
                "status": AUDIT_STATUS_COMPLETED,
                "completed": 2,
                "failed": 0,
                "visibility_score": 100.0,
            },
        )
        await session.commit()
        return audit.id


async def _load_rows(
    session_factory: async_sessionmaker[AsyncSession], audit_id: uuid.UUID
) -> list[AuditEvent]:
    """Persisted events in stream order (mirrors ``_load_events``)."""
    async with session_factory() as session:
        stmt = (
            select(AuditEvent)
            .where(AuditEvent.audit_id == audit_id)
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
        return list((await session.scalars(stmt)).all())


def _parse_sse(body: str) -> list[dict[str, Any]]:
    """Parse SSE frames into {event, id, data(dict)} triples."""
    frames: list[dict[str, Any]] = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        frame: dict[str, Any] = {}
        for line in raw.splitlines():
            key, _, value = line.partition(": ")
            frame[key] = value
        frame["data"] = json.loads(frame["data"])
        frames.append(frame)
    return frames


async def _read_stream(
    client: httpx.AsyncClient,
    audit_id: uuid.UUID,
    *,
    headers: dict[str, str],
    timeout: float = 10.0,
) -> str:
    """Read an SSE response to completion (bounded, so a hanging loop fails)."""
    async with client.stream(
        "GET", f"/api/v1/audits/{audit_id}/events?stream=true", headers=headers
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = await asyncio.wait_for(resp.aread(), timeout)
    return body.decode()


@pytest.fixture
async def _fast_stream(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Bind the SSE loop to the per-test schema with an instant poll cadence.

    ``_event_stream`` opens private sessions via ``SessionLocal`` (the request
    session is long closed by then), so it must be pointed at the test schema
    explicitly; the poll/terminal-grace knobs are monkeypatched on the
    settings singleton exactly the way conftest pins settings.
    """
    monkeypatch.setattr(audits_api, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_settings, "sse_poll_seconds", 0.01)


async def test_initial_stream_replays_events_in_order(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _fast_stream: None,
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    rows = await _load_rows(session_factory, audit_id)
    assert len(rows) >= 3  # planner lifecycle + terminal completion

    body = await _read_stream(client, audit_id, headers=_headers(seed))
    frames = _parse_sse(body)
    assert [f["id"] for f in frames] == [str(r.id) for r in rows]
    assert [f["data"]["event_type"] for f in frames] == [r.event_type for r in rows]

    # The JSON list shares the same discriminated DTOs and envelope fields.
    listed = await client.get(
        f"/api/v1/audits/{audit_id}/events", headers=_headers(seed)
    )
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [str(r.id) for r in rows]
    for event in listed.json():
        assert set(event) == {
            "id",
            "audit_id",
            "event_type",
            "occurred_at",
            "payload",
        }


async def test_resume_after_id_streams_only_later_events(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _fast_stream: None,
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    rows = await _load_rows(session_factory, audit_id)
    cursor = rows[0].id

    headers = _headers(seed, **{"Last-Event-ID": str(cursor)})
    body = await _read_stream(client, audit_id, headers=headers)
    frames = _parse_sse(body)
    # Only LATER events stream — the cursor event is never replayed.
    assert [f["id"] for f in frames] == [str(r.id) for r in rows[1:]]
    assert str(cursor) not in {f["id"] for f in frames}

    # The JSON list honors the same cursor.
    listed = await client.get(f"/api/v1/audits/{audit_id}/events", headers=headers)
    assert listed.status_code == 200
    assert [e["id"] for e in listed.json()] == [str(r.id) for r in rows[1:]]


@pytest.mark.parametrize("suffix", ["", "?stream=true"])
async def test_malformed_last_event_id_returns_422(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    suffix: str,
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    headers = _headers(seed, **{"Last-Event-ID": "not-a-uuid"})
    resp = await client.get(
        f"/api/v1/audits/{audit_id}/events{suffix}", headers=headers
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == CODE_VALIDATION_ERROR
    assert body["error"]["request_id"]


async def test_unknown_and_foreign_cursors_return_safe_not_found(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    # An event that belongs to a DIFFERENT audit in the same workspace.
    other_audit_id = await _create_terminal_audit(session_factory, seed)
    foreign_cursor = (await _load_rows(session_factory, other_audit_id))[0].id

    # Baseline shape: the safe not-found a foreign/missing AUDIT gets.
    missing = await client.get(
        f"/api/v1/audits/{uuid.uuid4()}/events", headers=_headers(seed)
    )
    assert missing.status_code == 404

    for cursor in (uuid.uuid4(), foreign_cursor):  # unknown, then foreign
        headers = _headers(seed, **{"Last-Event-ID": str(cursor)})
        for suffix in ("", "?stream=true"):
            resp = await client.get(
                f"/api/v1/audits/{audit_id}/events{suffix}", headers=headers
            )
            # Never a 200 replay from the beginning; the 404 shape is
            # identical to a foreign audit's, leaking nothing.
            assert resp.status_code == 404
            body = resp.json()
            assert body["detail"] == missing.json()["detail"]
            assert body["error"]["code"] == CODE_NOT_FOUND
            assert body["error"]["message"] == missing.json()["error"]["message"]


async def test_terminal_grace_comes_from_config(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With grace=1 and a 30s poll the stream must close after ONE pass.

    A hard-coded grace of 2 would sleep the (also config-read) 30s poll
    before its second pass and blow the 5s read budget — so completing in
    time proves the loop reads BOTH knobs from ``AuditSettings``.
    """
    monkeypatch.setattr(audits_api, "SessionLocal", session_factory)
    monkeypatch.setattr(audit_settings, "sse_terminal_grace_polls", 1)
    monkeypatch.setattr(audit_settings, "sse_poll_seconds", 30.0)
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    rows = await _load_rows(session_factory, audit_id)

    body = await _read_stream(client, audit_id, headers=_headers(seed), timeout=5.0)
    frames = _parse_sse(body)
    assert [f["id"] for f in frames] == [str(r.id) for r in rows]


async def test_sse_event_and_id_match_the_json_envelope(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _fast_stream: None,
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    rows = await _load_rows(session_factory, audit_id)
    row_ids = {str(r.id) for r in rows}

    body = await _read_stream(client, audit_id, headers=_headers(seed))
    for frame in _parse_sse(body):
        data = frame["data"]
        # SSE event: IS the JSON event_type; SSE id: IS the JSON id.
        assert frame["event"] == data["event_type"]
        assert frame["id"] == data["id"]
        # The cursor is the persisted event's UUID (the resume token).
        assert data["id"] in row_ids
        assert data["audit_id"] == str(audit_id)
        assert data["occurred_at"]


async def test_capacity_wait_uses_one_schema_on_list_and_stream(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    _fast_stream: None,
) -> None:
    seed = await _register_and_seed(client, session_factory)
    audit_id = await _create_terminal_audit(session_factory, seed)
    # The exact payload the worker persists for a capacity park (opaque ids +
    # retry timing only — invariant 6).
    expected_payload = {
        "task_id": str(uuid.uuid4()),
        "code": CAPACITY_CODE_CONCURRENCY,
        "pool_kind": POOL_KIND_TRANSPORT,
        "available_at": datetime.now(UTC).isoformat(),
        "retry_after_seconds": 2.0,
    }
    async with session_factory() as session:
        record_event(
            session,
            audit_id=audit_id,
            event_type=EVENT_TASK_CAPACITY_WAIT,
            message="task waiting on provider capacity",
            payload=expected_payload,
        )
        await session.commit()

    listed = await client.get(
        f"/api/v1/audits/{audit_id}/events", headers=_headers(seed)
    )
    assert listed.status_code == 200
    from_list = next(
        e for e in listed.json() if e["event_type"] == EVENT_TASK_CAPACITY_WAIT
    )

    body = await _read_stream(client, audit_id, headers=_headers(seed))
    from_stream = next(
        f["data"] for f in _parse_sse(body) if f["event"] == EVENT_TASK_CAPACITY_WAIT
    )

    # One shared strict DTO across both surfaces, payload verbatim.
    assert from_list == from_stream
    assert from_list["payload"] == expected_payload


def test_sse_knobs_are_config_owned_with_shipped_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The poll cadence + grace cutoff live in AuditSettings (invariant 1)."""
    monkeypatch.delenv("AUDIT_SSE_POLL_SECONDS", raising=False)
    monkeypatch.delenv("AUDIT_SSE_TERMINAL_GRACE_POLLS", raising=False)
    fresh = AuditSettings()
    assert fresh.sse_poll_seconds == 1.0
    assert fresh.sse_terminal_grace_polls == 2

    monkeypatch.setenv("AUDIT_SSE_POLL_SECONDS", "0.25")
    monkeypatch.setenv("AUDIT_SSE_TERMINAL_GRACE_POLLS", "5")
    overridden = AuditSettings()
    assert overridden.sse_poll_seconds == 0.25
    assert overridden.sse_terminal_grace_polls == 5


def test_every_config_event_type_has_a_discriminator_schema() -> None:
    """Every EVENT_* token maps to a union variant (the add-a-type rule)."""
    tokens = {
        value
        for name, value in vars(audits_config).items()
        if name.startswith("EVENT_") and isinstance(value, str)
    }
    assert tokens, "expected the config module to own the event vocabulary"
    assert tokens <= set(EVENT_SCHEMA_BY_TYPE)


def test_unmapped_event_type_raises_instead_of_streaming_untyped() -> None:
    ghost = SimpleNamespace(
        id=uuid.uuid4(),
        audit_id=uuid.uuid4(),
        event_type="audit.ghost",
        created_at=datetime.now(UTC),
        payload={},
    )
    with pytest.raises(ValueError, match="audit.ghost"):
        audit_event_response(ghost)


_VALID_PAYLOADS: dict[type, dict[str, Any]] = {
    AuditCreatedPayload: {"requested_count": 2, "engines": ["gemini"]},
    AuditQueuedPayload: {"task_count": 2},
    AuditStatusPayload: {"status": "running"},
    AuditCompletedPayload: {
        "status": AUDIT_STATUS_COMPLETED,
        "completed": 2,
        "failed": 0,
        "visibility_score": 100.0,
    },
    TaskSucceededPayload: {"task_id": uuid.uuid4()},
    TaskFailedPayload: {"task_id": uuid.uuid4(), "error_code": "provider_timeout"},
    TaskRetryPayload: {"task_id": uuid.uuid4(), "error_code": "provider_timeout"},
    TaskCapacityWaitPayload: {
        "task_id": uuid.uuid4(),
        "code": CAPACITY_CODE_CONCURRENCY,
        "pool_kind": POOL_KIND_TRANSPORT,
    },
}

# Every payload schema referenced by the union (the audit.running variant
# carries no payload — its envelope pins ``payload: None``).
_PAYLOAD_SCHEMAS = sorted(
    {
        variant.model_fields["payload"].annotation
        for variant in EVENT_SCHEMA_BY_TYPE.values()
    }
    - {type(None), None},
    key=lambda schema: schema.__name__,
)


@pytest.mark.parametrize("schema", _PAYLOAD_SCHEMAS, ids=lambda s: s.__name__)
def test_payload_schemas_forbid_unexpected_fields(schema: type) -> None:
    """extra='forbid' on EVERY variant — no payload may grow silently."""
    assert schema.model_config.get("extra") == "forbid"
    valid = _VALID_PAYLOADS[schema]
    schema.model_validate(valid)  # baseline: the minimal shape validates
    with pytest.raises(ValidationError):
        schema.model_validate({**valid, "unexpected_field": "nope"})
