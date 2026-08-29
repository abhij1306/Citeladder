from __future__ import annotations

from typing import Final

from app.core.config.site_health_architecture_rules import ARCHITECTURE_RULE_SPECS
from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    APPLICABILITY_OBSERVED_CONTENT,
    APPLICABILITY_SITE_ROOT,
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
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_APPLICABILITY_PREFIX,
    PAGE_KIND_ARTICLE,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_DOCS,
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_FAQ,
    PAGE_KIND_GUIDE,
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_SCHEMA_ANALYSIS_KINDS,
    PAGE_TRAIT_REVIEW_INTENT,
    _page_kinds,
    _page_traits,
)

DIMENSION_WEIGHT_TECHNICAL: Final = 0.5

DIMENSION_WEIGHT_AEO: Final = 0.5

SCORE_ROUNDING_DECIMALS: Final = 1

FINDING_CLASS_DEFECT: Final = "defect"

FINDING_CLASS_ADVISORY: Final = "advisory"

FINDING_CLASSES: Final[frozenset[str]] = frozenset(
    {FINDING_CLASS_DEFECT, FINDING_CLASS_ADVISORY}
)

# How a page-kind-scoped rule RELATES to the classification, which decides
# whether it may fire when that classification is weak.
#
# EXPECTATION  asserts something SHOULD be on the page because of what kind of
#              page it is. Only as sound as the classification behind it: a
#              page inferred to be an FAQ from a /support/ path segment must
#              not be accused of missing FAQ structure.
# TRIGGERED    validates an artifact that IS present, and already resolves
#              not_applicable when it is absent. The trigger is the artifact,
#              not the classification, so a Product block contradicting the
#              visible page is a defect however the page was classified.
# UNIVERSAL    not page-kind-scoped at all.
KIND_EVIDENCE_EXPECTATION: Final = "expectation"

KIND_EVIDENCE_TRIGGERED: Final = "triggered"

KIND_EVIDENCE_UNIVERSAL: Final = "universal"

KIND_EVIDENCE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        KIND_EVIDENCE_EXPECTATION,
        KIND_EVIDENCE_TRIGGERED,
        KIND_EVIDENCE_UNIVERSAL,
    }
)


