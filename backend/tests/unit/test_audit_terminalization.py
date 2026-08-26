"""Audit terminal success precondition tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.core.config.audits import AUDIT_STATUS_ANALYZING
from app.workers.audit import terminalization
from app.workers.audit.terminalization import AuditTerminalizationMixin


@pytest.mark.asyncio
async def test_success_persistence_requires_a_provider_response() -> None:
    with pytest.raises(RuntimeError, match="requires a response"):
        await AuditTerminalizationMixin._persist_success(
            object(),
            task_id=uuid.uuid4(),
            audit_id=uuid.uuid4(),
            attempts=[SimpleNamespace(response=None)],
            logical_engine="engine",
            transport_provider="provider",
            transport_model="model",
            request_snapshot={},
        )


@pytest.mark.asyncio
async def test_shelf_failure_does_not_block_audit_terminalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audit_id = uuid.uuid4()
    audit = SimpleNamespace(
        id=audit_id,
        status=AUDIT_STATUS_ANALYZING,
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    steps: list[str] = []

    class Context:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

    class Session(Context):
        async def get(self, *_: object, **__: object):
            return audit

        def begin_nested(self) -> Context:
            return Context()

        async def commit(self) -> None:
            steps.append("commit")

    async def fail_shelf(*_: object, **__: object) -> None:
        steps.append("shelf")
        raise RuntimeError("broken shelf")

    async def finalize_analysis(*_: object, **__: object) -> None:
        steps.append("analysis")

    async def enqueue(**_: object) -> None:
        steps.append("opportunity")

    monkeypatch.setattr(terminalization, "finalize_commerce_shelf", fail_shelf)
    monkeypatch.setattr(terminalization, "finalize_audit_analysis", finalize_analysis)
    worker = SimpleNamespace(
        _session_factory=lambda: Session(),
        _enqueue_opportunity_refresh=enqueue,
    )

    await AuditTerminalizationMixin._finalize_analysis(worker, audit_id)

    assert steps == ["shelf", "analysis", "commit", "opportunity"]
