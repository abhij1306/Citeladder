"""Pure deterministic reference classifier for one compiled industry pack.

The classifier performs no network, database, queue, embedding, or model calls.
Load and compile one exact pack once per worker/crawl, then call ``classify_page``
with bounded extracted page facts.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Any
from urllib.parse import unquote, urlsplit

from .catalog import (
    canonical_content_hash,
    load_pack,
    pack_manifest,
)

_SCALAR_LIMITS = {
    "url": 2048,
    "path": 2048,
    "filename": 512,
    "title": 512,
    "h1": 512,
    "body": 16_000,
    "media_type": 128,
    "page_kind": 128,
    "temporal_state": 64,
    "corpus_disposition": 64,
}
_COLLECTION_LIMITS = {
    "headings": (64, 512),
    "cta_text": (32, 256),
    "form_fields": (32, 128),
    "link_context": (64, 512),
    "schema_types": (32, 128),
}
_PRIOR_FIELDS = {"media_type", "page_kind"}
_SCHEMA_FIELD = "schema_types"
_TEMPORAL_STATES = {"current", "historical", "future", "unknown"}


@dataclass(frozen=True, slots=True)
class CompiledSignal:
    signal_id: str
    field: str
    operator: str
    weight: float
    values: tuple[str, ...]
    pattern: re.Pattern[str] | None
    ratio: float
    polarity: str


@dataclass(frozen=True, slots=True)
class CompiledRole:
    role_id: str
    page_kinds: tuple[str, ...]
    minimum_score: float
    minimum_margin: float
    allow_secondary: bool
    signals: tuple[CompiledSignal, ...]
    negative_signals: tuple[CompiledSignal, ...]


@dataclass(frozen=True, slots=True)
class CompiledPack:
    pack_id: str
    version: str
    classifier_version: str
    manifest: Mapping[str, str]
    minimum_score: float
    minimum_margin: float
    high_confidence_score: float
    negative_score_floor: float
    maximum_evidence_records: int
    maximum_alternatives: int
    maximum_conflicts: int
    maximum_secondary_roles: int
    roles: tuple[CompiledRole, ...]


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _normalize_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value))
    return text[:limit].casefold().strip()


def _normalize_collection(
    value: Any,
    *,
    item_limit: int,
    text_limit: int,
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        items: Sequence[Any] = (value,)
    else:
        items = value
    normalized = []
    for item in items[:item_limit]:
        text = _normalize_text(item, text_limit)
        if text:
            normalized.append(text)
    return tuple(normalized)


def _normalize_page_facts(
    facts: Mapping[str, Any],
) -> tuple[Mapping[str, Any] | None, str | None]:
    if not isinstance(facts, Mapping):
        return None, "invalid_input"

    raw_url = _normalize_text(facts.get("url"), _SCALAR_LIMITS["url"])
    raw_path = _normalize_text(facts.get("path"), _SCALAR_LIMITS["path"])
    if not raw_url and not raw_path:
        return None, "invalid_input"

    if raw_url:
        try:
            parsed_path = urlsplit(raw_url).path
        except ValueError:
            return None, "invalid_input"
    else:
        parsed_path = ""
    path = unquote(raw_path or parsed_path or "")
    path = _normalize_text(path, _SCALAR_LIMITS["path"])
    if not path.startswith("/"):
        path = f"/{path}" if path else ""
    if not path:
        return None, "invalid_input"

    normalized: dict[str, Any] = {
        "url": raw_url,
        "path": path,
        "root_path": path.rstrip("/") == "",
    }
    for field, limit in _SCALAR_LIMITS.items():
        if field in {"url", "path"}:
            continue
        normalized[field] = _normalize_text(facts.get(field), limit)
    for field, (item_limit, text_limit) in _COLLECTION_LIMITS.items():
        normalized[field] = _normalize_collection(
            facts.get(field),
            item_limit=item_limit,
            text_limit=text_limit,
        )
    if not normalized["filename"]:
        normalized["filename"] = path.rsplit("/", 1)[-1]
    return MappingProxyType(normalized), None


def _compile_signal(item: Mapping[str, Any]) -> CompiledSignal:
    signal_id = str(item["signal_id"])
    field = str(item["field"])
    operator = str(item["operator"])
    raw_values = item.get("values", ())
    values = tuple(_normalize_text(value, 512) for value in raw_values)
    raw_pattern = item.get("pattern")
    pattern = None
    if raw_pattern is not None:
        pattern_text = str(raw_pattern)
        if len(pattern_text) > 1024:
            raise ValueError(f"signal regex is too long: {signal_id}")
        pattern = re.compile(pattern_text, re.IGNORECASE)
    ratio = float(item.get("ratio", 0.5))
    return CompiledSignal(
        signal_id=signal_id,
        field=field,
        operator=operator,
        weight=float(item["weight"]),
        values=values,
        pattern=pattern,
        ratio=ratio,
        polarity=str(item.get("polarity", "positive")),
    )


def compile_pack(
    pack: Mapping[str, Any],
    *,
    manifest: Mapping[str, str] | None = None,
) -> CompiledPack:
    """Compile regexes and immutable role contracts once for hot-loop reuse."""

    policy = pack["classification_policy"]
    pack_id = str(pack["pack_id"])
    version = str(pack["version"])
    if manifest is None:
        generated_manifest = {
            "catalog_version": "unregistered",
            "pack_id": pack_id,
            "pack_version": version,
            "pack_content_hash": canonical_content_hash(_plain(pack)),
            "classifier_version": str(policy["classifier_version"]),
        }
        manifest = MappingProxyType(generated_manifest)

    default_margin = float(policy["minimum_margin"])
    roles = []
    for item in pack["page_roles"]:
        roles.append(
            CompiledRole(
                role_id=str(item["role_id"]),
                page_kinds=tuple(str(value) for value in item["page_kinds"]),
                minimum_score=float(item.get("minimum_score", policy["minimum_score"])),
                minimum_margin=float(item.get("minimum_margin", default_margin)),
                allow_secondary=bool(item.get("allow_secondary", True)),
                signals=tuple(_compile_signal(value) for value in item["signals"]),
                negative_signals=tuple(
                    _compile_signal(value) for value in item["negative_signals"]
                ),
            )
        )
    return CompiledPack(
        pack_id=pack_id,
        version=version,
        classifier_version=str(policy["classifier_version"]),
        manifest=MappingProxyType(dict(manifest)),
        minimum_score=float(policy["minimum_score"]),
        minimum_margin=default_margin,
        high_confidence_score=float(policy["high_confidence_score"]),
        negative_score_floor=float(policy["negative_score_floor"]),
        maximum_evidence_records=int(policy["maximum_evidence_records"]),
        maximum_alternatives=int(policy["maximum_alternatives"]),
        maximum_conflicts=int(policy["maximum_conflicts"]),
        maximum_secondary_roles=int(policy["maximum_secondary_roles"]),
        roles=tuple(roles),
    )


@lru_cache(maxsize=64)
def _compiled_registered_pack(pack_id: str, version: str) -> CompiledPack:
    pack = load_pack(pack_id, version)
    manifest = pack_manifest(pack_id, version)
    return compile_pack(pack, manifest=manifest)


def _field_values(value: Any) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, bool):
        return ("true" if value else "false",)
    if value is None:
        return ()
    return (str(value),)


def _match_signal(
    signal: CompiledSignal,
    facts: Mapping[str, Any],
) -> tuple[bool, tuple[str, ...]]:
    field_values = _field_values(facts.get(signal.field))
    if not field_values:
        return False, ()

    operator = signal.operator
    if operator == "regex":
        return _match_regex(signal, field_values)
    if operator in _MEMBERSHIP_OPERATORS:
        return _match_membership(signal, field_values)
    if operator in _SUBSTRING_OPERATORS:
        return _match_substring(signal, field_values)
    return False, ()


# Grouped so the dispatch above stays flat. Membership operators compare whole
# values; substring operators look inside them.
_MEMBERSHIP_OPERATORS = frozenset({"equals", "in", "intersects"})
_SUBSTRING_OPERATORS = frozenset({"contains_any", "contains_all", "ratio_gte"})


def _match_regex(
    signal: CompiledSignal,
    field_values: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    if signal.pattern is None:
        return False, ()
    matches = []
    for value in field_values:
        match = signal.pattern.search(value)
        if match:
            matches.append(match.group(0)[:160])
    return bool(matches), tuple(matches[:4])


def _match_membership(
    signal: CompiledSignal,
    field_values: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    if signal.operator == "intersects":
        matched = tuple(sorted(set(field_values).intersection(signal.values)))
    else:
        # `equals` and `in` are the same test here: the field is already a
        # sequence, so both ask whether any whole value is in the allowed set.
        matched = tuple(value for value in field_values if value in signal.values)
    return bool(matched), matched[:4]


def _match_substring(
    signal: CompiledSignal,
    field_values: Sequence[str],
) -> tuple[bool, tuple[str, ...]]:
    if signal.operator == "ratio_gte":
        if not signal.values:
            return False, ()
        matched = tuple(
            needle
            for needle in signal.values
            if any(needle in value for value in field_values)
        )
        return len(matched) / len(signal.values) >= signal.ratio, matched[:4]

    matched_needles = tuple(
        needle
        for needle in signal.values
        if needle and any(needle in value for value in field_values)
    )
    if signal.operator == "contains_any":
        return bool(matched_needles), matched_needles[:4]
    return len(matched_needles) == len(signal.values), matched_needles[:4]


def _score_role(
    role: CompiledRole,
    facts: Mapping[str, Any],
    *,
    evidence_limit: int,
    negative_floor: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    positive_score = 0.0
    negative_score = 0.0
    substantive_fields: set[str] = set()
    schema_matched = False

    for signal in role.signals:
        matched, values = _match_signal(signal, facts)
        if not matched:
            continue
        positive_score += signal.weight
        if signal.field == _SCHEMA_FIELD:
            schema_matched = True
        elif signal.field not in _PRIOR_FIELDS:
            substantive_fields.add(signal.field)
        if len(evidence) < evidence_limit:
            evidence.append(
                {
                    "signal_id": signal.signal_id,
                    "field": signal.field,
                    "operator": signal.operator,
                    "polarity": signal.polarity,
                    "weight": signal.weight,
                    "matched_values": list(values),
                }
            )

    for signal in role.negative_signals:
        matched, values = _match_signal(signal, facts)
        if not matched:
            continue
        negative_score += signal.weight
        if len(evidence) < evidence_limit:
            evidence.append(
                {
                    "signal_id": signal.signal_id,
                    "field": signal.field,
                    "operator": signal.operator,
                    "polarity": signal.polarity,
                    "weight": signal.weight,
                    "matched_values": list(values),
                }
            )

    total = max(positive_score + negative_score, negative_floor)
    matched_fields = sorted({item["field"] for item in evidence})
    return {
        "role_id": role.role_id,
        "score": round(total, 6),
        "positive_score": round(positive_score, 6),
        "negative_score": round(negative_score, 6),
        "minimum_score": role.minimum_score,
        "minimum_margin": role.minimum_margin,
        "allow_secondary": role.allow_secondary,
        "substantive_fields": tuple(sorted(substantive_fields)),
        "schema_matched": schema_matched,
        "matched_fields": matched_fields,
        "evidence": evidence,
    }


def _temporal_state(facts: Mapping[str, Any]) -> str:
    explicit = str(facts.get("temporal_state") or "")
    if explicit in _TEMPORAL_STATES:
        return explicit
    text = " ".join(
        [
            str(facts.get("path") or ""),
            str(facts.get("title") or ""),
            str(facts.get("h1") or ""),
            str(facts.get("body") or ""),
        ]
    )
    if facts.get("page_kind") == "archive" or any(
        marker in text
        for marker in (
            "archive",
            "archived",
            "historical record",
            "no longer current",
            "discontinued",
        )
    ):
        return "historical"
    return "unknown"


def _empty_result(
    pack: CompiledPack,
    reason: str,
    *,
    temporal_state: str = "unknown",
) -> dict[str, Any]:
    return {
        "classifier_version": pack.classifier_version,
        "manifest": dict(pack.manifest),
        "primary_role_id": None,
        "primary_score": None,
        "winner_margin": None,
        "confidence_band": "abstained",
        "secondary_role_ids": [],
        "abstention_reason": reason,
        "temporal_state": temporal_state,
        "evidence": [],
        "alternatives": [],
        "conflicts": [],
    }


def classify_page(
    pack: CompiledPack | Mapping[str, Any],
    facts: Mapping[str, Any],
    *,
    pack_eligible: bool = True,
) -> dict[str, Any]:
    """Classify bounded facts, or explicitly abstain with deterministic evidence."""

    compiled = pack if isinstance(pack, CompiledPack) else compile_pack(pack)
    if not pack_eligible:
        return _empty_result(compiled, "pack_not_eligible")

    normalized, error = _normalize_page_facts(facts)
    if error or normalized is None:
        return _empty_result(compiled, error or "invalid_input")
    temporal_state = _temporal_state(normalized)
    if normalized.get("corpus_disposition") == "exclude":
        return _empty_result(
            compiled,
            "not_applicable",
            temporal_state=temporal_state,
        )

    signaled = _rank_roles(compiled, normalized)
    if not any(
        item["substantive_fields"] or item["schema_matched"] for item in signaled
    ):
        result = _empty_result(
            compiled,
            "no_signal",
            temporal_state=temporal_state,
        )
        result["alternatives"] = _alternatives(compiled, signaled, None)
        return result

    return _decide_role(compiled, signaled, temporal_state)


def _rank_roles(
    compiled: CompiledPack,
    normalized: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Score every role, order by score then ID, and keep those with any signal."""

    candidates = [
        _score_role(
            role,
            normalized,
            evidence_limit=compiled.maximum_evidence_records,
            negative_floor=compiled.negative_score_floor,
        )
        for role in compiled.roles
    ]
    candidates.sort(key=lambda item: (-item["score"], item["role_id"]))
    return [item for item in candidates if item["positive_score"] > 0]


