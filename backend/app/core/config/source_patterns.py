# Cited-source pattern taxonomy (invariant 1: config owns catalogs + versions).
#
# Owns the deterministic domain -> source-class mapping used to describe WHAT
# KIND of sources an answer engine cited on a prompt where the tracked brand
# has no owned citation. This is descriptive only: it reports an OBSERVED
# SOURCE PATTERN beside a recommendation gap. It never asserts that a citation
# caused a recommendation, and it never produces an authority score.
#
# Classification order is identity-first: a citation the analyzer already
# resolved to an owned domain or to a tracked competitor keeps that identity.
# Only the remaining third-party domains are looked up in the tables below, and
# an unknown domain stays ``other_third_party`` — the taxonomy abstains rather
# than guessing (invariant 8: unknown is its own state).
#
# Bump ``SOURCE_TAXONOMY_VERSION`` on ANY change to the classes or the domain
# tables so a persisted evidence payload is traceable to the exact mapping that
# produced it (invariant 4).
from __future__ import annotations

from typing import Final

SOURCE_TAXONOMY_VERSION: Final = "source-taxonomy-1"

SOURCE_CLASS_BRAND_OWNED: Final = "brand_owned"
SOURCE_CLASS_COMPETITOR_OWNED: Final = "competitor_owned"
SOURCE_CLASS_COMMUNITY: Final = "community"
SOURCE_CLASS_VIDEO: Final = "video"
SOURCE_CLASS_REVIEW_MARKETPLACE: Final = "review_marketplace"
SOURCE_CLASS_EDITORIAL_THIRD_PARTY: Final = "editorial_third_party"
SOURCE_CLASS_OTHER_THIRD_PARTY: Final = "other_third_party"

# Stable render/report order (never alphabetical — this is the order a reader
# should reason about a gap in: who owns it, then how independent it is).
SOURCE_CLASS_ORDER: Final[tuple[str, ...]] = (
    SOURCE_CLASS_BRAND_OWNED,
    SOURCE_CLASS_COMPETITOR_OWNED,
    SOURCE_CLASS_REVIEW_MARKETPLACE,
    SOURCE_CLASS_EDITORIAL_THIRD_PARTY,
    SOURCE_CLASS_COMMUNITY,
    SOURCE_CLASS_VIDEO,
    SOURCE_CLASS_OTHER_THIRD_PARTY,
)

COMMUNITY_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "reddit.com",
        "news.ycombinator.com",
        "quora.com",
        "stackexchange.com",
        "stackoverflow.com",
        "discourse.org",
        "producthunt.com",
        "slashdot.org",
    }
)

VIDEO_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "youtube.com",
        "youtu.be",
        "vimeo.com",
        "tiktok.com",
        "twitch.tv",
        "dailymotion.com",
    }
)

REVIEW_MARKETPLACE_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "g2.com",
        "capterra.com",
        "trustpilot.com",
        "getapp.com",
        "softwareadvice.com",
        "trustradius.com",
        "gartner.com",
        "clutch.co",
        "sourceforge.net",
        "producthunt.com",
        "glassdoor.com",
        "yelp.com",
    }
)

EDITORIAL_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "techcrunch.com",
        "forbes.com",
        "wired.com",
        "theverge.com",
        "zdnet.com",
        "cnet.com",
        "businessinsider.com",
        "pcmag.com",
        "techradar.com",
        "venturebeat.com",
        "arstechnica.com",
        "economictimes.indiatimes.com",
        "yourstory.com",
    }
)

# Evaluated in order; the FIRST table containing the domain wins. Ordering is
# load-bearing where tables overlap (``producthunt.com`` is both a community
# and a marketplace — it is reported as a marketplace).
SOURCE_CLASS_DOMAIN_TABLES: Final[tuple[tuple[str, frozenset[str]], ...]] = (
    (SOURCE_CLASS_REVIEW_MARKETPLACE, REVIEW_MARKETPLACE_DOMAINS),
    (SOURCE_CLASS_VIDEO, VIDEO_DOMAINS),
    (SOURCE_CLASS_COMMUNITY, COMMUNITY_DOMAINS),
    (SOURCE_CLASS_EDITORIAL_THIRD_PARTY, EDITORIAL_DOMAINS),
)

PATTERN_COMPETITOR_OWNED_SOURCES: Final = "competitor_owned_sources_cited"
PATTERN_INDEPENDENT_VALIDATION: Final = "independent_validation_present"
PATTERN_COMMUNITY_EVIDENCE: Final = "community_evidence_present"
PATTERN_VIDEO_EVIDENCE: Final = "video_evidence_present"
PATTERN_MULTIPLE_INDEPENDENT_DOMAINS: Final = "multiple_independent_domains"

# A gap is only labelled "corroborated across independent domains" once this
# many DISTINCT non-brand, non-competitor domains appear. Two domains is noise;
# three is a pattern worth acting on.
MULTIPLE_INDEPENDENT_DOMAIN_MIN: Final = 3

# Upper bound on the citations embedded in one opportunity's evidence payload.
# The payload is persisted JSONB read by a drawer, not an export — the full
# citation set stays reachable through the run/evidence surfaces.
MAX_TOP_CITATIONS: Final = 6

ACTION_STRENGTHEN_OWNED_ANSWER: Final = "strengthen_owned_answer_page"
ACTION_PURSUE_INDEPENDENT_EVIDENCE: Final = "pursue_independent_evidence"
ACTION_PURSUE_COMMUNITY_EVIDENCE: Final = "pursue_community_evidence"
ACTION_INVESTIGATE_COMPETITOR_SOURCES: Final = "investigate_competitor_sources"
ACTION_DEFAULT: Final = ACTION_STRENGTHEN_OWNED_ANSWER

PATTERN_TO_ACTION: Final[tuple[tuple[str, str], ...]] = (
    (PATTERN_MULTIPLE_INDEPENDENT_DOMAINS, ACTION_PURSUE_INDEPENDENT_EVIDENCE),
    (PATTERN_COMPETITOR_OWNED_SOURCES, ACTION_INVESTIGATE_COMPETITOR_SOURCES),
    (PATTERN_INDEPENDENT_VALIDATION, ACTION_PURSUE_INDEPENDENT_EVIDENCE),
    (PATTERN_COMMUNITY_EVIDENCE, ACTION_PURSUE_COMMUNITY_EVIDENCE),
    (PATTERN_VIDEO_EVIDENCE, ACTION_PURSUE_COMMUNITY_EVIDENCE),
)