class SiteHealthRule:
    """One deterministic Site Health rule (frozen catalog entry).

    Every rule carries a stable ``rule_id`` + ``rule_version`` + dimension +
    category + severity + weight + applicability-predicate key + description +
    remediation. The evaluator applies these; it never invents rule metadata
    inline (invariant 1).
    """

    __slots__ = (
        "applicability_key",
        "category",
        "description",
        "dimension",
        "display_label",
        "display_label_variants",
        "finding_class",
        "kind_evidence",
        "remediation",
        "rule_id",
        "rule_version",
        "severity",
        "weight",
    )

    def __init__(
        self,
        *,
        rule_id: str,
        rule_version: str,
        dimension: str,
        category: str,
        severity: str,
        weight: float,
        applicability_key: str,
        description: str,
        remediation: str,
        display_label: str = "",
        display_label_variants: dict[str, str] | None = None,
        finding_class: str = FINDING_CLASS_DEFECT,
        kind_evidence: str = KIND_EVIDENCE_EXPECTATION,
    ) -> None:
        self.rule_id = rule_id
        self.rule_version = rule_version
        self.dimension = dimension
        self.category = category
        self.severity = severity
        if finding_class not in FINDING_CLASSES:
            raise ValueError(f"Unsupported finding class: {finding_class}")
        self.finding_class = finding_class
        if kind_evidence not in KIND_EVIDENCE_CLASSES:
            raise ValueError(f"Unsupported kind evidence: {kind_evidence}")
        # Expectation is the conservative default: a new page-kind rule is
        # gated by classification confidence unless it declares that its
        # trigger is the artifact rather than the page kind.
        self.kind_evidence = kind_evidence
        self.weight = weight
        self.applicability_key = applicability_key
        self.description = description
        self.remediation = remediation
        # Current human-facing catalog title (mockup 710/711). The persisted
        # issue/evaluation rows never store this; the API reads it live so a
        # relabel takes effect immediately. Empty falls back to ``rule_id``.
        self.display_label = display_label or rule_id
        # Optional per-outcome titles for a rule whose ONE condition covers
        # opposite failures. ``technical.single_h1`` fails on ``h1_count != 1``,
        # so its single title had to read "Multiple or missing H1" — which tells
        # a reader neither which one happened nor what to do. Keyed by a token
        # the projection derives from the persisted evidence; an unmatched token
        # falls back to ``display_label``, so a rule without variants (all but
        # one today) is unaffected.
        self.display_label_variants = dict(display_label_variants or {})


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
        # rule id is kept so the AEO Readiness machine-readability dimension
        # keeps its signal (AEO_READINESS_RULE_DIMENSIONS drops unmapped ids).
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
        description=(
            "Word count is below the per-page-kind minimum (PAGE_KIND_PROFILES)."
        ),
        remediation="Add substantive, answer-oriented body content to the page.",
        display_label="Thin content",
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
    ),
    SiteHealthRule(
        rule_id="technical.render_blocking",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_PERFORMANCE,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key="has_html",
        description=(
            "Synchronous scripts + stylesheets stay under the render-blocking "
            "resource limit."
        ),
        remediation=(
            "Defer/async non-critical scripts and reduce render-blocking stylesheets."
        ),
        display_label="Too many render-blocking resources",
    ),
    # --- v2 P2: site_root scope (evaluated once per crawl, weight 0) -------
    SiteHealthRule(
        rule_id="technical.ai_crawler_access",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=0.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        description=(
            "robots.txt does not block the major AI crawlers (GPTBot, "
            "ClaudeBot, PerplexityBot, Google-Extended)."
        ),
        remediation=(
            "Allow the AI crawlers you want citing your content in robots.txt "
            "(check CDN-managed default bot blocks)."
        ),
        display_label="AI crawlers blocked by robots.txt",
    ),
    SiteHealthRule(
        rule_id="aeo.llms_txt_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_LOW,
        weight=0.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        description="Site serves an llms.txt file at the root.",
        remediation=("Publish /llms.txt summarizing the site for AI answer engines."),
        display_label="Missing llms.txt",
    ),
    # --- v2 P2: per-type schema validity (per-page) -------------------------
    SiteHealthRule(
        rule_id="aeo.schema_expected_for_type",
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
    ),
    # --- v2 P2: citability (per-page) ---------------------------------------
    SiteHealthRule(
        rule_id="aeo.author_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        # Editorial page kinds only. A byline is a citability signal for
        # authored writing; demanding one on a product, category, pricing or
        # policy page reports a "problem" that page should never solve.
        #
        # case_study_review is dropped here because it is two page types in a
        # trenchcoat. A case study demonstrates problem, intervention, result,
        # and is usually published by the organisation rather than by a named
        # writer -- an absent byline is not a defect. A review needs an
        # identifiable evaluator, which ``aeo.reviewer_identified`` asks of
        # exactly the pages that read as reviews.
        applicability_key=_page_kinds(
            PAGE_KIND_ARTICLE,
            PAGE_KIND_GUIDE,
            PAGE_KIND_COMPARISON,
            reads_content=True,
        ),
        description=("Page exposes an author byline (visible, schema, or metadata)."),
        remediation="Add an author byline (visible, JSON-LD author, or meta).",
        display_label="Missing author byline",
    ),
    SiteHealthRule(
        rule_id="aeo.reviewer_identified",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        # Scoped by TRAIT, not by page kind. A review is a thing a page does,
        # not only a thing a page is: a product page carrying an editorial
        # verdict owes the reader an evaluator exactly as much as a page filed
        # under /reviews/ does, and neither has to be reclassified for the
        # question to be asked.
        #
        # Traits are observations, so this is not gated by classification
        # confidence -- there is no classification behind it to be unsure of.
        kind_evidence=KIND_EVIDENCE_UNIVERSAL,
        applicability_key=_page_traits(
            PAGE_TRAIT_REVIEW_INTENT,
            reads_content=True,
        ),
        description="A page presenting a review identifies who evaluated it.",
        remediation=(
            "Name the reviewer or the reviewing organization, so the verdict "
            "can be attributed."
        ),
        display_label="Review has no identified reviewer",
    ),
    SiteHealthRule(
        rule_id="aeo.date_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.5,
        # Same editorial set as the byline, plus docs: a reader needs to know
        # how current documentation is. Evergreen commercial pages (product,
        # category, pricing, about) carry no such expectation.
        applicability_key=_page_kinds(
            PAGE_KIND_ARTICLE,
            PAGE_KIND_GUIDE,
            PAGE_KIND_CASE_STUDY_REVIEW,
            PAGE_KIND_COMPARISON,
            PAGE_KIND_DOCS,
            reads_content=True,
        ),
        description="Page exposes a published or modified date.",
        remediation=(
            "Add machine-readable dates (JSON-LD datePublished/dateModified, "
            "article:published_time, or <time datetime>)."
        ),
        display_label="Missing published/modified date",
    ),
    SiteHealthRule(
        rule_id="aeo.outbound_citations",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_LOW,
        weight=1.0,
        # Citing external sources is an expectation of research-style content.
        # A product or category page linking out is not a goal.
        applicability_key=_page_kinds(
            PAGE_KIND_ARTICLE,
            PAGE_KIND_GUIDE,
            PAGE_KIND_CASE_STUDY_REVIEW,
            PAGE_KIND_COMPARISON,
            reads_content=True,
        ),
        description="Page links out to at least one non-social external domain.",
        remediation="Cite authoritative external sources relevant to the content.",
        display_label="No outbound citations",
    ),
    SiteHealthRule(
        rule_id="aeo.organization_identity",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=f"{PAGE_KIND_APPLICABILITY_PREFIX}{PAGE_KIND_HOMEPAGE}",
        description="Homepage Organization markup carries sameAs identity links.",
        remediation=(
            "Add sameAs links (official profiles) to the homepage Organization schema."
        ),
        display_label="Missing organization identity links",
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
        applicability_key=_page_kinds(
            PAGE_KIND_FAQ,
            PAGE_KIND_GUIDE,
            PAGE_KIND_DOCS,
            reads_content=True,
        ),
        description=(
            "The first block under the first heading is a substantive "
            "answer/definitional paragraph."
        ),
        remediation=("Open each section with a direct answer before elaborating."),
        display_label="No answer-first content structure",
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
        applicability_key=_page_kinds(
            PAGE_KIND_FAQ,
            reads_content=True,
        ),
        description="Page uses question-form h2/h3 headings.",
        remediation="Phrase section headings as the questions users ask.",
        display_label="No question-form headings",
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
    ),
    SiteHealthRule(
        rule_id="aeo.no_expand_gating",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=APPLICABILITY_OBSERVED_CONTENT,
        description=(
            "Most body text is not behind click-to-expand elements "
            "(collapsed details / aria-expanded=false)."
        ),
        remediation=(
            "Keep primary content visible without interaction; avoid gating "
            "answers behind expandable sections."
        ),
        display_label="Content behind expand controls",
        # This measures the OPPOSITE of what it claims. ``expand_gated_ratio``
        # counts words inside closed <details> and aria-expanded=false nodes --
        # text that is present in the DOM and extractable without executing or
        # clicking anything. A correctly built FAQ accordion, whose every
        # answer is server-rendered and readable, scored as though its content
        # were hidden.
        #
        # Collapsed-but-present is at most a presentation preference, so the
        # finding is demoted rather than deleted. Detecting content that is
        # genuinely unreachable without interaction needs a different extractor
        # signal; until that exists this cannot honestly be a defect.
        finding_class=FINDING_CLASS_ADVISORY,
    ),
    # --- v2 P2: crawl_finalize scope (weight 0; finalize-writer owned) ------
    SiteHealthRule(
        rule_id="technical.sitemap_orphan",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_LOW,
        weight=0.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        description=(
            "Sitemap URLs are reachable through internal links (not "
            "sitemap-only orphans)."
        ),
        remediation=("Link sitemap-listed pages from crawlable internal navigation."),
        display_label="Sitemap orphan URLs",
    ),
    SiteHealthRule(
        rule_id="technical.hreflang_conflict",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_MEDIUM,
        weight=0.0,
        applicability_key=APPLICABILITY_CRAWL_FINALIZE,
        description="Hreflang alternates carry reciprocal return tags.",
        remediation=(
            "Add return hreflang annotations on every alternate page so "
            "clusters are reciprocal."
        ),
        display_label="Hreflang return-tag conflict",
    ),
    *(SiteHealthRule(**spec) for spec in ARCHITECTURE_RULE_SPECS),
)

