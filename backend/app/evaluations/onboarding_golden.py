"""Scoring for the onboarding golden corpus.

The corpus in :mod:`app.evaluations.onboarding_corpus` states what good looks
like; this module measures a produced result against it.  It is a quality gate
for a generated review payload, not a source of production facts: the live
onboarding flow must still derive its recommendation from the supplied official
site and require user review before creating a project.

The headline metric is deliberately *not* a rating.  Probing five judge models
with a plain "score 0-100 how realistic these prompts are" returned 75-85 for a
set containing three literal template fills — models anchor high and will not
discriminate on an absolute scale.  :func:`evaluate_realism` instead runs a
discrimination test: gold and generated prompts are shuffled together unlabelled
and the judge must say which are machine-written.  Subtracting the judge's
false-positive rate on the gold prompts cancels its leniency, so the score only
falls when the judge can genuinely tell our prompts from real ones.
"""

from __future__ import annotations

import json
import os
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import httpx

from app.analysis.normalization import normalize_alias
from app.domain.prompts.portfolio import contains_tracked_name
from app.evaluations.onboarding_cases import (
    CASES_BY_SLUG,
    COLLISION_PAIR,
    GOLDEN_ONBOARDING_CASES,
)
from app.evaluations.onboarding_corpus import GoldenOnboardingCase

__all__ = [
    "CASES_BY_SLUG",
    "COLLISION_PAIR",
    "GOLDEN_ONBOARDING_CASES",
    "GoldenOnboardingCase",
    "PortfolioPrompt",
    "collision_score",
    "evaluate_competitors",
    "evaluate_context",
    "evaluate_portfolio",
    "evaluate_realism",
    "gold_overlap",
    "template_tell",
]

# Bounded, not exact.  A brand the model barely knows should ship fewer honest
# prompts rather than pad to a quota, so only the ceiling is enforced.
MARKET_VISIBILITY_MAX = 5
BRAND_RELEVANT_MAX = 5
BRANDED_MAX = 5
PORTFOLIO_MAX = MARKET_VISIBILITY_MAX + BRAND_RELEVANT_MAX + BRANDED_MAX
PORTFOLIO_MIN = 6

NEUTRAL_COHORTS = ("market_visibility", "brand_relevant")
BRANDED_COHORTS = ("brand_diagnostic", "comparison")

JUDGE_DEFAULT_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
JUDGE_DEFAULT_MODEL = "llama-3.3-70b-versatile"

_SLOT_PATTERN = re.compile(r"\{[a-z_]+\}")
_SLOT_SENTINEL = "zzslotzz"
# A produced category counts as correct when it shares most of its content words
# with an accepted alias.  Substring matching is too weak: it would let the bare
# word "software" satisfy "feed management software".
_CATEGORY_MATCH_THRESHOLD = 0.5
_WORD_PATTERN = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "best",
        "but",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "how",
        "i",
        "in",
        "is",
        "it",
        "me",
        "my",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "to",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
        "you",
        "your",
    }
)


@dataclass(frozen=True, slots=True)
class PortfolioPrompt:
    text: str
    cohort: str


@dataclass(frozen=True, slots=True)
class PortfolioEvaluation:
    valid: bool
    issues: tuple[str, ...]
    market_visibility_count: int
    brand_relevant_count: int
    branded_count: int
    market_signal_rate: float = 0.0
    offering_coverage: float = 0.0
    use_case_coverage: float = 0.0


@dataclass(frozen=True, slots=True)
class CompetitorEvaluation:
    precision: float
    recall: float
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextEvaluation:
    category_match: bool
    facet_accuracy: float
    jtbd_coverage: float
    mismatches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RealismEvaluation:
    """Result of the gold-versus-generated discrimination test."""

    skipped: bool
    score: float | None
    machine_detection_rate: float | None
    false_positive_rate: float | None
    model: str
    detail: str = ""


