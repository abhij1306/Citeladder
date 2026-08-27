"""Crawl admission, inventory, and runtime policy for Site Health.

This is deliberately separate from the fetch/rule catalog: these values govern
which URLs belong to a crawl and the allowance-to-runtime projection.  They
remain config-owned and are frozen onto a crawl by its planner.
"""

from __future__ import annotations

from typing import Final, Protocol

DISCOVERY_MODE_SAMPLE: Final = "sample"
DISCOVERY_MODE_FULL: Final = "full"
INVENTORY_SOURCE_CRAWL_IDS_KEY: Final = "inventory_source_crawl_ids"
AUTOMATIC_MONITOR_LIMIT_KEY: Final = "automatic_monitor_limit"
MANUAL_PHASE_LIFECYCLE_KEY: Final = "manual_phase_lifecycle"
SAMPLE_URL_LIMIT: Final = 10
SAMPLE_DISCOVERY_URL_CAP: Final = 200

URL_ADMISSION_POLICY_VERSION: Final = "sh-url-admission-3"
INPUT_MODE_AUTO: Final = "auto"
INPUT_MODE_EXACT_URLS: Final = "exact_urls"
INPUT_MODE_DISCOVERY_SEEDS: Final = "discovery_seeds"
INPUT_MODES: Final[frozenset[str]] = frozenset(
    {INPUT_MODE_AUTO, INPUT_MODE_EXACT_URLS, INPUT_MODE_DISCOVERY_SEEDS}
)
URL_EXCLUSION_HARD_PATH: Final = "hard_excluded_path"
URL_EXCLUSION_HARD_ASSET: Final = "hard_excluded_asset"
URL_EXCLUSION_HARD_QUERY: Final = "hard_excluded_query"
URL_EXCLUSION_OUT_OF_SCOPE: Final = "out_of_scope"
URL_EXCLUSION_NARROWED: Final = "narrowed"
URL_EXCLUSION_INVALID: Final = "invalid_url"
URL_EXCLUSION_DUPLICATE: Final = "duplicate"
URL_EXCLUSION_PAGE_KIND: Final = "page_kind_filtered"
URL_EXCLUSION_TRACKING: Final = "tracking_url"
URL_EXCLUSION_HARD_HOST: Final = "hard_excluded_host"

# These dispositions are distinct states, not a confidence gradient.
CORPUS_DISPOSITION_ANALYZE: Final = "analyze"
CORPUS_DISPOSITION_INVENTORY_ONLY: Final = "inventory_only"
CORPUS_DISPOSITION_EXCLUDE: Final = "exclude"
CORPUS_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {
        CORPUS_DISPOSITION_ANALYZE,
        CORPUS_DISPOSITION_INVENTORY_ONLY,
        CORPUS_DISPOSITION_EXCLUDE,
    }
)
DISPOSITION_REASON_HTML_CONTENT: Final = "html_content"
DISPOSITION_REASON_DOCUMENT: Final = "document"
DISPOSITION_REASON_UNSUPPORTED_MEDIA: Final = "unsupported_media"
CORPUS_DISPOSITION_VERSION: Final = "sh-disposition-1"

ITEM_KIND_HTML_PAGE: Final = "html_page"
ITEM_KIND_DOCUMENT: Final = "document"
ITEM_KIND_OTHER: Final = "other"
TEMPORAL_STATE_CURRENT: Final = "current"
TEMPORAL_STATE_HISTORICAL: Final = "historical"
TEMPORAL_STATE_FUTURE: Final = "future"
TEMPORAL_STATE_UNKNOWN: Final = "unknown"
TEMPORAL_STATES: Final[frozenset[str]] = frozenset(
    {
        TEMPORAL_STATE_CURRENT,
        TEMPORAL_STATE_HISTORICAL,
        TEMPORAL_STATE_FUTURE,
        TEMPORAL_STATE_UNKNOWN,
    }
)
URL_HARD_EXCLUSION_PATH_PATTERNS: Final[tuple[str, ...]] = (
    r"(?:^|/)(?:login|log-in|signin|sign-in|register|signup|sign-up)(?:/|$)",
    r"(?:^|/)(?:account|profile|admin|wp-admin|dashboard)(?:/|$)",
    r"(?:^|/)(?:cart|basket|checkout|payment|payments|order|orders|wishlist)(?:/|$)",
    r"(?:^|/)(?:search|tag|tags|author|authors|feed)(?:/|$)",
    r"(?:^|/)(?:viewcart|searchsuggestion)(?:/|$)",
    r"(?:^|/)item/(?:payments?[-_][^/]*|product[-_](?:delivery|warranty))(?:/|$)",
    r"(?:^|/)(?:preview|print|share)(?:/|$)",
)
# The same non-content endpoints as the path patterns above, but named by
# SUBDOMAIN instead of by path. Scope is the registrable domain plus every
# subdomain, so a storefront that puts its customer area on `account.<domain>`
# put it squarely in the frontier: the crawler spent budget on
# `https://account.<domain>/?buyer_flags=<jwt>` — a page that answers 401/403 to
# an unauthenticated fetch — and the resulting Error/Blocked rows were enough
# to finish the crawl as ``partially_completed``. Only the LEFTMOST label is
# matched, so `shop.<domain>` and a path like `/my-account-guide` are untouched.
URL_HARD_EXCLUSION_HOST_LABELS: Final[frozenset[str]] = frozenset(
    {
        "account",
        "accounts",
        "admin",
        "auth",
        "basket",
        "cart",
        "checkout",
        "login",
        "signin",
        "signup",
        "register",
        "payment",
        "payments",
        "orders",
        "wishlist",
    }
)
URL_HARD_EXCLUSION_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "q",
        "query",
        "s",
        "search",
        "filter",
        "filters",
        "facet",
        "sort",
        "page",
        "paged",
        "preview",
    }
)
# Documents remain inventory evidence.  Only unsafe/contentless assets exclude.
INVENTORY_DOCUMENT_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
)
DOCUMENT_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
URL_HARD_EXCLUSION_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        ".zip",
        ".gz",
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".svg",
        ".ico",
        ".css",
        ".js",
        ".mjs",
        ".xml",
        ".json",
        ".csv",
        ".txt",
        ".mp3",
        ".mp4",
        ".webm",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".tar",
        ".bz2",
        ".7z",
        ".rar",
        ".exe",
        ".msi",
        ".dmg",
        ".pkg",
        ".apk",
        ".deb",
        ".rpm",
    }
)
URL_VALUE_PRIORITIES: Final[dict[str, int]] = {
    "root": 100,
    "product": 90,
    "comparison": 85,
    "service": 80,
    "local": 80,
    "category": 70,
    "pricing": 70,
    "article": 60,
    "guide": 60,
    "faq": 60,
    "docs": 60,
    "trust": 40,
    "other": 20,
}

