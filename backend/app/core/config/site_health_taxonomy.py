from __future__ import annotations

from typing import Final

PAGE_KIND_HOMEPAGE: Final = "homepage"

PAGE_KIND_ARTICLE: Final = "article"

PAGE_KIND_PRODUCT: Final = "product"

PAGE_KIND_CATEGORY: Final = "category"

PAGE_KIND_PRICING: Final = "pricing"

PAGE_KIND_DOCS: Final = "docs"

PAGE_KIND_FAQ: Final = "faq"

PAGE_KIND_ABOUT_CONTACT: Final = "about_contact"

PAGE_KIND_OTHER: Final = "other"

PAGE_KIND_SERVICE: Final = "service"

PAGE_KIND_LOCAL: Final = "local"

PAGE_KIND_GUIDE: Final = "guide"

PAGE_KIND_COMPARISON: Final = "comparison"

PAGE_KIND_CASE_STUDY_REVIEW: Final = "case_study_review"

PAGE_KIND_TRUST_POLICY: Final = "trust_policy"

PAGE_KINDS: Final[tuple[str, ...]] = (
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_ARTICLE,
    PAGE_KIND_PRODUCT,
    PAGE_KIND_CATEGORY,
    PAGE_KIND_PRICING,
    PAGE_KIND_DOCS,
    PAGE_KIND_FAQ,
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_SERVICE,
    PAGE_KIND_LOCAL,
    PAGE_KIND_GUIDE,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_TRUST_POLICY,
    PAGE_KIND_OTHER,
)

HOMEPAGE_PATH_EQUIVALENTS: Final[frozenset[str]] = frozenset(
    {
        "",  # the root path itself ("/" or empty)
        "/index",
        "/index.html",
        "/index.htm",
        "/index.php",
        "/index.asp",
        "/index.aspx",
        "/home",
        "/home.html",
        "/default.html",
        "/default.aspx",
        # Locale roots (bounded, curated).
        "/en",
        "/en-us",
        "/en-gb",
        "/en-au",
        "/en-ca",
        "/fr",
        "/fr-fr",
        "/fr-ca",
        "/de",
        "/de-de",
        "/es",
        "/es-es",
        "/es-mx",
        "/pt",
        "/pt-br",
        "/it",
        "/it-it",
        "/nl",
        "/nl-nl",
        "/ja",
        "/ja-jp",
        "/ko",
        "/ko-kr",
        "/zh",
        "/zh-cn",
        "/zh-tw",
        "/ru",
        "/pl",
        "/sv",
        "/da",
        "/fi",
        "/no",
        "/tr",
        "/ar",
        "/hi",
        "/id",
        "/th",
        "/vi",
    }
)

PAGE_KIND_PATH_PATTERNS: Final[tuple[tuple[str, str], ...]] = (
    (PAGE_KIND_ARTICLE, r"^/(?:[^/]+/)*?(blogs?|news|articles?)(/|$)"),
    (PAGE_KIND_PRODUCT, r"^/(?:[^/]+/)*?(products?|p|shop)(/|$)"),
    (
        PAGE_KIND_CATEGORY,
        r"^/(?:[^/]+/)*?(category|categories|collections?|catalog)(/|$)",
    ),
    (PAGE_KIND_SERVICE, r"^/(?:[^/]+/)*?(services?|solutions?)(/|$)"),
    (PAGE_KIND_LOCAL, r"^/(?:[^/]+/)*?(locations?|stores?|offices?)(/|$)"),
    (PAGE_KIND_GUIDE, r"^/(?:[^/]+/)*?(guides?|how-to|tutorials?)(/|$)"),
    (
        PAGE_KIND_COMPARISON,
        r"^/(?:[^/]+/)*?(compare|comparisons?|vs)(/|$)",
    ),
    (PAGE_KIND_PRICING, r"^/(?:[^/]+/)*?(pricing|plans)(/|$)"),
    (
        PAGE_KIND_DOCS,
        r"^/(?:[^/]+/)*?(docs|documentation|reference|api)(/|$)",
    ),
    (PAGE_KIND_FAQ, r"^/(?:[^/]+/)*?(faqs?|help|support)(/|$)"),
    (
        PAGE_KIND_ABOUT_CONTACT,
        r"^/(?:[^/]+/)*?(about|about-us|contact|contact-us)(/|$)",
    ),
    (
        PAGE_KIND_CASE_STUDY_REVIEW,
        r"^/(?:[^/]+/)*?(case-study|case-studies|reviews?|testimonials?)(/|$)",
    ),
    (
        PAGE_KIND_TRUST_POLICY,
        r"^/(?:[^/]+/)*?(privacy|privacy-policy|terms|terms-of-service|security|trust|policies?|legal)(/|$)",
    ),
)

