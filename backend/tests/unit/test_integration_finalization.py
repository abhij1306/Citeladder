"""Integration finalization transaction-boundary tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.domain.integrations.derive import UnmappedPropertyError
from app.workers.integration.finalization import RunFinalizer


class _Rows:
    def all(self) -> list[object]:
        return []


class _Session:
    def __init__(self) -> None:
        self.pending: list[object] = []
        self.steps: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def scalars(self, *_: object) -> _Rows:
        return _Rows()

    async def get(self, *_: object, **__: object) -> object:
        return object()

    def add(self, value: object) -> None:
        self.pending.append(value)

    async def flush(self) -> None:
        self.steps.append("flush")

    async def rollback(self) -> None:
        self.steps.append("rollback")
        self.pending.clear()

    async def commit(self) -> None:
        self.steps.append("commit")


@pytest.mark.asyncio
async def test_unmapped_finalization_discards_derived_writes_before_failing_run() -> (
    None
):
    run_id = uuid.uuid4()
    original = SimpleNamespace(id=run_id)
    reclaimed = SimpleNamespace(id=run_id)
    session = _Session()
    claims: list[uuid.UUID] = []

    async def claim_owned_run(_: _Session, claimed_id: uuid.UUID):
        claims.append(claimed_id)
        return original if len(claims) == 1 else reclaimed

    async def derive_then_fail(active_session: _Session, **_: object):
        active_session.add("derived projection")
        await active_session.flush()
        raise UnmappedPropertyError("mapping is absent")

    finalizer = RunFinalizer(
        session_factory=lambda: session,  # type: ignore[arg-type]
        claim_owned_run=claim_owned_run,  # type: ignore[arg-type]
    )
    finalizer._derive = derive_then_fail  # type: ignore[method-assign]

    await finalizer.finalize(SimpleNamespace(run_id=run_id, connection_id=uuid.uuid4()))

    assert claims == [run_id, run_id]
    assert session.pending == []
    assert session.steps == ["flush", "rollback", "commit"]
    assert reclaimed.error_code == "unmapped_property"
    assert reclaimed.lease_owner is None
