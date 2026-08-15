# Opportunities configuration (invariant 1: all config lives in core/config).
#
# Owns EVERY tunable knob, enum, catalog entry, and version string for the
# Opportunities subsystem: the deterministic rule catalog, the site-issue ->
# opportunity-rule mapping sets, the priority-scoring formula weights, the
# analyzer/rule/formula versions stamped on every derived row (invariant 4),
# and the read/write bounds. Detection + scoring are deterministic
# projections over already-persisted visibility analysis + Site Health issue
# rows — no provider calls, no LLM (invariants 7 + 9). Domain, analysis, and
# API code READS these; it never hard-codes the literals inline.
from __future__ import annotations

from typing import Final

from app.core.config.demand import (
    DEMAND_SIGNAL_CANNIBALIZATION,
    DEMAND_SIGNAL_CTR_GAP,
    DEMAND_SIGNAL_DECLINING_QUERY,
    DEMAND_SIGNAL_EMERGING_QUERY,
    DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
    DEMAND_SIGNAL_STRIKING_DISTANCE,
)
from app.core.config.projects import (
    PROMPT_INTENT_COMPARISON,
    PROMPT_INTENT_DISCOVERY,
    PROMPT_INTENT_LOCAL,
    PROMPT_INTENT_PURCHASE,
    PROMPT_INTENT_SERVICE,
)

# =========================================================================
# Provenance versions (invariant 4)
# =========================================================================
# Stamped on every ``Opportunity`` row + ``OpportunitySnapshot``. Bump
# ``ANALYZER_VERSION`` on any detector-logic change, ``RULE_VERSION`` on any
# catalog change, and ``FORMULA_VERSION`` on any scoring change so a derived
# row is always traceable to the exact logic that produced it (mirrors
# ``SCORING_RULE_VERSION`` in ``config/analysis.py``).
ANALYZER_VERSION: Final = "opp-analyzer-4"
RULE_VERSION: Final = "opp-rules-6"
FORMULA_VERSION: Final = "opp-formula-1"
CONFIRMED_DECLINE_MIN_FACTOR: Final = 0.1
CONFIRMED_DECLINE_GAP_NORMALIZER: Final = 10.0
DEMAND_SIGNAL_GAP_FACTOR: Final = 2.0


# =========================================================================
# Vocabularies
# =========================================================================
# Opportunity type: which subsystem family the rule's evidence comes from.
OPPORTUNITY_TYPE_VISIBILITY: Final = "visibility"
OPPORTUNITY_TYPE_SITE: Final = "site"
OPPORTUNITY_TYPE_TRAFFIC: Final = "traffic"
OPPORTUNITY_TYPE_TOPIC: Final = "topic"
OPPORTUNITY_TYPES: Final[frozenset[str]] = frozenset(
    {
        OPPORTUNITY_TYPE_VISIBILITY,
        OPPORTUNITY_TYPE_SITE,
        OPPORTUNITY_TYPE_TRAFFIC,
        OPPORTUNITY_TYPE_TOPIC,
    }
)

# Severity vocabulary: the same five tokens as Site Health (D2) so the
# frontend badge palette helpers apply unchanged. Owned per-subsystem (do NOT
# import the site-health frozenset).
SEVERITY_CRITICAL: Final = "critical"
SEVERITY_HIGH: Final = "high"
SEVERITY_MEDIUM: Final = "medium"
SEVERITY_LOW: Final = "low"
SEVERITY_INFO: Final = "info"
OPPORTUNITY_SEVERITIES: Final[frozenset[str]] = frozenset(
    {
        SEVERITY_CRITICAL,
        SEVERITY_HIGH,
        SEVERITY_MEDIUM,
        SEVERITY_LOW,
        SEVERITY_INFO,
    }
)