def evaluate_competitors(
    case: GoldenOnboardingCase, proposed: Iterable[str]
) -> CompetitorEvaluation:
    """Score expected-set overlap without making competitor truth production data.

    Names are matched on identity, not on string equality. Exact matching scored
    Puma's competitor set at 0.0 for returning "Nike" and "Adidas" where the
    corpus says "Nike India" and "Adidas India" -- the same companies, correctly
    found. It likewise missed "JustDial Home Services" against "Justdial". A
    brand keeps its identity when a market or descriptive suffix is added, so
    the comparison drops those before deciding.
    """
    expected = {_normalized(name): name for name in case.expected_competitors}
    actual = {_normalized(name): name for name in proposed if name.strip()}
    matched_expected: set[str] = set()
    matched_actual: set[str] = set()
    for expected_key in expected:
        for actual_key in actual:
            if actual_key in matched_actual:
                continue
            if _same_company(expected_key, actual_key):
                matched_expected.add(expected_key)
                matched_actual.add(actual_key)
                break
    return CompetitorEvaluation(
        precision=len(matched_actual) / len(actual) if actual else 0.0,
        recall=len(matched_expected) / len(expected) if expected else 1.0,
        missing=tuple(
            expected[key] for key in sorted(expected.keys() - matched_expected)
        ),
        unexpected=tuple(actual[key] for key in sorted(actual.keys() - matched_actual)),
    )


# Words that never distinguish one company from another, so a name that differs
# only by these is the same company wearing a market or category label.
_NON_DISTINCTIVE = frozenset(
    {
        "india",
        "indian",
        "australia",
        "australian",
        "usa",
        "us",
        "uk",
        "global",
        "group",
        "inc",
        "ltd",
        "limited",
        "services",
        "service",
        "home",
        "online",
        "store",
        "stores",
        "shop",
        "company",
        "co",
    }
)


def _same_company(left: str, right: str) -> bool:
    """Same company if one name is the other plus only non-distinctive words.

    The test is on the *difference*, not the overlap. Requiring merely that the
    shorter name be a subset let a bare "Gold" satisfy "Fat Gold" -- two
    unrelated olive oil brands -- because the overlap looked brand-like. Asking
    what the longer name adds is the question that actually separates
    "Nike" / "Nike India" from "Gold" / "Fat Gold".
    """
    if left == right:
        return True
    left_words, right_words = set(left.split()), set(right.split())
    shorter, longer = sorted((left_words, right_words), key=len)
    if not shorter or not shorter <= longer:
        return False
    if not shorter - _NON_DISTINCTIVE:
        return False
    return not (longer - shorter) - _NON_DISTINCTIVE


def evaluate_portfolio(
    case: GoldenOnboardingCase, prompts: Sequence[PortfolioPrompt]
) -> PortfolioEvaluation:
    """Apply the structural contract, and *measure* topical coverage.

    Coverage is reported, never enforced.  The corpus's own hand-authored gold
    prompts fail a hard coverage rule, which is the finding rather than a bug:
    requiring every product string to appear verbatim forces keyword stuffing,
    and requiring the market name forces the stilted "... in United States"
    suffix onto queries no American ever types.  Structure is a contract;
    vocabulary is a score.
    """
    neutral = [p for p in prompts if p.cohort == "market_visibility"]
    brand_relevant = [p for p in prompts if p.cohort == "brand_relevant"]
    branded = [p for p in prompts if p.cohort in BRANDED_COHORTS]
    issues = [
        *_cohort_issues(prompts, neutral, brand_relevant, branded),
        *_identity_issues(case, prompts),
    ]
    combined = " ".join(_normalized(p.text) for p in prompts)
    return PortfolioEvaluation(
        valid=not issues,
        issues=tuple(issues),
        market_visibility_count=len(neutral),
        brand_relevant_count=len(brand_relevant),
        branded_count=len(branded),
        market_signal_rate=_signal_rate(prompts, case.market_terms),
        offering_coverage=_covered_fraction(combined, case.products_or_services),
        use_case_coverage=_covered_fraction(combined, case.use_cases),
    )


def _signal_rate(
    prompts: Sequence[PortfolioPrompt], market_terms: Sequence[str]
) -> float:
    """Share of prompts that name the market at all.

    Real buyers name their market often in India and rarely in the US, so this
    is a descriptive rate rather than a threshold.
    """
    if not prompts:
        return 0.0
    terms = [_normalized(term) for term in market_terms]
    hits = sum(
        1
        for prompt in prompts
        if any(term and term in _normalized(prompt.text) for term in terms)
    )
    return hits / len(prompts)


def _covered_fraction(text: str, requirements: Sequence[str]) -> float:
    if not requirements:
        return 1.0
    hits = sum(1 for item in requirements if _normalized(item) in text)
    return hits / len(requirements)