PAGE_KIND_QUESTION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "who",
        "what",
        "when",
        "where",
        "why",
        "how",
        "which",
        "whose",
        "whom",
        "can",
        "could",
        "should",
        "would",
        "will",
        "is",
        "are",
        "do",
        "does",
        "did",
    }
)

PAGE_KIND_FAQ_MIN_HEADINGS: Final = 3

PAGE_KIND_FAQ_QUESTION_RATIO: Final = 0.6

PAGE_KIND_PRICE_PATTERN: Final = (
    r"(?:[$€£¥]\s?\d+(?:[.,]\d{1,2})?"
    r"|\b(?:USD|EUR|GBP|AUD|CAD|JPY|INR)\s?\d+(?:[.,]\d{1,2})?)"
)

PAGE_KIND_CART_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "add to cart",
        "add-to-cart",
        "add to bag",
        "add-to-bag",
        "add to basket",
        "add-to-basket",
        "buy now",
    }
)

# --- Structural region extraction (fact_regions) -----------------------------
# Region names recorded per anchor and used to scope entity signals. These are
# structural landmarks, never a vocabulary judgement about what content means.
PAGE_REGION_MAIN: Final = "main"

PAGE_REGION_NAV: Final = "nav"

PAGE_REGION_HEADER: Final = "header"

PAGE_REGION_FOOTER: Final = "footer"

PAGE_REGION_ASIDE: Final = "aside"

PAGE_REGION_OTHER: Final = "other"

PAGE_REGIONS: Final[tuple[str, ...]] = (
    PAGE_REGION_MAIN,
    PAGE_REGION_NAV,
    PAGE_REGION_HEADER,
    PAGE_REGION_FOOTER,
    PAGE_REGION_ASIDE,
    PAGE_REGION_OTHER,
)

# Subtrees excluded from the primary region. Chrome landmarks plus non-rendered
# elements: an inline <script> body is why every crawled page reported a visible
# price of "$1" taken from a JavaScript regex replacement string.
REGION_EXCLUDED_TAGS: Final[tuple[str, ...]] = (
    "script",
    "style",
    "noscript",
    "template",
    "nav",
    "header",
    "footer",
    "aside",
)

REGION_EXCLUDED_ROLES: Final[tuple[str, ...]] = (
    "banner",
    "navigation",
    "contentinfo",
    "complementary",
)

# A container is a repeated card list when it holds at least this many
# structurally similar linked children. A recommendation carousel, a product
# grid and a related-posts strip are all the same shape, so one structural test
# covers them without naming any of them.
CARD_LIST_MIN_ITEMS: Final = 3

# Only this many direct child tags contribute to a repeated-card shape.
CARD_SHAPE_MAX_CHILDREN: Final = 8

# A listing PAGE needs a substantially larger grid than an incidental carousel.
LISTING_MIN_CARD_ITEMS: Final = 6

# Bounded scan caps so a hostile document cannot make region extraction costly.
REGION_MAX_CONTAINERS_SCANNED: Final = 4000

REGION_MAX_ANCESTOR_DEPTH: Final = 24

REGION_MAX_TEXT_CHARS: Final = 200_000

# A variant control is structural: one select with several options, or several
# radio inputs sharing a name.
VARIANT_MIN_OPTIONS: Final = 2

# Small, generic control vocabularies. These name UI affordances, not industries.
RESULT_COUNT_PATTERN: Final = r"\b\d{1,6}\s*(?:results?|items?|products?)\b"

SORT_CONTROL_TOKENS: Final[frozenset[str]] = frozenset({"sort", "sortby", "order-by"})