# Human workflow status — the ONLY mutable field on an ``Opportunity`` row.
STATUS_OPEN: Final = "open"
STATUS_IN_PROGRESS: Final = "in_progress"
STATUS_DISMISSED: Final = "dismissed"
STATUS_RESOLVED: Final = "resolved"
OPPORTUNITY_STATUSES: Final[frozenset[str]] = frozenset(
    {
        STATUS_OPEN,
        STATUS_IN_PROGRESS,
        STATUS_DISMISSED,
        STATUS_RESOLVED,
    }
)
# Default list view: the triage queue (not yet closed by the human).
OPPORTUNITY_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_OPEN, STATUS_IN_PROGRESS}
)

# =========================================================================
# Coded API failures (stable tokens returned to the client)
# =========================================================================
CODE_OPPORTUNITY_SUPERSEDED: Final = "opportunity_superseded"
CODE_OPPORTUNITY_ORDER_CONFLICT: Final = "opportunity_order_conflict"
CODE_OPPORTUNITY_GUIDANCE_UNAVAILABLE: Final = "opportunity_guidance_unavailable"
CODE_OPPORTUNITY_GUIDANCE_IDEMPOTENCY_CONFLICT: Final = (
    "opportunity_guidance_idempotency_conflict"
)
CODE_IMPLEMENTATION_TARGET_CONFLICT: Final = "implementation_target_conflict"
CODE_IMPLEMENTATION_IDEMPOTENCY_CONFLICT: Final = "implementation_idempotency_conflict"
IMPLEMENTATION_EVENT_DEFAULT_LIMIT: Final = 50
IMPLEMENTATION_EVENT_MAX_LIMIT: Final = 200
IMPLEMENTATION_IDEMPOTENCY_KEY_MAX_LEN: Final = 160
IMPLEMENTATION_EXPECTED_CHECKS_MAX: Final = 32
IMPLEMENTATION_TARGETS_MAX: Final = 64
IMPLEMENTATION_VERIFIER_VERSION: Final = "implementation-verifier-1"
IMPLEMENTATION_VERIFICATION_BATCH_MAX: Final = 100
IMPLEMENTATION_VERIFICATION_HISTORY_MAX: Final = 50

# =========================================================================
# Rule catalog
# =========================================================================


class OpportunityRule:
    """One deterministic opportunity rule (frozen catalog entry).

    The catalog is config, not a table, so a persisted ``Opportunity.rule_id``
    is a validated string, never a DB FK: the write path validates against
    this catalog (an unknown id is rejected) and stamps ``RULE_VERSION`` onto
    the row for provenance (invariants 1 + 4). ``title`` + ``remediation``
    are persisted on the row at write time (mirrors ``SiteIssue.remediation``
    snapshot semantics — a catalog relabel never rewrites history). A
    disabled rule (``enabled=False``) ships config-only: its shape is stable
    but no detector emits it.
    """

    __slots__ = (
        "rule_id",
        "opportunity_type",
        "severity",
        "title",
        "remediation",
        "enabled",
    )

    def __init__(
        self,
        *,
        rule_id: str,
        opportunity_type: str,
        severity: str,
        title: str,
        remediation: str,
        enabled: bool = True,
    ) -> None:
        self.rule_id = rule_id
        self.opportunity_type = opportunity_type
        self.severity = severity
        self.title = title
        self.remediation = remediation
        self.enabled = enabled


