"""Canonical public-site and primary-market normalization."""

from __future__ import annotations

from urllib.parse import urlsplit

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    registrable_domain,
)
from app.domain.projects.normalization import (
    normalize_primary_market as normalize_primary_market,
)


class InvalidWebsiteUrl(ValueError):
    pass


def normalize_website_url(value: str) -> tuple[str, str]:
    candidate = str(value or "").strip()
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        canonical = canonicalize(candidate)
    except (UrlPolicyError, ValueError) as exc:
        raise InvalidWebsiteUrl(
            "website_url must be a valid public HTTP(S) URL"
        ) from exc
    host = (urlsplit(canonical).hostname or "").casefold()
    domain = registrable_domain(host)
    if not domain:
        raise InvalidWebsiteUrl("website_url must use a registrable public domain")
    return canonical, domain
