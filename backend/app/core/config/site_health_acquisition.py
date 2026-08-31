from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final

SITE_HEALTH_MAX_TITLE_CHARS: Final = 2048

SITE_HEALTH_MAX_META_CHARS: Final = 4096

SITE_HEALTH_MAX_HEADING_CHARS: Final = 512

SITE_HEALTH_MAX_HEADINGS_KEPT: Final = 50

SITE_HEALTH_MAX_URL_CHARS: Final = 2048

SITE_HEALTH_MAX_ANCHOR_TEXT_CHARS: Final = 512

SITE_HEALTH_MAX_AUTHOR_CHARS: Final = 256

SITE_HEALTH_MAX_DATE_CHARS: Final = 64

SITE_HEALTH_MAX_OUTBOUND_DOMAINS: Final = 100

SITE_HEALTH_MAX_DOMAIN_CHARS: Final = 255

SITE_HEALTH_MAX_HREFLANG_ALTERNATES: Final = 50

SITE_HEALTH_MAX_HREFLANG_CHARS: Final = 35

SITE_HEALTH_MAX_CTA_TEXTS: Final = 32

SITE_HEALTH_MAX_CTA_TEXT_CHARS: Final = 256

SITE_HEALTH_MAX_FORM_FIELDS: Final = 32

SITE_HEALTH_MAX_FORM_FIELD_CHARS: Final = 128

SITE_HEALTH_MAX_LINK_CONTEXT: Final = 64

SITE_HEALTH_MAX_LINK_CONTEXT_CHARS: Final = 512

CTA_BUTTON_ROLE_TOKENS: Final[frozenset[str]] = frozenset(
    {"button", "btn", "cta", "apply", "enquire", "enquiry", "submit"}
)

SITE_HEALTH_MAX_FIRST_ANSWER_CHARS: Final = 512

SITE_HEALTH_MAX_INLINE_SCRIPT_CHARS: Final = 500_000

SITE_HEALTH_MAX_CONTACT_POINTS: Final = 16

SITE_HEALTH_MAX_CONTACT_VALUE_CHARS: Final = 256

SITE_HEALTH_MAX_PATH_CHARS: Final = 512

SITE_HEALTH_MAX_SIGNAL_DETAIL_CHARS: Final = 256

SITE_HEALTH_MAX_EVIDENCE_URLS: Final = 10

SITE_HEALTH_MAX_JSONLD_DEPTH: Final = 12

SITE_HEALTH_MAX_NAME_CHARS: Final = 256

SITE_HEALTH_MAX_SAME_AS_ENTRIES: Final = 8

SITE_HEALTH_MAX_SAME_AS_CHARS: Final = 256

_BASE_DIR = Path(__file__).resolve().parents[3]

_PROJECT_ROOT = _BASE_DIR.parent

if TYPE_CHECKING:
    # Type-only: config never imports a model at runtime (circular import).
    pass

FETCH_PURPOSE_DISCOVER: Final = "discover"

FETCH_PURPOSE_ANALYZE: Final = "analyze"

FETCH_PURPOSE_ROBOTS: Final = "robots"

FETCH_PURPOSE_SITEMAP: Final = "sitemap"

FETCH_PURPOSE_LLMS: Final = "llms"

INFRASTRUCTURE_FETCH_EXACT_PATHS: Final[dict[str, frozenset[str]]] = {
    FETCH_PURPOSE_ROBOTS: frozenset({"/robots.txt"}),
    FETCH_PURPOSE_LLMS: frozenset({"/llms.txt"}),
    FETCH_PURPOSE_SITEMAP: frozenset(),
}

INFRASTRUCTURE_FETCH_PATH_SUFFIXES: Final[dict[str, tuple[str, ...]]] = {
    FETCH_PURPOSE_ROBOTS: (),
    FETCH_PURPOSE_LLMS: (),
    FETCH_PURPOSE_SITEMAP: (".xml", ".xml.gz"),
}

SITE_HEALTH_USER_AGENT: Final = "CiteLadderSiteHealthBot/1.0 (+https://citeladder)"

ROBOTS_TXT_PATH: Final = "/robots.txt"

LLMS_TXT_PATH: Final = "/llms.txt"

SITEMAP_DEFAULT_PATHS: Final[tuple[str, ...]] = ("/sitemap.xml",)

SEARCH_CITATION_CRAWLER_BOTS: Final[tuple[str, ...]] = (
    "Googlebot",
    "Bingbot",
    "OAI-SearchBot",
    "PerplexityBot",
)
TRAINING_CRAWLER_BOTS: Final[tuple[str, ...]] = (
    "GPTBot",
    "ClaudeBot",
    "Google-Extended",
)
USER_TRIGGERED_FETCHER_BOTS: Final[tuple[str, ...]] = (
    "ChatGPT-User",
    "Perplexity-User",
)
AI_CRAWLER_BOTS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys(
        (
            *SEARCH_CITATION_CRAWLER_BOTS,
            *TRAINING_CRAWLER_BOTS,
            *USER_TRIGGERED_FETCHER_BOTS,
        )
    )
)

AI_CRAWLER_STANCE_ALLOW: Final = "allow"

