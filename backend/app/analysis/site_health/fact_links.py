"""Bounded HTML link and asset facts."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from app.core.config import site_health_acquisition as config
from app.core.config.site_health_contracts import (
    LINK_KIND_ANCHOR,
    LINK_KIND_IMAGE,
    LINK_KIND_SCRIPT,
    LINK_KIND_STYLESHEET,
)


def _text(node: Any) -> str:
    try:
        return (node.text_content() or "").strip()
    except Exception:
        return ""


def _is_internal_asset(url: str, *, base_host: str) -> bool:
    try:
        host = urlsplit(url).hostname
    except Exception:
        return False
    return host is None or (bool(base_host) and host.lower() == base_host.lower())


def _anchor_assets(
    root: Any, *, base_host: str, max_links: int
) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    try:
        for anchor in root.iter("a"):
            if len(anchors) >= max_links:
                break
            href = (anchor.get("href") or "").strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            anchors.append(
                {
                    "kind": LINK_KIND_ANCHOR,
                    "url": href[: config.SITE_HEALTH_MAX_URL_CHARS],
                    "is_internal": _is_internal_asset(href, base_host=base_host),
                    "rel": (anchor.get("rel") or "")[:128],
                    "anchor_text": _text(anchor)[
                        : config.SITE_HEALTH_MAX_ANCHOR_TEXT_CHARS
                    ],
                }
            )
    except Exception:
        pass
    return anchors


def _simple_assets(
    root: Any,
    *,
    tag: str,
    attribute: str,
    kind: str,
    base_host: str,
    max_links: int,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    try:
        for node in root.iter(tag):
            if len(assets) >= max_links:
                break
            url = (node.get(attribute) or "").strip()
            if not url:
                continue
            assets.append(
                {
                    "kind": kind,
                    "url": url[: config.SITE_HEALTH_MAX_URL_CHARS],
                    "is_internal": _is_internal_asset(url, base_host=base_host),
                }
            )
    except Exception:
        pass
    return assets


def _stylesheet_assets(
    root: Any, *, base_host: str, max_links: int
) -> list[dict[str, Any]]:
    stylesheets: list[dict[str, Any]] = []
    try:
        for link in root.iter("link"):
            if len(stylesheets) >= max_links:
                break
            rel = (link.get("rel") or "").strip().lower()
            href = (link.get("href") or "").strip()
            if "stylesheet" not in rel.split() or not href:
                continue
            stylesheets.append(
                {
                    "kind": LINK_KIND_STYLESHEET,
                    "url": href[: config.SITE_HEALTH_MAX_URL_CHARS],
                    "is_internal": _is_internal_asset(href, base_host=base_host),
                }
            )
    except Exception:
        pass
    return stylesheets


def links_and_assets(
    root: Any, *, base_host: str, max_links: int
) -> dict[str, list[dict]]:
    """Collect independently bounded anchors, images, scripts, and stylesheets."""
    return {
        "anchors": _anchor_assets(root, base_host=base_host, max_links=max_links),
        "images": _simple_assets(
            root,
            tag="img",
            attribute="src",
            kind=LINK_KIND_IMAGE,
            base_host=base_host,
            max_links=max_links,
        ),
        "scripts": _simple_assets(
            root,
            tag="script",
            attribute="src",
            kind=LINK_KIND_SCRIPT,
            base_host=base_host,
            max_links=max_links,
        ),
        "stylesheets": _stylesheet_assets(
            root, base_host=base_host, max_links=max_links
        ),
    }
