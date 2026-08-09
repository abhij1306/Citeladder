"""Demand Intelligence policy, vocabulary, and version ownership."""

from typing import Final, TypedDict

DEMAND_ANALYZER_VERSION: Final = "demand-analyzer-1"
DEMAND_FORMULA_VERSION: Final = "demand-priority-1"
DEMAND_RULE_VERSION: Final = "demand-rules-1"

DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR: Final = "high_impression_low_ctr"
DEMAND_SIGNAL_UNANSWERED_QUESTION: Final = "unanswered_required_question"
DEMAND_SIGNAL_TYPES: Final[frozenset[str]] = frozenset(
    {
        DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
        DEMAND_SIGNAL_UNANSWERED_QUESTION,
    }
)

DEMAND_SIGNAL_STATE_ACTIVE: Final = "active"
DEMAND_SIGNAL_STATE_RESOLVED: Final = "resolved"

DEMAND_MIN_IMPRESSIONS: Final = 10
DEMAND_LOW_CTR_THRESHOLD: Final = 0.02
DEMAND_SEARCH_GAP_WEIGHT: Final = 1.0
DEMAND_QUESTION_GAP_WEIGHT: Final = 0.5
DEMAND_LIST_DEFAULT_LIMIT: Final = 50
DEMAND_LIST_MAX_LIMIT: Final = 200

JOURNEY_STATUS_ACTIVE: Final = "active"
JOURNEY_STATUS_ARCHIVED: Final = "archived"
JOURNEY_STATUSES: Final[frozenset[str]] = frozenset(
    {JOURNEY_STATUS_ACTIVE, JOURNEY_STATUS_ARCHIVED}
)
JOURNEY_SOURCE_PACK: Final = "industry_pack"
JOURNEY_SOURCE_USER: Final = "user"
JOURNEY_SOURCES: Final[frozenset[str]] = frozenset(
    {JOURNEY_SOURCE_PACK, JOURNEY_SOURCE_USER}
)


class DemandPackJourney(TypedDict):
    slug: str
    name: str
    stages: list[str]
    key_events: list[str]


DEMAND_PACK_JOURNEYS: Final[dict[str, DemandPackJourney]] = {
    "education": {
        "slug": "admissions",
        "name": "Admissions",
        "stages": ["discover", "evaluate", "apply", "enroll"],
        "key_events": ["admissions_enquiry", "application_start", "application_submit"],
    },
    "commerce": {
        "slug": "purchase",
        "name": "Purchase",
        "stages": ["discover", "evaluate", "purchase", "retain"],
        "key_events": ["view_item", "add_to_cart", "purchase"],
    },
}
