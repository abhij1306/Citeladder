"""Value types produced by the fetch phases.

Separated from ``site_health_worker`` so a phase mixin can name its own
outcome type without importing the worker that mixes it in (a cycle).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.connectors.web_evidence.fetcher import FetchCallTrace, FetchResult
from app.domain.site_health.schemas import DiscoveryOutput


@dataclass(frozen=True, slots=True)
class LinkProbeOutcome:
    """Observable inputs captured by a bounded link probe."""

    reachable: bool
    method: str
    status_code: int | None
    # True when the target's own robots.txt policy denied the probe (no
    # request was made — recorded as policy-skipped, never a fetch failure).
    skipped_by_policy: bool = False


@dataclass(slots=True)
class DiscoverOutcome:
    """Bounded, in-memory result of a single discover fetch+parse.

    Holds either a success (``result`` + parsed ``output``) or a classified
    failure (``error_code`` + ``retryable``), never both, so the persist step
    can branch on ``output is not None``. ``result`` is present for HTTP
    4xx/5xx (the fetcher returns them) so an artifact can still be written.
    The v2 P2 site-setup fields are populated only by the depth-0 (root)
    task: ``site_facts`` for the crawl row, plus the sitemap-ingested URL /
    file lists (empty on Free sample crawls — sitemap page ingestion is a
    Starter behavior).
    """

    result: FetchResult | None = None
    output: DiscoveryOutput | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    # The fetcher's per-network-call trace (T7/T8): one entry per REAL call
    # (both rungs, every redirect hop), carried from ``FetchResult.attempts``
    # or ``FetchError.attempts`` so persistence writes one attempt ROW per
    # call. Empty when no network call happened (robots short-circuit).
    attempts: tuple[FetchCallTrace, ...] = ()
    site_facts: dict | None = None
    sitemap_urls: tuple[str, ...] = ()
    sitemap_files: tuple[str, ...] = ()


@dataclass(slots=True)
class AnalyzeOutcome:
    """Bounded, in-memory result of a single analyze fetch+parse.

    Holds either a success (``result`` + parsed ``facts``) or a classified
    failure (``error_code`` + ``retryable``). ``result`` is present for HTTP
    4xx/5xx so an artifact/attempt can still be recorded on a hard failure.
    """

    result: FetchResult | None = None
    facts: dict | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    # The fetcher's per-network-call trace (T7/T8), as on ``DiscoverOutcome``.
    attempts: tuple[FetchCallTrace, ...] = ()
