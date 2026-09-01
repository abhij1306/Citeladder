"""Pure extraction and evaluation for canonical About-page entity completeness."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from app.core.config.site_health_company_entity import (
    AUDIENCE_PATTERNS,
    COMPANY_ENTITY_EVIDENCE_MAX_CHARS,
    COMPANY_ENTITY_SCAN_MAX_CHARS,
    COMPANY_ENTITY_SIGNAL_WEIGHTS,
    COMPANY_IDENTITY_PATTERN,
    DURABLE_PROOF_PATTERNS,
    OFFERING_PATTERNS,
    PROOF_EXCLUSION_TERMS,
    VALUE_PROPOSITION_PATTERNS,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bounded(value: object) -> str:
    return " ".join(str(value or "").split())[:COMPANY_ENTITY_EVIDENCE_MAX_CHARS]


def _first_match(text: str, patterns: Iterable[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            return _bounded(match.groupdict().get("value") or match.group(0))
    return ""


def _organization_name(facts: dict[str, Any], text: str) -> str:
    proposition = _mapping(facts.get("entity_proposition"))
    provider = _bounded(proposition.get("provider"))
    if provider and provider.casefold() not in {"about", "about us", "our story"}:
        return provider
    structured = _mapping(facts.get("structured_data"))
    for block in structured.get("blocks") or ():
        candidate = _mapping(block)
        if candidate.get("type") in {"Organization", "LocalBusiness"}:
            name = _bounded(candidate.get("name"))
            if name:
                return name
    match = re.search(COMPANY_IDENTITY_PATTERN, text)
    return _bounded(match.group("value")) if match is not None else ""


def extract_company_entity_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Derive a bounded normalized fact shape from already-acquired page facts."""
    body = _mapping(facts.get("body"))
    text = " ".join(str(body.get("text") or "").split())[:COMPANY_ENTITY_SCAN_MAX_CHARS]
    proposition = _mapping(facts.get("entity_proposition"))
    proposition_text = _bounded(proposition.get("proposition"))
    searchable = f"{proposition_text}. {text}".strip()
    identity = _organization_name(facts, searchable)
    offering = _bounded(proposition.get("named_capability")) or _first_match(
        searchable, OFFERING_PATTERNS
    )
    audience = _bounded(proposition.get("audience_or_outcome")) or _first_match(
        searchable, AUDIENCE_PATTERNS
    )
    value = _first_match(searchable, VALUE_PROPOSITION_PATTERNS)
    proof = ""
    for sentence in re.split(r"(?<=[.!?;])\s+", searchable):
        if any(term in sentence.casefold() for term in PROOF_EXCLUSION_TERMS):
            continue
        proof = _first_match(sentence, DURABLE_PROOF_PATTERNS)
        if proof:
            break
    return {
        "readable": isinstance(body.get("text"), str),
        "company_identity": identity,
        "offering": offering,
        "audience_or_use_case": audience,
        "concrete_value_proposition": value,
        "durable_first_party_proof": proof,
    }


def _evidence_by_signal(normalized: dict[str, Any]) -> dict[str, Any]:
    return {
        "company_and_offering_definition": {
            "company_identity": _bounded(normalized.get("company_identity")),
            "offering": _bounded(normalized.get("offering")),
        },
        "audience_or_use_case": _bounded(normalized.get("audience_or_use_case")),
        "concrete_value_proposition": _bounded(
            normalized.get("concrete_value_proposition")
        ),
        "durable_first_party_proof": _bounded(
            normalized.get("durable_first_party_proof")
        ),
    }


def _signal_presence(evidence: dict[str, Any]) -> dict[str, bool]:
    definition = _mapping(evidence["company_and_offering_definition"])
    return {
        "company_and_offering_definition": bool(
            definition.get("company_identity") and definition.get("offering")
        ),
        "audience_or_use_case": bool(evidence["audience_or_use_case"]),
        "concrete_value_proposition": bool(evidence["concrete_value_proposition"]),
        "durable_first_party_proof": bool(evidence["durable_first_party_proof"]),
    }


def _company_entity_outcome(present: dict[str, bool]) -> str:
    if all(present.values()):
        return RULE_OUTCOME_SATISFIED
    if not present["company_and_offering_definition"] or sum(present.values()) < 2:
        return RULE_OUTCOME_MISSING
    return RULE_OUTCOME_PARTIAL


def evaluate_company_entity_facts(normalized: dict[str, Any]) -> tuple[str, dict]:
    """Evaluate four determinate weighted atoms without I/O or company exceptions."""
    if not normalized.get("readable"):
        return RULE_OUTCOME_UNKNOWN, {
            "reason": "primary_content_unreadable",
            "atoms": [],
            "normalized_coverage": 0.0,
        }
    evidence_by_signal = _evidence_by_signal(normalized)
    present = _signal_presence(evidence_by_signal)
    credit = sum(
        COMPANY_ENTITY_SIGNAL_WEIGHTS[key]
        for key, satisfied in present.items()
        if satisfied
    )
    atoms = [
        {
            "name": key,
            "outcome": RULE_OUTCOME_SATISFIED if present[key] else RULE_OUTCOME_MISSING,
            "weight": weight,
            "evidence": evidence_by_signal[key],
        }
        for key, weight in COMPANY_ENTITY_SIGNAL_WEIGHTS.items()
    ]
    outcome = _company_entity_outcome(present)
    return outcome, {
        "atoms": atoms,
        "missing_signals": [key for key, satisfied in present.items() if not satisfied],
        "normalized_score": round(credit, 4),
        "normalized_coverage": 1.0,
    }


def check_company_entity_completeness(facts: dict[str, Any]) -> tuple[str, dict]:
    return evaluate_company_entity_facts(extract_company_entity_facts(facts))


__all__ = [
    "check_company_entity_completeness",
    "evaluate_company_entity_facts",
    "extract_company_entity_facts",
]
