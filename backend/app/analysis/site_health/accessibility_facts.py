"""Bounded static accessibility facts extracted from the acquired DOM."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.core.config.site_health_acquisition import (
    SITE_HEALTH_MAX_ACCESSIBILITY_CONTROL_DESCRIPTORS,
    SITE_HEALTH_MAX_ACCESSIBILITY_IDENTIFIER_CHARS,
)


def _input_type(control: Any) -> str:
    return str(control.get("type") or "").strip().casefold()


def _accessible_text(node: Any) -> str:
    """Return bounded text alternatives contributed by one naming subtree."""
    try:
        parts = [str(value) for value in node.itertext()]
        parts.extend(
            str(image.get("alt") or "") for image in node.xpath(".//img[@alt]")
        )
        return " ".join(" ".join(parts).split())
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        return ""


def _has_labelledby_text(root: Any, control: Any) -> bool:
    labelled_by = str(control.get("aria-labelledby") or "").split()
    try:
        return any(
            _accessible_text(node)
            for reference in labelled_by
            for node in root.xpath("//*[@id=$id]", id=reference)
        )
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        return False


def _has_native_name(control: Any) -> bool:
    tag = str(control.tag or "").lower()
    if tag == "button" and _accessible_text(control):
        return True
    input_type = _input_type(control)
    if tag == "input" and input_type in ("button", "submit", "reset"):
        value = str(control.get("value") or "").strip()
        return bool(value) or input_type in {"submit", "reset"}
    image_alt = str(control.get("alt") or "").strip()
    return tag == "input" and input_type == "image" and bool(image_alt)


def _has_associated_label(root: Any, control: Any) -> bool:
    control_id = str(control.get("id") or "").strip()
    if control_id:
        try:
            if any(
                _accessible_text(label)
                for label in root.xpath("//label[@for=$id]", id=control_id)
            ):
                return True
        except DOM_ERRORS as exc:
            dom_failure("extract_accessibility_facts", exc)
    try:
        ancestor = control.getparent()
        while ancestor is not None:
            if str(ancestor.tag or "").lower() == "label":
                return bool(_accessible_text(ancestor))
            ancestor = ancestor.getparent()
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
    return False


def _has_programmatic_name(root: Any, control: Any) -> bool:
    return (
        bool(str(control.get("aria-label") or "").strip())
        or _has_labelledby_text(root, control)
        or _has_native_name(control)
        or _has_associated_label(root, control)
        or bool(str(control.get("title") or "").strip())
    )


def _is_excluded_control(control: Any) -> bool:
    """Return whether a native control is outside the HTTP accessibility tree."""
    node = control
    try:
        while node is not None:
            tag = str(node.tag or "").lower()
            if (
                tag == "template"
                or "hidden" in node.attrib
                or "inert" in node.attrib
                or str(node.get("aria-hidden") or "").strip().casefold() == "true"
            ):
                return True
            node = node.getparent()
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        return True
    return False


def _safe_identifier(control: Any, attribute: str) -> str:
    value = " ".join(str(control.get(attribute) or "").split())
    return value[:SITE_HEALTH_MAX_ACCESSIBILITY_IDENTIFIER_CHARS]


def _control_descriptor(control: Any, *, ordinal: int) -> dict[str, Any]:
    tag = str(control.tag or "").lower()
    input_type = _input_type(control)
    return {
        "tag": tag,
        "type": (input_type or "text") if tag == "input" else tag,
        "id": _safe_identifier(control, "id"),
        "name": _safe_identifier(control, "name"),
        "ordinal": ordinal,
    }


def _controls(root: Any) -> tuple[int, int, list[dict[str, Any]]]:
    try:
        controls = root.xpath("//input | //select | //textarea | //button")
    except DOM_ERRORS as exc:
        dom_failure("extract_accessibility_facts", exc)
        controls = []
    visible_controls = [
        control
        for control in controls
        if not (
            (
                str(control.tag or "").lower() == "input"
                and _input_type(control) == "hidden"
            )
            or _is_excluded_control(control)
        )
    ]
    missing_descriptors = [
        _control_descriptor(control, ordinal=ordinal)
        for ordinal, control in enumerate(visible_controls, start=1)
        if not _has_programmatic_name(root, control)
    ]
    return (
        len(visible_controls),
        len(missing_descriptors),
        missing_descriptors[:SITE_HEALTH_MAX_ACCESSIBILITY_CONTROL_DESCRIPTORS],
    )


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
    control_count, missing_names, missing_descriptors = _controls(root)
    heading_levels, level_skips = _heading_levels(root, limit=max_headings)
    return {
        "control_count": control_count,
        "controls_missing_accessible_name": missing_names,
        "controls_missing_accessible_name_descriptors": missing_descriptors,
        "heading_levels": heading_levels,
        "heading_level_skips": level_skips,
        "document_language": _document_language(root),
    }