# The v2 catalog. The two visibility rules + the three site-sourced rules +
# the three commerce-derived rules are enabled; ``low_share_of_voice_theme``
# (no persisted per-topic SOV aggregate) and ``high_traffic_low_visibility``
# (no Traffic surface) ship disabled as documented config-only entries. The
# commerce rules are typed ``visibility``: their evidence is the same audit's
# persisted product-analysis slice (ProductMetricSnapshot/ProductMention), so
# no new opportunity-type token is introduced.
OPPORTUNITY_RULES: Final[tuple[OpportunityRule, ...]] = (
    OpportunityRule(
        rule_id="brand_absent_high_value_prompt",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_HIGH,
        title="Brand absent on high-value prompt",
        remediation=(
            "Publish or update an owned page that directly answers this"
            " prompt: lead with a clear, quotable definition, then add"
            " structured data so answer engines can attribute it. Re-run an"
            " audit to confirm owned citations appear."
        ),
    ),
    OpportunityRule(
        rule_id="owned_page_not_cited",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_MEDIUM,
        title="Owned page not cited for target prompt",
        remediation=(
            "Strengthen the owned page that should win this prompt: align its"
            " title, headings, and opening answer with the prompt intent so"
            " answer engines have a citable owned source."
        ),
    ),
    OpportunityRule(
        rule_id="confirmed_prompt_decline",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_HIGH,
        title="Prompt visibility has a confirmed decline",
        remediation=(
            "Refresh the owned page that best answers this prompt. Lead with a "
            "direct answer, close the measured visibility or citation gap, and "
            "use this opportunity as evidence context for Content generation."
        ),
    ),
    OpportunityRule(
        rule_id="missing_structured_data",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_MEDIUM,
        title="Missing structured data on owned page",
        remediation=(
            "Add schema.org structured data (JSON-LD preferred) so answer"
            " engines can parse and attribute the page's content."
        ),
    ),
    OpportunityRule(
        rule_id="thin_content",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_LOW,
        title="Thin content on owned page",
        remediation=(
            "Add substantive, answer-oriented body content to the page so"
            " answer engines have enough text to quote and cite."
        ),
    ),
    OpportunityRule(
        rule_id="schema_type_mismatch",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_HIGH,
        title="Structured data missing the expected schema type",
        # Own copy, NOT missing_structured_data's: this rule fires when
        # structured data EXISTS but lacks the page-type-expected type, so
        # "add structured data" would give wrong guidance.
        remediation=(
            "The page already ships structured data, but not the schema.org"
            " type expected for its page type (e.g. Product on a product"
            " page, FAQPage on an FAQ page). Add the expected type to the"
            " existing JSON-LD so answer engines can classify and cite the"
            " page correctly."
        ),
    ),
    OpportunityRule(
        rule_id="schema_properties_incomplete",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_MEDIUM,
        title="Schema properties are incomplete",
        remediation=(
            "Complete the required and recommended properties for the page's "
            "expected schema type, using the exact missing-property evidence "
            "as the implementation checklist."
        ),
    ),
    OpportunityRule(
        rule_id="schema_visible_content_conflict",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_HIGH,
        title="Visible content conflicts with schema",
        remediation=(
            "Align the visible title, headings, and page claims with the "
            "corresponding schema.org values; do not leave competing facts "
            "for answer engines to resolve."
        ),
    ),
    OpportunityRule(
        rule_id="content_structure_incomplete",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_LOW,
        title="Answer-oriented content structure is incomplete",
        remediation=(
            "Strengthen the page's substantive content, answer-first opening, "
            "and question-led headings using the persisted rule evidence."
        ),
    ),
    OpportunityRule(
        rule_id="citability_trust_incomplete",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_MEDIUM,
        title="Citability and trust signals are incomplete",
        remediation=(
            "Add the missing author, date, source, or organization identity "
            "signals so readers and answer engines can assess provenance."
        ),
    ),
    OpportunityRule(
        rule_id="product_not_mentioned",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_HIGH,
        title="Catalog product never mentioned by answer engines",
        remediation=(
            "No answer engine mentioned this product anywhere in the latest"
            " audit. Add product-named prompts that mirror how buyers ask,"
            " and strengthen the product's owned pages with quotable specs,"
            " pricing, and comparisons so engines have a citable source."
        ),
    ),
    OpportunityRule(
        rule_id="competitor_product_dominates",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_HIGH,
        title="Competitor product dominates product share of voice",
        remediation=(
            "A competing product takes the majority of product mentions in"
            " the latest audit. Publish comparison content that positions"
            " your product against it (pricing, specs, use cases) so answer"
            " engines have owned material to cite instead."
        ),
    ),
    OpportunityRule(
        rule_id="price_mention_mismatch",
        opportunity_type=OPPORTUNITY_TYPE_VISIBILITY,
        severity=SEVERITY_MEDIUM,
        title="Quoted prices disagree with the catalog",
        remediation=(
            "Answer engines quote prices that do not match your catalog for"
            " this product. Make the current price prominent and"
            " machine-readable on the product page (visible price plus"
            " schema.org Offer markup) so engines stop citing stale figures."
        ),
    ),
    OpportunityRule(
        rule_id="search_demand_content_gap",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="Search demand is not earning expected clicks",
        remediation=(
            "Improve the matching owned page and search snippet for this "
            "measured query or page. Keep the answer aligned with the observed "
            "intent and verify the later GSC window."
        ),
    ),
    OpportunityRule(
        rule_id="striking_distance_query",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="Query is within striking distance",
        remediation=(
            "Strengthen the resolved page for this non-branded query and "
            "verify its next GSC window."
        ),
    ),
    OpportunityRule(
        rule_id="query_cannibalization",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="Multiple pages compete for one query",
        remediation=(
            "Consolidate or differentiate the qualifying resolved pages, "
            "then verify which page earns the query."
        ),
    ),
    OpportunityRule(
        rule_id="property_relative_ctr_gap",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="CTR trails comparable property queries",
        remediation=(
            "Improve the page title and snippet against its property-relative "
            "position cohort, then verify CTR."
        ),
    ),
    OpportunityRule(
        rule_id="emerging_query",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_LOW,
        title="Search demand is emerging",
        remediation=(
            "Expand the owned answer while demand is rising and verify the "
            "next adjacent GSC window."
        ),
    ),
    OpportunityRule(
        rule_id="declining_query",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="Search demand is declining",
        remediation=(
            "Refresh the owned answer for the declining query and verify "
            "recovery in a later GSC window."
        ),
    ),
    OpportunityRule(
        rule_id="site_link_near_orphan",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_MEDIUM,
        title="Indexable page has too few followed internal links",
        remediation=(
            "Add relevant followed internal links from the suggested source "
            "pages to make this page easier to discover and reach."
        ),
    ),
    OpportunityRule(
        rule_id="site_link_weak_authority",
        opportunity_type=OPPORTUNITY_TYPE_SITE,
        severity=SEVERITY_LOW,
        title="Page has weak internal-link authority",
        remediation=(
            "Strengthen this page with relevant followed links from the "
            "suggested higher-authority pages."
        ),
    ),
    OpportunityRule(
        rule_id="low_share_of_voice_theme",
        opportunity_type=OPPORTUNITY_TYPE_TOPIC,
        severity=SEVERITY_MEDIUM,
        title="Low share of voice in theme",
        remediation=(
            "Increase owned coverage across this theme: publish"
            " answer-oriented pages for the theme's highest-value prompts."
        ),
        # DEFERRED (delta 3): no persisted per-topic SOV aggregate yet.
        enabled=False,
    ),
    OpportunityRule(
        rule_id="high_traffic_low_visibility",
        opportunity_type=OPPORTUNITY_TYPE_TRAFFIC,
        severity=SEVERITY_MEDIUM,
        title="High-traffic page with low answer-engine visibility",
        remediation=(
            "Prioritize this high-traffic page for AEO improvements: add"
            " quotable answers and structured data where engines already send"
            " visitors."
        ),
        # DEFERRED (delta 4): the Traffic surface is not implemented.
        enabled=False,
    ),
)

