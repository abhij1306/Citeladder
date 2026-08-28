"""Deterministic entity-level recommendation assessment over one answer."""

from __future__ import annotations

import re

from app.analysis.normalization import normalize_alias
from app.analysis.scoring import ScoringConfig
from app.core.config.analysis import AMBIGUOUS_ALIASES, ENTITY_ASSESSMENT_VERSION

# Separator between the tokens of a normalized alias. Zero-width so the
# ``&`` -> ``and`` expansion in ``normalize_alias`` still matches the raw
# ``Best&Less``, where no separator sits between the tokens.
_TOKEN_GAP = r"[^0-9A-Za-z]*"
# Common semantic uses that must NOT count as a mention of an ambiguous,
# ordinary-word brand alias (mirrors ``scoring._entity_alias_present``).
_AMBIGUOUS_EXCLUSIONS = r"(?!\s+(?:audience|price|market|demographic))"


def _alias_pattern(normalized_alias: str) -> str:
    """Regex matching a normalized alias inside the RAW answer text.

    Matching stays on the raw answer so evidence-span offsets remain valid,
    but the pattern is built from the normalized alias so ``Best&Less``,
    ``Best & Less`` and ``Best and Less`` all match one another — the same
    equivalence ``normalization.normalize_alias`` gives the scorer.
    """
    tokens = [
        r"(?:and|&)" if token == "and" else re.escape(token)
        for token in normalized_alias.split()
    ]
    return r"(?<!\w)" + _TOKEN_GAP.join(tokens) + r"(?!\w)"


def _alias_match(alias: str, answer: str) -> re.Match[str] | None:
    normalized = normalize_alias(alias)
    if not normalized:
        return None
    pattern = _alias_pattern(normalized)
    if normalized not in AMBIGUOUS_ALIASES:
        return re.search(pattern, answer, re.IGNORECASE)
    # An ordinary-word alias needs a qualifier or proper-noun casing before it
    # counts, so "the market price" never reads as the brand.
    qualified = re.search(
        pattern + r"[^0-9A-Za-z]+australia(?!\w)", answer, re.IGNORECASE
    )
    return qualified or re.search(pattern + _AMBIGUOUS_EXCLUSIONS, answer)


def _assessment(
    name: str, aliases: tuple[str, ...], answer: str, entity_kind: str
) -> dict:
    matches = (_alias_match(alias, answer) for alias in aliases)
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
        r"(?:avoid|do not recommend|not recommended|recommend against)"
        r"(?:\s+(?:the|a|an|this|that))*\s*$",
        before,
    ) or re.search(
        r"^\W*(?:is|are|was|were)?\s*(?:not recommended|best avoided|"
        r"not a good (?:choice|pick|fit))\b",
        after_text,
    ):
        state = "recommended_against"
    elif re.search(
        r"(?:recommend|recommended|top pick|best choice|choose)"
        r"(?:\s+(?:the|a|an|this|that))*\s*$",
        before,
    ) or re.search(
        r"^\W*(?:is|are|was|were)?\s*(?:recommended|the top pick|"
        r"the best choice)\b",
        after_text,
    ):
        state = "recommended"
    elif re.search(
        r"(?:consider|may prefer|could choose|option)"
        r"(?:\s+(?:the|a|an|this|that))*\s*$",
        before,
    ):
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
