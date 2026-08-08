"""Config owner for the Site Intelligence knowledge layer (S2/S3).

Vocabularies, versions, and thresholds for typed knowledge, question coverage,
journey coverage, and dimension scoring. Services read these; none of them
hardcode a state token, a threshold, or a formula weight (repo invariant:
configuration lives here, not in service code).

Industry-specific vocabulary — entity types, predicates, relation types,
journeys, questions — is NOT here. That is pack-owned
(``app/core/config/industry_packs/``) and is resolved from the crawl's frozen
manifest. This module owns only what is industry-neutral: the states a fact can
be in, the shape of the score, and the version stamps that make a recomputation
comparable.
"""

from __future__ import annotations

from typing import Final

# =========================================================================
# Versions frozen onto every derived row (invariant: derived rows carry the
# version of the logic that produced them)
# =========================================================================
# Bump when extraction changes which candidates are produced from the same
# facts. A crawl's knowledge rows are only comparable to another crawl's at the
# same version.
KNOWLEDGE_EXTRACTOR_VERSION: Final = "si-knowledge-1"
# Bump when question-state resolution changes.
QUESTION_COVERAGE_VERSION: Final = "si-coverage-1"
# Bump when journey stage coverage changes.
JOURNEY_COVERAGE_VERSION: Final = "si-journey-1"
# Bump when a dimension's components or the composite formula change.
DIMENSION_FORMULA_VERSION: Final = "si-dimensions-1"

# Crawl-configuration key holding the project's reviewed overlay (currently the
# questions a reviewer has declared out of scope). Part of the spec's
# ``core + pack + capabilities + versioned project overlay`` composition, and
# frozen onto the crawl like the pack manifest so a later overlay edit can never
# change what a past crawl reported.
PROJECT_OVERLAY_KEY: Final = "project_intelligence_overlay"
OVERLAY_NOT_APPLICABLE_QUESTIONS_KEY: Final = "not_applicable_question_ids"

# =========================================================================
# Knowledge review state
# =========================================================================
# Derived rows start ``observed``. Only an explicit user action moves a row
# further; nothing in the deterministic pipeline writes ``approved``.
REVIEW_STATE_OBSERVED: Final = "observed"
REVIEW_STATE_APPROVED: Final = "approved"
REVIEW_STATE_SUPERSEDED: Final = "superseded"
REVIEW_STATE_REJECTED: Final = "rejected"
REVIEW_STATES: Final[frozenset[str]] = frozenset(
    {
        REVIEW_STATE_OBSERVED,
        REVIEW_STATE_APPROVED,
        REVIEW_STATE_SUPERSEDED,
        REVIEW_STATE_REJECTED,
    }
)

# How an assertion's value was produced. ``visible_text`` and ``structured_data``
# are both deterministic and directly evidenced; they are kept apart because a
# claim present only in JSON-LD and a claim present only in visible copy are
# different findings (schema/visible parity).
DERIVATION_STRUCTURED_DATA: Final = "structured_data"
DERIVATION_VISIBLE_TEXT: Final = "visible_text"
DERIVATION_URL_STRUCTURE: Final = "url_structure"
DERIVATION_MODEL_PROPOSAL: Final = "model_proposal"
DERIVATION_USER_CORRECTION: Final = "user_correction"

# =========================================================================
# Assertion value typing
# =========================================================================
# Pack predicates declare one of these. The normalized form is what
# contradiction comparison uses, so two spellings of the same fact collapse and
# two genuinely different facts do not.
VALUE_TYPE_STRING: Final = "string"
VALUE_TYPE_NUMBER: Final = "number"
VALUE_TYPE_BOOLEAN: Final = "boolean"
VALUE_TYPE_DATE: Final = "date"
VALUE_TYPE_MONEY: Final = "money"
VALUE_TYPE_DURATION: Final = "duration"
VALUE_TYPE_URL: Final = "url"
VALUE_TYPE_ENTITY_REF: Final = "entity_ref"
VALUE_TYPE_OBJECT: Final = "object"

