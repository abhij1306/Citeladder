from __future__ import annotations

from typing import Final

CRAWL_STATUS_DRAFT: Final = "draft"

CRAWL_STATUS_VALIDATING: Final = "validating"

CRAWL_STATUS_QUEUED: Final = "queued"

CRAWL_STATUS_RUNNING: Final = "running"

CRAWL_STATUS_PAUSED: Final = "paused"

CRAWL_STATUS_COMPLETED: Final = "completed"

CRAWL_STATUS_PARTIALLY_COMPLETED: Final = "partially_completed"

CRAWL_STATUS_FAILED: Final = "failed"

CRAWL_STATUS_CANCELLED: Final = "cancelled"

CRAWL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        CRAWL_STATUS_DRAFT,
        CRAWL_STATUS_VALIDATING,
        CRAWL_STATUS_QUEUED,
        CRAWL_STATUS_RUNNING,
        CRAWL_STATUS_PAUSED,
        CRAWL_STATUS_COMPLETED,
        CRAWL_STATUS_PARTIALLY_COMPLETED,
        CRAWL_STATUS_FAILED,
        CRAWL_STATUS_CANCELLED,
    }
)

CRAWL_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        CRAWL_STATUS_COMPLETED,
        CRAWL_STATUS_PARTIALLY_COMPLETED,
        CRAWL_STATUS_FAILED,
        CRAWL_STATUS_CANCELLED,
    }
)

CRAWL_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        CRAWL_STATUS_DRAFT,
        CRAWL_STATUS_VALIDATING,
        CRAWL_STATUS_QUEUED,
        CRAWL_STATUS_RUNNING,
        CRAWL_STATUS_PAUSED,
    }
)

DISCOVERY_STATUS_PENDING: Final = "pending"

DISCOVERY_STATUS_RUNNING: Final = "running"

DISCOVERY_STATUS_STOPPED: Final = "stopped"

DISCOVERY_STATUS_COMPLETED: Final = "completed"

DISCOVERY_STATUS_SAMPLE_COMPLETED: Final = "sample_completed"

DISCOVERY_STATUS_FAILED: Final = "failed"

DISCOVERY_STATUS_CANCELLED: Final = "cancelled"

DISCOVERY_STATUSES: Final[frozenset[str]] = frozenset(
    {
        DISCOVERY_STATUS_PENDING,
        DISCOVERY_STATUS_RUNNING,
        DISCOVERY_STATUS_STOPPED,
        DISCOVERY_STATUS_COMPLETED,
        DISCOVERY_STATUS_SAMPLE_COMPLETED,
        DISCOVERY_STATUS_FAILED,
        DISCOVERY_STATUS_CANCELLED,
    }
)

ANALYSIS_STATUS_PENDING: Final = "pending"

ANALYSIS_STATUS_RUNNING: Final = "running"

ANALYSIS_STATUS_STOPPED: Final = "stopped"

ANALYSIS_STATUS_COMPLETED: Final = "completed"

ANALYSIS_STATUS_PARTIALLY_COMPLETED: Final = "partially_completed"

ANALYSIS_STATUS_FAILED: Final = "failed"

ANALYSIS_STATUS_CANCELLED: Final = "cancelled"

ANALYSIS_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ANALYSIS_STATUS_PENDING,
        ANALYSIS_STATUS_RUNNING,
        ANALYSIS_STATUS_STOPPED,
        ANALYSIS_STATUS_COMPLETED,
        ANALYSIS_STATUS_PARTIALLY_COMPLETED,
        ANALYSIS_STATUS_FAILED,
        ANALYSIS_STATUS_CANCELLED,
    }
)

PAGE_ANALYSIS_STATUS_PENDING: Final = "pending"

PAGE_ANALYSIS_STATUS_RUNNING: Final = "running"

PAGE_ANALYSIS_STATUS_COMPLETED: Final = "completed"

PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED: Final = "partially_completed"

PAGE_ANALYSIS_STATUS_FAILED: Final = "failed"

TASK_KIND_DISCOVER: Final = "discover"

