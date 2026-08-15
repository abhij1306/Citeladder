"""Deterministic grounding-envelope contract and provider validation."""

from __future__ import annotations

import pytest

from app.domain.content.grounding import (
    freeze_grounding_envelope,
    validate_provider_output,
)

_REF_A = "a" * 64
_REF_B = "b" * 64


def _fact(value: str, source_ref_id: str = _REF_A) -> dict:
    return {
        "fact_id": value,
        "field": "description",
        "value": value,
        "claim_class": "identity",
        "source_ref_ids": [source_ref_id],
        "review_state": "confirmed",
        "limitations": [],
    }


def _source(source_ref_id: str = _REF_A) -> dict:
    return {
        "source_ref_id": source_ref_id,
        "source_kind": "profile_field",
        "source_id": "00000000-0000-0000-0000-000000000001",
        "field_or_fragment": "description",
        "observed_at": "2026-08-15T00:00:00Z",
        "origin": "manual",
        "review_state": "confirmed",
    }


def test_confirmed_fact_is_allowed_and_exact_source_marker_validates() -> None:
    envelope = freeze_grounding_envelope([_fact("Acme")], [_source()], [])
    assert envelope.status == "included"
    assert envelope.allowed_facts[0]["value"] == "Acme"
    assert "identity" not in {
        item["claim_class"] for item in envelope.prohibited_claims
    }
    validate_provider_output(f"Acme [[source:{_REF_A}]]", envelope)


def test_absent_fact_source_and_provider_source_are_rejected() -> None:
    with pytest.raises(ValueError, match="absent source reference"):
        freeze_grounding_envelope([_fact("Acme", _REF_B)], [_source()], [])
    envelope = freeze_grounding_envelope([_fact("Acme")], [_source()], [])
    with pytest.raises(ValueError, match="absent grounding source"):
        validate_provider_output(f"Claim [[source:{_REF_B}]]", envelope)


def test_conflicting_confirmed_identity_facts_are_omitted() -> None:
    envelope = freeze_grounding_envelope(
        [_fact("Acme", _REF_A), _fact("Different", _REF_B)],
        [_source(_REF_A), _source(_REF_B)],
        [],
    )
    assert envelope.status == "conflicting"
    assert envelope.allowed_facts == []
    identity = next(
        item for item in envelope.prohibited_claims if item["claim_class"] == "identity"
    )
    assert identity["reason_code"] == "conflicting_confirmed_facts"


def test_empty_inputs_produce_truthful_unavailable_envelope() -> None:
    envelope = freeze_grounding_envelope([], [], [])
    assert envelope.status == "unavailable"
    assert envelope.budget.selected_count == 0