# =========================================================================
# The shared cross-pack vocabulary the extractor is written against
# =========================================================================
# Every one of the 16 catalog packs declares these twelve predicate suffixes
# (verified against the catalog), and every pack's entity types fall into the
# categories below. Extraction targets the SHARED vocabulary rather than any
# pack's private predicates, so one deterministic extractor serves Education and
# Commerce identically — the S4 gate ("commerce introduces no second knowledge
# model") is a property of this choice, not a later porting exercise.
#
# A predicate is addressed by SUFFIX and resolved to the active pack's namespaced
# id at compile time (``education.address`` / ``commerce.address``).
PREDICATE_LEGAL_NAME: Final = "legal_name"
PREDICATE_DESCRIPTION: Final = "description"
PREDICATE_CONTACT_POINT: Final = "contact_point"
PREDICATE_ADDRESS: Final = "address"
PREDICATE_AVAILABILITY: Final = "availability"
PREDICATE_PRICE_OR_FEE: Final = "price_or_fee"
PREDICATE_ELIGIBILITY: Final = "eligibility"
PREDICATE_PROCESS_STEP: Final = "process_step"
PREDICATE_POLICY_SUMMARY: Final = "policy_summary"
PREDICATE_PROOF_CLAIM: Final = "proof_claim"
PREDICATE_EFFECTIVE_DATE: Final = "effective_date"
PREDICATE_SERVICE_AREA: Final = "service_area"
CORE_PREDICATE_SUFFIXES: Final[tuple[str, ...]] = (
    PREDICATE_LEGAL_NAME,
    PREDICATE_DESCRIPTION,
    PREDICATE_CONTACT_POINT,
    PREDICATE_ADDRESS,
    PREDICATE_AVAILABILITY,
    PREDICATE_PRICE_OR_FEE,
    PREDICATE_ELIGIBILITY,
    PREDICATE_PROCESS_STEP,
    PREDICATE_POLICY_SUMMARY,
    PREDICATE_PROOF_CLAIM,
    PREDICATE_EFFECTIVE_DATE,
    PREDICATE_SERVICE_AREA,
)
# Suffixes this slice's DETERMINISTIC extractor can evidence today. The rest
# stay declared-but-unextracted, and a question needing one of them resolves to
# ``unsupported`` — a visible gap with a named cause, never a silent zero.
EXTRACTED_PREDICATE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        PREDICATE_LEGAL_NAME,
        PREDICATE_DESCRIPTION,
        PREDICATE_CONTACT_POINT,
        PREDICATE_ADDRESS,
        PREDICATE_PRICE_OR_FEE,
        PREDICATE_EFFECTIVE_DATE,
        PREDICATE_POLICY_SUMMARY,
    }
)

CATEGORY_ORGANIZATION: Final = "organization"
CATEGORY_AUDIENCE: Final = "audience"
CATEGORY_OFFERING: Final = "offering"
CATEGORY_PERSON: Final = "person"
CATEGORY_POLICY: Final = "policy"
CATEGORY_EVIDENCE: Final = "evidence"
CATEGORY_EVENT: Final = "event"
CATEGORY_PLACE: Final = "place"
CATEGORY_DOCUMENT: Final = "document"
# A page whose whole job is stating terms of exchange (a fee schedule, a price
# list). Kept separate from ``offering``: the thing being sold and the schedule
# of what it costs are different subjects, and packs declare money predicates
# against one or the other.
CATEGORY_COMMERCIAL: Final = "commercial"

# schema.org ``@type`` -> shared entity category. One signal among several: the
# first acceptance corpus publishes ZERO structured data, so every category here
# must also be reachable from visible evidence (see the extractor's role-driven
# path) or the knowledge model would be empty on a real site.
SCHEMA_TYPE_CATEGORIES: Final[dict[str, str]] = {
    "Organization": CATEGORY_ORGANIZATION,
    "EducationalOrganization": CATEGORY_ORGANIZATION,
    "School": CATEGORY_ORGANIZATION,
    "CollegeOrUniversity": CATEGORY_ORGANIZATION,
    "LocalBusiness": CATEGORY_ORGANIZATION,
    "Corporation": CATEGORY_ORGANIZATION,
    "NGO": CATEGORY_ORGANIZATION,
    "Person": CATEGORY_PERSON,
    "Place": CATEGORY_PLACE,
    "PostalAddress": CATEGORY_PLACE,
    "Event": CATEGORY_EVENT,
    "Product": CATEGORY_OFFERING,
    "Service": CATEGORY_OFFERING,
    "Course": CATEGORY_OFFERING,
    "Offer": CATEGORY_OFFERING,
}

# Suffixes that commonly trail an organization's name in a <title>. Trimmed
# before the identity key is computed so "The Asian School | Fees" and "The
# Asian School" are one entity rather than two.
TITLE_SEPARATORS: Final[tuple[str, ...]] = ("|", "–", "—", " - ", "::", "»", "•")

