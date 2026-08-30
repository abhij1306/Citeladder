"""Pure helpers shared by the worker loop and explicit phase modules.

Module-level and side-effect free: HTTP-status classification, robots denial
tokens, URL canonicalization that tolerates junk, and the Free-tier
count-disclosure rule. They live outside ``site_health_worker`` because the
phase modules use them and the worker imports the phases — the other direction
would be a cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.connectors.web_evidence.contracts import FetchResult
from app.connectors.web_evidence.fetcher_body import is_bot_block_result
from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health_acquisition import (
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
)
from app.domain.site_health.normalization import canonical_identity
from app.models.site_health.crawl import SiteCrawl


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _classify_http_error(status: int) -> tuple[str, bool] | None:
    """Map an HTTP status the fetcher returned (not raised) to (code, retry).

    Returns ``None`` for a non-error status. A 4xx is terminal except 429
    (rate limit, retryable); every 5xx is retryable. Shared by the discover
    and analyze fetch paths so the classification stays in one place.
    """
    if 400 <= status < 500:
        return ERROR_HTTP_4XX, status == 429
    if status >= 500:
        return ERROR_HTTP_5XX, True
    return None


def _is_bot_block(result: FetchResult) -> bool:
    """Whether this fetch came back as a bot-protection challenge (T8).

    Thin pass-through to the fetcher's marker-based signature so the phases
    depend on one predicate. A match is terminal: the crawler makes a plain,
    honestly-identified request, so a site that answers with a challenge is
    reported as ``blocked`` rather than retried.
    """
    return is_bot_block_result(result)


def _count_disclosure(crawl: SiteCrawl) -> bool:
    """Whether this crawl opted into exact-count disclosure in its config."""
    return bool((crawl.configuration or {}).get("count_disclosure", False))


def _serialize_redirect_chain(result: FetchResult) -> list[dict]:
    """Serialize a fetch result's redirect hops to plain JSON-safe dicts."""
    return [
        {
            "from_url": hop.from_url,
            "to_url": hop.to_url,
            "status_code": hop.status_code,
        }
        for hop in result.redirect_chain
    ]


def _robots_denial_error(policy: RobotsPolicy) -> tuple[str, str]:
    """The (error_code, detail) for a robots-denied fetch.

    A 5xx robots.txt (RFC 9309 complete/temporary disallow) surfaces as
    ``robots_unavailable`` — distinct from a real robots-rule disallow so the
    UI can explain the site is misbehaving rather than blocking crawlers.
    """
    if policy.unavailable:
        return (
            ERROR_ROBOTS_UNAVAILABLE,
            "robots.txt responded 5xx; fetches paused for this site",
        )
    return (
        ERROR_ROBOTS_DENIED,
        "robots.txt disallows the crawler user-agent for this URL",
    )


def _canonical_or_empty(url: str) -> str:
    """The canonical form of ``url``, or ``""`` when it fails normalization.

    The finalize pass canonicalizes persisted URLs (link targets, hreflang
    alternates, sitemap observations) that may no longer parse — an
    unnormalizable URL simply contributes nothing.

    Catches ``ValueError`` (the ``UrlPolicyError`` base) rather than the policy
    error alone: a malformed persisted URL can fail inside ``urlsplit`` itself
    (an unclosed IPv6 bracket, a junk port) before the policy checks run, and a
    finalize pass must never die on one bad stored row.
    """
    try:
        return canonical_identity(url)[0]
    except ValueError:
        return ""