AI_CRAWLER_STANCE_BLOCK: Final = "block"

ROBOTS_FETCH_STATUS_FETCHED: Final = "fetched"

ROBOTS_FETCH_STATUS_NOT_FOUND: Final = "not_found"

ROBOTS_FETCH_STATUS_FETCH_FAILED: Final = "fetch_failed"

ACQUISITION_TRANSPORT_CURL_CFFI: Final = "curl_cffi"

ACQUISITION_TRIGGER_INITIAL: Final = "initial"

BOT_BLOCK_BODY_MARKERS: Final[tuple[str, ...]] = (
    "cf-chl",
    "challenge-platform",
    # Distinctive Cloudflare interstitial title, verbatim including the
    # ellipsis — the bare phrase "just a moment" is ordinary English and would
    # misreport a healthy page whose copy contains it as blocked.
    "just a moment...",
    # NOTE: "attention required" was removed — it is plain English, not a
    # distinctive challenge-platform string, so it could false-positive a
    # healthy page into ERROR_BOT_BLOCKED (no artifact, no analysis).
    "px-captcha",
    "perimeterx",
    "datadome",
    "incapsula",
    "distil_r",
)

BOT_BLOCK_MARKER_SCAN_BYTES: Final = 8192

ERROR_ROBOTS_DENIED: Final = "robots_denied"

ERROR_ROBOTS_UNAVAILABLE: Final = "robots_unavailable"

ERROR_DNS_RESOLUTION_FAILED: Final = "dns_resolution_failed"

ERROR_SSRF_BLOCKED: Final = "ssrf_blocked"

ERROR_REDIRECT_LIMIT: Final = "redirect_limit"

ERROR_RESPONSE_TOO_LARGE: Final = "response_too_large"

ERROR_UNSUPPORTED_CONTENT_TYPE: Final = "unsupported_content_type"

ERROR_TIMEOUT: Final = "timeout"

ERROR_HTTP_4XX: Final = "http_4xx"

ERROR_HTTP_5XX: Final = "http_5xx"

ERROR_CONNECTION_FAILED: Final = "connection_failed"

ERROR_MALFORMED_RESPONSE: Final = "malformed_response"

ERROR_URL_ADMISSION_REJECTED: Final = "url_admission_rejected"

ERROR_ACQUISITION_UNAVAILABLE: Final = "acquisition_unavailable"

ERROR_BOT_BLOCKED: Final = "bot_blocked"

CLASSIFICATION_BODYLESS_STATUS_CODES: Final[frozenset[int]] = frozenset({204, 205})

FETCH_ATTEMPT_OUTCOME_SUCCESS: Final = "success"

FETCH_ATTEMPT_OUTCOME_ERROR: Final = "error"

SITE_FETCH_ERROR_TOKENS: Final[frozenset[str]] = frozenset(
    {
        ERROR_ROBOTS_DENIED,
        ERROR_ROBOTS_UNAVAILABLE,
        ERROR_DNS_RESOLUTION_FAILED,
        ERROR_SSRF_BLOCKED,
        ERROR_REDIRECT_LIMIT,
        ERROR_RESPONSE_TOO_LARGE,
        ERROR_UNSUPPORTED_CONTENT_TYPE,
        ERROR_TIMEOUT,
        ERROR_HTTP_4XX,
        ERROR_HTTP_5XX,
        ERROR_CONNECTION_FAILED,
        ERROR_MALFORMED_RESPONSE,
        ERROR_URL_ADMISSION_REJECTED,
        ERROR_ACQUISITION_UNAVAILABLE,
        ERROR_BOT_BLOCKED,
    }
)

POLICY_BLOCKING_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        ERROR_ROBOTS_DENIED,
        ERROR_ROBOTS_UNAVAILABLE,
        ERROR_SSRF_BLOCKED,
        ERROR_BOT_BLOCKED,
    }
)

# Terminal outcomes that mean the page LEFT the corpus, not that we failed to
# get it. Nothing went wrong for any of these: we decided not to analyze the
# page (our admission policy rejected the resolved URL), or the site told us
# not to (``robots_denied`` -- a directive we chose to obey, and obeying it is
# not a defect). Supported documents complete successfully as inventory-only
# evidence and therefore never need an error-code exception here.
#
# Counting these as failures is what left a crawl that reached every real page
# reporting ``partially_completed`` / ``discovery_incomplete``. They must leave
# the applicable set on BOTH sides of the ratio, never be counted as errors.
# ``robots_unavailable`` is deliberately absent: that is a fetch that did not
# work, and it may work on the next attempt.
CORPUS_EXCLUSION_ERROR_CODES: Final[frozenset[str]] = frozenset(
    {
        ERROR_URL_ADMISSION_REJECTED,
        ERROR_ROBOTS_DENIED,
    }
)

# Everything that must not be reported to the user as an error: a page we were
# blocked from, plus a page that left the corpus by policy. Kept as one set so
# the two overlap (``robots_denied`` is both) without being subtracted twice.
NON_ERROR_TERMINAL_CODES: Final[frozenset[str]] = (
    POLICY_BLOCKING_ERROR_CODES | CORPUS_EXCLUSION_ERROR_CODES
)
