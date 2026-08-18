from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.site_health_acquisition import (
    _BASE_DIR,
    _PROJECT_ROOT,
    ERROR_ACQUISITION_UNAVAILABLE,
    ERROR_CONNECTION_FAILED,
    ERROR_TIMEOUT,
)
from app.core.config.site_health_crawl_policy import (
    SAMPLE_DISCOVERY_URL_CAP as SAMPLE_DISCOVERY_URL_CAP,
)
from app.core.config.site_health_crawl_policy import (
    SAMPLE_URL_LIMIT,
    SiteHealthRuntimePolicy,
)
from app.core.config.site_health_crawl_policy import (
    runtime_policy_for_allowance as _runtime_policy_for_allowance,
)
from app.core.config.task_queue import ERROR_MAX_ATTEMPTS, PostgresQueueSpec


class SiteHealthSettings(BaseSettings):
    """Env-overridable Site Health crawler/queue guardrails.

    Every operational bound the secure fetcher, frontier, robots/sitemap
    parser, worker, and queue read. Frozen into ``SiteCrawl.configuration`` at
    creation so a live change never alters an in-flight run (invariant 9). All
    knobs use the ``SITE_HEALTH_`` env prefix (no service literals — invariant
    1).
    """

    model_config = SettingsConfigDict(
        env_prefix="SITE_HEALTH_",
        extra="ignore",
        # Same .env sources as the root Settings so SITE_HEALTH_* overrides in
        # the repo-root / backend-local .env work without exporting them.
        env_file=(str(_PROJECT_ROOT / ".env"), str(_BASE_DIR / ".env")),
        env_file_encoding="utf-8",
    )

    # --- Neutral sample policy (dev-tunable) ---
    # Manual seed, page-kind, and oversized crawl controls are development-only.
    # The standard product path is one bounded, progressively analyzed crawl.
    advanced_controls_enabled: bool = False
    # Standard user-initiated crawls discover at most 500 pages. Development
    # advanced controls may explicitly request more, up to the separate
    # 50,000-URL internal ceilings below.
    automatic_page_limit: int = 500
    max_requested_page_limit: int = 500
    max_discovery_urls: int = 50_000
    max_analysis_urls: int = 50_000
    max_preview_rows: int = 500
    max_preview_input_bytes: int = 262_144
    max_seed_urls: int = 500
    max_narrowing_globs: int = 100
    max_glob_length: int = 512
    # Sample-mode crawl allowance used when the workspace's resolved
    # ``monitored_urls`` entitlement is zero: a deterministic automatic sample
    # of this many admitted URLs across the whole workspace; no user
    # selection; no count disclosure.
    sample_url_limit: int = SAMPLE_URL_LIMIT
    # Sample mode: how far discovery maps the site (inventory only — NOT
    # analyzed). Decoupled from the analysis budget above.
    sample_discovery_url_cap: int = SAMPLE_DISCOVERY_URL_CAP

    # --- Frontier / discovery bounds ---
    # Absolute frontier ceiling for a FULL (Starter) crawl to bound memory/time.
    max_frontier_urls: int = 50000
    # Max discovery depth from the root.
    max_crawl_depth: int = 20
    # Batch size for progressive inventory admission (INSERT ... ON CONFLICT).
    admission_batch_size: int = 200
    # Maximum number of prior full-discovery crawl inventories carried forward
    # into a Starter recrawl's dashboard scope. Bounds the frozen JSON config
    # and the UNION used by inventory/page queries.
    inventory_history_crawl_limit: int = 20

    # --- Concurrency / politeness ---
    # Global in-process concurrent fetch ceiling for the Site Health worker.
    global_concurrency: int = 8
    # Per-host concurrent fetch ceiling.
    per_host_concurrency: int = 6
    # Minimum delay between requests to the same host (politeness); robots
    # crawl-delay overrides upward. A 150 ms floor permits roughly six request
    # starts per second on a responsive owned site without turning that rate
    # into a promise; fetch latency, retries, parsing, and declared crawl-delay
    # still determine observed throughput.
    per_host_delay_seconds: float = 0.15
    # Default crawl delay applied when robots does not specify one.
    default_crawl_delay_seconds: float = 0.0
    # Cap on any robots-declared crawl delay we will honor.
    max_crawl_delay_seconds: float = 30.0

    # --- Fetch limits ---
    # Per-request wall-clock timeout.
    request_timeout_seconds: float = 20.0
    # Max redirect hops manually followed (each re-validated for SSRF/scope).
    max_redirects: int = 5
    # Wire-byte (raw network) cap per response.
    max_response_wire_bytes: int = 5_000_000
    # Decoded-byte cap per response (guards decompression bombs).
    max_response_decoded_bytes: int = 20_000_000
    # HTML size cap fed to the parser.
    max_html_bytes: int = 5_000_000

    # --- Server-owned acquisition ladder ---
    # Each crawl freezes these values in its configuration. They are kept here
    # (not in a connector) because acquisition behavior is an operational
    # policy, not application logic.
    acquisition_policy_version: str = "sh-acquisition-1"
    curl_cffi_enabled: bool = False
    curl_cffi_impersonation_profile: str = "chrome"
    # A successful but unusually small HTML document is commonly a challenge
    # shell. Zero disables this signal for installations that prefer only
    # explicit challenge/status evidence.
    curl_cffi_low_content_bytes: int = 512
    curl_cffi_trigger_statuses: tuple[int, ...] = (403, 429, 503)
    # Client-rendered-shell detection. ``curl_cffi_low_content_bytes`` measures
    # the whole RESPONSE, which is the wrong ruler for the case the browser rung
    # exists to fix: a real JS shell ships a full nav, footer, and bundle
    # reference, so its byte count is ample while its readable text is nearly
    # empty. Measured live against a public JS-shell page, the served document
    # was well over the low-content floor and never escalated — rung 3 was
    # unreachable for exactly the input it was built for.
    #
    # A response escalates as a shell only when ALL THREE hold, so an ordinary
    # short page (a brief contact page) never pays for a render:
    #   - readable text below ``js_shell_min_text_chars``;
    #   - total decoded bytes at/above ``curl_cffi_low_content_bytes`` (below
    #     that it is plain ``low_content``, a different fact);
    #   - the document actually loads script (``<script src>`` or a substantial
    #     inline script), i.e. content plausibly arrives client-side.
    # 0 disables the signal.
    js_shell_min_text_chars: int = 600
    js_shell_min_inline_script_chars: int = 1024
    # Bounded prefix of the decoded body the detector scans. Text-bearing markup
    # is front-loaded; scanning a whole multi-megabyte document to answer "is
    # this empty?" would be per-response work for no added signal.
    js_shell_scan_bytes: int = 262_144
    # Only these curl-rung failure tokens may advance to the browser rung.
    # Policy/cap/redirect failures must never be bypassed.
    browser_continue_error_codes: tuple[str, ...] = (
        ERROR_CONNECTION_FAILED,
        ERROR_TIMEOUT,
        ERROR_ACQUISITION_UNAVAILABLE,
    )
    # --- Rung 3: bundled headless browser (patchright) ---
    # The last rung of the frozen ladder. It renders a JS shell locally; there
    # is deliberately no paid acquisition vendor and no real-Chrome escalation.
    browser_enabled: bool = False
    browser_navigation_timeout_seconds: float = 20.0
    # How long readiness may wait for the DOM to settle after navigation.
    browser_readiness_timeout_seconds: float = 8.0
    # A rendered document below this size is still treated as a challenge/JS
    # shell rather than usable evidence.
    browser_low_content_bytes: int = 512
    # NOTE: the same-site JSON/XHR capture knobs that used to live here are
    # gone with the capture itself. Keeping tunables for a feature the transport
    # no longer has advertises a capability that does nothing.
    # Each pooled entry is a live browser process pinned to one resolved
    # address, so the pool is bounded and evicts least-recently-used. Contexts
    # are deliberately NOT pooled — one fresh context per fetch is what keeps
    # cookies and storage from leaking between crawled pages.
    browser_pool_max_browsers: int = 4
    # Chromium's sandbox contains code fetched from crawled sites. Disable it
    # ONLY on a platform that cannot grant the required kernel capability.
    browser_disable_sandbox: bool = False

    # --- Sitemap limits ---
    max_sitemap_index_depth: int = 3
    max_sitemap_urls: int = 50000
    max_sitemap_decoded_bytes: int = 50_000_000
    # v2 P2 site-setup ingestion (Starter crawls): how many sitemap DOCUMENTS
    # (index children included) one crawl fetches, and how many sitemap URLs
    # one crawl admits into the frontier (bounded, deterministic).
    max_sitemap_documents: int = 32
    max_sitemap_admitted_urls: int = 5000
    # --- Site setup fetch caps (v2 P2: robots.txt / llms.txt probes) ---
    # Decoded-byte caps for the well-known file fetches (much tighter than the
    # page-fetch cap: these files are small; anything larger is abuse/error).
    robots_max_decoded_bytes: int = 512_000
    llms_txt_max_decoded_bytes: int = 262_144
    # How long a cached per-authority robots policy stays fresh before the
    # worker re-fetches it (RFC 9309 caching guidance is ~24h).
    robots_cache_ttl_seconds: float = 86_400.0
    # Hard ceiling on cached authorities. The cache is NOT bounded by the
    # crawl's own domain: link checks resolve robots for arbitrary EXTERNAL
    # link targets, so a long-lived worker would otherwise retain one policy +
    # one lock per host it ever probed. Expired entries are dropped first;
    # beyond the cap, the oldest go. 0 disables the cap.
    robots_cache_max_authorities: int = 2048

    # --- Parser bounds (bounded, deterministic extraction) ---
    max_links_per_page: int = 2000
    max_structured_data_blocks: int = 100
    max_text_chars: int = 200_000

    # --- Queue / lease / retry ---
    lease_ttl_seconds: float = 120.0
    heartbeat_interval_seconds: float = 30.0
    max_attempts: int = 4
    retry_base_delay_seconds: float = 2.0
    retry_max_delay_seconds: float = 60.0
    retry_jitter_seconds: float = 1.5
    worker_concurrency: int = 8
    poll_interval_seconds: float = 1.0
    # Bounded recheck when analyze observes a still-running discover task for
    # the same URL. A non-zero delay prevents a claim/defer hot loop.
    analysis_dependency_retry_seconds: float = 1.0
    # Deterministic bound on how many expired leases the sweeper reclaims in
    # ONE transaction. A mass expiry across a large frontier (e.g. 50,000
    # URLs) would otherwise lock and update every expired row in a single
    # long-running transaction and stall live claims; the sweeper instead
    # drains the remainder across subsequent polls.
    lease_reclaim_batch_size: int = 500
    # Backstop for crawl terminalization. A crawl normally goes terminal from a
    # task's finalize; any path that drains the last non-terminal task without
    # running one (a sweeper reclaim at max attempts, a killed process between
    # the queue ack and the finalize) would strand it in an active status
    # forever. The worker force-reconciles active crawls that have no
    # outstanding tasks and have not been touched for this long. Defaults to
    # 2x the lease TTL so a crawl merely between tasks is never swept up. Set
    # to 0 to disable.
    stalled_crawl_reconcile_seconds: float = 240.0
    # Bound on how many stalled crawls one sweep reconciles, keeping the
    # backstop's cost per loop iteration flat.
    stalled_crawl_reconcile_batch: int = 50

    # --- Link checking ---
    max_link_checks_per_page: int = 200
    link_check_timeout_seconds: float = 10.0
    # How many of ONE page's link probes may be in flight at once. Probes used
    # to run strictly serially, so a page's links cost (links x host delay) and
    # the crawl sat visibly "finished" for ~10s per page while they drained.
    # The per-host gate + crawl-delay still serialize same-host requests
    # underneath this; the ceiling keeps a 200-link page from queueing 200
    # simultaneous probes.
    link_check_concurrency: int = 8

    # --- Export ---
    # Bounds how many rows ``_export_items`` materializes into memory for a
    # single CSV/Markdown export before it truncates, so a very large Starter
    # inventory can never exhaust memory on one request.
    max_export_items: int = 20_000

    # --- SSE / events ---
    sse_poll_interval_seconds: float = 2.0
    sse_max_duration_seconds: float = 300.0

    @model_validator(mode="after")
    def _validate_sample_limits(self) -> SiteHealthSettings:
        """Reject a negative sample limit from env overrides.

        The limit feeds quota arithmetic and SQL ``LIMIT`` clauses; a negative
        value would silently break sampling. Zero stays allowed (an
        intentional "no sample" configuration).
        """
        for name in ("sample_url_limit", "sample_discovery_url_cap"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.inventory_history_crawl_limit <= 0:
            raise ValueError("inventory_history_crawl_limit must be positive")
        for name in (
            "automatic_page_limit",
            "max_requested_page_limit",
            "max_discovery_urls",
            "max_analysis_urls",
            "max_preview_rows",
            "max_preview_input_bytes",
            "max_seed_urls",
            "max_narrowing_globs",
            "max_glob_length",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        return self

    @model_validator(mode="after")
    def _validate_page_limit_relationships(self) -> SiteHealthSettings:
        """Keep defaults inside their public and internal ceilings."""
        if self.automatic_page_limit > self.max_requested_page_limit:
            raise ValueError(
                "automatic_page_limit must not exceed max_requested_page_limit"
            )
        if self.max_requested_page_limit > self.max_discovery_urls:
            raise ValueError(
                "max_requested_page_limit must not exceed max_discovery_urls"
            )
        return self

    @model_validator(mode="after")
    def _validate_acquisition_ladder(self) -> SiteHealthSettings:
        """Keep fallback behavior bounded, server-owned, and reproducible."""
        if not self.acquisition_policy_version.strip():
            raise ValueError("acquisition_policy_version must not be empty")
        if not self.curl_cffi_impersonation_profile.strip():
            raise ValueError("curl_cffi_impersonation_profile must not be empty")
        if self.curl_cffi_low_content_bytes < 0:
            raise ValueError("curl_cffi_low_content_bytes must not be negative")
        if any(
            status < 100 or status > 599 for status in self.curl_cffi_trigger_statuses
        ):
            raise ValueError("curl_cffi_trigger_statuses must be HTTP status codes")
        if self.browser_low_content_bytes < 0:
            raise ValueError("browser_low_content_bytes must not be negative")
        if self.browser_navigation_timeout_seconds <= 0:
            raise ValueError("browser_navigation_timeout_seconds must be positive")
        if self.browser_readiness_timeout_seconds <= 0:
            raise ValueError("browser_readiness_timeout_seconds must be positive")
        if self.browser_pool_max_browsers < 1:
            raise ValueError("browser_pool_max_browsers must be at least 1")
        # Negative bounds do not disable a signal, they invert it: a negative
        # scan window makes every body read as empty, and a negative text floor
        # makes every 2xx page a shell. Zero is the documented "off" value for
        # the two that gate the signal.
        for name in ("js_shell_min_text_chars", "js_shell_scan_bytes"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must not be negative")
        # This one has no "off" meaning: zero would make every empty inline
        # <script> count as application code, so an ordinary analytics stub
        # would escalate a static page to a browser render.
        if self.js_shell_min_inline_script_chars < 1:
            raise ValueError("js_shell_min_inline_script_chars must be positive")
        return self

    @model_validator(mode="after")
    def _validate_discovery_cap(self) -> SiteHealthSettings:
        """Discovery must map a superset of what it analyzes.

        A cap below the sample budget would starve analysis of candidates it is
        entitled to fetch. Its own validator (rather than a branch bolted onto
        ``_validate_sample_limits``) keeps that method on its downward
        complexity ratchet.
        """
        if self.sample_discovery_url_cap < self.sample_url_limit:
            raise ValueError(
                "sample_discovery_url_cap must not be less than sample_url_limit"
            )
        return self

    @model_validator(mode="after")
    def _validate_lease_and_heartbeat(self) -> SiteHealthSettings:
        """Enforce positive lease/heartbeat values and heartbeat < lease TTL.

        A heartbeat interval that is not strictly less than the lease TTL
        would let the sweeper reclaim a still-live task before it ever gets a
        chance to send its first heartbeat.
        """
        if self.lease_ttl_seconds <= 0:
            raise ValueError("lease_ttl_seconds must be positive")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be positive")
        if self.heartbeat_interval_seconds >= self.lease_ttl_seconds:
            raise ValueError(
                "heartbeat_interval_seconds must be strictly less than "
                "lease_ttl_seconds"
            )
        if self.lease_reclaim_batch_size <= 0:
            raise ValueError("lease_reclaim_batch_size must be positive")
        if self.stalled_crawl_reconcile_batch <= 0:
            raise ValueError("stalled_crawl_reconcile_batch must be positive")
        if self.stalled_crawl_reconcile_seconds < 0:
            raise ValueError("stalled_crawl_reconcile_seconds must not be negative")
        if (
            0 < self.stalled_crawl_reconcile_seconds
            and self.stalled_crawl_reconcile_seconds <= self.lease_ttl_seconds
        ):
            # A threshold inside the lease window could force-reconcile a crawl
            # whose last task is still legitimately leased and about to write.
            raise ValueError(
                "stalled_crawl_reconcile_seconds must exceed lease_ttl_seconds "
                "(or be 0 to disable)"
            )
        for name in (
            "global_concurrency",
            "per_host_concurrency",
            "worker_concurrency",
            "link_check_concurrency",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.per_host_concurrency > self.global_concurrency:
            raise ValueError("per_host_concurrency must not exceed global_concurrency")
        return self

    def retry_delay(
        self, attempt: int, retry_after_seconds: float | None = None
    ) -> float:
        """Seconds to wait before the next attempt.

        Prefers a server-advised ``Retry-After`` (clamped); else exponential
        backoff capped at the max, plus deterministic jitter (derived from the
        attempt number, not RNG, so it stays reproducible — invariant 9).
        """
        cap = self.retry_max_delay_seconds
        if retry_after_seconds is not None:
            return min(retry_after_seconds, cap)
        base = self.retry_base_delay_seconds * (2**attempt)
        jitter = (attempt * 0.37) % 1.0 * self.retry_jitter_seconds
        return min(base, cap) + jitter

site_health_settings = SiteHealthSettings()

def runtime_policy_for_allowance(
    monitored_urls_allowance: int,
) -> SiteHealthRuntimePolicy:
    """Resolve the runtime policy using the live Site Health settings."""
    return _runtime_policy_for_allowance(
        monitored_urls_allowance, settings=site_health_settings
    )

def _site_crawl_task_model() -> type[SiteCrawlTask]:
    # Lazy import: this config module must never import a model at import time
    # (would create a config <-> models circular import).
    from app.models.site_health.queue import SiteCrawlTask

    return SiteCrawlTask

def _site_task_claim_order(model: type[SiteCrawlTask]) -> tuple:
    # Deterministic claim order: priority, then FIFO by availability, then the
    # frozen randomized frontier position, then a stable id tiebreak.
    return (
        model.priority.desc(),
        model.available_at.asc(),
        model.randomized_position.asc(),
        model.id.asc(),
    )

SITE_CRAWL_QUEUE_SPEC: Final[PostgresQueueSpec[SiteCrawlTask]] = PostgresQueueSpec(
    model_ref=_site_crawl_task_model,
    lease_ttl=lambda: site_health_settings.lease_ttl_seconds,
    claim_order=_site_task_claim_order,
    max_attempts_error=ERROR_MAX_ATTEMPTS,
    # A crawl terminalizes only via the worker's reconcile, which runs in a
    # task's finalize. The sweeper failing a task at max attempts bypasses that
    # path entirely, so it must report the owning crawl for reconciliation —
    # otherwise a crawl whose LAST task the sweeper failed stays 'running'
    # forever (no snapshot, no completion event, endless client polling).
    parent_id_attr="crawl_id",
)

if TYPE_CHECKING:
    # Type-only: config never imports a model at runtime (circular import).
    from app.models.site_health.queue import SiteCrawlTask
