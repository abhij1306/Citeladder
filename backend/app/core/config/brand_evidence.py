"""Brand web-evidence crawl guardrails (invariant 1).

Owns the knobs for grounding the brand-profile drafter in the brand's OWN
website instead of the model's prior knowledge of the brand name. Domain code
READs these values; it never hard-codes the literals inline.

Why this exists: ``build_brand_knowledge_data`` passes ``website_url`` to the
agent as a bare string — a fact the model is told about, never a page anyone
read. For a brand with no training-data footprint (a small consultancy, a new
company) the model has nothing to draft from but the NAME, so it pattern-matches
the name into a plausible-sounding business that does not exist. That fabricated
profile then becomes the binding vocabulary and the competitor/prompt context,
so one hallucination propagates into every downstream surface.
"""

from typing import Final

BRAND_EVIDENCE_USER_AGENT: Final = "CiteLadderBrandEvidenceBot/1.0"

# One homepage fetch per draft. The budget is deliberately tight: this runs
# inline in a user-facing request, and the homepage is where a brand states
# what it does. Additional pages (``/about``) are fetched only when the
# homepage yields too little text to draft from.
BRAND_EVIDENCE_REQUEST_TIMEOUT_SECONDS: Final = 5.0
BRAND_EVIDENCE_TOTAL_TIMEOUT_SECONDS: Final = 12.0
BRAND_EVIDENCE_MAX_REDIRECTS: Final = 3
BRAND_EVIDENCE_MAX_HTML_BYTES: Final = 2_097_152

# Secondary paths tried (in order) only when the homepage text is too thin to
# ground a profile. Most small-business sites put the real self-description on
# an about page rather than a marketing homepage.
BRAND_EVIDENCE_FALLBACK_PATHS: Final[tuple[str, ...]] = (
    "/about",
    "/about-us",
    "/products",
    "/services",
    "/pricing",
)

# Text budget handed to the agent per page, and in total. Large enough to carry
# a real self-description, small enough to keep the user message bounded.
BRAND_EVIDENCE_MAX_PAGE_CHARS: Final = 6_000
BRAND_EVIDENCE_MAX_TOTAL_CHARS: Final = 12_000

# The grounding floor. Below this many words of extracted visible text across
# all fetched pages, the evidence is treated as ABSENT: the drafter is not
# called at all and the caller is told to fill the profile in by hand. This is
# the whole point of the fix — an unknown brand must produce "insufficient
# evidence", never a confident fabrication.
BRAND_EVIDENCE_MIN_WORDS: Final = 40

# Short-lived in-process cache of collected evidence, keyed by canonical
# homepage URL. Concurrent discovery/profile reads share one crawl.
# Deliberately brief — long enough
# to cover one onboarding step, short enough that re-running later re-reads a
# site that has since changed.
BRAND_EVIDENCE_CACHE_SECONDS: Final = 300.0
# Empty successful crawls are cached only long enough to collapse concurrent
# callers. By the time a person can click Retry, the site is eligible again.
BRAND_EVIDENCE_NEGATIVE_CACHE_SECONDS: Final = 1.0
BRAND_EVIDENCE_CACHE_MAX_ENTRIES: Final = 256

BRAND_EVIDENCE_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
    }
)

# Stamped into bounded generation provenance so evidence selection is inspectable.
BRAND_EVIDENCE_VERSION: Final = "brand-evidence-v1"

# Human-facing guidance per evidence-failure reason. The stable contract is the
# reason TOKEN (mirroring ``BINDING_FAILURE_MESSAGES``); both the persisted
# profile drafter and persisted onboarding discovery render these, so the
# text lives here rather than in either caller.
BRAND_EVIDENCE_FAILURE_MESSAGES: Final[dict[str, str]] = {
    "no_usable_website_url": (
        "No usable website URL was supplied, so there is no brand content to "
        "work from. Add the brand's website URL, or describe the brand "
        "manually."
    ),
    "website_unreachable": (
        "The brand's website could not be read (unreachable, blocked, or "
        "empty). Check the website URL, or describe the brand manually."
    ),
    "insufficient_website_content": (
        "The brand's website returned too little readable text to work from — "
        "often a site that renders its content with JavaScript. Describe the "
        "brand manually instead."
    ),
    "evidence_fetch_timeout": (
        "Reading the brand's website timed out. Try again, or describe the "
        "brand manually."
    ),
    "evidence_fetch_failed": (
        "Reading the brand's website failed unexpectedly. Try again, or "
        "describe the brand manually."
    ),
}
