"""Pure helpers shared by the worker loop and every phase mixin.

Module-level and side-effect free: HTTP-status classification, fetch-engine
labelling, robots denial tokens, URL canonicalization that tolerates junk, and
the Free-tier count-disclosure rule. They live outside ``site_health_worker``
because the phase modules use them and the worker imports the phases — the
other direction would be a cycle.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.connectors.web_evidence.contracts import FetchResult
from app.connectors.web_evidence.fetcher import is_bot_block_result
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.site_health import (
    APPLICABILITY_CRAWL_FINALIZE,
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
    FETCH_ENGINE_CURL_CFFI,
    FETCH_ENGINE_HTTPX,
    SITE_HEALTH_RULES_BY_ID,
)
from app.domain.site_health.normalization import canonical_identity
from app.models.site_health import SiteCrawl


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


def _fetch_engine_for_rung(rung_number: int | None) -> str:
    """Map a trace rung number to its config ``FETCH_ENGINE_*`` token (T8)."""
    if rung_number == 2:
        return FETCH_ENGINE_CURL_CFFI
    return FETCH_ENGINE_HTTPX


def _result_fetch_engine(result: FetchResult) -> str:
    """The engine that PRODUCED ``result``: its last trace entry's rung.

    The trace contract guarantees the entry describing a returned result is
    always last (an escalation continues the ordinal sequence), so the last
    entry's rung is the winning call's engine. A trace-less result (built
    directly by a test/caller) defaults to rung 1's engine.
    """
    if result.attempts:
        return _fetch_engine_for_rung(result.attempts[-1].rung_number)
    return FETCH_ENGINE_HTTPX


def _is_exhausted_bot_block(result: FetchResult) -> bool:
    """True ONLY when BOTH fetch-ladder rungs returned signature blocks (T8).

    Rung 2 fires exclusively on a rung-1 bot-block signature, so a trace
    containing a rung-2 entry proves rung 1 was signature-blocked; the
    returned result (which is then rung 2's terminal response) matching the
    signature proves rung 2 was too. Anything else — a plain returned 403 on
    rung 1 with no escalation, or an escalated rung-2 200 — is NOT an
    exhausted bot block and keeps its normal classification.
    """
    return any(entry.rung_number == 2 for entry in result.attempts) and (
        is_bot_block_result(result)
    )


def _count_disclosure(crawl: SiteCrawl) -> bool:
    """Whether this crawl opted into exact-count disclosure in its config."""
    return bool((crawl.configuration or {}).get("count_disclosure", False))


def _is_crawl_finalize_rule(rule_id: str) -> bool:
    """Whether a catalog rule is scoped ``crawl_finalize`` (finalize-owned)."""
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    return rule is not None and rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE


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
    """
    try:
        return canonical_identity(url)[0]
    except UrlPolicyError:
        return ""
