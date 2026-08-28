"""Deterministic entity-level recommendation assessment over one answer."""

from __future__ import annotations

import re

from app.analysis.normalization import normalize_alias
from app.analysis.scoring import ScoringConfig
from app.core.config.analysis import ENTITY_ASSESSMENT_VERSION


def _assessment(
    name: str, aliases: tuple[str, ...], answer: str, entity_kind: str
) -> dict:
    matches = (
        re.search(rf"\b{re.escape(alias)}\b", answer, re.IGNORECASE)
        for alias in aliases
        if normalize_alias(alias)
    )
    match = min(
        (item for item in matches if item is not None),
        key=lambda item: item.start(),
        default=None,
    )
    if match is None:
        return _row(name, entity_kind, "absent", None, "Entity matching completed.")
    start = max(0, match.start() - 60)
    end = min(len(answer), match.end() + 60)
    span = answer[start:end]
    before = answer[max(0, match.start() - 45) : match.start()].lower()
    after_text = answer[match.end() : match.end() + 45].lower()
    if re.search(
        r"(?:avoid|do not recommend|not recommended|recommend against)\s*$", before
    ) or re.search(
        r"^\W*(?:is|are|was|were)?\s*(?:not recommended|best avoided|"
        r"not a good (?:choice|pick|fit))\b",
        after_text,
    ):
        state = "recommended_against"
    elif re.search(
        r"(?:recommend|recommended|top pick|best choice|choose)\s*$", before
    ) or re.search(
        r"^\W*(?:is|are|was|were)?\s*(?:recommended|the top pick|"
        r"the best choice)\b",
        after_text,
    ):
        state = "recommended"
    elif re.search(r"(?:consider|may prefer|could choose|option)\s*$", before):
        state = "hedged"
    else:
        state = "mentioned"
    return _row(
        name, entity_kind, state, {"start": start, "end": end, "text": span}, ""
    )


def _row(
    name: str, entity_kind: str, state: str, span: dict | None, limitation: str
) -> dict:
    return {
        "entity_id": f"{entity_kind}:{normalize_alias(name)}",
        "entity_name": name,
        "entity_kind": entity_kind,
        "state": state,
        "confidence": 1.0 if state in {"absent", "unavailable"} else 0.85,
        "evidence_spans": [span] if span else [],
        "method": "deterministic_explicit_language",
        "analyzer_version": ENTITY_ASSESSMENT_VERSION,
        "model": None,
        "template_version": None,
        "limitation": limitation,
    }


def assess_entities(answer: str, config: ScoringConfig) -> list[dict]:
    roster = [
        (config.brand_name, config.brand_aliases, "brand"),
        *((item.name, item.aliases, "competitor") for item in config.competitors),
    ]
    if not answer.strip():
        return [
            _row(name, kind, "unavailable", None, "Answer text is unavailable.")
            for name, _aliases, kind in roster
            if name
        ]
    return [
        _assessment(name, aliases, answer, kind)
        for name, aliases, kind in roster
        if name
    ]