FILTER_CONTROL_TOKENS: Final[frozenset[str]] = frozenset(
    {"filter", "filters", "refine", "facet"}
)

SKU_ATTRIBUTE_TOKENS: Final[frozenset[str]] = frozenset(
    {"sku", "data-sku", "data-product-id", "productid"}
)

CART_FORM_ACTION_TOKENS: Final[frozenset[str]] = frozenset(
    {"/cart", "cart/add", "basket"}
)

PAGE_KIND_ARTICLE_SCAN_CHARS: Final = 2000

PAGE_KIND_BYLINE_PATTERN: Final = r"\b[Bb]y\s+[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){1,2}\b"

PAGE_KIND_DATE_PATTERN: Final = (
    r"(?:\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b)"
)

PAGE_KIND_SCHEMA_TYPE_MAP: Final[dict[str, str]] = {
    "FAQPage": PAGE_KIND_FAQ,
    "Product": PAGE_KIND_PRODUCT,
    "CollectionPage": PAGE_KIND_CATEGORY,
    "ContactPage": PAGE_KIND_ABOUT_CONTACT,
    "LocalBusiness": PAGE_KIND_LOCAL,
    "Service": PAGE_KIND_SERVICE,
    "HowTo": PAGE_KIND_GUIDE,
    "Review": PAGE_KIND_CASE_STUDY_REVIEW,
    "TechArticle": PAGE_KIND_DOCS,
    "NewsArticle": PAGE_KIND_ARTICLE,
    "BlogPosting": PAGE_KIND_ARTICLE,
    "Article": PAGE_KIND_ARTICLE,
}

# Tier C semantic fallback. Matched against the page's own title, H1 and final
# path segment ONLY when no structural evidence and no route family produced a
# type. Every phrase names a page's own stated purpose in plain English; none
# names an industry, a brand or a platform, and none maps to a page kind that
# is not already in PAGE_KINDS. Longest phrase wins; declaration order breaks
# ties. Deliberately small: this is the weakest evidence in the classifier and
# only ever fires where the alternative is `other`.
PAGE_KIND_TITLE_KEYWORDS: Final[tuple[tuple[str, str], ...]] = (
    (PAGE_KIND_TRUST_POLICY, "privacy policy"),
    (PAGE_KIND_TRUST_POLICY, "cookie policy"),
    (PAGE_KIND_TRUST_POLICY, "refund policy"),
    (PAGE_KIND_TRUST_POLICY, "return policy"),
    (PAGE_KIND_TRUST_POLICY, "shipping policy"),
    (PAGE_KIND_TRUST_POLICY, "terms of service"),
    (PAGE_KIND_TRUST_POLICY, "terms and conditions"),
    (PAGE_KIND_TRUST_POLICY, "accessibility"),
    (PAGE_KIND_TRUST_POLICY, "disclaimer"),
    (PAGE_KIND_TRUST_POLICY, "guarantee"),
    (PAGE_KIND_TRUST_POLICY, "counterfeit"),
    (PAGE_KIND_TRUST_POLICY, "policy"),
    (PAGE_KIND_TRUST_POLICY, "terms"),
    (PAGE_KIND_TRUST_POLICY, "legal"),
    (PAGE_KIND_GUIDE, "how to"),
    (PAGE_KIND_GUIDE, "care and cleaning"),
    (PAGE_KIND_GUIDE, "care cleaning"),
    (PAGE_KIND_GUIDE, "size guide"),
    (PAGE_KIND_GUIDE, "buying guide"),
    (PAGE_KIND_GUIDE, "tutorial"),
    (PAGE_KIND_GUIDE, "instructions"),
    (PAGE_KIND_SERVICE, "track your order"),
    (PAGE_KIND_SERVICE, "order status"),
    (PAGE_KIND_SERVICE, "store locator"),
    (PAGE_KIND_SERVICE, "find a store"),
    (PAGE_KIND_SERVICE, "product registration"),
    (PAGE_KIND_SERVICE, "repair request"),
    (PAGE_KIND_SERVICE, "returns portal"),
    (PAGE_KIND_SERVICE, "orders and payments"),
    (PAGE_KIND_SERVICE, "orders payments"),
    (PAGE_KIND_SERVICE, "delivery"),
    (PAGE_KIND_SERVICE, "shipping"),
    (PAGE_KIND_SERVICE, "warranty"),
    (PAGE_KIND_SERVICE, "register"),
    (PAGE_KIND_SERVICE, "repair"),
    (PAGE_KIND_FAQ, "frequently asked questions"),
    (PAGE_KIND_FAQ, "faq"),
    (PAGE_KIND_ABOUT_CONTACT, "contact us"),
    (PAGE_KIND_ABOUT_CONTACT, "about us"),
    (PAGE_KIND_ABOUT_CONTACT, "our story"),
    (PAGE_KIND_ABOUT_CONTACT, "contact"),
)