def _cohort_issues(prompts, neutral, brand_relevant, branded):
    issues = []
    known = len(neutral) + len(brand_relevant) + len(branded)
    if known != len(prompts):
        issues.append("every prompt must carry a known cohort")
    if not PORTFOLIO_MIN <= len(prompts) <= PORTFOLIO_MAX:
        issues.append(
            f"expected {PORTFOLIO_MIN}-{PORTFOLIO_MAX} prompts, got {len(prompts)}"
        )
    if len(neutral) > MARKET_VISIBILITY_MAX:
        issues.append(f"at most {MARKET_VISIBILITY_MAX} market_visibility prompts")
    if len(brand_relevant) > BRAND_RELEVANT_MAX:
        issues.append(f"at most {BRAND_RELEVANT_MAX} brand_relevant prompts")
    if len(branded) > BRANDED_MAX:
        issues.append(f"at most {BRANDED_MAX} branded prompts")
    return issues


def _identity_issues(case, prompts):
    """Neutral cohorts must never name the brand; branded cohorts must."""
    issues = []
    normalized = [_normalized(p.text) for p in prompts]
    if len(set(normalized)) != len(normalized):
        issues.append("prompt portfolio contains duplicate questions")
    brand_terms = (case.brand_name,)
    neutral = [p for p in prompts if p.cohort in NEUTRAL_COHORTS]
    if any(
        contains_tracked_name(p.text, brand_terms)
        or contains_tracked_name(p.text, case.expected_competitors)
        for p in neutral
    ):
        issues.append("neutral prompts must be brand and competitor neutral")
    branded = [p for p in prompts if p.cohort in BRANDED_COHORTS]
    if any(not contains_tracked_name(p.text, brand_terms) for p in branded):
        issues.append("branded prompts must name the brand")
    return issues


def evaluate_context(
    case: GoldenOnboardingCase, produced: dict[str, object]
) -> ContextEvaluation:
    """Score the resolved business context against the expected facets."""
    category = str(produced.get("category") or "")
    category_match = _category_matches(case, category)
    hits, mismatches = _facet_hits(case, produced)
    if not category_match:
        mismatches.append(f"category: expected ~{case.category!r}, got {category!r}")

    jtbd_blob = _normalized(f"{_produced_terms(produced)} {category}")
    covered = sum(1 for job in case.jobs_to_be_done if _shares_content(job, jtbd_blob))
    return ContextEvaluation(
        category_match=category_match,
        facet_accuracy=hits / len(_SCORED_FACETS),
        jtbd_coverage=covered / len(case.jobs_to_be_done),
        mismatches=tuple(mismatches),
    )


_SCORED_FACETS = ("business_model", "market_scope", "buyer_type")


def _category_matches(case: GoldenOnboardingCase, category: str) -> bool:
    """Does the produced category cover a recognised alias?

    Containment, not symmetric similarity. Jaccard punished the right answer for
    being richer: "premium mattress and sleep products brand" scored below
    threshold against the alias "mattress brand" purely because it said more.
    What matters is whether an accepted alias is substantially *present*, so the
    denominator is the alias, and extra specificity costs nothing.
    """
    produced = _content_words(category)
    if not produced:
        return False
    aliases = [*case.category_aliases, case.category]
    return any(
        len(alias_words & produced) / len(alias_words) >= _CATEGORY_MATCH_THRESHOLD
        for alias in aliases
        if (alias_words := _content_words(alias))
    )


def _facet_hits(
    case: GoldenOnboardingCase, produced: dict[str, object]
) -> tuple[int, list[str]]:
    hits = 0
    mismatches: list[str] = []
    for facet in _SCORED_FACETS:
        expected = getattr(case, facet)
        actual = str(produced.get(facet) or "")
        candidates = {actual}
        if facet == "business_model":
            # A composite business satisfies the expectation from either slot:
            # calling Urban Company a marketplace is not wrong, it is partial.
            secondary = produced.get("secondary_business_models")
            if isinstance(secondary, list | tuple):
                candidates |= {str(item) for item in secondary}
        if expected in candidates:
            hits += 1
        else:
            mismatches.append(f"{facet}: expected {expected!r}, got {actual!r}")
    return hits, mismatches


def _produced_terms(produced: dict[str, object]) -> str:
    terms = produced.get("category_terms")
    if not isinstance(terms, list | tuple):
        return ""
    return " ".join(str(term) for term in terms)


