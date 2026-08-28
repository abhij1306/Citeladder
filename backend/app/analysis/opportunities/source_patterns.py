# Observed source-pattern summary for a recommendation gap (pure, no I/O).
#
# Given the citations an audit already persisted for one prompt's repetitions,
# this module answers one question: WHAT KIND of sources did the engines cite
# where the tracked brand has no owned citation? It is a deterministic
# projection over ``Citation`` rows plus the config-owned domain taxonomy —
# no DB, no provider, no LLM, no score (invariants 7 + 9).
#
# Deliberately NOT claimed: that any cited source caused the recommendation.
# The output is phrased throughout as an OBSERVED SOURCE PATTERN sitting beside
# a measured gap. Callers must keep that framing in user-facing copy.
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.analysis.normalization import domain_matches, normalize_domain
from app.core.config.source_patterns import (
    ACTION_DEFAULT,
    MAX_TOP_CITATIONS,
    MULTIPLE_INDEPENDENT_DOMAIN_MIN,
    PATTERN_COMMUNITY_EVIDENCE,
    PATTERN_COMPETITOR_OWNED_SOURCES,
    PATTERN_INDEPENDENT_VALIDATION,
    PATTERN_MULTIPLE_INDEPENDENT_DOMAINS,
    PATTERN_TO_ACTION,
    PATTERN_VIDEO_EVIDENCE,
    SOURCE_CLASS_BRAND_OWNED,
    SOURCE_CLASS_COMMUNITY,
    SOURCE_CLASS_COMPETITOR_OWNED,
    SOURCE_CLASS_DOMAIN_TABLES,
    SOURCE_CLASS_EDITORIAL_THIRD_PARTY,
    SOURCE_CLASS_INSTITUTIONAL,
    SOURCE_CLASS_ORDER,
    SOURCE_CLASS_OTHER_THIRD_PARTY,
    SOURCE_CLASS_REVIEW_MARKETPLACE,
    SOURCE_CLASS_SOCIAL,
    SOURCE_CLASS_VIDEO,
    SOURCE_TAXONOMY_VERSION,
)

# The classes that count as evidence NOT published by the brand or by a tracked
# competitor. "Independent" here means independent OWNERSHIP, nothing more.
_INDEPENDENT_CLASSES = frozenset(
    {
        SOURCE_CLASS_REVIEW_MARKETPLACE,
        SOURCE_CLASS_EDITORIAL_THIRD_PARTY,
        SOURCE_CLASS_COMMUNITY,
        SOURCE_CLASS_SOCIAL,
        SOURCE_CLASS_INSTITUTIONAL,
        SOURCE_CLASS_VIDEO,
        SOURCE_CLASS_OTHER_THIRD_PARTY,
    }
)


@dataclass(frozen=True)
class CitationEvidence:
    """One persisted ``Citation`` reduced to its source-pattern signals.

    ``is_owned`` / ``matched_competitor`` are the analyzer's ALREADY-PERSISTED
    identity verdicts (invariant 4) — this module never re-derives them from
    the domain, it only classifies what the analyzer left as third-party.
    """

    domain: str
    url: str
    title: str
    is_owned: bool
    matched_competitor: str | None


def classify_source_domain(
    domain: str, *, is_owned: bool, matched_competitor: str | None
) -> str:
    """Deterministic source class for one citation (identity first).

    An analyzer-resolved owned domain or tracked-competitor domain keeps that
    identity regardless of the domain tables — a competitor's own YouTube
    channel is still competitor-owned content. Everything else falls through
    to the config tables, and an unknown domain abstains to
    ``other_third_party`` rather than being guessed into a class.
    """
    if is_owned:
        return SOURCE_CLASS_BRAND_OWNED
    if matched_competitor:
        return SOURCE_CLASS_COMPETITOR_OWNED
    normalized = normalize_domain(domain)
    if not normalized:
        return SOURCE_CLASS_OTHER_THIRD_PARTY
    for source_class, known in SOURCE_CLASS_DOMAIN_TABLES:
        if any(domain_matches(normalized, entry) for entry in known):
            return source_class
    return SOURCE_CLASS_OTHER_THIRD_PARTY


