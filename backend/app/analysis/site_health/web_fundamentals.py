"""Deterministic HTTP-evidence checks for the Web Fundamentals projection."""

from __future__ import annotations

from collections.abc import Callable

from app.core.config.site_health_contracts import RULE_OUTCOME_FAIL, RULE_OUTCOME_PASS


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_PASS if condition else RULE_OUTCOME_FAIL


def _image_alt(facts: dict) -> tuple[str, dict]:
    images = facts.get("images") or {}
    missing = int(images.get("missing_alt", 0) or 0)
    return _pass_fail(missing == 0), {
        "image_count": int(images.get("count", 0) or 0),
        "missing_alt": missing,
        "decorative_alt": int(images.get("decorative_alt", 0) or 0),
    }


def _form_names(facts: dict) -> tuple[str, dict]:
    accessibility = facts.get("accessibility") or {}
    missing = int(accessibility.get("controls_missing_accessible_name", 0) or 0)
    return _pass_fail(missing == 0), {
        "control_count": int(accessibility.get("control_count", 0) or 0),
        "missing_accessible_name": missing,
    }


def _heading_order(facts: dict) -> tuple[str, dict]:
    accessibility = facts.get("accessibility") or {}
    skipped = int(accessibility.get("heading_level_skips", 0) or 0)
    return _pass_fail(skipped == 0), {
        "heading_levels": list(accessibility.get("heading_levels") or ())[:64],
        "level_skips": skipped,
    }


def _document_language(facts: dict) -> tuple[str, dict]:
    language = str((facts.get("accessibility") or {}).get("document_language") or "")
    return _pass_fail(bool(language)), {"document_language": language}


def _mobile_viewport(facts: dict) -> tuple[str, dict]:
    viewport = (facts.get("mobile") or {}).get("viewport") or {}
    declared = bool(viewport.get("declared"))
    return _pass_fail(declared), {
        "declared": declared,
        "content": str(viewport.get("content") or "")[:512],
    }


def _mixed_content(facts: dict) -> tuple[str, dict]:
    links = facts.get("links") or {}
    insecure = [
        str(asset.get("url") or "")[:512]
        for group in ("images", "scripts", "stylesheets")
        for asset in links.get(group) or ()
        if str(asset.get("url") or "").lower().startswith("http://")
        and bool((facts.get("delivery") or {}).get("is_https"))
    ]
    return _pass_fail(not insecure), {
        "absolute_http_asset_count": len(insecure),
        "assets": insecure[:20],
    }


WEB_FUNDAMENTALS_CHECKS: dict[str, Callable[[dict], tuple[str, dict]]] = {
    "web.accessibility_image_alt": _image_alt,
    "web.accessibility_form_names": _form_names,
    "web.accessibility_heading_order": _heading_order,
    "web.accessibility_document_language": _document_language,
    "web.mobile_viewport": _mobile_viewport,
    "web.security_mixed_content": _mixed_content,
}
