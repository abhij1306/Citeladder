"""Bounded content and citability signals extracted from parsed HTML."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.analysis.site_health.dom import node_text as _text
from app.connectors.web_evidence.url_policy import registrable_domain
from app.core.config import site_health_acquisition as config
from app.core.config.site_health_rules import ANSWER_FIRST_MAX_HOPS


def _is_cta_anchor(node: Any) -> bool:
    role = str(node.get("role") or "").strip().casefold()
    if role == "button":
        return True
    classes = str(node.get("class") or "").casefold()
    return bool(
        classes and set(re.split(r"[\s_-]+", classes)) & config.CTA_BUTTON_ROLE_TOKENS
    )


def _append_unique(values: list[str], seen: set[str], value: str, limit: int) -> None:
    cleaned = " ".join(str(value or "").split())[:limit]
    if cleaned and cleaned.casefold() not in seen:
        seen.add(cleaned.casefold())
        values.append(cleaned)


def _cta_value(node: Any) -> str:
    tag = str(node.tag).lower()
    if tag == "button":
        return _text(node)
    if tag == "input" and str(node.get("type") or "").strip().casefold() in {
        "submit",
        "button",
    }:
        return str(node.get("value") or "")
    return _text(node) if tag == "a" and _is_cta_anchor(node) else ""


def cta_texts(root: Any) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()

    try:
        for node in root.iter("button", "a", "input"):
            if len(texts) >= config.SITE_HEALTH_MAX_CTA_TEXTS:
                break
            _append_unique(
                texts,
                seen,
                _cta_value(node),
                config.SITE_HEALTH_MAX_CTA_TEXT_CHARS,
            )
    except DOM_ERRORS as exc:
        dom_failure("cta_texts", exc)
    return texts[: config.SITE_HEALTH_MAX_CTA_TEXTS]


def form_fields(root: Any) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    try:
        labels_by_for: dict[str, str] = {}
        for label in root.iter("label"):
            target = str(label.get("for") or "").strip()
            if target and target not in labels_by_for:
                labels_by_for[target] = _text(label)
        for node in root.iter("input", "select", "textarea"):
            if len(fields) >= config.SITE_HEALTH_MAX_FORM_FIELDS:
                break
            if _ignored_field(node):
                continue
            candidate = _field_candidate(node, labels_by_for)
            _append_unique(
                fields, seen, candidate, config.SITE_HEALTH_MAX_FORM_FIELD_CHARS
            )
    except DOM_ERRORS as exc:
        dom_failure("form_fields", exc)
    return fields[: config.SITE_HEALTH_MAX_FORM_FIELDS]


def _ignored_field(node: Any) -> bool:
    return str(node.get("type") or "").strip().casefold() in {
        "hidden",
        "submit",
        "button",
        "reset",
        "image",
    }


def _field_candidate(node: Any, labels_by_for: dict[str, str]) -> str:
    return (
        labels_by_for.get(str(node.get("id") or "").strip(), "")
        or node.get("aria-label")
        or node.get("placeholder")
        or node.get("name")
        or ""
    )


def outbound_domains(anchors: list[dict], *, base_host: str) -> list[str]:
    base_registrable = registrable_domain(base_host) if base_host else ""
    domains: set[str] = set()
    for entry in anchors or []:
        host = _external_host(
            entry,
            base_host=base_host,
            base_registrable=base_registrable,
        )
        if host is None:
            continue
        domains.add(host[: config.SITE_HEALTH_MAX_DOMAIN_CHARS])
        if len(domains) >= config.SITE_HEALTH_MAX_OUTBOUND_DOMAINS:
            break
    return sorted(domains)


def _external_host(entry: dict, *, base_host: str, base_registrable: str) -> str | None:
    if bool(entry.get("is_internal")):
        return None
    try:
        parts = urlsplit(str(entry.get("url") or "").strip())
    except DOM_ERRORS as exc:
        dom_failure("_external_host", exc)
        return None
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("http", "https"):
        return None
    if base_registrable and registrable_domain(host) == base_registrable:
        return None
    if not base_registrable and base_host and host == base_host.lower():
        return None
    return host


def _first_heading(root: Any) -> Any | None:
    try:
        # Default rather than catching StopIteration: "no heading on the page"
        # is an ordinary result, not a DOM failure worth reporting.
        return next((node for node in root.iter() if node.tag in ("h1", "h2")), None)
    except DOM_ERRORS as exc:
        dom_failure("_first_heading", exc)
        return None


def _sibling_answer(heading: Any) -> str:
    try:
        for sibling in heading.itersiblings():
            text = _text(sibling)
            if text:
                return " ".join(text.split())
    except DOM_ERRORS as exc:
        dom_failure("_sibling_answer", exc)
        return ""
    return ""


def _walk_answer(root: Any, heading: Any) -> str:
    hops = 0
    seen_heading = False
    try:
        for node in root.iter():
            if node is heading:
                seen_heading = True
                continue
            if not seen_heading:
                continue
            hops += 1
            if hops > ANSWER_FIRST_MAX_HOPS:
                break
            if node.tag in ("script", "style", "noscript", "template"):
                continue
            text = _text(node)
            if text:
                return " ".join(text.split())
    except DOM_ERRORS as exc:
        dom_failure("_walk_answer", exc)
        return ""
    return ""


def first_answer_text(root: Any) -> str:
    first_heading = _first_heading(root)
    if first_heading is None:
        return ""
    answer = _sibling_answer(first_heading) or _walk_answer(root, first_heading)
    return answer[: config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS]
