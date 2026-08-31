from __future__ import annotations

from typing import Final

from app.core.config.site_health_architecture_rules import ARCHITECTURE_RULE_SPECS
from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    APPLICABILITY_OBSERVED_CONTENT,
    CATEGORY_CITABILITY,
    CATEGORY_CONTENT,
    CATEGORY_INDEXABILITY,
    CATEGORY_METADATA,
    CATEGORY_PERFORMANCE,
    CATEGORY_SECURITY,
    CATEGORY_STRUCTURED_DATA,
    DIMENSION_AEO,
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from app.core.config.site_health_measurement import (
    CHECKPOINT_FAMILY_BY_ID,
    validate_measurement_profile,
)
from app.core.config.site_health_readiness_rules import READINESS_EXPANSION_RULES
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_ADVISORY,
    FINDING_CLASS_DIAGNOSTIC,
    KIND_EVIDENCE_TRIGGERED,
    RULE_SCOPE_CLUSTER,
    RULE_SCOPE_GRAPH,
    SCORE_ROLE_AEO,
    SCORE_ROLE_WEB_FUNDAMENTALS,
    SiteHealthRule,
    validate_triggered_rule_links,
)
from app.core.config.site_health_search_rules import SEARCH_ACCESS_RULES
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_ARTICLE,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_DOCS,
    PAGE_KIND_FAQ,
    PAGE_KIND_FAQ_QUESTION_RATIO,
    PAGE_KIND_GUIDE,
    PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
    _page_kinds,
)
from app.core.config.site_health_web_fundamentals import WEB_FUNDAMENTALS_RULES

_SCHEMA_EXPECTED_FOR_TYPE_RULE_ID: Final = "aeo.schema_expected_for_type"