def _decide_role(
    compiled: CompiledPack,
    signaled: list[dict[str, Any]],
    temporal_state: str,
) -> dict[str, Any]:
    """Pick a winner or abstain, with the evidence for either outcome attached."""

    winner = signaled[0]
    runner = signaled[1] if len(signaled) > 1 else None
    margin = winner["score"] - runner["score"] if runner else winner["score"]
    result = {
        "classifier_version": compiled.classifier_version,
        "manifest": dict(compiled.manifest),
        "primary_role_id": None,
        "primary_score": winner["score"],
        "winner_margin": round(margin, 6),
        "confidence_band": "abstained",
        "secondary_role_ids": [],
        "abstention_reason": None,
        "temporal_state": temporal_state,
        "evidence": winner["evidence"],
        "alternatives": _alternatives(compiled, signaled, winner["role_id"]),
        "conflicts": _conflicts(compiled, winner, signaled[1:]),
    }

    abstention = _abstention_reason(winner, runner, margin)
    if abstention is not None:
        result["abstention_reason"] = abstention
        return result

    result["primary_role_id"] = winner["role_id"]
    result["confidence_band"] = (
        "high" if winner["score"] >= compiled.high_confidence_score else "moderate"
    )
    result["secondary_role_ids"] = _secondary_roles(compiled, winner, signaled[1:])
    return result