# Fast lookup by rule id.
OPPORTUNITY_RULES_BY_ID: Final[dict[str, OpportunityRule]] = {
    rule.rule_id: rule for rule in OPPORTUNITY_RULES
}

DEMAND_SIGNAL_RULE_IDS: Final[dict[str, str]] = {
    DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR: "search_demand_content_gap",
    DEMAND_SIGNAL_STRIKING_DISTANCE: "striking_distance_query",
    DEMAND_SIGNAL_CANNIBALIZATION: "query_cannibalization",
    DEMAND_SIGNAL_CTR_GAP: "property_relative_ctr_gap",
    DEMAND_SIGNAL_EMERGING_QUERY: "emerging_query",
    DEMAND_SIGNAL_DECLINING_QUERY: "declining_query",
}


def validate_rule_id(rule_id: str) -> str:
    """Return ``rule_id`` when it is a known catalog id; reject unknown ids.

    The write path calls this before persisting any derived row so a row can
    never reference a rule the catalog does not own (invariants 1 + 4).
    """
    if rule_id not in OPPORTUNITY_RULES_BY_ID:
        raise ValueError(f"unknown opportunity rule_id: {rule_id!r}")
    return rule_id


# =========================================================================
# Site-issue -> opportunity-rule mapping sets (config-owned, invariant 1)
# =========================================================================
# ``SiteIssue`` rule ids (from the Site Health catalog) that project into
# each site-type opportunity rule. Owned here so the detector never
# hard-codes the mapping.
SITE_STRUCTURED_DATA_RULE_IDS: Final[frozenset[str]] = frozenset(
    {"aeo.structured_data_present"}
)
# ``aeo.schema_expected_for_type`` fires when structured data EXISTS but the
# page-type-expected type is absent — a distinct failure mode from "no
# structured data at all", so it maps to its own opportunity rule with its
# own remediation copy.
SITE_SCHEMA_TYPE_RULE_IDS: Final[frozenset[str]] = frozenset(
    {"aeo.schema_expected_for_type"}
)
# ``technical.thin_content`` is the v2 (sh-rules-2) id; it was renamed from the
# v1 ``aeo.sufficient_text`` (see site_health.py — the per-type-minimum
# word-count check moved dimension). Using the retired id here would make the
# thin-content opportunity silently never fire on real data.
SITE_THIN_CONTENT_RULE_IDS: Final[frozenset[str]] = frozenset(
    {"technical.thin_content"}
)