# =========================================================================
# Contradiction policy
# =========================================================================
# Pack predicates carry a ``conflict_policy``. These are the values the shared
# core understands; a predicate declaring anything else is treated as
# ``single_current`` (the strictest) rather than silently unguarded.
CONFLICT_POLICY_SINGLE_CURRENT: Final = "single_current"
CONFLICT_POLICY_SCOPED_VALUES: Final = "scoped_values"
CONFLICT_POLICY_MULTI_VALUE: Final = "multi_value"
# Predicates that legitimately hold many simultaneous values (several campuses,
# several contact points) never raise a contradiction on multiplicity alone.
NON_CONFLICTING_POLICIES: Final[frozenset[str]] = frozenset(
    {CONFLICT_POLICY_MULTI_VALUE, "multiple_compatible"}
)
# Cardinalities that permit several simultaneous values. A predicate declaring
# one of these is multi-valued by definition — a school publishes several phone
# numbers and several campuses — so multiplicity alone is never a contradiction.
MULTI_VALUE_CARDINALITIES: Final[frozenset[str]] = frozenset(
    {"many", "scoped_many"}
)

# =========================================================================
# Question coverage states
# =========================================================================
# Eight DISTINCT states. Collapsing any pair is the failure this vocabulary
# exists to prevent: "we could not fetch the page that would answer this" and
# "the page exists and does not answer it" lead to opposite actions.
COVERAGE_ANSWERED_STRONG: Final = "answered_strong"
COVERAGE_ANSWERED_WEAK: Final = "answered_weak"
COVERAGE_MISSING: Final = "missing"
COVERAGE_CONFLICTING: Final = "conflicting"
COVERAGE_UNSUPPORTED: Final = "unsupported"
COVERAGE_HISTORICAL_ONLY: Final = "historical_only"
COVERAGE_UNAVAILABLE_EVIDENCE: Final = "unavailable_evidence"
COVERAGE_NOT_APPLICABLE: Final = "not_applicable"
COVERAGE_STATES: Final[tuple[str, ...]] = (
    COVERAGE_ANSWERED_STRONG,
    COVERAGE_ANSWERED_WEAK,
    COVERAGE_MISSING,
    COVERAGE_CONFLICTING,
    COVERAGE_UNSUPPORTED,
    COVERAGE_HISTORICAL_ONLY,
    COVERAGE_UNAVAILABLE_EVIDENCE,
    COVERAGE_NOT_APPLICABLE,
)
# Only these count as answered when a coverage RATIO is reported. A weak answer
# counts at a discount rather than not at all, because a partially answered
# question is genuinely better than an absent one — but never as good.
COVERAGE_ANSWERED_CREDIT: Final[dict[str, float]] = {
    COVERAGE_ANSWERED_STRONG: 1.0,
    COVERAGE_ANSWERED_WEAK: 0.5,
}
# ``not_applicable`` is the ONLY state removed from the coverage denominator:
# a reviewer has said the question does not apply to this business, so counting
# it as a gap would be a permanent false finding. Every other state — including
# ``unavailable_evidence`` — stays in the denominator, because missing evidence
# is the finding, not an excuse to shrink the measurement.
COVERAGE_EXCLUDED_FROM_DENOMINATOR: Final[frozenset[str]] = frozenset(
    {COVERAGE_NOT_APPLICABLE}
)

# =========================================================================
# Journey coverage
# =========================================================================
# An outcome with no compatible integration event is ``unavailable`` and never
# numeric zero: zero conversions and no way to measure conversions are opposite
# findings (kernel spec ``JourneyDefinition``).
OUTCOME_STATE_UNAVAILABLE: Final = "unavailable"
OUTCOME_STATE_OBSERVED: Final = "observed"

# =========================================================================
# Universal dimensions (plan §7)
# =========================================================================
DIMENSION_DISCOVERABILITY: Final = "discoverability_delivery"
DIMENSION_KNOWLEDGE: Final = "knowledge_completeness"
DIMENSION_ANSWERABILITY: Final = "answerability"
DIMENSION_TRUST: Final = "trust_evidence"
DIMENSION_JOURNEY: Final = "journey_clarity"
DIMENSION_MACHINE: Final = "machine_clarity"