PAGE_KIND_SIGNAL_ROOT_PATH: Final = "root_path"

PAGE_KIND_SIGNAL_PATH_PATTERN: Final = "path_pattern"

PAGE_KIND_SIGNAL_CONTENT_HEURISTIC: Final = "content_heuristic"

PAGE_KIND_SIGNAL_STRUCTURED_DATA: Final = "structured_data"

PAGE_KIND_SIGNAL_NONE: Final = "none"

PAGE_KIND_SIGNAL_PRIMARY_PRODUCT: Final = "primary_product_entity"

PAGE_KIND_SIGNAL_PRIMARY_LISTING: Final = "primary_listing_structure"

PAGE_KIND_SIGNAL_PRIMARY_LOCATION: Final = "primary_location_entity"

PAGE_KIND_SIGNAL_SEMANTIC_TITLE: Final = "semantic_title"

# Evidence tiers. The classifier resolves a page kind by taking the highest
# tier that produced evidence, NOT by summing weights: a score built from
# several weak agreeing signals must never outrank one decisive structural
# observation, and a later reader must be able to say which single fact
# decided the type.
PAGE_KIND_TIER_STRUCTURAL: Final = "structural"

PAGE_KIND_TIER_ROUTE: Final = "route"

PAGE_KIND_TIER_SEMANTIC: Final = "semantic"

PAGE_KIND_TIERS: Final[tuple[str, ...]] = (
    PAGE_KIND_TIER_STRUCTURAL,
    PAGE_KIND_TIER_ROUTE,
    PAGE_KIND_TIER_SEMANTIC,
)

PAGE_KIND_SIGNAL_TIERS: Final[dict[str, str]] = {
    PAGE_KIND_SIGNAL_PRIMARY_PRODUCT: PAGE_KIND_TIER_STRUCTURAL,
    PAGE_KIND_SIGNAL_PRIMARY_LISTING: PAGE_KIND_TIER_STRUCTURAL,
    PAGE_KIND_SIGNAL_PRIMARY_LOCATION: PAGE_KIND_TIER_STRUCTURAL,
    # Not a route guess: an exact match against the curated root-equivalent
    # set means the page IS the site root, which is the most certain
    # classification the system makes.
    PAGE_KIND_SIGNAL_ROOT_PATH: PAGE_KIND_TIER_STRUCTURAL,
    PAGE_KIND_SIGNAL_PATH_PATTERN: PAGE_KIND_TIER_ROUTE,
    PAGE_KIND_SIGNAL_CONTENT_HEURISTIC: PAGE_KIND_TIER_SEMANTIC,
    PAGE_KIND_SIGNAL_STRUCTURED_DATA: PAGE_KIND_TIER_SEMANTIC,
    PAGE_KIND_SIGNAL_SEMANTIC_TITLE: PAGE_KIND_TIER_SEMANTIC,
}

# Confidence is a LABEL, never a number. A decimal invites the UI and later
# code to treat it as a calibrated probability, which it is not.
PAGE_KIND_CONFIDENCE_HIGH: Final = "high"

PAGE_KIND_CONFIDENCE_MEDIUM: Final = "medium"

PAGE_KIND_CONFIDENCE_LOW: Final = "low"

PAGE_KIND_CONFIDENCE_UNKNOWN: Final = "unknown"

