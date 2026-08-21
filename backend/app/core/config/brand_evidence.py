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

# One homepage plus a small set of offering pages per draft. The budget is
# deliberately tight because this runs during onboarding.
BRAND_EVIDENCE_REQUEST_TIMEOUT_SECONDS: Final = 5.0
BRAND_EVIDENCE_TOTAL_TIMEOUT_SECONDS: Final = 12.0
BRAND_EVIDENCE_MAX_REDIRECTS: Final = 3
BRAND_EVIDENCE_MAX_HTML_BYTES: Final = 2_097_152
BRAND_EVIDENCE_MAX_PAGES: Final = 5
# Every same-origin link on the page, not a document-order prefix of them. The
# offering harvest ranks before it truncates, and a large catalogue homepage
# carries hundreds of anchors with the real categories far past position 60.
# These are short strings; the harvest, not this cap, decides what survives.
BRAND_EVIDENCE_MAX_NAVIGATION_LINKS: Final = 400

# Generic secondary paths used only to fill unused slots after homepage
# navigation has supplied its offering candidates.
BRAND_EVIDENCE_FALLBACK_PATHS: Final[tuple[str, ...]] = (
    "/about",
    "/about-us",
    "/products",
    "/services",
    "/pricing",
)

# Where a business publishes "here is what we offer". The words differ by
# industry -- a retailer says shop, a law firm says capabilities, a hospital
# says specialties -- but the structure is the same everywhere, so one
# vocabulary routes internal-page selection for every business model. This
# replaces a thirteen-term retail list that selected a marketplace's gift-card
# page, a search stub and two login redirects as its four "commercial" reads.
# Entries must be single tokens as produced by ``[a-z0-9]+``: a path such as
# ``/what-we-do`` tokenizes to {what, we, do}, so a hyphenated entry would never
# match anything. Multi-word concepts are listed in their concatenated form and
# by their distinctive part.
BRAND_EVIDENCE_OFFERING_HUB_TERMS: Final[frozenset[str]] = frozenset(
    {
        "capabilities",
        "capability",
        "catalog",
        "catalogue",
        "categories",
        "category",
        "centres",
        "centers",
        "collection",
        "collections",
        "courses",
        "departments",
        "disciplines",
        "expertise",
        "industries",
        "offerings",
        "platform",
        "practice",
        "practices",
        "pricing",
        "products",
        "programs",
        "programmes",
        "sectors",
        "services",
        "shop",
        "solutions",
        "specialities",
        "specialties",
        "store",
        "treatments",
        "whatwedo",
        "usecases",
    }
)

# Link classification selects offering navigation without encoding any
# industry's actual categories.
BRAND_EVIDENCE_EDITORIAL_LINK_TERMS: Final[frozenset[str]] = frozenset(
    {"article", "blog", "guide", "insights", "journal", "news", "resources"}
)
# Things a company publishes ABOUT ITSELF. None of them is something a customer
# wants, and on a large institutional site they outnumber the offering links by
# an order of magnitude: one hospital homepage led with its entire investor
# relations and board-of-directors tree, which filled the whole harvest budget
# with "Shareholding Pattern" and "Unclaimed Dividends".
BRAND_EVIDENCE_UTILITY_LINK_TERMS: Final[frozenset[str]] = frozenset(
    {
        # account and transaction chrome
        "account",
        "basket",
        "cart",
        "checkout",
        "help",
        "login",
        "logout",
        "signin",
        "signup",
        "register",
        "wishlist",
        "orders",
        # corporate, governance and investor relations
        "about",
        "accessibility",
        "alumni",
        "annualreport",
        "awards",
        "board",
        "careers",
        "complaints",
        "contact",
        "corporate",
        "csr",
        "dividend",
        "esg",
        "governance",
        "investor",
        "investors",
        "leadership",
        "legal",
        "milestones",
        "press",
        "privacy",
        "shareholding",
        "sustainability",
        "terms",
    }
)
# Labels lifted from image alt text, and locale switchers. Neither is ever an
# offering, and both appear on sites in every industry.
BRAND_EVIDENCE_JUNK_LABEL_TERMS: Final[frozenset[str]] = frozenset(
    {"image", "logo", "icon", "banner", "thumbnail", "img"}
)
BRAND_EVIDENCE_LOCALE_LABELS: Final[frozenset[str]] = frozenset(
    {
        "english",
        "deutsch",
        "français",
        "francais",
        "español",
        "espanol",
        "italiano",
        "português",
        "portugues",
        "nederlands",
        "svenska",
        "dansk",
        "norsk",
        "suomi",
        "polski",
        "türkçe",
        "turkce",
        "русский",
        "日本語",
        "한국어",
        "中文",
        "简体中文",
        "繁體中文",
        "العربية",
        "हिन्दी",
    }
)
# A run of labels sharing a template -- "Ambulance in Chennai", "Ambulance in
# Delhi", "Hapur, India", "Kheri, India" -- is one offering expressed once per
# location, not many offerings. Keeping a few of each family preserves the
# signal and stops a store locator or city index flooding the budget. Generic:
# it needs no place-name list and works in any language.
BRAND_EVIDENCE_MAX_NODES_PER_LABEL_FAMILY: Final = 3

# Bare navigation verbs. They label a control, never an offering.
BRAND_EVIDENCE_NAVIGATION_VERBS: Final[frozenset[str]] = frozenset(
    {
        "all",
        "apply now",
        "book now",
        "browse",
        "explore",
        "get started",
        "home",
        "learn more",
        "menu",
        "more",
        "new",
        "offers",
        "overview",
        "read more",
        "sale",
        "search",
        "see all",
        "shop now",
        "sign up",
        "start now",
        "view all",
    }
)

# Harvest bounds. Ranking happens first; these decide how much survives.
BRAND_EVIDENCE_MAX_OFFERING_NODES: Final = 60
# No single site section may consume the budget. Grouping by first path segment
# and capping is what stops an investor-relations tree crowding out clinical or
# product navigation.
BRAND_EVIDENCE_MAX_NODES_PER_PREFIX: Final = 8
# Nor may one fetched PAGE consume the budget. A store locator, a city index or
# a brand sitemap yields hundreds of shallow links that all pass every other
# filter, and without this one such page buries the homepage's real rail.
BRAND_EVIDENCE_MAX_NODES_PER_PAGE: Final = 25
BRAND_EVIDENCE_OFFERING_LABEL_MAX_WORDS: Final = 6
BRAND_EVIDENCE_OFFERING_LABEL_MIN_CHARS: Final = 3
BRAND_EVIDENCE_OFFERING_MAX_PATH_DEPTH: Final = 3
# Below this many surviving nodes the harvest is reported as empty and topic
# selection falls back to page text alone.
BRAND_EVIDENCE_MIN_OFFERING_NODES: Final = 3

# Detail pages, not offering hubs: one phone model or one article is never a
# topic.
BRAND_EVIDENCE_DETAIL_PATH_PATTERN: Final = (
    r"(?:/p/|/dp/|/product/|/item/|[?&]pid=|/blog/|/news/|/press/|/\d{4}/\d{2}/)"
)
# Partner, consultant and clinician directories otherwise dominate
# professional-service and healthcare sites.
BRAND_EVIDENCE_PERSON_LABEL_PATTERN: Final = r"^(?:dr|mr|mrs|ms|prof)\.?\s"

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
BRAND_EVIDENCE_VERSION: Final = "brand-evidence-v2"

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