TASK_KIND_SITE_SETUP: Final = "site_setup"

TASK_KIND_ANALYZE: Final = "analyze"

TASK_KIND_CHANGE_INTEL: Final = "change_intel"

TASK_KIND_LINK_METRICS: Final = "link_metrics"

TASK_KIND_ARCHITECTURE: Final = "architecture"

SITE_ACQUISITION_TASK_KINDS: Final[frozenset[str]] = frozenset(
    {TASK_KIND_DISCOVER, TASK_KIND_SITE_SETUP}
)

POST_TERMINAL_SITE_TASK_KINDS: Final[frozenset[str]] = frozenset(
    {TASK_KIND_CHANGE_INTEL, TASK_KIND_LINK_METRICS, TASK_KIND_ARCHITECTURE}
)

SITE_TASK_KINDS: Final[frozenset[str]] = frozenset(
    {
        TASK_KIND_DISCOVER,
        TASK_KIND_SITE_SETUP,
        TASK_KIND_ANALYZE,
        TASK_KIND_CHANGE_INTEL,
        TASK_KIND_LINK_METRICS,
        TASK_KIND_ARCHITECTURE,
    }
)

SITE_PROCESSING_TASK_KINDS: Final[frozenset[str]] = (
    SITE_TASK_KINDS - SITE_ACQUISITION_TASK_KINDS
)

INITIAL_TASK_GENERATION: Final = 0

OBSERVATION_SOURCE_ROOT: Final = "root"

OBSERVATION_SOURCE_LINK: Final = "link"

OBSERVATION_SOURCE_SITEMAP: Final = "sitemap"

OBSERVATION_SOURCE_REDIRECT: Final = "redirect"

OBSERVATION_SOURCES: Final[frozenset[str]] = frozenset(
    {
        OBSERVATION_SOURCE_ROOT,
        OBSERVATION_SOURCE_LINK,
        OBSERVATION_SOURCE_SITEMAP,
        OBSERVATION_SOURCE_REDIRECT,
    }
)

# Why a terminal crawl is PARTIALLY_COMPLETED. A crawl that fetched fewer URLs
# than it discovered is a DIFFERENT fact from one whose analyses fell short, and
# on a real site the first is routine — a dead link, a PDF, a blocked host. They
# had one shared status and one analysis-flavoured message, so every crawl with
# a single unreachable link reported that pages "could not be analyzed".
CRAWL_PARTIAL_REASON_NONE: Final = ""
CRAWL_PARTIAL_REASON_DISCOVERY: Final = "discovery_incomplete"
CRAWL_PARTIAL_REASON_ANALYSIS: Final = "analysis_incomplete"
CRAWL_PARTIAL_REASON_BOTH: Final = "discovery_and_analysis_incomplete"
CRAWL_PARTIAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        CRAWL_PARTIAL_REASON_NONE,
        CRAWL_PARTIAL_REASON_DISCOVERY,
        CRAWL_PARTIAL_REASON_ANALYSIS,
        CRAWL_PARTIAL_REASON_BOTH,
    }
)

RULE_ID_TECHNICAL_INDEXABLE: Final = "technical.indexable"

AEO_READINESS_DIMENSIONS: Final[tuple[str, ...]] = (
    "answerability",
    "structure",
    "evidence",
    "machine-readability",
    "authority",
    "freshness",
    "crawlability",
)

AEO_READINESS_DIMENSION_LABELS: Final[dict[str, str]] = {
    "answerability": "Answerability",
    "structure": "Structure",
    "evidence": "Evidence",
    "machine-readability": "Machine readability",
    "authority": "Provenance & trust signals",
    "freshness": "Freshness",
    "crawlability": "Crawlability",
}