# Every documented structured-data and content/citability failure maps to a
# site opportunity rule.  The detector reads this one table so its mapping
# remains total, reviewable, and config-owned as the Site Health catalog grows.
SITE_ISSUE_TO_OPPORTUNITY_RULE_ID: Final[dict[str, str]] = {
    "aeo.structured_data_present": "missing_structured_data",
    "aeo.schema_expected_for_type": "schema_type_mismatch",
    "aeo.schema_required_valid": "schema_properties_incomplete",
    "aeo.schema_recommended_present": "schema_properties_incomplete",
    "aeo.product_offer_details": "schema_properties_incomplete",
    "aeo.schema_matches_content": "schema_visible_content_conflict",
    "aeo.product_visible_schema_parity": "schema_visible_content_conflict",
    "technical.thin_content": "thin_content",
    "aeo.answer_first": "content_structure_incomplete",
    "aeo.question_headings": "content_structure_incomplete",
    "aeo.author_present": "citability_trust_incomplete",
    "aeo.date_present": "citability_trust_incomplete",
    "aeo.outbound_citations": "citability_trust_incomplete",
    "aeo.organization_identity": "citability_trust_incomplete",
}

# =========================================================================
# Deterministic scoring formula (config-owned tables, invariants 1 + 9)
# =========================================================================
# priority = SEVERITY_WEIGHTS[severity] * value_factor * gap_factor
#            * PRIORITY_SCALE, rounded to PRIORITY_ROUNDING_DECIMALS.
SEVERITY_WEIGHTS: Final[dict[str, float]] = {
    SEVERITY_CRITICAL: 4.0,
    SEVERITY_HIGH: 3.0,
    SEVERITY_MEDIUM: 2.0,
    SEVERITY_LOW: 1.0,
    SEVERITY_INFO: 0.5,
}
# Fallback for a severity outside the known vocabulary (fail-safe, neutral).
SEVERITY_WEIGHT_DEFAULT: Final = 1.0

# Value factor by prompt intent (covers every ``PROMPT_INTENTS`` token).
INTENT_VALUE_WEIGHTS: Final[dict[str, float]] = {
    PROMPT_INTENT_DISCOVERY: 1.0,
    PROMPT_INTENT_COMPARISON: 1.5,
    PROMPT_INTENT_PURCHASE: 2.0,
    PROMPT_INTENT_SERVICE: 1.5,
    PROMPT_INTENT_LOCAL: 1.25,
}
# Fallback for an empty/unknown intent.
INTENT_VALUE_DEFAULT: Final = 1.0

