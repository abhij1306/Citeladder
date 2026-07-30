"""Bounded, SSRF-safe favicon discovery and fetching."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin

from lxml import etree
from lxml import html as lxml_html

from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    registrable_domain,
)
from app.core.config.brand_logos import (
    BRAND_LOGO_FALLBACK_PATH,
    BRAND_LOGO_IMAGE_CONTENT_TYPES,
    BRAND_LOGO_MAX_CANDIDATES,
    BRAND_LOGO_MAX_HTML_BYTES,
    BRAND_LOGO_MAX_IMAGE_BYTES,
    BRAND_LOGO_MAX_REDIRECTS,
    BRAND_LOGO_REQUEST_TIMEOUT_SECONDS,
)
from app.core.config.site_health import FETCH_PURPOSE_DISCOVER, HTML_CONTENT_TYPES


@dataclass(frozen=True, slots=True)
class FetchedBrandLogo:
    source_url: str
    content_type: str
    image_data: bytes


class BrandLogoFetcher(Protocol):
    async def fetch(
        self,
        request: FetchRequest,
        *,
        root_registrable_domain: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        enforce_scope: bool = False,
    ) -> FetchResult: ...


def detect_logo_content_type(body: bytes) -> str | None:
    """Return a safe raster MIME type from magic bytes, never headers alone."""
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if body.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if body.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


def discover_icon_urls(body: bytes, *, base_url: str) -> list[str]:
    """Extract bounded icon links in document order, followed by /favicon.ico."""
    candidates: list[str] = []
    seen: set[str] = set()
    if body:
        parser = lxml_html.HTMLParser(recover=True, no_network=True)
        try:
            root = lxml_html.document_fromstring(body, parser=parser)
        except (etree.ParserError, ValueError):
            root = None
        if root is not None:
            for link in root.iter("link"):
                rel = str(link.get("rel") or "").strip().lower().split()
                if not any(token == "icon" or token.endswith("-icon") for token in rel):
                    continue
                href = str(link.get("href") or "").strip()
                if not href:
                    continue
                try:
                    candidate = canonicalize(href, base_url=base_url)
                except UrlPolicyError:
                    continue
                if candidate in seen:
                    continue
                seen.add(candidate)
                candidates.append(candidate)
                if len(candidates) >= BRAND_LOGO_MAX_CANDIDATES - 1:
                    break

    try:
        fallback = canonicalize(urljoin(base_url, BRAND_LOGO_FALLBACK_PATH))
    except UrlPolicyError:
        fallback = ""
    if fallback and fallback not in seen:
        candidates.append(fallback)
    return candidates[:BRAND_LOGO_MAX_CANDIDATES]


async def fetch_brand_logo(
    homepage_url: str, *, fetcher: BrandLogoFetcher
) -> FetchedBrandLogo | None:
    """Fetch one site's declared icon (or /favicon.ico) through the safe fetcher."""
    try:
        homepage = canonicalize(homepage_url)
    except UrlPolicyError:
        return None
    root_domain = registrable_domain(homepage)
    if not root_domain:
        return None

    base_url = homepage
    page_body = b""
    try:
        page = await fetcher.fetch(
            FetchRequest(
                url=homepage,
                purpose=FETCH_PURPOSE_DISCOVER,
                max_wire_bytes=BRAND_LOGO_MAX_HTML_BYTES,
                max_decoded_bytes=BRAND_LOGO_MAX_HTML_BYTES,
                timeout_seconds=BRAND_LOGO_REQUEST_TIMEOUT_SECONDS,
                max_redirects=BRAND_LOGO_MAX_REDIRECTS,
                allowed_content_types=HTML_CONTENT_TYPES,
            ),
            root_registrable_domain=root_domain,
            enforce_scope=True,
        )
        if 200 <= page.status_code < 300:
            base_url = page.final_url
            page_body = page.body
    except (FetchError, UrlPolicyError):
        pass

    for icon_url in discover_icon_urls(page_body, base_url=base_url):
        try:
            result = await fetcher.fetch(
                FetchRequest(
                    url=icon_url,
                    purpose=FETCH_PURPOSE_DISCOVER,
                    max_wire_bytes=BRAND_LOGO_MAX_IMAGE_BYTES,
                    max_decoded_bytes=BRAND_LOGO_MAX_IMAGE_BYTES,
                    timeout_seconds=BRAND_LOGO_REQUEST_TIMEOUT_SECONDS,
                    max_redirects=BRAND_LOGO_MAX_REDIRECTS,
                    allowed_content_types=BRAND_LOGO_IMAGE_CONTENT_TYPES,
                ),
                enforce_scope=False,
            )
        except (FetchError, UrlPolicyError):
            continue
        if not 200 <= result.status_code < 300:
            continue
        content_type = detect_logo_content_type(result.body)
        if content_type is None:
            continue
        return FetchedBrandLogo(
            source_url=result.final_url,
            content_type=content_type,
            image_data=result.body,
        )
    return None