SITE_HEALTH_RULES_BY_ID: Final[dict[str, SiteHealthRule]] = {
    rule.rule_id: rule for rule in SITE_HEALTH_RULES
}

STRUCTURED_DATA_REQUIRED_PROPERTIES: Final[dict[str, tuple[str, ...]]] = {
    "Organization": ("name", "url"),
    "WebSite": ("name", "url"),
    "WebPage": ("name",),
    "Article": ("headline", "author", "datePublished"),
    "Product": ("name", "offers"),
    "FAQPage": ("mainEntity",),
    "BreadcrumbList": ("itemListElement",),
}

STRUCTURED_DATA_RECOGNIZED_TYPES: Final[frozenset[str]] = frozenset(
    STRUCTURED_DATA_REQUIRED_PROPERTIES
) | frozenset(
    schema_type
    for expectation in PAGE_KIND_EXPECTED_SCHEMA.values()
    for schema_type in expectation.expected_types
)

TITLE_LENGTH_BAND: Final[tuple[int, int]] = (30, 60)

META_DESCRIPTION_LENGTH_BAND: Final[tuple[int, int]] = (70, 160)

TTFB_WARN_MS: Final = 800

RENDER_BLOCKING_MAX_RESOURCES: Final = 2

ANSWER_FIRST_MIN_WORDS: Final = 10

ANSWER_FIRST_MAX_HOPS: Final = 8

EXPAND_GATED_MAX_RATIO: Final = 0.5

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

QUESTION_HEADINGS_MIN_RATIO: Final = 0.0

SOCIAL_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "linkedin.com",
        "youtube.com",
        "tiktok.com",
        "pinterest.com",
    }
)

SCHEMA_CONTENT_MATCH_MAX_CANDIDATES: Final = 5

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