# Gap factor: competitor pressure (bounded) + owned-citation shortfall.
GAP_COMPETITOR_WEIGHT: Final = 1.0
GAP_COMPETITOR_CAP: Final = 3
GAP_OWNED_CITATION_WEIGHT: Final = 1.0

# Site-sourced rules carry no intent/gap modulation: their factors are the
# neutral base (the severity weight already encodes their importance).
SITE_VALUE_FACTOR: Final = 1.0
SITE_GAP_FACTOR: Final = 1.0

# Commerce-derived rules (ProductMetricSnapshot/ProductMention evidence):
# same neutral-base treatment as the site rules — the severity weight already
# encodes importance, and the thresholds below are the firing conditions.
COMMERCE_VALUE_FACTOR: Final = 1.0
COMMERCE_GAP_FACTOR: Final = 1.0
# ``competitor_product_dominates`` fires when one competitor product's
# persisted SOV share (0-1) exceeds this threshold.
COMMERCE_COMPETITOR_SOV_THRESHOLD: Final = 0.5
# ``price_mention_mismatch`` fires when a product's persisted price-relation
# mismatch rate (0-1, over verifiable price mentions) exceeds this threshold.
COMMERCE_PRICE_MISMATCH_RATE_THRESHOLD: Final = 0.25

PRIORITY_SCALE: Final = 10.0
PRIORITY_ROUNDING_DECIMALS: Final = 1
# Write-time floor: hits below this score are never persisted. Set so a
# ``low``-severity hit at base factors (1.0 * 1.0 * 1.0 * 10 = 10.0) still
# surfaces — every enabled catalog rule can produce rows — while ``info``
# hits at base factors (5.0) stay below the floor.
MIN_PRIORITY_TO_SURFACE: Final = 10.0

# =========================================================================
# Bounds (recompute reads, list pagination, exports)
# =========================================================================
# Bounded recompute reads (deterministic truncation order: prompt_index, id).
RECOMPUTE_MAX_ANALYSES: Final = 5000
RECOMPUTE_MAX_ISSUES: Final = 5000
# Bounded commerce evidence read (per-audit ProductMetricSnapshot rows).
RECOMPUTE_MAX_PRODUCT_SNAPSHOTS: Final = 5000
# List pagination bounds.
LIST_DEFAULT_LIMIT: Final = 50
LIST_MAX_LIMIT: Final = 200
# Hard cap on rows materialized for one export request.
MAX_EXPORT_ITEMS: Final = 20000

# =========================================================================
# On-demand guidance policy (development-only, immutable records)
# =========================================================================
# Guidance is deliberately deterministic in this slice: it turns the already
# persisted opportunity evidence into a bounded recommendation snapshot. No
# provider is contacted by this write or its read projections (invariant 7).
GUIDANCE_ENABLED_ENVIRONMENTS: Final[frozenset[str]] = frozenset(
    {"", "development", "dev", "local", "test", "testing"}
)
GUIDANCE_GENERATOR_VERSION: Final = "opportunity-guidance-deterministic-v1"
GUIDANCE_PROMPT_VERSION: Final = "opportunity-guidance-template-v1"
GUIDANCE_PROVIDER: Final = "deterministic"
GUIDANCE_MODEL: Final = "none"
GUIDANCE_IDEMPOTENCY_KEY_MAX_LEN: Final = 160
GUIDANCE_HISTORY_DEFAULT_LIMIT: Final = 20
GUIDANCE_HISTORY_MAX_LIMIT: Final = 100
GUIDANCE_MAX_EVIDENCE_KEYS: Final = 24
GUIDANCE_MAX_EVIDENCE_VALUE_CHARS: Final = 500
GUIDANCE_MAX_EVIDENCE_LIST_ITEMS: Final = 20
GUIDANCE_MAX_FINDINGS: Final = 8
