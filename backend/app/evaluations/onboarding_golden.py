"""Golden evaluation corpus for the brand-onboarding research experience.

The corpus intentionally contains public, well-known brands only.  It is a
quality gate for a generated review payload, not a source of production facts:
the live onboarding flow must still derive its recommendation from the supplied
official site and require user review before creating a project.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import httpx

from app.analysis.normalization import normalize_alias
from app.core.config.agent import (
    DEFAULT_AGENT_BASE_URL,
    DEFAULT_AGENT_MODEL,
    default_agent_settings,
)
from app.domain.prompts.portfolio import contains_tracked_name

PORTFOLIO_SIZE = 10
MARKET_VISIBILITY_COUNT = 5
BRAND_DIAGNOSTIC_COUNT = 5
NVIDIA_DEFAULT_ENDPOINT = f"{DEFAULT_AGENT_BASE_URL}/chat/completions"
NVIDIA_DEFAULT_MODEL = DEFAULT_AGENT_MODEL


@dataclass(frozen=True, slots=True)
class GoldenOnboardingCase:
    """Known-brand expectation used to compare a proposed onboarding result."""

    slug: str
    brand_name: str
    primary_market: str
    website_url: str
    expected_competitors: tuple[str, ...]
    products_or_services: tuple[str, ...]
    use_cases: tuple[str, ...]
    market_terms: tuple[str, ...]


GOLDEN_ONBOARDING_CASES: tuple[GoldenOnboardingCase, ...] = (
    GoldenOnboardingCase(
        slug="flipkart-india",
        brand_name="Flipkart",
        primary_market="India",
        website_url="https://www.flipkart.com",
        expected_competitors=(
            "Amazon India",
            "Meesho",
            "JioMart",
            "Myntra",
            "Tata CLiQ",
        ),
        products_or_services=("online shopping", "electronics", "fashion"),
        use_cases=("buy products online", "compare prices", "home delivery"),
        market_terms=("india", "indian", "inr"),
    ),
    GoldenOnboardingCase(
        slug="best-less-australia",
        brand_name="Best&Less",
        primary_market="Australia",
        website_url="https://www.bestandless.com.au",
        expected_competitors=(
            "Kmart Australia",
            "BIG W",
            "Target Australia",
            "Cotton On",
            "Bonds",
        ),
        products_or_services=("affordable clothing", "kids clothing", "homewares"),
        use_cases=("family essentials", "school clothes", "budget fashion"),
        market_terms=("australia", "australian", "aud"),
    ),
    GoldenOnboardingCase(
        slug="feedonomics-united-states",
        brand_name="Feedonomics",
        primary_market="United States",
        website_url="https://feedonomics.com",
        expected_competitors=(
            "Productsup",
            "Channable",
            "DataFeedWatch",
            "GoDataFeed",
            "Rithum",
            "Lengow",
        ),
        products_or_services=(
            "product feed management",
            "marketplace integrations",
            "catalog optimization",
        ),
        use_cases=(
            "sell on marketplaces",
            "shopping ads",
            "manage product data",
        ),
        market_terms=("united states", "u.s.", "us market", "usa"),
    ),
    GoldenOnboardingCase(
        slug="canva-australia",
        brand_name="Canva",
        primary_market="Australia",
        website_url="https://www.canva.com",
        expected_competitors=(
            "Adobe Express",
            "Microsoft Designer",
            "VistaCreate",
            "Figma",
        ),
        products_or_services=(
            "graphic design",
            "presentation design",
            "social media design",
        ),
        use_cases=(
            "create marketing materials",
            "team collaboration",
            "brand templates",
        ),
        market_terms=("australia", "australian", "aud"),
    ),
    GoldenOnboardingCase(
        slug="puma-india",
        brand_name="Puma",
        primary_market="India",
        website_url="https://in.puma.com",
        expected_competitors=(
            "Adidas India",
            "Nike India",
            "Skechers India",
            "ASICS India",
            "New Balance India",
        ),
        products_or_services=("sportswear", "running shoes", "athletic footwear"),
        use_cases=("running", "training", "everyday sneakers"),
        market_terms=("india", "indian", "inr"),
    ),
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
    brand_diagnostic_count: int


@dataclass(frozen=True, slots=True)
class CompetitorEvaluation:
    precision: float
    recall: float
    missing: tuple[str, ...]
    unexpected: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NvidiaEvaluation:
    skipped: bool
    quality_score: float | None
    findings: tuple[str, ...]
    model: str


def evaluate_competitors(
    case: GoldenOnboardingCase, proposed: Iterable[str]
) -> CompetitorEvaluation:
    """Score expected-set overlap without making competitor truth production data."""
    expected = {_normalized(name): name for name in case.expected_competitors}
    actual = {_normalized(name): name for name in proposed if name.strip()}
    shared = set(expected) & set(actual)
    return CompetitorEvaluation(
        precision=len(shared) / len(actual) if actual else 0.0,
        recall=len(shared) / len(expected) if expected else 1.0,
        missing=tuple(expected[key] for key in sorted(expected.keys() - actual.keys())),
        unexpected=tuple(
            actual[key] for key in sorted(actual.keys() - expected.keys())
        ),
    )


def evaluate_portfolio(
    case: GoldenOnboardingCase, prompts: Sequence[PortfolioPrompt]
) -> PortfolioEvaluation:
    """Apply the deterministic 50/50, market-aware prompt-quality contract."""
    neutral = [prompt for prompt in prompts if prompt.cohort == "market_visibility"]
    diagnostic = [prompt for prompt in prompts if prompt.cohort == "brand_diagnostic"]
    issues = [
        *_cohort_issues(prompts, neutral, diagnostic),
        *_identity_issues(case, prompts, neutral, diagnostic),
        *_coverage_issues(case, prompts),
    ]
    return PortfolioEvaluation(
        valid=not issues,
        issues=tuple(issues),
        market_visibility_count=len(neutral),
        brand_diagnostic_count=len(diagnostic),
    )


def _cohort_issues(prompts, neutral, diagnostic):
    issues = []
    if len(prompts) != PORTFOLIO_SIZE:
        issues.append(f"expected exactly {PORTFOLIO_SIZE} prompts, got {len(prompts)}")
    if len(neutral) != MARKET_VISIBILITY_COUNT:
        issues.append("expected exactly five market_visibility prompts")
    if len(diagnostic) != BRAND_DIAGNOSTIC_COUNT:
        issues.append("expected exactly five brand_diagnostic prompts")
    if len(neutral) + len(diagnostic) != len(prompts):
        issues.append("prompt cohorts must be market_visibility or brand_diagnostic")
    return issues


def _identity_issues(case, prompts, neutral, diagnostic):
    issues = []
    normalized = [_normalized(prompt.text) for prompt in prompts]
    if len(set(normalized)) != len(normalized):
        issues.append("prompt portfolio contains duplicate questions")
    brand_terms = (case.brand_name,)
    competitor_terms = case.expected_competitors
    if any(
        contains_tracked_name(prompt.text, brand_terms)
        or contains_tracked_name(prompt.text, competitor_terms)
        for prompt in neutral
    ):
        issues.append("market_visibility prompts must be brand and competitor neutral")
    if any(
        not contains_tracked_name(prompt.text, brand_terms) for prompt in diagnostic
    ):
        issues.append("brand_diagnostic prompts must name the tracked brand")
    return issues


def _coverage_issues(case, prompts):
    combined = " ".join(_normalized(prompt.text) for prompt in prompts)
    issues = []
    if not any(_normalized(term) in combined for term in case.market_terms):
        issues.append(f"portfolio does not reflect the {case.primary_market} market")
    if not _covers_all(combined, case.products_or_services):
        issues.append("portfolio does not cover the known products or services")
    if not _covers_all(combined, case.use_cases):
        issues.append("portfolio does not cover the known buyer use cases")
    return issues


async def evaluate_with_nvidia(
    case: GoldenOnboardingCase,
    prompts: Sequence[PortfolioPrompt],
    *,
    api_key: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> NvidiaEvaluation:
    """Optionally obtain a qualitative reviewer score from NVIDIA.

    A missing key is an expected local-development condition, so this returns a
    skipped result rather than making tests or CI depend on a paid network call.
    """
    resolved_key = (
        api_key
        or os.environ.get("NVIDIA_API_KEY", "")
        or default_agent_settings.resolved_api_key
    )
    resolved_model = model or os.environ.get(
        "ONBOARDING_EVAL_NVIDIA_MODEL", NVIDIA_DEFAULT_MODEL
    )
    if not resolved_key:
        return NvidiaEvaluation(
            True, None, ("NVIDIA_API_KEY is not configured",), resolved_model
        )
    resolved_endpoint = endpoint or os.environ.get(
        "ONBOARDING_EVAL_NVIDIA_ENDPOINT", NVIDIA_DEFAULT_ENDPOINT
    )
    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Review this onboarding prompt portfolio. Return JSON only with "
                    "quality_score (0-100) and findings (short string array)."
                ),
            },
            {"role": "user", "content": _nvidia_review_input(case, prompts)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 512,
    }
    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=60.0, transport=transport) as client:
        response = await client.post(resolved_endpoint, json=payload, headers=headers)
    response.raise_for_status()
    body = response.json()
    content = body["choices"][0]["message"]["content"]
    review = json.loads(content)
    score = float(review["quality_score"])
    if not math.isfinite(score) or not 0 <= score <= 100:
        raise ValueError("NVIDIA evaluation quality_score must be finite and 0-100")
    findings = review.get("findings", [])
    if not isinstance(findings, list) or not all(
        isinstance(item, str) for item in findings
    ):
        raise ValueError("NVIDIA evaluation findings must be a string array")
    return NvidiaEvaluation(False, score, tuple(findings), resolved_model)


def _covers_all(text: str, requirements: Iterable[str]) -> bool:
    return all(_normalized(requirement) in text for requirement in requirements)


def _normalized(value: str) -> str:
    return normalize_alias(value).strip()


def _nvidia_review_input(
    case: GoldenOnboardingCase, prompts: Sequence[PortfolioPrompt]
) -> str:
    return json.dumps(
        {
            "brand": case.brand_name,
            "primary_market": case.primary_market,
            "products_or_services": case.products_or_services,
            "use_cases": case.use_cases,
            "prompts": [
                {"text": prompt.text, "cohort": prompt.cohort} for prompt in prompts
            ],
        },
        ensure_ascii=False,
    )
