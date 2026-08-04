"""Resolve site existence and optionally extract one homepage."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

from app.connectors.web_evidence.brand_evidence import (
    BrandEvidencePage,
    extract_brand_page,
)
from app.connectors.web_evidence.contracts import FetchError, FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.url_policy import UrlPolicyError, registrable_domain
from app.core.config.brand_discovery import ONBOARDING_DIRECT_FETCH_SETTINGS
from app.core.config.brand_evidence import (
    BRAND_EVIDENCE_CONTENT_TYPES,
    BRAND_EVIDENCE_MAX_HTML_BYTES,
    BRAND_EVIDENCE_MAX_REDIRECTS,
    BRAND_EVIDENCE_REQUEST_TIMEOUT_SECONDS,
    BRAND_EVIDENCE_USER_AGENT,
)
from app.core.config.site_health import FETCH_PURPOSE_ANALYZE


class SiteNotFoundError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedSite:
    entered_url: str
    canonical_url: str
    registrable_domain: str
    status_code: int
    page: BrandEvidencePage | None
    warning: str = ""


def _http_variant(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(("http", parts.netloc, parts.path, parts.query, ""))


async def resolve_site(entered_url: str, normalized_url: str) -> ResolvedSite:
    request_urls = [normalized_url]
    if urlsplit(normalized_url).scheme == "https":
        request_urls.append(_http_variant(normalized_url))
    last_error = ""
    async with SecureFetcher(
        resolver=SystemDnsResolver(),
        settings=ONBOARDING_DIRECT_FETCH_SETTINGS,
        user_agent=BRAND_EVIDENCE_USER_AGENT,
    ) as fetcher:
        for request_url in request_urls:
            try:
                result = await fetcher.fetch(
                    FetchRequest(
                        url=request_url,
                        purpose=FETCH_PURPOSE_ANALYZE,
                        timeout_seconds=BRAND_EVIDENCE_REQUEST_TIMEOUT_SECONDS,
                        max_redirects=BRAND_EVIDENCE_MAX_REDIRECTS,
                        max_decoded_bytes=BRAND_EVIDENCE_MAX_HTML_BYTES,
                        allowed_content_types=BRAND_EVIDENCE_CONTENT_TYPES,
                    )
                )
            except (FetchError, UrlPolicyError) as exc:
                last_error = getattr(exc, "error_code", type(exc).__name__)
                continue
            if result.status_code == 404:
                last_error = "http_404"
                continue
            final_url = result.final_url or request_url
            domain = registrable_domain(final_url)
            if not domain:
                raise SiteNotFoundError("site_not_found")
            page = None
            warning = ""
            is_https = urlsplit(request_url).scheme == "https"
            if 200 <= result.status_code < 300 and is_https:
                extracted = extract_brand_page(
                    result.body, url=final_url, charset=result.charset
                )
                if extracted.word_count or extracted.meta_description:
                    page = extracted
                else:
                    warning = "research_degraded"
            else:
                warning = "research_degraded"
            return ResolvedSite(
                entered_url=entered_url,
                canonical_url=final_url,
                registrable_domain=domain,
                status_code=result.status_code,
                page=page,
                warning=warning,
            )
    raise SiteNotFoundError(last_error or "site_not_found")