# One plain sentence per dimension, in the reader's language. The screen used to
# show only the key, so "Machine-readability 12 / 3 / 40" asked the reader to
# already know what the row meant.
AEO_READINESS_DIMENSION_DESCRIPTIONS: Final[dict[str, str]] = {
    "answerability": (
        "Whether a page answers its question directly, near the top, without "
        "hiding the answer behind a click."
    ),
    "structure": (
        "Whether headings and structured data describe the page accurately "
        "enough for an answer engine to quote the right part."
    ),
    "evidence": "Whether claims are backed by sources a reader can follow.",
    "machine-readability": (
        "Whether the page states what it is in machine-readable form, rather "
        "than leaving an engine to infer it from prose."
    ),
    "authority": "Whether it is clear who published the page and stands behind it.",
    "freshness": "Whether the page says when it was written or last updated.",
    "crawlability": (
        "Whether an answer engine can reach and read the page at all — the "
        "checks that make every other dimension moot when they fail."
    ),
}

AEO_READINESS_MAX_EVALUATIONS: Final = 100_000

# Evidence is listed one row per PAGE, not one per (page, rule): the same URL
# appearing five times under five rule IDs was the single worst thing about the
# old drawer. The cap bounds pages, and the projection reports the true failing
# page total beside it so a capped list never reads as the whole set.
AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION: Final = 25

# Temporary PR1 presentation guard. The persisted PR2 checkpoint-family and
# measurement-state contract does not exist yet, so PR1 qualifies the current
# nullable AEO score with determinate checkpoint and readiness-dimension breadth.
PR1_AEO_MIN_DETERMINATE_CHECKPOINTS: Final = 4
PR1_AEO_MIN_DETERMINATE_DIMENSIONS: Final = 3

# The shipped outcome vocabulary still stores these states as not_applicable.
# They mean expected-but-unresolved, however, so they stay in readiness coverage
# denominators until PR2 gives them explicit unknown/unavailable outcomes.
PR1_AEO_UNCERTAINTY_REASONS: Final[frozenset[str]] = frozenset(
    {
        "coverage_not_complete",
        "insufficient_evidence",
        "no_checkable_alternates",
    }
)

DIMENSION_TECHNICAL: Final = "technical"

DIMENSION_AEO: Final = "aeo"

RULE_DIMENSIONS: Final[frozenset[str]] = frozenset({DIMENSION_TECHNICAL, DIMENSION_AEO})

RULE_OUTCOME_SATISFIED: Final = "satisfied"

RULE_OUTCOME_PASS: Final = RULE_OUTCOME_SATISFIED

RULE_OUTCOME_MISSING: Final = "missing"

RULE_OUTCOME_FAIL: Final = RULE_OUTCOME_MISSING

RULE_OUTCOME_PARTIAL: Final = "partial"

RULE_OUTCOME_UNKNOWN: Final = "unknown"

RULE_OUTCOME_UNAVAILABLE: Final = "unavailable"

RULE_OUTCOME_CONFLICTING: Final = "conflicting"

RULE_OUTCOME_EXCLUDED: Final = "excluded"

RULE_OUTCOME_NOT_APPLICABLE: Final = "not_applicable"

RULE_OUTCOME_ERROR: Final = "error"

RULE_FAILING_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        RULE_OUTCOME_FAIL,
        RULE_OUTCOME_PARTIAL,
    }
)

RULE_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        RULE_OUTCOME_PASS,
        RULE_OUTCOME_FAIL,
        RULE_OUTCOME_PARTIAL,
        RULE_OUTCOME_UNKNOWN,
        RULE_OUTCOME_UNAVAILABLE,
        RULE_OUTCOME_CONFLICTING,
        RULE_OUTCOME_EXCLUDED,
        RULE_OUTCOME_NOT_APPLICABLE,
        RULE_OUTCOME_ERROR,
    }
)

SEVERITY_CRITICAL: Final = "critical"

SEVERITY_HIGH: Final = "high"

SEVERITY_MEDIUM: Final = "medium"

SEVERITY_LOW: Final = "low"

SEVERITY_INFO: Final = "info"

RULE_SEVERITIES: Final[frozenset[str]] = frozenset(
    {
        SEVERITY_CRITICAL,
        SEVERITY_HIGH,
        SEVERITY_MEDIUM,
        SEVERITY_LOW,
        SEVERITY_INFO,
    }
)