def _abstention_reason(
    winner: Mapping[str, Any],
    runner: Mapping[str, Any] | None,
    margin: float,
) -> str | None:
    """Why the classifier must not commit, or `None` when it may."""

    if not winner["substantive_fields"] and winner["schema_matched"]:
        return "schema_only"
    if winner["score"] < winner["minimum_score"]:
        return "below_minimum_score"
    if runner is not None and margin < winner["minimum_margin"]:
        return "ambiguous_margin"
    return None


def _alternatives(
    pack: CompiledPack,
    candidates: list[dict[str, Any]],
    winner_id: str | None,
) -> list[dict[str, Any]]:
    alternatives = []
    for item in candidates:
        if item["role_id"] == winner_id:
            continue
        alternatives.append(
            {
                "role_id": item["role_id"],
                "score": item["score"],
                "positive_score": item["positive_score"],
                "negative_score": item["negative_score"],
                "matched_fields": item["matched_fields"],
                "evidence": item["evidence"],
            }
        )
        if len(alternatives) >= pack.maximum_alternatives:
            break
    return alternatives


def _conflicts(
    pack: CompiledPack,
    winner: dict[str, Any],
    alternatives: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    conflicts = []
    if winner["negative_score"] < 0:
        conflicts.append(
            {
                "type": "negative_signal_on_winner",
                "role_id": winner["role_id"],
                "score": winner["score"],
            }
        )
    route_fields = {"filename", "path"}
    visible_fields = {
        "body",
        "cta_text",
        "form_fields",
        "h1",
        "headings",
        "link_context",
        "title",
    }
    winner_fields = set(winner["matched_fields"])
    for item in alternatives:
        candidate_fields = set(item["matched_fields"])
        route_visible_disagreement = bool(
            (winner_fields & route_fields and candidate_fields & visible_fields)
            or (candidate_fields & route_fields and winner_fields & visible_fields)
        )
        if item["score"] < item["minimum_score"] and not route_visible_disagreement:
            continue
        conflict_type = (
            "route_visible_disagreement"
            if route_visible_disagreement
            else "competing_candidate"
        )
        conflicts.append(
            {
                "type": conflict_type,
                "role_id": item["role_id"],
                "score": item["score"],
                "margin_from_winner": round(winner["score"] - item["score"], 6),
                "matched_fields": item["matched_fields"],
            }
        )
        if len(conflicts) >= pack.maximum_conflicts:
            break
    return conflicts[: pack.maximum_conflicts]


def _secondary_roles(
    pack: CompiledPack,
    winner: dict[str, Any],
    alternatives: list[dict[str, Any]],
) -> list[str]:
    secondary = []
    for item in alternatives:
        if not item["allow_secondary"]:
            continue
        if item["score"] < item["minimum_score"]:
            continue
        if winner["score"] - item["score"] < winner["minimum_margin"]:
            continue
        secondary.append(str(item["role_id"]))
        if len(secondary) >= pack.maximum_secondary_roles:
            break
    return secondary


def classify_registered_page(
    pack_id: str,
    version: str,
    facts: Mapping[str, Any],
    *,
    pack_eligible: bool = True,
) -> dict[str, Any]:
    """Load/compile one exact registered pack through a process-local cache."""

    return classify_page(
        _compiled_registered_pack(pack_id, version),
        facts,
        pack_eligible=pack_eligible,
    )
