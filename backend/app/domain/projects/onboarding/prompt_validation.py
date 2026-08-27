"""Deterministic admission for generated visibility prompts.

Every rule here exists because a model ignored the same instruction in prose.
The old system prompt asked for no padded lead-ins and got "What are my best
options for online general merchandise in India?"; it asked for no pasted
positioning and got "...best fits my needs as Indian consumers seeking a wide
range of products with competitive pricing, convenience, and fast delivery".
Asking is advisory. This is not.

Validation never rewrites or synthesizes prompt text. A candidate that fails is
dropped with a reason, and the reason is fed back into a single retry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.analysis.normalization import normalize_alias
from app.core.config.brand_discovery import MARKET_CONTEXT_TERMS
from app.core.config.projects import PROMPT_INTENTS
from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_CORE,
    TOPICAL_BINDING_STOPWORDS,
)
from app.core.config.visibility_prompts import (
    BUYER_QUERY_CORE_PATTERNS,
    BUYER_QUERY_PATTERN_MIN_WORDS,
    PROVIDER_DESCRIPTION_PHRASES,
    VISIBILITY_MAX_ORGANIC_PROMPTS,
    VISIBILITY_MAX_SHARED_OPENINGS,
    VISIBILITY_PROMPT_DUPLICATE_RATIO,
    VISIBILITY_PROMPT_MAX_WORDS,
    VISIBILITY_PROMPT_MIN_WORDS,
)
from app.domain.prompts.portfolio import contains_tracked_name
from app.domain.prompts.style import (
    names_market,
    opening_key,
    positioning_shingles,
    repeats_positioning,
    starts_with_template,
    words,
)

__all__ = [
    "PortfolioValidator",
    "brand_terms",
    "market_terms",
    "ordered_portfolio",
    "positioning_shingles",
]


def brand_terms(
    brand_name: str,
    aliases: list[str],
    category_vocabulary: list[str] | None = None,
) -> list[str]:
    """The brand name, its aliases, and the short form people actually type.

    An organic prompt must never name the tracked brand, or the visibility
    score measures the brand answering about itself. Matching only the full
    name let every short form through: with "Apollo Hospitals" tracked, the
    generator produced "Best Apollo hospital for kidney stone treatment" as an
    ORGANIC prompt and nothing rejected it.

    Only distinctive tokens are added. A token naming the kind of provider
    ("Hospitals", "Company") or a common query word ("Best", "Top", "Shop") is
    not the brand, and banning it would reject legitimate prompts across the
    whole category. A brand built entirely from such words keeps only its full
    name, which is the safe direction to fail in.

    `category_vocabulary` is the same escape hatch driven by evidence rather
    than by a fixed word list. "Red Dress" sells dresses, so the static generic
    set never saw "dress" and banned it -- which rejected every organic dress
    query, emptied the core cohort, and left a portfolio of nothing but the two
    mandatory brand-diagnostic prompts. A token the business's own confirmed
    category uses is category language first and brand language second: it is
    dropped from the token bans. The full name and the aliases are always
    banned, so "Red Dress" itself still cannot appear in an organic prompt.
    """
    generic = {
        _singular(word)
        for phrase in PROVIDER_DESCRIPTION_PHRASES
        for word in phrase.split()
    } | TOPICAL_BINDING_STOPWORDS
    category = {
        _stem(token) for phrase in category_vocabulary or [] for token in words(phrase)
    }
    tokens = [
        token
        for token in words(brand_name)
        if len(token) >= 4
        and token not in generic
        and _singular(token) not in generic
        and _stem(token) not in category
    ]
    return list(dict.fromkeys([brand_name, *aliases, *tokens]))


def _singular(token: str) -> str:
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _stem(token: str) -> str:
    """Fold a word to a form that matches its own plural.

    `_singular` strips a single trailing "s", which is enough for the generic
    provider vocabulary but cannot match "dress" to "dresses" -- it produces
    "dres" and the comparison silently fails, which is exactly the bug this
    guards. "-es" is stripped only when what remains still ends in a sibilant,
    so "dresses" folds to "dress" while "shoes" folds to "shoe".
    """
    if (
        len(token) > 4
        and token.endswith("es")
        and (token[-3] in "sxz" or token[-4:-2] in {"ch", "sh"})
    ):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def market_terms(market: str, service_areas: list[str]) -> tuple[str, ...]:
    """Words whose presence means a prompt named where the buyer is.

    The bare ISO code is deliberately NOT included. "IN" matched as a substring
    of "running", "finding" and "shipping", so nearly every prompt registered as
    naming its market and the one-per-topic cap rejected good prompts wholesale.
    The configured context terms already carry the readable names a buyer would
    actually type.
    """
    configured = MARKET_CONTEXT_TERMS.get(market.upper(), ())
    areas = [str(area).strip() for area in service_areas if str(area).strip()]
    return tuple(dict.fromkeys([*configured, *areas]))


@dataclass(slots=True)
class PortfolioValidator:
    """Accumulates an accepted portfolio, enforcing the cross-prompt rules.

    Stateful because three of the rules are portfolio-wide, not per-prompt:
    duplicates, opening diversity, and the per-topic market-mention cap. Batches
    are generated separately and concurrently, so the state has to live outside
    any one of them.
    """

    topic_ids: frozenset[str]
    brand_terms: list[str]
    competitor_terms: list[str]
    positioning: frozenset[str] = frozenset()
    market_words: tuple[str, ...] = ()
    _accepted: list[dict] = field(default_factory=list, init=False)
    _normalized: list[str] = field(default_factory=list, init=False)
    _openings: dict[str, int] = field(default_factory=dict, init=False)
    _market_by_topic: dict[str, int] = field(default_factory=dict, init=False)

    @property
    def accepted(self) -> list[dict]:
        return list(self._accepted)

    def topics_covered(self) -> set[str]:
        return {prompt["topic_id"] for prompt in self._accepted}

    def _shape_error(
        self, text: str, topic_id: str, intent: str, cohort: str, pattern: str
    ) -> str:
        if cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC:
            # A diagnostic prompt need not name a topic, but an id it does
            # carry has to be one of ours. Blanking an unknown id threw the
            # association away silently; rejecting feeds the reason back into
            # the retry and leaves every accepted id a canonical one.
            if topic_id and topic_id not in self.topic_ids:
                return "topic_id"
        elif topic_id not in self.topic_ids:
            return "topic_id"
        if intent not in PROMPT_INTENTS:
            return "intent"
        minimum_words = BUYER_QUERY_PATTERN_MIN_WORDS.get(
            pattern, VISIBILITY_PROMPT_MIN_WORDS
        )
        if not minimum_words <= len(words(text)) <= VISIBILITY_PROMPT_MAX_WORDS:
            return "length"
        return ""

    def _name_error(self, text: str, cohort: str, intent: str) -> str:
        tracked = [*self.brand_terms, *self.competitor_terms]
        if cohort == PROMPT_COHORT_CORE and contains_tracked_name(text, tracked):
            return "tracked_name"
        if cohort != PROMPT_COHORT_CORE and not contains_tracked_name(
            text, self.brand_terms
        ):
            return "missing_brand_name"
        if cohort == PROMPT_COHORT_COMPARISON:
            if intent != "comparison":
                return "comparison_intent"
            if not contains_tracked_name(text, self.competitor_terms):
                return "missing_competitor_name"
        return ""

    def _style_error(self, text: str, topic_id: str) -> str:
        if starts_with_template(text):
            return "template_lead_in"
        if repeats_positioning(text, self.positioning):
            return "positioning_paste_in"
        alias = normalize_alias(text)
        if any(
            alias == prior
            or SequenceMatcher(None, alias, prior).ratio()
            >= VISIBILITY_PROMPT_DUPLICATE_RATIO
            for prior in self._normalized
        ):
            return "duplicate"
        if self._openings.get(opening_key(text), 0) >= VISIBILITY_MAX_SHARED_OPENINGS:
            return "repeated_opening"
        if (
            topic_id
            and self._names_market(text)
            and self._market_by_topic.get(topic_id, 0) >= 1
        ):
            return "market_mention_cap"
        return ""

    def _names_market(self, text: str) -> bool:
        return names_market(text, self.market_words)

    def offer(self, candidate: dict, *, cohort: str) -> str:
        """Accept one candidate, or return the reason it was rejected."""
        text = " ".join(str(candidate.get("text") or "").split())
        topic_id = str(candidate.get("topic_id") or "")
        intent = str(candidate.get("intent") or "").strip().casefold()
        pattern = str(candidate.get("pattern") or "")
        error = (
            self._shape_error(text, topic_id, intent, cohort, pattern)
            or self._name_error(text, cohort, intent)
            or self._style_error(text, topic_id)
        )
        if error:
            return error
        self._normalized.append(normalize_alias(text))
        opening = opening_key(text)
        self._openings[opening] = self._openings.get(opening, 0) + 1
        if topic_id and self._names_market(text):
            self._market_by_topic[topic_id] = self._market_by_topic.get(topic_id, 0) + 1
        self._accepted.append(
            {
                "slot_id": str(candidate.get("slot_id") or ""),
                "topic_id": topic_id,
                "text": text,
                "intent": intent,
                "cohort": cohort,
                "pattern": pattern,
            }
        )
        return ""


def _partition_portfolio(
    prompts: list[dict], topic_ids: list[str]
) -> tuple[dict[str, list[dict]], list[dict]]:
    by_topic: dict[str, list[dict]] = {topic_id: [] for topic_id in topic_ids}
    trailing: list[dict] = []
    for prompt in prompts:
        if prompt["cohort"] == PROMPT_COHORT_CORE and prompt["topic_id"] in by_topic:
            by_topic[prompt["topic_id"]].append(prompt)
        else:
            trailing.append(prompt)
    return by_topic, trailing


def _available_index(
    rows: list[dict], used: set[int], desired_pattern: str
) -> int | None:
    preferred = next(
        (
            index
            for index, row in enumerate(rows)
            if index not in used and row.get("pattern") == desired_pattern
        ),
        None,
    )
    if preferred is not None:
        return preferred
    return next((index for index in range(len(rows)) if index not in used), None)


def _rotated_organic(
    by_topic: dict[str, list[dict]], topic_ids: list[str]
) -> list[dict]:
    ordered: list[dict] = []
    used: dict[str, set[int]] = {topic_id: set() for topic_id in topic_ids}
    round_index = 0
    while len(ordered) < VISIBILITY_MAX_ORGANIC_PROMPTS and any(
        len(used[topic_id]) < len(by_topic[topic_id]) for topic_id in topic_ids
    ):
        for topic_index, topic_id in enumerate(topic_ids):
            rows = by_topic[topic_id]
            if len(ordered) >= VISIBILITY_MAX_ORGANIC_PROMPTS:
                break
            desired = BUYER_QUERY_CORE_PATTERNS[
                (topic_index + round_index) % len(BUYER_QUERY_CORE_PATTERNS)
            ]
            choice = _available_index(rows, used[topic_id], desired)
            if choice is not None:
                used[topic_id].add(choice)
                ordered.append(rows[choice])
        round_index += 1
    return ordered


def ordered_portfolio(prompts: list[dict], *, topic_ids: list[str]) -> list[dict]:
    """Round-robin across topics and patterns, then append named cohorts.

    Every topic gets a first prompt before any gets a second. The preferred
    pattern rotates by topic and round so a ten-topic cap does not become ten
    identical ``What is ...?`` questions.
    """
    by_topic, trailing = _partition_portfolio(prompts, topic_ids)
    return [*_rotated_organic(by_topic, topic_ids), *trailing]