CATEGORY_INDEXABILITY: Final = "indexability"

CATEGORY_METADATA: Final = "metadata"

CATEGORY_CONTENT: Final = "content"

CATEGORY_STRUCTURED_DATA: Final = "structured_data"

CATEGORY_PERFORMANCE: Final = "performance"

CATEGORY_LINKS: Final = "links"

CATEGORY_SECURITY: Final = "security"

CATEGORY_CITABILITY: Final = "citability"

CATEGORY_ARCHITECTURE: Final = "architecture"

APPLICABILITY_SITE_ROOT: Final = "site_root"

APPLICABILITY_CRAWL_FINALIZE: Final = "crawl_finalize"

APPLICABILITY_OBSERVED_CONTENT: Final = "observed_content"

# NOT_APPLICABLE reason vocabulary. These strings reach the user through the
# evaluation evidence -- a skipped rule has to be able to explain itself -- so
# they are named constants rather than literals scattered through the checks.
#
# ``insufficient_evidence`` is deliberately a REASON and not a fifth outcome.
# not_applicable already delivers exactly what uncertainty needs: excluded from
# scoring, disclosed rather than hidden, and never a failure. Uncertainty must
# never be converted into a defect.
SKIP_REASON_INSUFFICIENT_EVIDENCE: Final = "insufficient_evidence"

SKIP_REASON_LOW_CONFIDENCE_KIND: Final = "low_confidence_kind"

CODE_MONITORING_NOT_ALLOWED: Final = "monitoring_not_allowed"

CODE_QUOTA_EXCEEDED: Final = "site_health_quota_exceeded"

CODE_STALE_SELECTION_VERSION: Final = "stale_selection_version"

CODE_CRAWL_ALREADY_ACTIVE: Final = "crawl_already_active"

CODE_DISCOVERY_LIMIT_EXCEEDED: Final = "site_health_discovery_limit_exceeded"

CODE_ANALYSIS_LIMIT_EXCEEDED: Final = "site_health_analysis_limit_exceeded"

CODE_PHASE_ALREADY_RUNNING: Final = "site_health_phase_already_running"

CODE_PHASE_NOT_RESUMABLE: Final = "site_health_phase_not_resumable"

CODE_ADVANCED_CONTROLS_UNAVAILABLE: Final = "advanced_controls_unavailable"

CANCELLED_DISCOVERY_TASK_CLONE_LIMIT: Final = 32

EVENT_CRAWL_CREATED: Final = "crawl.created"

EVENT_CRAWL_QUEUED: Final = "crawl.queued"

EVENT_CRAWL_RUNNING: Final = "crawl.running"

EVENT_DISCOVERY_PROGRESS: Final = "discovery.progress"

EVENT_ANALYSIS_PROGRESS: Final = "analysis.progress"

EVENT_DISCOVERY_STARTED: Final = "discovery.started"

EVENT_DISCOVERY_STOPPED: Final = "discovery.stopped"

EVENT_ANALYSIS_STARTED: Final = "analysis.started"

EVENT_ANALYSIS_STOPPED: Final = "analysis.stopped"

EVENT_CRAWL_STATUS: Final = "crawl.status"

EVENT_CRAWL_COMPLETED: Final = "crawl.completed"

EVENT_CRAWL_FAILED: Final = "crawl.failed"

EVENT_CRAWL_CANCELLED: Final = "crawl.cancelled"

# Pre-launch semantic versions reset with the disposable development database.
EXTRACTOR_VERSION: Final = "sh-extractor-1"

LINK_REWRITE_VERSION: Final = "sh-link-rewrite-1"

LINK_REWRITE_ENCODED_TRACKING_QUERY: Final = "encoded_tracking_query_delimiter"

ANALYZER_VERSION: Final = "sh-analyzer-1"

RULE_CATALOG_VERSION: Final = "sh-rules-1"

SCORING_VERSION: Final = "sh-scoring-1"

CLASSIFIER_VERSION: Final = "sh-classifier-1"