PHASE_DISCOVERY: Final = "discovery"
PHASE_ANALYSIS: Final = "analysis"
PHASES: Final[frozenset[str]] = frozenset({PHASE_DISCOVERY, PHASE_ANALYSIS})
PHASE_RUN_RUNNING: Final = "running"
PHASE_RUN_STOPPED: Final = "stopped"
PHASE_RUN_COMPLETED: Final = "completed"
PHASE_RUN_FAILED: Final = "failed"
PHASE_RUN_STATUSES: Final[frozenset[str]] = frozenset(
    {PHASE_RUN_RUNNING, PHASE_RUN_STOPPED, PHASE_RUN_COMPLETED, PHASE_RUN_FAILED}
)
FRONTIER_PENDING: Final = "pending"
FRONTIER_ADMITTED: Final = "admitted"
SELECTION_SOURCE_USER: Final = "user"
SELECTION_SOURCE_FREE_SAMPLE: Final = "free_sample"
SELECTION_SOURCE_BOOTSTRAP: Final = "bootstrap"
SELECTION_SOURCES: Final[frozenset[str]] = frozenset(
    {SELECTION_SOURCE_USER, SELECTION_SOURCE_FREE_SAMPLE, SELECTION_SOURCE_BOOTSTRAP}
)


class _RuntimeSettings(Protocol):
    sample_discovery_url_cap: int
    sample_url_limit: int


class SiteHealthRuntimePolicy:
    """Neutral, immutable projection of a resolved monitored-URL allowance."""

    __slots__ = (
        "discovery_mode",
        "discovery_url_cap",
        "sample_url_limit",
        "monitored_url_limit",
        "allows_user_selection",
        "count_disclosure",
    )

    def __init__(
        self,
        *,
        discovery_mode: str,
        discovery_url_cap: int | None,
        sample_url_limit: int,
        monitored_url_limit: int,
        allows_user_selection: bool,
        count_disclosure: bool,
    ) -> None:
        self.discovery_mode = discovery_mode
        self.discovery_url_cap = discovery_url_cap
        self.sample_url_limit = sample_url_limit
        self.monitored_url_limit = monitored_url_limit
        self.allows_user_selection = allows_user_selection
        self.count_disclosure = count_disclosure


def runtime_policy_for_allowance(
    monitored_urls_allowance: int, *, settings: _RuntimeSettings
) -> SiteHealthRuntimePolicy:
    """Fail closed to a bounded sample policy for a non-positive allowance."""
    if monitored_urls_allowance > 0:
        return SiteHealthRuntimePolicy(
            discovery_mode=DISCOVERY_MODE_FULL,
            discovery_url_cap=None,
            sample_url_limit=0,
            monitored_url_limit=monitored_urls_allowance,
            allows_user_selection=True,
            count_disclosure=True,
        )
    return SiteHealthRuntimePolicy(
        discovery_mode=DISCOVERY_MODE_SAMPLE,
        discovery_url_cap=settings.sample_discovery_url_cap,
        sample_url_limit=settings.sample_url_limit,
        monitored_url_limit=0,
        allows_user_selection=False,
        count_disclosure=False,
    )
