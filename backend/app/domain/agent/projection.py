"""Public projection helpers for persisted Growth Agent results."""

from __future__ import annotations

import uuid
from typing import Any, Final

SOURCE_METADATA: Final = {
    "site.read_snapshot": ("site_health", "Site Health"),
    "demand.read_snapshot": ("search_demand", "Search Demand"),
    "opportunities.read_ranked": ("opportunities", "Opportunities"),
    "audits.read_latest": ("ai_visibility", "AI Visibility"),
}

_TYPED_RESULT_FIELDS = {
    "summary",
    "observations",
    "roadmap_items",
    "sources",
    "limitations",
    "artifact_refs",
}


def _legacy_artifact_refs(result: dict[str, Any]) -> list[dict[str, str]]:
    refs: list[dict[str, str]] = []
    for ref in result.get("artifact_refs") or []:
        if not isinstance(ref, dict) or not ref.get("kind") or not ref.get("id"):
            continue
        try:
            artifact_id = uuid.UUID(str(ref["id"]))
        except ValueError:
            continue
        refs.append({"kind": str(ref["kind"]), "id": str(artifact_id)})
    return refs


def public_result(result: object) -> dict[str, Any] | None:
    """Normalize current and pre-v3 persisted results without a repair read."""
    if not isinstance(result, dict):
        return None
    if _TYPED_RESULT_FIELDS.issubset(result):
        return result
    summary = str(result.get("summary") or result.get("answer") or "").strip()
    if not summary:
        return None
    return {
        "summary": summary,
        "observations": [],
        "roadmap_items": [],
        "sources": [
            {
                "key": key,
                "label": label,
                "availability": "unavailable",
                "window": None,
                "coverage": None,
                "reason": "Availability was not recorded for this earlier run.",
            }
            for key, label in SOURCE_METADATA.values()
        ],
        "limitations": [
            str(item) for item in result.get("limitations") or [] if str(item).strip()
        ],
        "artifact_refs": _legacy_artifact_refs(result),
    }
