# Gathering brand web evidence for the profile drafter.
#
# Orchestrates the connector: canonicalize the project's website URL, fetch the
# homepage plus at most four commercial internal pages, and report whether the
# result clears the grounding floor. Thin evidence never authorizes a
# model-memory fallback.
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

from app.connectors.web_evidence.brand_evidence import (
    BrandEvidenceLink,
    BrandEvidencePage,
    fallback_urls,
    fetch_brand_page,
    serialize_brand_evidence,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.url_policy import UrlPolicyError, canonicalize
from app.core.config.brand_evidence import (
    BRAND_EVIDENCE_CACHE_MAX_ENTRIES,
    BRAND_EVIDENCE_CACHE_SECONDS,
    BRAND_EVIDENCE_EDITORIAL_LINK_TERMS,
    BRAND_EVIDENCE_FALLBACK_PATHS,
    BRAND_EVIDENCE_MAX_PAGES,
    BRAND_EVIDENCE_MIN_WORDS,
    BRAND_EVIDENCE_NAVIGATION_VERBS,
    BRAND_EVIDENCE_NEGATIVE_CACHE_SECONDS,
    BRAND_EVIDENCE_OFFERING_HUB_TERMS,
    BRAND_EVIDENCE_TOTAL_TIMEOUT_SECONDS,
    BRAND_EVIDENCE_UTILITY_LINK_TERMS,
    BRAND_EVIDENCE_VERSION,
)

logger = logging.getLogger(__name__)
_LINK_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class BrandEvidence:
    """The outcome of trying to read a brand's own website."""

    pages: tuple[BrandEvidencePage, ...] = ()
    # Why grounding failed, when it did (safe token for logs + API detail).
    failure_reason: str | None = None

    @property
    def word_count(self) -> int:
        return sum(page.word_count for page in self.pages)

    @property
    def is_sufficient(self) -> bool:
        """Whether there is enough captured text to ground a profile draft."""
        return self.word_count >= BRAND_EVIDENCE_MIN_WORDS

    def serialize(self) -> str:
        return serialize_brand_evidence(list(self.pages))

    def provenance(self) -> dict[str, object]:
        """Compact record of what was actually read, for the draft snapshot."""
        return {
            "evidence_version": BRAND_EVIDENCE_VERSION,
            "page_urls": [page.url for page in self.pages],
            "word_count": self.word_count,
        }


def _homepage_url(website_url: str) -> str:
    """Canonicalize the project's website URL, or "" when unusable.

    Shape/scheme/port validation ONLY. SSRF classes (loopback, private,
    link-local, cloud metadata) are deliberately NOT checked here: they are
    enforced by ``resolve_target`` inside the fetcher, after DNS resolution and
    on every redirect hop, which is the only place a name-based check cannot be
    defeated by DNS rebinding. A blocked target raises ``FetchError``, which
    ``fetch_brand_page`` reports as no evidence.
    """
    candidate = str(website_url or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        return canonicalize(candidate)
    except UrlPolicyError:
        return ""


def _link_terms(link: BrandEvidenceLink) -> set[str]:
    text = f"{link.label} {urlsplit(link.url).path}".casefold()
    return set(_LINK_TOKEN.findall(text))


def _offering_navigation_links(page: BrandEvidencePage) -> list[BrandEvidenceLink]:
    """Prefer links to where the business lists what it offers.

    The previous ranker used a thirteen-term retail vocabulary (shop, catalog,
    departments...). For a marketplace whose category rail is not in the header
    it matched nothing real, so the four internal reads became the gift-card
    store, a search stub and two login redirects -- four of five evidence pages
    saying nothing about what the business sells. The offering-hub vocabulary
    covers capabilities, practice areas, specialties, treatments, courses and
    use cases as well as shop and catalog, so it hits for every business model.

    A shallow path outranks a deep one: an offering INDEX is what is worth
    reading, not one leaf of it.
    """
    ranked: list[tuple[int, int, int, BrandEvidenceLink]] = []
    for index, link in enumerate(page.navigation_links):
        terms = _link_terms(link)
        excluded = (
            BRAND_EVIDENCE_EDITORIAL_LINK_TERMS | BRAND_EVIDENCE_UTILITY_LINK_TERMS
        )
        if terms & excluded:
            continue
        if link.label.casefold() in BRAND_EVIDENCE_NAVIGATION_VERBS:
            continue
        depth = len([part for part in urlsplit(link.url).path.split("/") if part])
        priority = 0 if terms & BRAND_EVIDENCE_OFFERING_HUB_TERMS else 1
        ranked.append((priority, depth, index, link))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in ranked]


def _selected_internal_links(
    homepage: str, page: BrandEvidencePage | None
) -> list[BrandEvidenceLink]:
    selected = [
        link
        for link in (_offering_navigation_links(page) if page is not None else [])
        if link.url != homepage
    ]
    known = {homepage, *(link.url for link in selected)}
    for url in fallback_urls(homepage, BRAND_EVIDENCE_FALLBACK_PATHS):
        if url not in known:
            selected.append(BrandEvidenceLink(url=url, label=""))
            known.add(url)
    return selected[: max(0, BRAND_EVIDENCE_MAX_PAGES - 1)]


async def _gather(homepage: str) -> list[BrandEvidencePage]:
    """Fetch one homepage plus at most four high-signal internal pages."""
    pages: list[BrandEvidencePage] = []
    # Keyed on the FINAL url (post-redirect): a site that redirects ``/about``
    # back to the homepage, or serves the same page at several paths, would
    # otherwise have its word count counted twice and could clear the grounding
    # floor on a single thin page repeated.
    seen_urls: set[str] = set()

    def _add(page: BrandEvidencePage | None) -> None:
        if page is None or page.url in seen_urls:
            return
        seen_urls.add(page.url)
        pages.append(page)

    async with SecureFetcher(resolver=SystemDnsResolver()) as fetcher:
        home_page = await fetch_brand_page(homepage, fetcher=fetcher)
        if home_page is not None:
            home_page = replace(home_page, role="homepage")
        _add(home_page)
        links = _selected_internal_links(homepage, home_page)
        fetched = await asyncio.gather(
            *(fetch_brand_page(link.url, fetcher=fetcher) for link in links),
            return_exceptions=True,
        )
        for link, result in zip(links, fetched, strict=True):
            if isinstance(result, BrandEvidencePage):
                _add(replace(result, role="commercial", navigation_label=link.label))
    return pages


# Short-lived cache + single-flight, keyed by canonical homepage URL. This
# prevents concurrent profile/discovery reads from crawling the same site more
# than once.
_cache: dict[str, tuple[float, BrandEvidence]] = {}
_cache_locks: dict[str, asyncio.Lock] = {}


def _cache_get(homepage: str) -> BrandEvidence | None:
    entry = _cache.get(homepage)
    if entry is None:
        return None
    expires_at, evidence = entry
    if expires_at <= asyncio.get_running_loop().time():
        _cache.pop(homepage, None)
        return None
    return evidence


def _cache_put(homepage: str, evidence: BrandEvidence, *, ttl_seconds: float) -> None:
    now = asyncio.get_running_loop().time()
    # Drop expired entries first, then bound the map so a long-lived process
    # crawling many brands cannot grow it without limit.
    for key, (expires_at, _) in list(_cache.items()):
        if expires_at <= now:
            _cache.pop(key, None)
    while len(_cache) >= BRAND_EVIDENCE_CACHE_MAX_ENTRIES:
        _cache.pop(next(iter(_cache)), None)
    _cache[homepage] = (now + ttl_seconds, evidence)


def _cache_result(homepage: str, evidence: BrandEvidence) -> None:
    """Cache useful content longer than transient empty crawl results."""
    ttl = (
        BRAND_EVIDENCE_CACHE_SECONDS
        if evidence.pages
        else BRAND_EVIDENCE_NEGATIVE_CACHE_SECONDS
    )
    _cache_put(homepage, evidence, ttl_seconds=ttl)


def reset_brand_evidence_cache() -> None:
    """Drop all cached evidence (tests; never called in request paths)."""
    _cache.clear()
    _cache_locks.clear()


async def collect_brand_evidence(website_url: str) -> BrandEvidence:
    """Read the brand's own site, under a total wall-clock budget.

    Never raises: a missing/invalid URL, an unreachable site, or a timeout all
    resolve to insufficient evidence with a safe reason. Callers must request
    user input instead of asking a model to fill factual gaps from memory.

    Results are cached briefly per canonical homepage URL, and concurrent
    callers for the same URL share a single crawl.
    """
    # Bound before the guard so the handlers can log it even when
    # ``_homepage_url`` is what failed (otherwise ``extra={"url": homepage}``
    # would itself raise UnboundLocalError inside the handler).
    homepage = ""
    try:
        # Inside the guard: ``canonicalize`` handles ``UrlPolicyError`` itself,
        # but a malformed user-supplied URL can still raise something else
        # (e.g. ValueError from IDNA/port parsing), and the contract here is
        # that this function never raises.
        homepage = _homepage_url(website_url)
        if not homepage:
            return BrandEvidence(failure_reason="no_usable_website_url")

        cached = _cache_get(homepage)
        if cached is not None:
            return cached

        # Single-flight: the first caller crawls, the rest await it and then
        # read the cache the winner populated.
        lock = _cache_locks.setdefault(homepage, asyncio.Lock())
        async with lock:
            cached = _cache_get(homepage)
            if cached is not None:
                return cached
            async with asyncio.timeout(BRAND_EVIDENCE_TOTAL_TIMEOUT_SECONDS):
                pages = await _gather(homepage)
            evidence = BrandEvidence(pages=tuple(pages))
            # Cache empty crawls only for the short single-flight window. They
            # must not make an explicit Retry replay a miss for the full
            # positive-result cache duration.
            _cache_result(homepage, evidence)
            return evidence
    except TimeoutError:
        logger.info("Brand evidence collection timed out", extra={"url": homepage})
        return BrandEvidence(failure_reason="evidence_fetch_timeout")
    except Exception:
        # Grounding is best-effort: an unexpected crawl failure returns empty
        # evidence with a reason for telemetry; drafting still proceeds.
        logger.exception("Unexpected brand evidence failure", extra={"url": homepage})
        return BrandEvidence(failure_reason="evidence_fetch_failed")
    finally:
        # Drop an uncontended lock so the map cannot grow unbounded.
        lock_obj = _cache_locks.get(homepage)
        if lock_obj is not None and not lock_obj.locked():
            _cache_locks.pop(homepage, None)