def template_tell(
    prompts: Sequence[PortfolioPrompt], templates: Iterable[str]
) -> float:
    """Share of prompts that match a known archetype skeleton.

    A template is turned into an anchored regex by replacing each ``{slot}``
    with a non-greedy wildcard, so a slot-filled prompt matches its own
    skeleton exactly.  This is the machine-detectable half of "synthetic
    language" and needs no judge.
    """
    patterns = [
        pattern
        for pattern in (_template_pattern(template) for template in templates)
        if pattern is not None
    ]
    if not prompts or not patterns:
        return 0.0
    hits = sum(
        1
        for prompt in prompts
        if any(pattern.match(_normalized(prompt.text)) for pattern in patterns)
    )
    return hits / len(prompts)


def _template_pattern(template: str) -> re.Pattern[str] | None:
    # The sentinel must survive `normalize_alias`, which strips punctuation and
    # control characters -- so it has to be an ordinary alphanumeric word.
    normalized = _normalized(_SLOT_PATTERN.sub(f" {_SLOT_SENTINEL} ", template))
    if _SLOT_SENTINEL not in normalized:
        return None
    escaped = "".join(
        ".+?" if part == _SLOT_SENTINEL else re.escape(part)
        for part in re.split(f"({_SLOT_SENTINEL})", normalized)
    )
    return re.compile(f"^{escaped}$")


def gold_overlap(prompts: Sequence[PortfolioPrompt], gold: Sequence[str]) -> float:
    """Mean best-match content-word similarity of each prompt to the gold set.

    Deterministic and dependency-free: content-word Jaccard, best gold match per
    generated prompt.  It rewards talking about the same things as real buyers
    without requiring identical phrasing.
    """
    if not prompts or not gold:
        return 0.0
    gold_tokens = [_content_words(text) for text in gold]
    gold_tokens = [tokens for tokens in gold_tokens if tokens]
    if not gold_tokens:
        return 0.0
    total = 0.0
    for prompt in prompts:
        tokens = _content_words(prompt.text)
        if not tokens:
            continue
        total += max(_jaccard(tokens, candidate) for candidate in gold_tokens)
    return total / len(prompts)


def collision_score(
    left: Sequence[PortfolioPrompt],
    right: Sequence[PortfolioPrompt],
    *,
    left_market_terms: Sequence[str] = (),
    right_market_terms: Sequence[str] = (),
) -> float:
    """Jaccard overlap of two portfolios' neutral prompt text.

    Two different brands in the same category should not receive the same
    prompts.  Market names are stripped first, because the question is whether
    the *questions* are identical, not whether they mention different countries:
    a generator that swaps only the country token has still produced one
    portfolio, not two.  A table-driven generator scores ~1.0 here.
    """
    left_set = _neutral_texts(left, left_market_terms)
    right_set = _neutral_texts(right, right_market_terms)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _neutral_texts(
    prompts: Sequence[PortfolioPrompt], market_terms: Sequence[str]
) -> set[str]:
    stripped = [
        term
        for term in sorted(
            (_normalized(term) for term in market_terms), key=len, reverse=True
        )
        if term
    ]
    # Whole words only. A bare `str.replace` for "us" also gutted "business" and
    # "customers", which silently changed what was being compared.
    patterns = [re.compile(r"\b" + re.escape(term) + r"\b") for term in stripped]
    texts = set()
    for prompt in prompts:
        if prompt.cohort not in NEUTRAL_COHORTS:
            continue
        text = _normalized(prompt.text)
        for pattern in patterns:
            text = pattern.sub(" ", text)
        texts.add(" ".join(text.split()))
    return texts


