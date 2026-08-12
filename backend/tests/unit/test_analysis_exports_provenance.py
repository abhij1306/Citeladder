"""Unit tests for CSV/Markdown export measurement provenance (invariants 4/7).

Pure renderer tests over in-memory ORM rows (no DB): the exports must project
``measurement_mode`` + ``retrieval_enabled`` ONLY from frozen audit/task
fields (the audit mode column + frozen policy block, the task request/route
snapshots) and the Markdown methodology must identify the audit's measurement
mode plus the stable catalog-ordered aggregate ``model_provenance`` list.
The canonical vocabulary is locked: no ``mode`` alias is ever emitted.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from app.analysis.exports import audit_to_csv, audit_to_markdown
from app.core.config.audits import MEASUREMENT_POLICY_KEY
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
)
from app.domain.audits.schemas import (
    AuditCreatedEvent,
    AuditTaskResponse,
    ModelProvenance,
    build_model_provenance,
    execution_frozen_provenance,
    frozen_retrieval_enabled,
)
from app.models.audit import Audit, AuditEngineSnapshot, AuditTask

_MODEL_CHATGPT = "gpt-5.4"
_MODEL_CLAUDE = "claude-sonnet-4-6"
_MODEL_GEMINI = "gemini-flash-latest"


def _engine_snapshot(
    audit_id: uuid.UUID,
    *,
    logical_engine: str,
    transport_provider: str,
    transport_model: str,
) -> AuditEngineSnapshot:
    return AuditEngineSnapshot(
        id=uuid.uuid4(),
        audit_id=audit_id,
        logical_engine=logical_engine,
        transport_provider=transport_provider,
        transport_model=transport_model,
    )


def _audit(
    *,
    measurement_mode: str = "benchmark",
    retrieval_enabled: bool | None = True,
    engine_order: str = "gemini_first",
) -> Audit:
    audit_id = uuid.uuid4()
    configuration = {
        "brand_name": "Acme Corp",
        "engines": [ENGINE_GEMINI],
        "benchmark_mode": "consumer_like",
    }
    if retrieval_enabled is not None:
        configuration[MEASUREMENT_POLICY_KEY] = {
            "retrieval_enabled": retrieval_enabled,
            "max_output_tokens": 1024,
            "timeout_seconds": 30.0,
            "repetitions": 1,
            "answer_instruction": "",
        }
    audit = Audit(
        id=audit_id,
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        status="completed",
        measurement_mode=measurement_mode,
        configuration=configuration,
        benchmark_mode="consumer_like",
        repetitions=1,
        random_seed="1",
        requested_count=1,
        completed_count=1,
        failed_count=0,
        summary={},
    )
    chatgpt = _engine_snapshot(
        audit_id,
        logical_engine=ENGINE_CHATGPT,
        transport_provider=TRANSPORT_OPENAI,
        transport_model=_MODEL_CHATGPT,
    )
    claude = _engine_snapshot(
        audit_id,
        logical_engine=ENGINE_CLAUDE,
        transport_provider=TRANSPORT_ANTHROPIC,
        transport_model=_MODEL_CLAUDE,
    )
    gemini = _engine_snapshot(
        audit_id,
        logical_engine=ENGINE_GEMINI,
        transport_provider=TRANSPORT_GOOGLE,
        transport_model=_MODEL_GEMINI,
    )
    # Seed OUT of catalog order: the renderer must re-order deterministically.
    if engine_order == "gemini_first":
        audit.engine_snapshots = [gemini, chatgpt, claude]
    else:
        audit.engine_snapshots = [claude, gemini, chatgpt]
    return audit


def _task(
    audit_id: uuid.UUID,
    *,
    request_snapshot: dict | None,
    route_snapshot: dict | None = None,
) -> AuditTask:
    return AuditTask(
        id=uuid.uuid4(),
        audit_id=audit_id,
        workspace_id=uuid.uuid4(),
        prompt_snapshot_id=uuid.uuid4(),
        engine_snapshot_id=uuid.uuid4(),
        prompt_index=0,
        repetition=0,
        randomized_position=0,
        logical_engine=ENGINE_GEMINI,
        transport_provider=TRANSPORT_GOOGLE,
        transport_model=_MODEL_GEMINI,
        prompt_text="best crm for acme",
        idempotency_key=f"{audit_id}:0:0:{ENGINE_GEMINI}:",
        status="succeeded",
        answer_text="Acme Corp.",
        search_used=True,
        search_events=[],
        citations=[],
        score={},
        latency_ms=5,
        error_code="",
        request_snapshot=request_snapshot,
        provider_route_snapshot=route_snapshot,
    )


def _csv_records(body: str) -> tuple[list[str], list[dict[str, str]]]:
    rows = list(csv.reader(io.StringIO(body)))
    header, data = rows[0], rows[1:]
    return header, [dict(zip(header, row, strict=True)) for row in data]


class TestCsvProvenance:
    def test_rows_carry_frozen_task_provenance(self) -> None:
        audit = _audit(measurement_mode="pulse", retrieval_enabled=False)
        task = _task(
            audit.id,
            request_snapshot={
                "measurement_mode": "pulse",
                "retrieval_enabled": False,
                "transport_model": _MODEL_GEMINI,
            },
        )
        header, records = _csv_records(audit_to_csv(audit, [task]))
        # The new columns sit beside the transport-model/search columns.
        assert header.index("measurement_mode") == header.index("transport_model") + 1
        assert header.index("retrieval_enabled") == header.index("transport_model") + 2
        assert header.index("retrieval_enabled") < header.index("search_used")
        assert records[0]["measurement_mode"] == "pulse"
        assert records[0]["retrieval_enabled"] == "False"
        assert records[0]["transport_model"] == _MODEL_GEMINI

    def test_rows_fall_back_to_frozen_audit_fields(self) -> None:
        # No task snapshots at all (legacy row): the audit's frozen mode
        # column + frozen policy block carry the provenance.
        audit = _audit(measurement_mode="benchmark", retrieval_enabled=True)
        task = _task(audit.id, request_snapshot=None, route_snapshot=None)
        _, records = _csv_records(audit_to_csv(audit, [task]))
        assert records[0]["measurement_mode"] == "benchmark"
        assert records[0]["retrieval_enabled"] == "True"

    def test_unrecorded_retrieval_renders_empty_never_inferred(self) -> None:
        # No frozen policy block anywhere: retrieval is unrecorded and the
        # renderer must NOT infer it from current mode config (inv. 4/7).
        audit = _audit(measurement_mode="pulse", retrieval_enabled=None)
        task = _task(audit.id, request_snapshot=None, route_snapshot=None)
        _, records = _csv_records(audit_to_csv(audit, [task]))
        assert records[0]["measurement_mode"] == "pulse"
        assert records[0]["retrieval_enabled"] == ""

    def test_no_mode_alias_column(self) -> None:
        audit = _audit()
        task = _task(audit.id, request_snapshot=None)
        header, _ = _csv_records(audit_to_csv(audit, [task]))
        assert "mode" not in header
        assert "measurement_mode" in header

    def test_every_cell_neutralizes_spreadsheet_formulas(self) -> None:
        audit = _audit()
        task = _task(audit.id, request_snapshot=None)
        task.prompt_text = '  =HYPERLINK("https://attacker.invalid")'
        task.error_code = "@SUM(1+1)"

        _, records = _csv_records(audit_to_csv(audit, [task]))
        assert records[0]["prompt_text"] == "'" + task.prompt_text
        assert records[0]["error_code"] == "'" + task.error_code


class TestMarkdownProvenance:
    def test_methodology_identifies_measurement_mode(self) -> None:
        audit = _audit(measurement_mode="pulse", retrieval_enabled=False)
        body = audit_to_markdown(audit, [])
        assert "- **Measurement mode:** `pulse`" in body
        # No bare "mode" alias metadata line (vocabulary lock).
        assert "- **Mode:**" not in body

    def test_stable_catalog_order_regardless_of_seed_order(self) -> None:
        first = audit_to_markdown(_audit(engine_order="gemini_first"), [])
        second = audit_to_markdown(_audit(engine_order="claude_first"), [])
        provenance = [
            line
            for line in first.splitlines()
            if line.startswith("- **Model provenance:**")
        ]
        assert len(provenance) == 1
        line = provenance[0]
        # Catalog order: chatgpt -> claude -> gemini, not insertion order.
        assert line.index("`chatgpt`") < line.index("`claude`")
        assert line.index("`claude`") < line.index("`gemini`")
        # Multi-model aggregate: every route's exact model id appears.
        assert f"model `{_MODEL_CHATGPT}`" in line
        assert f"model `{_MODEL_CLAUDE}`" in line
        assert f"model `{_MODEL_GEMINI}`" in line
        assert "retrieval on" in line
        # The ordering is stable across reversed insertion orders.
        assert (
            line
            == [
                entry
                for entry in second.splitlines()
                if entry.startswith("- **Model provenance:**")
            ][0]
        )

    def test_retrieval_state_comes_from_frozen_policy_block(self) -> None:
        body = audit_to_markdown(_audit(retrieval_enabled=False), [])
        line = next(
            entry
            for entry in body.splitlines()
            if entry.startswith("- **Model provenance:**")
        )
        assert "retrieval off" in line
        assert "retrieval on;" not in line

    def test_unrecorded_retrieval_is_never_inferred(self) -> None:
        body = audit_to_markdown(_audit(retrieval_enabled=None), [])
        line = next(
            entry
            for entry in body.splitlines()
            if entry.startswith("- **Model provenance:**")
        )
        assert "retrieval unrecorded" in line


class TestProvenanceHelpers:
    def test_model_provenance_shape_has_no_mode_alias(self) -> None:
        item = ModelProvenance(
            logical_engine=ENGINE_CHATGPT,
            transport_provider=TRANSPORT_OPENAI,
            transport_model=_MODEL_CHATGPT,
            retrieval_enabled=True,
        )
        assert set(item.model_dump()) == {
            "logical_engine",
            "transport_provider",
            "transport_model",
            "retrieval_enabled",
        }

    def test_build_model_provenance_dedupes_and_orders(self) -> None:
        gemini = ModelProvenance(
            logical_engine=ENGINE_GEMINI,
            transport_provider=TRANSPORT_GOOGLE,
            transport_model=_MODEL_GEMINI,
            retrieval_enabled=True,
        )
        chatgpt = ModelProvenance(
            logical_engine=ENGINE_CHATGPT,
            transport_provider=TRANSPORT_OPENAI,
            transport_model=_MODEL_CHATGPT,
            retrieval_enabled=True,
        )
        ordered = build_model_provenance([gemini, chatgpt, gemini, chatgpt])
        assert ordered == [chatgpt, gemini]

    def test_execution_frozen_provenance_precedence(self) -> None:
        # Task request snapshot (executed truth) wins over the route snapshot,
        # which wins over the audit-level frozen fallback.
        mode, retrieval = execution_frozen_provenance(
            request_snapshot={"measurement_mode": "pulse", "retrieval_enabled": False},
            route_snapshot={"measurement_mode": "benchmark", "retrieval_enabled": True},
            audit_measurement_mode="benchmark",
            audit_configuration={MEASUREMENT_POLICY_KEY: {"retrieval_enabled": True}},
        )
        assert (mode, retrieval) == ("pulse", False)
        mode, retrieval = execution_frozen_provenance(
            request_snapshot=None,
            route_snapshot={"measurement_mode": "pulse", "retrieval_enabled": False},
            audit_measurement_mode="benchmark",
            audit_configuration={MEASUREMENT_POLICY_KEY: {"retrieval_enabled": True}},
        )
        assert (mode, retrieval) == ("pulse", False)
        mode, retrieval = execution_frozen_provenance(
            request_snapshot=None,
            route_snapshot=None,
            audit_measurement_mode="benchmark",
            audit_configuration={MEASUREMENT_POLICY_KEY: {"retrieval_enabled": True}},
        )
        assert (mode, retrieval) == ("benchmark", True)
        # Nothing frozen anywhere: unrecorded, never inferred from live config.
        mode, retrieval = execution_frozen_provenance(
            request_snapshot=None,
            route_snapshot=None,
            audit_measurement_mode=None,
            audit_configuration=None,
        )
        assert (mode, retrieval) == ("", None)

    def test_frozen_retrieval_skips_explicit_null_values(self) -> None:
        assert (
            frozen_retrieval_enabled(
                {"retrieval_enabled": None}, {"retrieval_enabled": True}
            )
            is True
        )
        assert (
            frozen_retrieval_enabled(
                {"retrieval_enabled": None}, {"retrieval_enabled": None}
            )
            is None
        )

    def test_task_response_uses_audit_level_frozen_fallback(self) -> None:
        now = datetime(2026, 7, 20, tzinfo=UTC)
        task = SimpleNamespace(
            id=uuid.uuid4(),
            audit_id=uuid.uuid4(),
            prompt_index=0,
            repetition=0,
            randomized_position=0,
            logical_engine=ENGINE_GEMINI,
            transport_provider=TRANSPORT_GOOGLE,
            transport_model=_MODEL_GEMINI,
            status="succeeded",
            attempt_count=1,
            max_attempts=5,
            prompt_text="best crm",
            answer_text="Acme",
            search_used=True,
            error_code="",
            error_detail="",
            latency_ms=10,
            created_at=now,
            completed_at=now,
            request_snapshot={"measurement_mode": ""},
            provider_route_snapshot={"retrieval_enabled": None},
            audit_measurement_mode="benchmark",
            audit_configuration={MEASUREMENT_POLICY_KEY: {"retrieval_enabled": True}},
        )

        response = AuditTaskResponse.model_validate(task)

        assert response.measurement_mode == "benchmark"
        assert response.retrieval_enabled is True

    def test_audit_event_accepts_both_timestamp_input_names(self) -> None:
        now = datetime(2026, 7, 20, tzinfo=UTC)
        common = {
            "id": uuid.uuid4(),
            "audit_id": uuid.uuid4(),
            "event_type": "audit.created",
            "payload": {"requested_count": 1, "engines": ["gemini"]},
        }

        from_created = AuditCreatedEvent.model_validate({**common, "created_at": now})
        from_occurred = AuditCreatedEvent.model_validate({**common, "occurred_at": now})

        assert from_created.occurred_at == now
        assert from_occurred.occurred_at == now
        assert "created_at" not in from_occurred.model_dump()