PAGE_KIND_TIER_CONFIDENCE: Final[dict[str, str]] = {
    PAGE_KIND_TIER_STRUCTURAL: PAGE_KIND_CONFIDENCE_HIGH,
    PAGE_KIND_TIER_ROUTE: PAGE_KIND_CONFIDENCE_MEDIUM,
    PAGE_KIND_TIER_SEMANTIC: PAGE_KIND_CONFIDENCE_LOW,
}

PAGE_KIND_APPLICABILITY_PREFIX: Final = "page_kind:"

PAGE_KIND_HTML_APPLICABILITY_PREFIX: Final = "page_kind_html:"

PAGE_KIND_CONTENT_APPLICABILITY_PREFIX: Final = "page_kind_content:"


def _page_kinds(
    *kinds: str,
    requires_html: bool = False,
    reads_content: bool = False,
) -> str:
    """Build a ``page_kind:a|b|c`` applicability key.

    A rule that names its page kinds is only evaluated on those kinds; on every
    other kind it is INAPPLICABLE, which is different from failing. This is what
    stops a product page being reported for a missing author byline and an FAQ
    page for missing Product/offers markup — the complaint that every page kind
    got the same generic checklist.

    ``requires_html=True`` preserves the HTML-response guard for rules that
    inspect markup. ``reads_content=True`` additionally preserves the
    server-rendered-body guard for rules that inspect visible content.
    """
    if reads_content:
        prefix = PAGE_KIND_CONTENT_APPLICABILITY_PREFIX
    elif requires_html:
        prefix = PAGE_KIND_HTML_APPLICABILITY_PREFIX
    else:
        prefix = PAGE_KIND_APPLICABILITY_PREFIX
    return f"{prefix}{'|'.join(kinds)}"


class PageKindProfile:
    """Per-page-type rule-tuning profile (frozen, config-owned).

    The profile key doubles as the rule ``applicability_key`` token this
    page type answers to (``page_kind:<type>`` — unknown tokens stay
    fail-closed in the evaluator). ``min_sufficient_words`` is the per-type
    thin-content minimum read by ``technical.thin_content`` (the v1 global
    ``MIN_SUFFICIENT_WORDS`` analysis constant moved here in v2 — invariant
    1; the check itself moved from ``aeo.sufficient_text`` to
    ``technical.thin_content`` in the sh-rules-2 catalog, spec §5.3).
    ``rule_weight_overrides`` maps ``rule_id -> weight`` resolved at
    evaluation time; sparse by design.
    """

    __slots__ = (
        "page_kind",
        "min_sufficient_words",
        "rule_weight_overrides",
    )

    def __init__(
        self,
        *,
        page_kind: str,
        min_sufficient_words: int,
        rule_weight_overrides: dict[str, float] | None = None,
    ) -> None:
        self.page_kind = page_kind
        self.min_sufficient_words = min_sufficient_words
        self.rule_weight_overrides = dict(rule_weight_overrides or {})


PAGE_KIND_PROFILES: Final[dict[str, PageKindProfile]] = {
    # Homepages are naturally link-heavy/thin; a lower minimum and a
    # reduced thin-content weight keep them from reading as thin.
    PAGE_KIND_HOMEPAGE: PageKindProfile(
        page_kind=PAGE_KIND_HOMEPAGE,
        min_sufficient_words=40,
        rule_weight_overrides={"technical.thin_content": 1.0},
    ),
    PAGE_KIND_ARTICLE: PageKindProfile(
        page_kind=PAGE_KIND_ARTICLE, min_sufficient_words=300
    ),
    PAGE_KIND_PRODUCT: PageKindProfile(
        page_kind=PAGE_KIND_PRODUCT, min_sufficient_words=80
    ),
    PAGE_KIND_CATEGORY: PageKindProfile(
        page_kind=PAGE_KIND_CATEGORY, min_sufficient_words=60
    ),
    PAGE_KIND_PRICING: PageKindProfile(
        page_kind=PAGE_KIND_PRICING, min_sufficient_words=80
    ),
    PAGE_KIND_DOCS: PageKindProfile(page_kind=PAGE_KIND_DOCS, min_sufficient_words=150),
    PAGE_KIND_FAQ: PageKindProfile(page_kind=PAGE_KIND_FAQ, min_sufficient_words=120),
    PAGE_KIND_ABOUT_CONTACT: PageKindProfile(
        page_kind=PAGE_KIND_ABOUT_CONTACT, min_sufficient_words=60
    ),
    PAGE_KIND_SERVICE: PageKindProfile(
        page_kind=PAGE_KIND_SERVICE, min_sufficient_words=100
    ),
    PAGE_KIND_LOCAL: PageKindProfile(
        page_kind=PAGE_KIND_LOCAL, min_sufficient_words=80
    ),
    PAGE_KIND_GUIDE: PageKindProfile(
        page_kind=PAGE_KIND_GUIDE, min_sufficient_words=200
    ),
    PAGE_KIND_COMPARISON: PageKindProfile(
        page_kind=PAGE_KIND_COMPARISON, min_sufficient_words=150
    ),
    PAGE_KIND_CASE_STUDY_REVIEW: PageKindProfile(
        page_kind=PAGE_KIND_CASE_STUDY_REVIEW, min_sufficient_words=150
    ),
    PAGE_KIND_TRUST_POLICY: PageKindProfile(
        page_kind=PAGE_KIND_TRUST_POLICY, min_sufficient_words=80
    ),
    PAGE_KIND_OTHER: PageKindProfile(
        page_kind=PAGE_KIND_OTHER, min_sufficient_words=100
    ),
}