def _observed_patterns(
    classes_present: set[str], independent_domain_count: int
) -> list[str]:
    """The descriptive labels this citation set supports (config order)."""
    patterns: list[str] = []
    if SOURCE_CLASS_COMPETITOR_OWNED in classes_present:
        patterns.append(PATTERN_COMPETITOR_OWNED_SOURCES)
    if classes_present & {
        SOURCE_CLASS_REVIEW_MARKETPLACE,
        SOURCE_CLASS_EDITORIAL_THIRD_PARTY,
    }:
        patterns.append(PATTERN_INDEPENDENT_VALIDATION)
    if SOURCE_CLASS_COMMUNITY in classes_present:
        patterns.append(PATTERN_COMMUNITY_EVIDENCE)
    if SOURCE_CLASS_VIDEO in classes_present:
        patterns.append(PATTERN_VIDEO_EVIDENCE)
    if independent_domain_count >= MULTIPLE_INDEPENDENT_DOMAIN_MIN:
        patterns.append(PATTERN_MULTIPLE_INDEPENDENT_DOMAINS)
    return patterns


def _recommended_action(patterns: Iterable[str]) -> str:
    """The single next action implied by the strongest observed pattern."""
    present = set(patterns)
    for pattern, action in PATTERN_TO_ACTION:
        if pattern in present:
            return action
    return ACTION_DEFAULT


def by_domain(
    citations: Iterable[CitationEvidence],
) -> dict[str, tuple[str, CitationEvidence]]:
    """Collapse citations to one representative per normalized domain.

    A gap's shape is "which distinct sources back the competitors", so the same
    domain cited on four repetitions is ONE observation, not four. The first
    citation seen for a domain (caller-ordered) represents it.
    """
    seen: dict[str, tuple[str, CitationEvidence]] = {}
    for citation in citations:
        domain = normalize_domain(citation.domain) or normalize_domain(citation.url)
        if not domain or domain in seen:
            continue
        source_class = classify_source_domain(
            domain,
            is_owned=citation.is_owned,
            matched_competitor=citation.matched_competitor,
        )
        seen[domain] = (source_class, citation)
    return seen


def summarize_source_pattern(citations: Iterable[CitationEvidence]) -> dict[str, Any]:
    """Project one prompt's citations into an observed source-pattern block.

    Returns a JSON-ready dict for embedding in an ``Opportunity.evidence``
    payload: distinct-domain counts per class, the observed patterns, the
    competitor -> cited-domain map, a bounded list of representative citations,
    and the taxonomy version that produced all of it (invariant 4).

    An empty citation set is a valid, distinct answer: zero counts, no
    patterns, and the default action — NOT a missing block. "No sources were
    cited" is evidence too, and the drawer must be able to say so.
    """
    domains = by_domain(citations)
    class_counts: dict[str, int] = {}
    competitor_domains: dict[str, list[str]] = {}
    independent_domains: set[str] = set()

    for domain, (source_class, citation) in domains.items():
        class_counts[source_class] = class_counts.get(source_class, 0) + 1
        if source_class in _INDEPENDENT_CLASSES:
            independent_domains.add(domain)
        if citation.matched_competitor:
            competitor_domains.setdefault(citation.matched_competitor, []).append(
                domain
            )

    patterns = _observed_patterns(set(class_counts), len(independent_domains))
    ordered = sorted(
        domains.items(),
        key=lambda item: (SOURCE_CLASS_ORDER.index(item[1][0]), item[0]),
    )
    return {
        "taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "distinct_domain_count": len(domains),
        "independent_domain_count": len(independent_domains),
        # Only non-zero classes, in config render order — a zero is absence of
        # observation, and padding the map with zeros would read as a measured
        # zero on every class the engines never touched.
        "class_counts": {
            source_class: class_counts[source_class]
            for source_class in SOURCE_CLASS_ORDER
            if source_class in class_counts
        },
        "observed_patterns": patterns,
        "competitor_source_domains": {
            competitor: sorted(domains)
            for competitor, domains in sorted(competitor_domains.items())
        },
        "top_citations": [
            {
                "domain": domain,
                "url": citation.url,
                "title": citation.title,
                "source_class": source_class,
                "matched_competitor": citation.matched_competitor,
            }
            for domain, (source_class, citation) in ordered[:MAX_TOP_CITATIONS]
        ],
        "top_citations_truncated": len(ordered) > MAX_TOP_CITATIONS,
        "recommended_action": _recommended_action(patterns),
    }
