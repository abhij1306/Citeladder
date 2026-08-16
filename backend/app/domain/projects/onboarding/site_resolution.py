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
from app.core.config.site_health import (
    ERROR_RESPONSE_TOO_LARGE,
    FETCH_PURPOSE_ANALYZE,
)


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
    errors: list[str] = []
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
                errors.append(getattr(exc, "error_code", type(exc).__name__))
                continue
            if result.status_code == 404:
                errors.append("http_404")
                continue
            final_url = result.final_url or request_url
            domain = registrable_domain(final_url)
            if not domain:
                raise SiteNotFoundError("site_not_found")
            page = None
            warning = ""
            is_https = urlsplit(final_url).scheme == "https"
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
    return _unreadable_site(entered_url, normalized_url, errors)


# Failures that prove the site EXISTS but could not be read. Treating these as
# "site not found" aborted onboarding for real brands -- burrow.com is an
# ordinary storefront whose homepage simply exceeds the byte cap. The site is
# not missing, so the honest outcome is a resolved site with no page text and a
# degraded-research warning; the model prior still has something to work with.
_READABLE_SITE_FAILURES = frozenset({ERROR_RESPONSE_TOO_LARGE})


def _unreadable_site(
    entered_url: str, normalized_url: str, errors: list[str]
) -> ResolvedSite:
    """Decide from *every* attempt, not just the last one.

    The https attempt can prove the site exists by being too large while the
    http fallback then 404s; keeping only the final error threw that proof away
    and reported a live site as missing.
    """
    domain = registrable_domain(normalized_url)
    readable = any(code in _READABLE_SITE_FAILURES for code in errors)
    if not readable or not domain:
        raise SiteNotFoundError(next(iter(errors), "") or "site_not_found")
    return ResolvedSite(
        entered_url=entered_url,
        canonical_url=normalized_url,
        registrable_domain=domain,
        status_code=0,
        page=None,
        warning="research_degraded",
    )
