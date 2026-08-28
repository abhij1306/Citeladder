"""Deterministic vocabulary for buyer-query archetype validation.

Kept separate from the prompt instructions and archetype catalog so the
configuration owners remain readable. These sets are semantic signals, not
sentence-prefix rules.
"""

from typing import Final

# Words naming a kind of provider a buyer is trying to reach.
PROVIDER_NOUNS: Final[frozenset[str]] = frozenset(
    {
        "store",
        "stores",
        "shop",
        "shops",
        "retailer",
        "retailers",
        "seller",
        "sellers",
        "supplier",
        "suppliers",
        "brand",
        "brands",
        "site",
        "sites",
        "website",
        "websites",
        "marketplace",
        "outlet",
        "outlets",
        "platform",
        "platforms",
        "tool",
        "tools",
        "software",
        "app",
        "apps",
        "service",
        "services",
        "provider",
        "providers",
        "company",
        "companies",
        "agency",
        "agencies",
        "firm",
        "firms",
        "clinic",
        "clinics",
        "hospital",
        "hospitals",
        "doctor",
        "doctors",
        "surgeon",
        "dentist",
        "lawyer",
        "lawyers",
        "solicitor",
        "attorney",
        "accountant",
        "plumber",
        "electrician",
        "mechanic",
        "cleaner",
        "cleaners",
        "contractor",
        "builder",
        "installer",
        "school",
        "schools",
        "college",
        "colleges",
        "university",
        "universities",
        "course",
        "courses",
        "bank",
        "banks",
        "insurer",
        "broker",
        "restaurant",
        "salon",
        "gym",
        "someone",
        "anyone",
        "who",
    }
)

# Words that ask the answer to rank, select, or qualify options.
SELECTION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "best",
        "top",
        "better",
        "good",
        "great",
        "leading",
        "recommended",
        "recommend",
        "recommendations",
        "cheapest",
        "cheap",
        "affordable",
        "budget",
        "value",
        "inexpensive",
        "premium",
        "quality",
        "reliable",
        "trusted",
        "worth",
        "favourite",
        "favorite",
        "popular",
    }
)

# Verbs and interrogatives that signal acquisition rather than curiosity.
ACQUISITION_WORDS: Final[frozenset[str]] = frozenset(
    {
        "buy",
        "buying",
        "purchase",
        "order",
        "get",
        "getting",
        "find",
        "finding",
        "looking",
        "look",
        "shop",
        "shopping",
        "hire",
        "hiring",
        "book",
        "booking",
        "need",
        "needed",
        "want",
        "where",
        "which",
        "who",
        "stock",
        "stocks",
        "sell",
        "sells",
        "delivery",
        "deliver",
        "ship",
        "shipping",
        # Provider-seeking pronouns: "Someone to deep clean two bathrooms
        # this weekend" is an acquisition query with no verb of purchase.
        "someone",
        "anyone",
    }
)

PRICE_WORDS: Final[frozenset[str]] = frozenset(
    {
        "price",
        "prices",
        "pricing",
        "cost",
        "costs",
        "cheap",
        "cheapest",
        "affordable",
        "budget",
        "deal",
        "deals",
        "discount",
        "sale",
        "under",
        "below",
        "spend",
        "worth",
    }
)

COMPARISON_WORDS: Final[frozenset[str]] = frozenset(
    {
        "vs",
        "versus",
        "compare",
        "compared",
        "comparison",
        "difference",
        "differences",
        "better",
        "instead",
        "rather",
        "or",
        "against",
        "alternative",
        "alternatives",
    }
)

PROCEDURAL_WORDS: Final[frozenset[str]] = frozenset(
    {
        "how",
        "clean",
        "wash",
        "care",
        "fix",
        "repair",
        "replace",
        "install",
        "set",
        "setup",
        "return",
        "returns",
        "exchange",
        "maintain",
        "remove",
        "keep",
        "stop",
        "size",
        "sizing",
        "fit",
        "measure",
        "monitor",
        "track",
    }
)

# Minimum content tokens a prompt must carry beyond its topic name and the
# generic-word stoplist. Two is enough to separate "What is womenswear
# including plus size?" (one) from "Looking for cheap kids school clothes
# before term starts" (three) without demanding contrived specificity.
MIN_CONSTRAINT_TOKENS: Final = 2
