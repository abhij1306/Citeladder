"""The golden onboarding corpus, assembled.

The cases themselves live in the two sibling modules, split product-side from
service-side. This module only orders them and builds the lookups, so the
corpus can grow without any one file becoming unreadable.
"""

from __future__ import annotations

from evaluations.onboarding_cases_commerce import COMMERCE_CASES
from evaluations.onboarding_cases_services import SOFTWARE_AND_SERVICE_CASES
from evaluations.onboarding_corpus import GoldenOnboardingCase

GOLDEN_ONBOARDING_CASES: tuple[GoldenOnboardingCase, ...] = (
    *COMMERCE_CASES,
    *SOFTWARE_AND_SERVICE_CASES,
)

# Same category, different geography and size.  A generator driven by a fixed
# industry table emits the same market prompts for both; the harness scores that
# collision directly rather than relying on inspection.
COLLISION_PAIR = ("wakefit-india", "burrow-united-states")

CASES_BY_SLUG: dict[str, GoldenOnboardingCase] = {
    case.slug: case for case in GOLDEN_ONBOARDING_CASES
}