class PageKindSchemaExpectation:
    """Per-page-type expected structured-data contract (frozen, config-owned).

    ``expected_types`` are the schema.org types a page of this type should
    carry (any one of them satisfies ``aeo.schema_expected_for_type``);
    ``required_properties`` / ``recommended_properties`` are the property
    paths (dotted for one-level nesting, e.g. ``offers.price``) validated by
    ``aeo.schema_required_valid`` / ``aeo.schema_recommended_present``
    (spec §5.2). Property presence is checked against the extractor's
    bounded ``props_present`` per structured-data block.
    """

    __slots__ = (
        "page_kind",
        "expected_types",
        "required_properties",
        "recommended_properties",
        "required_properties_by_type",
        "recommended_properties_by_type",
    )

    def __init__(
        self,
        *,
        page_kind: str,
        expected_types: tuple[str, ...],
        required_properties: tuple[str, ...],
        recommended_properties: tuple[str, ...],
        required_properties_by_type: dict[str, tuple[str, ...]] | None = None,
        recommended_properties_by_type: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self.page_kind = page_kind
        self.expected_types = expected_types
        self.required_properties = required_properties
        self.recommended_properties = recommended_properties
        self.required_properties_by_type = dict(required_properties_by_type or {})
        self.recommended_properties_by_type = dict(recommended_properties_by_type or {})

    def properties_for(self, schema_type: str, *, recommended: bool) -> tuple[str, ...]:
        """Return the property contract for one allowed schema type.

        A page kind may accept structurally different schema alternatives.
        For example, a guide can use ``HowTo.name`` or ``Article.headline``.
        Applying one shared property list to both types produces false issues,
        so explicit per-type overrides take precedence over the common default.
        """
        overrides = (
            self.recommended_properties_by_type
            if recommended
            else self.required_properties_by_type
        )
        fallback = (
            self.recommended_properties if recommended else self.required_properties
        )
        return overrides.get(schema_type, fallback)


PAGE_KIND_EXPECTED_SCHEMA: Final[dict[str, PageKindSchemaExpectation]] = {
    PAGE_KIND_HOMEPAGE: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_HOMEPAGE,
        expected_types=("Organization", "WebSite"),
        required_properties=("name", "url"),
        recommended_properties=("sameAs", "logo"),
        # ``sameAs`` and ``logo`` describe the Organization identity, not the
        # WebSite node. A valid WebSite-only block must not fail an
        # Organization-specific recommendation.
        recommended_properties_by_type={"WebSite": ()},
    ),
    PAGE_KIND_ARTICLE: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_ARTICLE,
        expected_types=("Article", "BlogPosting", "NewsArticle"),
        required_properties=("headline", "author", "datePublished"),
        recommended_properties=("image", "dateModified"),
    ),
    PAGE_KIND_PRODUCT: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_PRODUCT,
        expected_types=("Product",),
        required_properties=("name", "offers"),
        recommended_properties=(
            "offers.price",
            "offers.priceCurrency",
            "aggregateRating",
        ),
    ),
    PAGE_KIND_CATEGORY: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_CATEGORY,
        expected_types=("BreadcrumbList", "CollectionPage", "ItemList"),
        required_properties=("itemListElement",),
        recommended_properties=(),
        # CollectionPage is a WebPage and does not itself have to expose
        # itemListElement; its own identity is the bounded contract here.
        required_properties_by_type={"CollectionPage": ("name",)},
    ),
    PAGE_KIND_PRICING: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_PRICING,
        expected_types=("Product", "Service"),
        required_properties=("offers",),
        # Nested paths: price and currency live on the Offer, not on the
        # Product/Service itself. Bare names never matched, so a correctly
        # marked-up pricing page was reported as missing both.
        recommended_properties=("offers.price", "offers.priceCurrency"),
    ),
    PAGE_KIND_DOCS: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_DOCS,
        expected_types=("TechArticle",),
        required_properties=("headline",),
        recommended_properties=("author", "dateModified"),
    ),
    PAGE_KIND_FAQ: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_FAQ,
        expected_types=("FAQPage",),
        required_properties=("mainEntity",),
        recommended_properties=(),
    ),
    PAGE_KIND_ABOUT_CONTACT: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_ABOUT_CONTACT,
        expected_types=("Organization", "LocalBusiness", "ContactPage"),
        required_properties=("name",),
        recommended_properties=("contactPoint", "address"),
        # ContactPage describes the page. Contact details may live in a
        # separate Organization/LocalBusiness node and should not be demanded
        # on the ContactPage object itself.
        recommended_properties_by_type={"ContactPage": ()},
    ),
    PAGE_KIND_SERVICE: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_SERVICE,
        expected_types=("Service",),
        required_properties=("name",),
        recommended_properties=("provider", "areaServed"),
    ),
    PAGE_KIND_LOCAL: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_LOCAL,
        expected_types=("LocalBusiness",),
        required_properties=("name", "address"),
        recommended_properties=("telephone", "geo"),
    ),
    PAGE_KIND_GUIDE: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_GUIDE,
        expected_types=("HowTo", "Article"),
        required_properties=("name",),
        recommended_properties=("step", "image"),
        required_properties_by_type={"Article": ("headline",)},
        recommended_properties_by_type={
            "Article": ("image", "dateModified"),
        },
    ),
    PAGE_KIND_COMPARISON: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_COMPARISON,
        expected_types=("Article", "ItemList"),
        required_properties=("name",),
        recommended_properties=("itemListElement",),
        required_properties_by_type={
            "Article": ("headline",),
            "ItemList": ("itemListElement",),
        },
        recommended_properties_by_type={"Article": ("dateModified",)},
    ),
    PAGE_KIND_CASE_STUDY_REVIEW: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_CASE_STUDY_REVIEW,
        expected_types=("Article", "Review"),
        required_properties=("name",),
        recommended_properties=("author", "datePublished"),
        required_properties_by_type={"Article": ("headline",)},
    ),
    PAGE_KIND_TRUST_POLICY: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_TRUST_POLICY,
        expected_types=("WebPage",),
        required_properties=("name",),
        recommended_properties=("dateModified",),
    ),
    PAGE_KIND_OTHER: PageKindSchemaExpectation(
        page_kind=PAGE_KIND_OTHER,
        expected_types=("WebPage",),
        required_properties=("name",),
        recommended_properties=(),
    ),
}

SCHEMA_PROPERTY_PATHS: Final[frozenset[str]] = frozenset(
    path
    for expectation in PAGE_KIND_EXPECTED_SCHEMA.values()
    for paths in (
        expectation.required_properties,
        expectation.recommended_properties,
        *expectation.required_properties_by_type.values(),
        *expectation.recommended_properties_by_type.values(),
    )
    for path in paths
)

PAGE_KIND_SCHEMA_ANALYSIS_KINDS: Final[tuple[str, ...]] = tuple(
    page_kind for page_kind in PAGE_KINDS if page_kind != PAGE_KIND_OTHER
)
