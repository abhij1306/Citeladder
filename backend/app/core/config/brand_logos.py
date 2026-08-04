"""Brand-logo crawl/cache guardrails (invariant 1)."""

from typing import Final

BRAND_LOGO_STATUS_READY: Final = "ready"
BRAND_LOGO_STATUS_FAILED: Final = "failed"

BRAND_LOGO_USER_AGENT: Final = "CiteLadderBrandLogoBot/1.0"
BRAND_LOGO_REQUEST_TIMEOUT_SECONDS: Final = 4.0
BRAND_LOGO_MAX_REDIRECTS: Final = 3
# Big-brand homepages routinely exceed a few hundred KB of HTML. The icon
# <link> tags live in <head>, but the fetcher caps the WHOLE response — so a cap
# smaller than the page means the fetch fails outright and discovery falls back
# to /favicon.ico, which many large sites do not serve (samsung.com 404s it and
# declares its icon on a CDN host instead). Budget for a large homepage rather
# than lose the logo for exactly the biggest brands.
BRAND_LOGO_MAX_HTML_BYTES: Final = 2_097_152
BRAND_LOGO_MAX_IMAGE_BYTES: Final = 262_144
BRAND_LOGO_MAX_CANDIDATES: Final = 6
BRAND_LOGO_FETCH_CONCURRENCY: Final = 4
BRAND_LOGO_REFRESH_TIMEOUT_SECONDS: Final = 10.0
BRAND_LOGO_SUCCESS_CACHE_SECONDS: Final = 604_800
BRAND_LOGO_FAILURE_CACHE_SECONDS: Final = 86_400
BRAND_LOGO_CACHE_MAX_AGE_SECONDS: Final = 86_400
BRAND_LOGO_FALLBACK_PATH: Final = "/favicon.ico"

BRAND_LOGO_IMAGE_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/vnd.microsoft.icon",
        "image/webp",
        "image/x-icon",
    }
)
