"""Generic, bounded vocabulary for canonical About-page entity evidence."""

from __future__ import annotations

from typing import Final

COMPANY_ENTITY_SIGNAL_WEIGHTS: Final[dict[str, float]] = {
    "company_and_offering_definition": 0.40,
    "audience_or_use_case": 0.25,
    "concrete_value_proposition": 0.20,
    "durable_first_party_proof": 0.15,
}

COMPANY_PROFILE_ROUTE_SEGMENTS: Final[tuple[str, ...]] = (
    "about",
    "about-us",
    "our-company",
    "our-story",
    "who-we-are",
)
COMPANY_PROFILE_TITLE_PHRASES: Final[tuple[str, ...]] = (
    "about",
    "about us",
    "our company",
    "our story",
    "who we are",
    "story of",
)
COMPANY_PROFILE_EXCLUDED_TERMS: Final[tuple[str, ...]] = (
    "careers",
    "company history",
    "contact",
    "history",
    "leadership",
    "our team",
    "ownership",
    "responsibility",
    "sourcing",
    "sustainability",
    "team",
)

# These expressions describe factual sentence grammar, not benchmark wording.
COMPANY_IDENTITY_PATTERN: Final = (
    r"\b(?P<value>[A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,5})\s+"
    r"(?:is|are)\s+(?:an?\s+|the\s+)?"
)
OFFERING_PATTERNS: Final[tuple[str, ...]] = (
    r"\b(?:builds?|creates?|designs?|develops?|delivers?|makes?|manufactures?|"
    r"offers?|operates?|provides?|sells?|supplies?|specializes\s+in)\s+"
    r"(?P<value>[^.;]{3,180})",
    r"\b(?:products?|services?|capabilities|solutions)\s+(?:include|are)\s+"
    r"(?P<value>[^.;]{3,180})",
)
AUDIENCE_PATTERNS: Final[tuple[str, ...]] = (
    r"\bfor\s+(?P<value>(?:businesses|companies|customers|families|people|"
    r"professionals|retailers|teams|users|organizations|communities)\b[^.;]{0,140})",
    r"\b(?:helps?|enables?|supports?|serves?)\s+"
    r"(?P<value>[^.;]{3,180})",
    r"\b(?:so|so that)\s+(?P<value>[^.;]{3,180})",
)
VALUE_PROPOSITION_PATTERNS: Final[tuple[str, ...]] = (
    r"\b(?:specializes?\s+in|focused\s+on|built\s+around|designed\s+to|"
    r"purpose-built|vertically\s+integrated|end-to-end|direct-to-consumer)\b[^.;]{3,180}",
    r"\b(?:our|the)\s+(?:approach|method|model|platform|process|system)\s+"
    r"(?:combines?|connects?|enables?|gives?|helps?|uses?)\b[^.;]{3,180}",
)
DURABLE_PROOF_PATTERNS: Final[tuple[str, ...]] = (
    r"\b(?:founded|established|launched)\s+(?:in\s+)?(?:18|19|20)\d{2}\b",
    r"\bsince\s+(?:18|19|20)\d{2}\b",
    r"\b(?:headquartered|based)\s+in\s+[^.;]{2,100}",
    r"\b(?:family-owned|employee-owned|founder-owned|privately\s+owned|"
    r"publicly\s+listed)\b",
    r"\b\d[\d,.+]*\s+(?:customers?|employees?|locations?|markets?|stores?|"
    r"countries|years)\b",
    r"\b(?:manufactures?|operates?|sources?|tests?)\s+(?:all|every|from|in|our)\b[^.;]{3,160}",
    r"\b(?:certified|certification|quality\s+(?:process|standard|testing)|"
    r"warranty|guarantee)\b[^.;]{0,120}",
)
PROOF_EXCLUSION_TERMS: Final[tuple[str, ...]] = (
    "award",
    "campaign",
    "donated",
    "promotion",
    "raised",
    "testimonial",
)

COMPANY_ENTITY_EVIDENCE_MAX_CHARS: Final = 256
COMPANY_ENTITY_SCAN_MAX_CHARS: Final = 12_000