async def evaluate_realism(
    case: GoldenOnboardingCase,
    prompts: Sequence[PortfolioPrompt],
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    seed: int = 17,
) -> RealismEvaluation:
    """Run the gold-versus-generated discrimination test.

    A missing key is an expected local-development condition, so this returns a
    skipped result rather than making tests or CI depend on a paid network call.
    """
    resolved_key = api_key or os.environ.get("JUDGE_API_KEY", "")
    resolved_model = model or os.environ.get(
        "ONBOARDING_EVAL_MODEL", JUDGE_DEFAULT_MODEL
    )
    if not resolved_key:
        return RealismEvaluation(
            True, None, None, None, resolved_model, "no judge API key configured"
        )
    if not prompts:
        return RealismEvaluation(
            True, None, None, None, resolved_model, "no generated prompts to judge"
        )

    items = _discrimination_items(case, prompts, seed=seed)
    resolved_endpoint = endpoint or os.environ.get(
        "ONBOARDING_EVAL_ENDPOINT", JUDGE_DEFAULT_ENDPOINT
    )
    payload = {
        "model": resolved_model,
        "messages": [
            {"role": "system", "content": _DISCRIMINATION_SYSTEM},
            {"role": "user", "content": _discrimination_input(case, items)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 1024,
    }
    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=90.0, transport=transport) as client:
            response = await client.post(
                resolved_endpoint, json=payload, headers=headers
            )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
        # A rate-limited or unreachable judge is a missing measurement, not a
        # failed case. Crashing here would discard a whole corpus run over a
        # free-tier 429 and make the deterministic metrics unavailable too.
        return RealismEvaluation(
            True, None, None, None, resolved_model, f"judge unavailable: {exc!s}"[:200]
        )
    try:
        return _score_discrimination(json.loads(content), items, resolved_model)
    except (ValueError, TypeError) as exc:
        # A malformed verdict is a missing measurement, not a failed case.
        return RealismEvaluation(
            True, None, None, None, resolved_model, f"judge unparsable: {exc!s}"[:200]
        )


_DISCRIMINATION_SYSTEM = (
    "You are shown search prompts for one business. Some were written by real "
    "buyers; others were produced by software. For each id say which. Judge only "
    "whether the wording sounds like a person actually typing a query - not "
    "whether it is well formed. Stilted, over-complete, uniformly structured "
    "questions are machine-written. Return JSON only: "
    '{"labels": [{"id": <int>, "source": "human"|"machine"}]}'
)


def _discrimination_items(
    case: GoldenOnboardingCase,
    prompts: Sequence[PortfolioPrompt],
    *,
    seed: int,
) -> list[tuple[int, str, bool]]:
    """Interleave gold and generated prompts. Returns (id, text, is_generated)."""
    gold = [*case.gold_buyer_prompts, *case.gold_branded_prompts][: len(prompts) + 4]
    items = [(text, False) for text in gold]
    items += [(prompt.text, True) for prompt in prompts]
    random.Random(seed).shuffle(items)
    return [(index, text, generated) for index, (text, generated) in enumerate(items)]


def _discrimination_input(
    case: GoldenOnboardingCase, items: Sequence[tuple[int, str, bool]]
) -> str:
    return json.dumps(
        {
            "business": f"{case.brand_name} - {case.category} ({case.primary_market})",
            "prompts": [{"id": index, "text": text} for index, text, _ in items],
        },
        ensure_ascii=False,
    )


def _label_id(entry: dict) -> int | None:
    """Tolerate a judge that omits an id or returns it as a string."""
    try:
        return int(entry["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _score_discrimination(
    review: dict, items: Sequence[tuple[int, str, bool]], model: str
) -> RealismEvaluation:
    labels = review.get("labels")
    if not isinstance(labels, list):
        raise ValueError("judge response must contain a labels array")
    called_machine = {
        int(entry["id"])
        for entry in labels
        if isinstance(entry, dict) and str(entry.get("source", "")).lower() == "machine"
    }
    generated = [index for index, _, is_generated in items if is_generated]
    human = [index for index, _, is_generated in items if not is_generated]
    if not generated or not human:
        raise ValueError("discrimination test needs both gold and generated prompts")

    detection = len(called_machine & set(generated)) / len(generated)
    false_positive = len(called_machine & set(human)) / len(human)
    # Subtracting the false-positive rate cancels judge leniency: a judge that
    # labels everything machine scores the same as one that labels nothing.
    score = 100.0 * (1.0 - (detection - false_positive))
    return RealismEvaluation(
        skipped=False,
        score=max(0.0, min(100.0, score)),
        machine_detection_rate=detection,
        false_positive_rate=false_positive,
        model=model,
    )


def _normalized(value: str) -> str:
    return normalize_alias(value).strip()


def _content_words(value: str) -> frozenset[str]:
    words = _WORD_PATTERN.findall(_normalized(value))
    return frozenset(word for word in words if word not in _STOPWORDS)


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _shares_content(phrase: str, blob: str) -> bool:
    words = _content_words(phrase)
    if not words:
        return False
    blob_words = _content_words(blob)
    return bool(words & blob_words)
