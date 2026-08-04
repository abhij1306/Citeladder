"""Deterministic thresholds for post-audit competitor suggestions."""

from typing import Final

ANALYZER_VERSION: Final = "observed-competitor-v1"
MIN_DISTINCT_PROMPTS: Final = 2
MIN_DISTINCT_ENGINES: Final = 2
MAX_CANDIDATES_PER_AUDIT: Final = 20
EXCLUDED_RESEARCH_DOMAINS: Final = frozenset(
    {
        "wikipedia.org",
        "youtube.com",
        "reddit.com",
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "x.com",
    }
)
STATUS_PENDING: Final = "pending"
STATUS_ACCEPTED: Final = "accepted"
STATUS_REJECTED: Final = "rejected"
STATUSES: Final = frozenset({STATUS_PENDING, STATUS_ACCEPTED, STATUS_REJECTED})
