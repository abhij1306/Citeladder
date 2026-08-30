"""Bounded static accessibility facts extracted from the acquired DOM."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure


def _has_labelledby_text(root: Any, control: Any) -> bool:
    labelled_by = str(control.get("aria-labelledby") or "").split()
    try:
        return any(
            " ".join(node.itertext()).strip()
            for reference in labelled_by
            for node in root.xpath("//*[@id=$id]", id=reference)
        )
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        return False


def _has_native_name(control: Any) -> bool:
    tag = str(control.tag or "").lower()
    if tag == "button" and " ".join(control.itertext()).strip():
        return True
    input_type = str(control.get("type") or "").lower()
    if tag == "input" and input_type in ("button", "submit", "reset"):
        return True
    image_alt = str(control.get("alt") or "").strip()
    return tag == "input" and input_type == "image" and bool(image_alt)


def _has_associated_label(root: Any, control: Any) -> bool:
    control_id = str(control.get("id") or "").strip()
    if control_id:
        try:
            return bool(root.xpath("//label[@for=$id]", id=control_id))
        except DOM_ERRORS as exc:
            dom_failure("extract_accessibility_facts", exc)
            return False
    parent = control.getparent()
    return parent is not None and parent.tag == "label"


def _has_programmatic_name(root: Any, control: Any) -> bool:
    return (
        bool(str(control.get("aria-label") or "").strip())
        or _has_labelledby_text(root, control)
        or _has_native_name(control)
        or _has_associated_label(root, control)
    )


def _controls(root: Any) -> tuple[int, int]:
    try:
        controls = root.xpath(
            "//input[translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')"
            "!='hidden'] | //select | //textarea | //button"
        )
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        controls = []
    missing = sum(not _has_programmatic_name(root, control) for control in controls)
    return len(controls), missing


def _heading_levels(root: Any, *, limit: int) -> tuple[list[int], int]:
    try:
        levels = [
            int(node.tag[1]) for node in root.xpath("//h1|//h2|//h3|//h4|//h5|//h6")
        ]
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        levels = []
    except (ValueError, TypeError) as exc:
        dom_failure("extract_accessibility_facts", exc)
        levels = []
    skipped = sum(1 for left, right in pairwise(levels) if right > left + 1)
    return levels[:limit], skipped


def _document_language(root: Any) -> str:
    try:
        nodes = root.xpath("//html")
        return str(nodes[0].get("lang") or "").strip()[:32] if nodes else ""
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        return ""


def extract_accessibility_facts(root: Any, *, max_headings: int) -> dict[str, Any]:
    """Return accessible-name, heading-order, and language observations."""
    control_count, missing_names = _controls(root)
    heading_levels, level_skips = _heading_levels(root, limit=max_headings)
    return {
        "control_count": control_count,
        "controls_missing_accessible_name": missing_names,
        "heading_levels": heading_levels,
        "heading_level_skips": level_skips,
        "document_language": _document_language(root),
    }