# The FULL denominator. A composite is always reported over all six, whatever
# the crawl observed. Renormalizing over observed dimensions only would rank a
# site with no schema graph, no policy pages, and no author attribution ABOVE a
# site that published all three and did them badly — it is missing exactly the
# dimensions it would have failed. Low coverage is itself the finding.
DIMENSION_IDS: Final[tuple[str, ...]] = (
    DIMENSION_DISCOVERABILITY,
    DIMENSION_KNOWLEDGE,
    DIMENSION_ANSWERABILITY,
    DIMENSION_TRUST,
    DIMENSION_JOURNEY,
    DIMENSION_MACHINE,
)
DIMENSION_LABELS: Final[dict[str, str]] = {
    DIMENSION_DISCOVERABILITY: "Discoverability and delivery",
    DIMENSION_KNOWLEDGE: "Knowledge completeness",
    DIMENSION_ANSWERABILITY: "Answerability",
    DIMENSION_TRUST: "Trust and evidence",
    DIMENSION_JOURNEY: "Journey clarity",
    DIMENSION_MACHINE: "Machine clarity",
}

# Each dimension's components, in report order. A component either scores in
# [0,1] from persisted evidence or reports UNAVAILABLE — and an unavailable
# component contributes 0 to the dimension score while removing itself from the
# dimension's coverage. That is the same non-renormalizing rule applied one
# level down.
DIMENSION_COMPONENTS: Final[dict[str, tuple[str, ...]]] = {
    DIMENSION_DISCOVERABILITY: (
        "indexable_ratio",
        "canonical_integrity",
        "internal_reachability",
        "acquisition_success",
    ),
    DIMENSION_KNOWLEDGE: (
        "identity_entity",
        "offering_entities",
        "audience_entities",
        "predicate_coverage",
        "relation_coverage",
        "role_coverage",
    ),
    DIMENSION_ANSWERABILITY: (
        "question_coverage",
        "question_units",
        "answer_first",
        "heading_structure",
    ),
    DIMENSION_TRUST: (
        "authorship",
        "dated_content",
        "policy_evidence",
        "external_citation",
        "contradiction_freedom",
    ),
    DIMENSION_JOURNEY: (
        "stage_role_coverage",
        "stage_question_coverage",
        "stage_conversion_actions",
        "stage_continuity",
    ),
    DIMENSION_MACHINE: (
        "schema_presence",
        "schema_validity",
        "schema_visible_parity",
        "entity_consistency",
    ),
}

COMPONENT_LABELS: Final[dict[str, str]] = {
    "indexable_ratio": "Pages admitted and indexable",
    "canonical_integrity": "Canonical declarations resolve",
    "internal_reachability": "Pages reachable by internal link",
    "acquisition_success": "Pages successfully acquired",
    "identity_entity": "Organization identity established",
    "offering_entities": "Offerings identified",
    "audience_entities": "Audiences identified",
    "predicate_coverage": "Required facts asserted",
    "relation_coverage": "Relationships between entities",
    "role_coverage": "Industry roles present in the corpus",
    "question_coverage": "Required questions answered",
    "question_units": "Question-shaped content",
    "answer_first": "Pages that answer before they narrate",
    "heading_structure": "Usable heading structure",
    "authorship": "Attributed authorship",
    "dated_content": "Published or modified dates",
    "policy_evidence": "Policy and disclosure pages",
    "external_citation": "Outbound citation",
    "contradiction_freedom": "Facts free of unresolved conflict",
    "stage_role_coverage": "Journey stages have their pages",
    "stage_question_coverage": "Journey stages answer their questions",
    "stage_conversion_actions": "Stages offer a next action",
    "stage_continuity": "Stages link onward",
    "schema_presence": "Structured data present",
    "schema_validity": "Structured data valid",
    "schema_visible_parity": "Schema matches visible content",
    "entity_consistency": "Entity naming is consistent",
}

# =========================================================================
# Bounds (nothing derived from a crawl may grow without limit)
# =========================================================================
MAX_ENTITIES_PER_CRAWL: Final = 2000
MAX_ASSERTIONS_PER_CRAWL: Final = 20000
MAX_RELATIONS_PER_CRAWL: Final = 5000
MAX_EVIDENCE_REFS_PER_ROW: Final = 8
MAX_ENTITY_ALIASES: Final = 16
MAX_VALUE_CHARS: Final = 512
MAX_IDENTITY_KEY_CHARS: Final = 256
MAX_CANONICAL_NAME_CHARS: Final = 512
# Assertions extracted from one page. A page that produces more than this is
# a listing or a generated dump, not a source of distinct facts.
MAX_ASSERTIONS_PER_PAGE: Final = 64