SITE_HEALTH_RULES: Final[tuple[SiteHealthRule, ...]] = (
    SiteHealthRule(
        rule_id="technical.title_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_METADATA,
        severity=SEVERITY_HIGH,
        weight=3.0,
        # HTML only. "always" also ran this on PDFs and other documents, which
        # have no <title> to be missing and are successful inventory evidence,
        # not broken pages.
        applicability_key="has_html",
        description="Page has a non-empty <title>.",
        remediation="Add a concise, descriptive <title> element to the page.",
        display_label="Missing page title",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.meta_description_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_METADATA,
        severity=SEVERITY_MEDIUM,
        weight=2.0,
        applicability_key="has_html",
        description="Page has a non-empty meta description.",
        remediation="Add a meta description summarizing the page content.",
        display_label="Missing meta description",
        # A search engine generates a snippet from the page when the author
        # supplies none, so an absent description costs a measure of control
        # over the snippet -- it does not make the page defective. Worth
        # recommending, never worth scoring against.
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="technical.canonical_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_MEDIUM,
        weight=2.0,
        applicability_key="has_html",
        description="Page declares a canonical URL.",
        remediation='Add a <link rel="canonical"> pointing at the preferred URL.',
        display_label="Missing canonical URL",
        # A canonical declaration is a strong consolidation SIGNAL, not a
        # requirement: a page with no duplicates and no parameter variants is
        # complete without one. Recommend it; do not score its absence.
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="technical.indexable",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_CRITICAL,
        weight=4.0,
        applicability_key="always",
        description="Page is not blocked from indexing by a robots meta noindex.",
        remediation="Remove the noindex directive if the page should be indexed.",
        display_label="Page blocked from indexing",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS, SCORE_ROLE_AEO),
    ),
    SiteHealthRule(
        rule_id="technical.https",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_SECURITY,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key="always",
        description="Final URL is served over HTTPS.",
        remediation="Serve the page over HTTPS and redirect HTTP to HTTPS.",
        display_label="Not served over HTTPS",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.single_h1",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key=APPLICABILITY_OBSERVED_CONTENT,
        description="Page has exactly one <h1> heading.",
        remediation="Use a single <h1> that describes the page's primary topic.",
        display_label="Missing or duplicate H1",
        display_label_variants={
            "none": "Missing H1 heading",
            "multiple": "More than one H1 heading",
        },
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="aeo.structured_data_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_STRUCTURED_DATA,
        severity=SEVERITY_MEDIUM,
        weight=3.0,
        applicability_key=_page_kinds(
            *PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
            requires_html=True,
        ),
        description="Page includes JSON-LD or microdata structured data.",
        remediation="Add schema.org structured data (JSON-LD preferred).",
        display_label="Missing structured data",
        # Structured data helps a search engine understand a page and can
        # unlock specific features; it has never been a requirement, and no
        # special markup is needed to be read by an answer engine. Absence is
        # an opportunity.
        #
        # It also duplicated ``aeo.schema_expected_for_type``, which is already
        # an advisory for the SAME condition. Together they spent 3.5 weight of
        # the AEO denominator on one fact: this page carries no markup. The
        # rule id is kept so the PR2 measurement manifest can retain the
        # machine-readability capability without duplicating the absence signal.
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="aeo.open_graph_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_METADATA,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="has_html",
        description="Page declares Open Graph title/description metadata.",
        remediation="Add og:title and og:description meta tags.",
        display_label="Missing Open Graph metadata",
        # Open Graph controls how a link previews when it is SHARED. It is
        # optional social metadata whose absence changes nothing about the
        # page itself -- the same class of finding as the two above, and it
        # fired on nearly every valid fixture in the contract suite.
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    # --- v2 P2: hygiene (per-page) ----------------------------------------
    SiteHealthRule(
        rule_id="technical.thin_content",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=2.0,
        applicability_key=APPLICABILITY_OBSERVED_CONTENT,
        description="Page has too little page-owned content to evaluate reliably.",
        remediation=(
            "Add enough page-owned content to make the page purpose observable."
        ),
        display_label="Very little observable content",
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="technical.canonical_conflict",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        applicability_key="has_html",
        description=(
            "Declared canonical URL is a usable consolidation target "
            "(absolute, same-origin, and not a different hreflang alternate)."
        ),
        remediation=(
            "Point the canonical at an absolute same-origin URL. A page that "
            "declares hreflang alternates must canonicalise to itself."
        ),
        display_label="Canonical URL conflict",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.title_length_band",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_METADATA,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="has_html",
        description="Title length falls inside the recommended band (30-60 chars).",
        remediation="Rewrite the <title> to roughly 30-60 characters.",
        display_label="Title length outside recommended band",
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="technical.meta_description_length_band",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_METADATA,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="has_html",
        description=(
            "Meta description length falls inside the recommended band (70-160 chars)."
        ),
        remediation="Rewrite the meta description to roughly 70-160 characters.",
        display_label="Meta description length outside recommended band",
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="technical.hsts_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_SECURITY,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="always",
        description="Response sends a Strict-Transport-Security header.",
        remediation=(
            "Serve Strict-Transport-Security on HTTPS responses to enforce "
            "secure transport."
        ),
        display_label="Missing HSTS header",
        finding_class=FINDING_CLASS_DIAGNOSTIC,
        web_fundamentals_area="security",
    ),
    SiteHealthRule(
        rule_id="technical.ttfb_band",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_PERFORMANCE,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="always",
        description="Time to first byte is within the recommended band (<= 800 ms).",
        remediation="Reduce server response time (caching, CDN, faster origin).",
        display_label="Slow time to first byte",
        finding_class=FINDING_CLASS_DIAGNOSTIC,
        web_fundamentals_area="lab",
    ),
    SiteHealthRule(
        rule_id="technical.uncompressed_html",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_PERFORMANCE,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="always",
        description="HTML response is served compressed (gzip/deflate/br).",
        remediation="Enable gzip or brotli compression for HTML responses.",
        display_label="HTML served uncompressed",
        finding_class=FINDING_CLASS_DIAGNOSTIC,
        web_fundamentals_area="lab",
    ),
    *WEB_FUNDAMENTALS_RULES,
    *SEARCH_ACCESS_RULES,
    *READINESS_EXPANSION_RULES,
    # --- v2 P2: per-type schema validity (per-page) -------------------------
    SiteHealthRule(
        rule_id=_SCHEMA_EXPECTED_FOR_TYPE_RULE_ID,
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_STRUCTURED_DATA,
        # ABSENT markup is an optimization opportunity, not a reproducible
        # defect: a valid trust-policy page without a WebPage node is not
        # broken. As a HIGH weight-3.0 defect this rule fired on every
        # correctly classified page that simply had no markup yet, so
        # improving the classifier would have LOWERED scores across a site
        # for pages that had nothing wrong with them. Malformed or
        # contradictory markup remains a defect -- see
        # ``aeo.schema_required_valid``.
        severity=SEVERITY_LOW,
        finding_class=FINDING_CLASS_ADVISORY,
        weight=0.5,
        applicability_key=_page_kinds(
            *PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
            requires_html=True,
        ),
        description=(
            "Structured data includes a schema.org type expected for the "
            "classified page type."
        ),
        remediation=(
            "Add the expected schema.org type for this page type "
            "(PAGE_KIND_EXPECTED_SCHEMA)."
        ),
        display_label="Missing expected schema type for page type",
        score_roles=(SCORE_ROLE_AEO,),
    ),
    SiteHealthRule(
        rule_id="aeo.schema_required_valid",
        kind_evidence=KIND_EVIDENCE_TRIGGERED,
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_STRUCTURED_DATA,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key=_page_kinds(
            *PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
            requires_html=True,
        ),
        description=(
            "Expected-type structured data carries every required property "
            "for the page type."
        ),
        remediation="Add the missing required properties to the schema markup.",
        display_label="Required schema properties missing",
        score_roles=(SCORE_ROLE_AEO,),
        triggered_by=_SCHEMA_EXPECTED_FOR_TYPE_RULE_ID,
    ),
    SiteHealthRule(
        rule_id="aeo.schema_recommended_present",
        kind_evidence=KIND_EVIDENCE_TRIGGERED,
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_STRUCTURED_DATA,
        # Recommended properties are, by their own name, guidance.
        severity=SEVERITY_LOW,
        finding_class=FINDING_CLASS_ADVISORY,
        weight=0.5,
        applicability_key=_page_kinds(
            *PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
            requires_html=True,
        ),
        description=(
            "Expected-type structured data carries the recommended properties "
            "for the page type."
        ),
        remediation=("Add the recommended properties to strengthen the schema markup."),
        display_label="Recommended schema properties missing",
        score_roles=(SCORE_ROLE_AEO,),
        triggered_by=_SCHEMA_EXPECTED_FOR_TYPE_RULE_ID,
    ),
    SiteHealthRule(
        rule_id="aeo.schema_matches_content",
        kind_evidence=KIND_EVIDENCE_TRIGGERED,
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_STRUCTURED_DATA,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        applicability_key=_page_kinds(
            *PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
            reads_content=True,
        ),
        description=(
            "Structured-data names match the visible <title>/h1 content "
            "(bounded cross-check)."
        ),
        remediation=(
            "Align schema name/headline values with the visible page content."
        ),
        display_label="Schema markup does not match visible content",
        score_roles=(SCORE_ROLE_AEO,),
        triggered_by=_SCHEMA_EXPECTED_FOR_TYPE_RULE_ID,
    ),
    # --- v2 P2: citability (per-page) ---------------------------------------
    SiteHealthRule(
        rule_id="aeo.visible_attribution",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        applicability_key=_page_kinds(
            PAGE_KIND_ARTICLE,
            PAGE_KIND_GUIDE,
            PAGE_KIND_COMPARISON,
            PAGE_KIND_CASE_STUDY_REVIEW,
            reads_content=True,
        ),
        description=(
            "Authored content exposes a visible creator name and linked profile."
        ),
        remediation=(
            "Add a visible creator byline linked to a stable profile or biography."
        ),
        display_label="Visible creator attribution incomplete",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.source_support_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key=_page_kinds(
            PAGE_KIND_ARTICLE,
            PAGE_KIND_GUIDE,
            PAGE_KIND_CASE_STUDY_REVIEW,
            PAGE_KIND_COMPARISON,
            PAGE_KIND_DOCS,
            reads_content=True,
        ),
        description=(
            "Research-sensitive claims attach sources through a bounded "
            "references, methodology, citation-marker, or attribution relation."
        ),
        remediation=(
            "Attach authoritative sources to the claims they support using "
            "a references or methodology section, citation markers, or nearby "
            "attribution."
        ),
        display_label="Claim support sources missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    # --- v2 P2: extractability (per-page) -----------------------------------
    SiteHealthRule(
        rule_id="aeo.answer_first",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=2.0,
        # A writing STYLE, not a defect. A service page has no obligation to
        # open like a reference answer, a case study may deliberately open with
        # context, and a narrative article is not worse for building to its
        # point. Kept where the reader genuinely arrived with a question --
        # and kept as an advisory even there, because "answer first" is a
        # recommendation about prose, not a reproducible fault.
        applicability_key=_page_kinds(PAGE_KIND_FAQ, reads_content=True),
        description=(
            "The first block under the first heading is a substantive "
            "answer/definitional paragraph."
        ),
        remediation=("Open each section with a direct answer before elaborating."),
        display_label="No answer-first content structure",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    SiteHealthRule(
        rule_id="aeo.question_headings",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_LOW,
        weight=1.0,
        # Question-form headings are the SHAPE of an answer page. A homepage,
        # product or category page is not written as questions and should not
        # be scored as though it failed to be.
        #
        # Narrowed further to FAQ alone. An FAQ whose sections are not
        # questions genuinely is not an FAQ, so the finding survives there as a
        # defect. A guide, a reference page or an essay has no such obligation:
        # API reference documentation has no subheadings at all, and demanding
        # question headings of it was inventing a fault.
        applicability_key=_page_kinds(PAGE_KIND_FAQ),
        description="Page uses question-form h2/h3 headings.",
        remediation="Phrase section headings as the questions users ask.",
        display_label="No question-form headings",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.server_rendered_content",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_HIGH,
        weight=2.0,
        applicability_key="has_html",
        description=(
            "Key text is present in the server-rendered HTML (not a script-only shell)."
        ),
        remediation=(
            "Server-render or pre-render primary content so crawlers can "
            "extract it without executing JavaScript."
        ),
        display_label="Content not present in server HTML",
        score_roles=(),
        finding_class=FINDING_CLASS_DIAGNOSTIC,
    ),
    # --- crawl-finalize Web Fundamentals rules --------------------------
    SiteHealthRule(
        rule_id="technical.broken_internal_link",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        scope=RULE_SCOPE_GRAPH,
        description="Crawlable internal links resolve without an HTTP error.",
        remediation="Repair or remove internal links whose targets return errors.",
        display_label="Broken internal links",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.canonical_resolvable",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        description="The declared or implicit canonical target resolves directly.",
        remediation="Point the canonical at a fetched, non-error, non-redirecting URL.",
        display_label="Canonical target does not resolve directly",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.sitemap_url_unreachable",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        description="Sitemap-listed URLs resolve without an HTTP error.",
        remediation="Remove unreachable sitemap URLs or restore their resources.",
        display_label="Unreachable sitemap URLs",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    # --- crawl-finalize cluster rules --------------------------------------
    # These use cross-page evidence. Their rows stay root/page-anchored for
    # provenance, but their measurement ownership is the relevant URL cluster.
    SiteHealthRule(
        rule_id="technical.sitemap_orphan",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        scope=RULE_SCOPE_CLUSTER,
        description=(
            "Sitemap URLs are reachable through internal links (not "
            "sitemap-only orphans)."
        ),
        remediation=("Link sitemap-listed pages from crawlable internal navigation."),
        display_label="Sitemap orphan URLs",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    SiteHealthRule(
        rule_id="technical.hreflang_conflict",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_MEDIUM,
        weight=2.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        scope=RULE_SCOPE_CLUSTER,
        description="Hreflang alternates carry reciprocal return tags.",
        remediation=(
            "Add return hreflang annotations on every alternate page so "
            "clusters are reciprocal."
        ),
        display_label="Hreflang return-tag conflict",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
    *(SiteHealthRule(**spec) for spec in ARCHITECTURE_RULE_SPECS),
)

SITE_HEALTH_RULES_BY_ID: Final[dict[str, SiteHealthRule]] = {
    rule.rule_id: rule for rule in SITE_HEALTH_RULES
}


validate_triggered_rule_links(
    SITE_HEALTH_RULES,
    SITE_HEALTH_RULES_BY_ID,
    CHECKPOINT_FAMILY_BY_ID,
)
validate_measurement_profile(implemented_checkpoint_ids=tuple(SITE_HEALTH_RULES_BY_ID))

TITLE_LENGTH_BAND: Final[tuple[int, int]] = (30, 60)

META_DESCRIPTION_LENGTH_BAND: Final[tuple[int, int]] = (70, 160)

TTFB_WARN_MS: Final = 800

ANSWER_FIRST_MIN_WORDS: Final = 10

ANSWER_FIRST_MAX_HOPS: Final = 8


SERVER_RENDERED_MIN_WORDS: Final = 20

INLINE_SCRIPT_JAVASCRIPT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "module",
        "text/javascript",
        "application/javascript",
        "text/ecmascript",
        "application/ecmascript",
        "text/jscript",
    }
)

QUESTION_HEADINGS_MIN_RATIO: Final = PAGE_KIND_FAQ_QUESTION_RATIO


TRACKING_QUERY_PARAMS: Final[frozenset[str]] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "intpromo",
        "gclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "ref",
        "ref_src",
    }
)

PERSISTED_RESPONSE_HEADERS: Final[frozenset[str]] = frozenset(
    {
        "content-type",
        "content-length",
        "content-encoding",
        "cache-control",
        "etag",
        "last-modified",
        "expires",
        "vary",
        "server",
        "x-content-type-options",
        "strict-transport-security",
        "content-security-policy",
        "x-frame-options",
        "referrer-policy",
        "x-robots-tag",
    }
)

HTML_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {"text/html", "application/xhtml+xml"}
)

SITEMAP_CONTENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "application/xml",
        "text/xml",
        "application/gzip",
        "application/x-gzip",
    }
)

ALLOWED_URL_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

ALLOWED_URL_PORTS: Final[frozenset[int]] = frozenset({80, 443})
