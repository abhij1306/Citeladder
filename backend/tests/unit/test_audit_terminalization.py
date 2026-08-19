"""Audit terminal success precondition tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

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
