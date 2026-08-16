"""Score the live onboarding pipeline against the golden corpus.

This is an opt-in developer tool, never part of CI: it makes real network
requests to customer sites and real model calls.  It exists because the corpus
is the *specification* for onboarding — the pipeline is built backwards from
what this script measures, so the baseline must be produced before any product
code changes.

Usage (from ``backend/``)::

    uv run python -m scripts.run_onboarding_eval --baseline
    uv run python -m scripts.run_onboarding_eval --case feedonomics-united-states

Credentials are read from ``infra/docker/.env`` when the process environment
does not already carry them.  Keys are never logged.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import time
from dataclasses import dataclass, field
from typing import Any

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPOSITORY = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _load_env() -> None:
    """Populate the process env from infra/docker/.env without overriding it."""
    env_path = REPOSITORY / "infra" / "docker" / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


_load_env()

from app.domain.projects.onboarding.industry_library import (  # noqa: E402
    archetype_templates,
    industry_context,
)
from app.domain.projects.onboarding.normalization import (  # noqa: E402
    normalize_website_url,
)
from app.domain.projects.onboarding.portfolio_generation import (  # noqa: E402
    generate_portfolio,
)
from app.domain.projects.onboarding.prompt_generation import (  # noqa: E402
    fallback_portfolio,
    validated_portfolio,
)
from app.domain.projects.onboarding.prompt_validation import (  # noqa: E402
    template_patterns,
)
from app.domain.projects.onboarding.research import research_brand  # noqa: E402
from app.domain.projects.onboarding.site_resolution import resolve_site  # noqa: E402
from app.evaluations.onboarding_cases import (  # noqa: E402
    COLLISION_PAIR,
    GOLDEN_ONBOARDING_CASES,
)
from app.evaluations.onboarding_golden import (  # noqa: E402
    PortfolioPrompt,
    collision_score,
    evaluate_competitors,
    evaluate_context,
    evaluate_portfolio,
    evaluate_realism,
    gold_overlap,
    template_tell,
)

# The current product makes the user pick an industry from a fixed list.  To
# give today's pipeline its best possible score we hand it the closest match
# rather than the "General" default a real user would often leave in place.
# Two cases have no honest match at all, which is itself a baseline finding.
BEST_FIT_INDUSTRY: dict[str, tuple[str, str]] = {
    "flipkart-india": ("Ecommerce", "Marketplaces"),
    "best-less-australia": ("Ecommerce", "Fashion Retail"),
    "feedonomics-united-states": ("Software", "Commerce Technology"),
    "canva-australia": ("Software", "Marketing Technology"),
    "puma-india": ("Ecommerce", "Fashion Retail"),
    "urban-company-india": ("General", ""),  # no home-services vertical exists
    "jupiter-india": ("Financial Services", "Banking"),
    "zoho-india": ("Software", "Collaboration"),
    "graza-united-states": ("Ecommerce", "Home and General Merchandise"),
    "wakefit-india": ("Ecommerce", "Home and General Merchandise"),
    "burrow-united-states": ("Ecommerce", "Home and General Merchandise"),
    # A third case the taxonomy cannot express: an implementation agency is not
    # an ecommerce business, and "Software" would restate the very confusion the
    # case exists to catch.
    "valtech-global": ("General", ""),
}

MARKET_CODES = {
    "India": "IN",
    "Australia": "AU",
    "United States": "US",
    "Global": "GLOBAL",
}


@dataclass
class CaseResult:
    slug: str
    brand_name: str
    ok: bool
    detail: str = ""
    industry: str = ""
    subindustry: str = ""
    prompts: list[PortfolioPrompt] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    elapsed_ms: int = 0


def _archetype_templates() -> list[str]:
    """Every slot template the deterministic fallback can emit."""
    return list(archetype_templates())


async def _run_case(case, *, judge_key: str, judge_model: str | None) -> CaseResult:
    started = time.perf_counter()
    industry, subindustry = BEST_FIT_INDUSTRY[case.slug]
    result = CaseResult(
        slug=case.slug,
        brand_name=case.brand_name,
        ok=False,
        industry=industry,
        subindustry=subindustry,
    )
    try:
        normalized_url, _domain = normalize_website_url(case.website_url)
        site = await resolve_site(case.website_url, normalized_url)
        selected_industry, context = industry_context(industry)
        market = MARKET_CODES[case.primary_market]
        research = await research_brand(
            brand_name=case.brand_name,
            primary_market=market,
            industry=selected_industry,
            subindustry=subindustry,
            language_code="en",
            site=site,
            industry_context=context,
        )
        profile = _as_mapping(research.profile)
        competitors = [_competitor_name(entry) for entry in research.competitors]
        competitors = [name for name in competitors if name]
        # Generation is inside the guard on purpose: `validated_portfolio`
        # raises when its own deterministic fallback fails the quality gate,
        # which in production aborts project creation outright.
        model_prompts, _shortfall = await generate_portfolio(
            brand_name=case.brand_name,
            primary_market=market,
            profile=profile,
            competitors=competitors,
        )
        prompts = _generate_portfolio(
            case, context, profile, competitors, market, model_prompts
        )
        result.prompts = [
            PortfolioPrompt(text=str(item["text"]), cohort=str(item["cohort"]))
            for item in prompts
        ]
        result.metrics = await _score(
            case,
            result.prompts,
            profile=profile,
            competitors=competitors,
            research_topics=list(research.topics),
            warnings=list(research.warnings),
            judge_key=judge_key,
            judge_model=judge_model,
        )
        result.issues = evaluate_portfolio(case, result.prompts).issues
        result.ok = True
    except Exception as exc:  # noqa: BLE001 - the harness reports, never aborts
        result.ok = False
        result.detail = f"{type(exc).__name__}: {exc}"
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


def _competitor_name(entry: Any) -> str:
    """Competitors arrive as dicts once verified, as models before that."""
    if isinstance(entry, dict):
        return str(entry.get("name") or "").strip()
    return str(getattr(entry, "name", "") or "").strip()


def _as_mapping(value: Any) -> dict[str, Any]:
    """Research results carry either the Pydantic profile or its dumped dict."""
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    return dict(dump()) if callable(dump) else {}


def _generate_portfolio(
    case, context, profile, competitors, market, model_prompts
) -> list[dict]:
    """Reproduce `_prepare_confirmed_portfolio` without requiring a database."""
    products = [str(item) for item in (profile.get("products_services") or [])]
    context_terms = [
        str(profile.get("target_audience") or ""),
        *products,
        *(context.get("use_cases") or []),
        *(context.get("topics") or []),
    ]
    fallback = fallback_portfolio(
        primary_market=market,
        industry=BEST_FIT_INDUSTRY[case.slug][0],
        industry_context=context,
        products_services=products,
        target_audience=str(profile.get("target_audience") or ""),
        price_tier=str(profile.get("price_tier") or "unknown"),
    )
    return validated_portfolio(
        model_prompts,
        fallback_prompts=fallback,
        brand_name=case.brand_name,
        primary_market=market,
        competitor_terms=competitors,
        context_terms=context_terms,
        banned_patterns=template_patterns(archetype_templates()),
    )


async def _score(
    case,
    prompts: list[PortfolioPrompt],
    *,
    profile,
    competitors: list[str],
    research_topics: list[str],
    warnings: list[str],
    judge_key: str,
    judge_model: str | None,
) -> dict[str, Any]:
    competitor_eval = evaluate_competitors(case, competitors)
    context_eval = evaluate_context(
        case,
        {
            "category": str(profile.get("category") or ""),
            "category_terms": [
                *(profile.get("category_terms") or []),
                *research_topics,
            ],
            "business_model": str(profile.get("business_model") or ""),
            "secondary_business_models": profile.get("secondary_business_models") or [],
            "market_scope": str(profile.get("market_scope") or ""),
            "buyer_type": str(profile.get("business_type") or ""),
        },
    )
    realism = await evaluate_realism(
        case, prompts, api_key=judge_key, model=judge_model
    )
    gold = [*case.gold_buyer_prompts, *case.gold_branded_prompts]
    portfolio = evaluate_portfolio(case, prompts)
    return {
        "prompt_count": len(prompts),
        "template_tell": round(template_tell(prompts, _archetype_templates()), 3),
        "gold_overlap": round(gold_overlap(prompts, gold), 3),
        "buyer_realism": None if realism.skipped else round(realism.score or 0.0, 1),
        "machine_detection_rate": realism.machine_detection_rate,
        "false_positive_rate": realism.false_positive_rate,
        "judge_model": realism.model,
        "judge_detail": realism.detail,
        "resolved_category": str(profile.get("category") or ""),
        "knowledge_strength": str(profile.get("knowledge_strength") or ""),
        "category_match": context_eval.category_match,
        "facet_accuracy": round(context_eval.facet_accuracy, 3),
        "jtbd_coverage": round(context_eval.jtbd_coverage, 3),
        "context_mismatches": list(context_eval.mismatches),
        "competitor_precision": round(competitor_eval.precision, 3),
        "competitor_recall": round(competitor_eval.recall, 3),
        "competitors_found": competitors,
        "competitors_missing": list(competitor_eval.missing),
        "portfolio_valid": portfolio.valid,
        "portfolio_issues": list(portfolio.issues),
        "branded_count": portfolio.branded_count,
        "market_signal_rate": round(portfolio.market_signal_rate, 3),
        "offering_coverage": round(portfolio.offering_coverage, 3),
        "use_case_coverage": round(portfolio.use_case_coverage, 3),
        "research_warnings": warnings,
    }


def _markdown(results: list[CaseResult], collision: float | None) -> str:
    lines = [
        "# Onboarding baseline scorecard",
        "",
        "| case | prompts | realism | template_tell | gold_overlap | "
        "category | facets | comp_recall | valid |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        if not result.ok:
            lines.append(f"| {result.slug} | FAILED: {result.detail} | | | | | | | |")
            continue
        metrics = result.metrics
        realism = metrics.get("buyer_realism")
        lines.append(
            f"| {result.slug} | {metrics['prompt_count']} | "
            f"{'skipped' if realism is None else realism} | "
            f"{metrics['template_tell']} | {metrics['gold_overlap']} | "
            f"{'yes' if metrics['category_match'] else 'NO'} | "
            f"{metrics['facet_accuracy']} | {metrics['competitor_recall']} | "
            f"{'yes' if metrics['portfolio_valid'] else 'no'} |"
        )
    if collision is not None:
        lines += [
            "",
            f"**cross_brand_collision** ({COLLISION_PAIR[0]} vs "
            f"{COLLISION_PAIR[1]}): **{collision:.3f}** "
            "(1.0 = identical neutral prompts)",
        ]
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="run every case")
    parser.add_argument("--case", action="append", default=[], help="run one slug")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--out", default=None, help="write JSON results here")
    args = parser.parse_args()

    if args.case:
        selected = [case for case in GOLDEN_ONBOARDING_CASES if case.slug in args.case]
        unknown = set(args.case) - {case.slug for case in selected}
        if unknown:
            parser.error(f"unknown case slug(s): {', '.join(sorted(unknown))}")
    elif args.baseline:
        selected = list(GOLDEN_ONBOARDING_CASES)
    else:
        # Every case is a live crawl plus several model calls, so the full run is
        # opt-in rather than what you get for forgetting an argument.
        parser.error("pass --baseline for the whole corpus, or --case <slug>")

    judge_key = os.environ.get("GROQ_API_KEY", "")
    if not judge_key:
        print("! GROQ_API_KEY absent - buyer_realism will be skipped", file=sys.stderr)

    results: list[CaseResult] = []
    for case in selected:
        print(f"-> {case.slug} ...", file=sys.stderr, flush=True)
        result = await _run_case(
            case, judge_key=judge_key, judge_model=args.judge_model
        )
        status = "ok" if result.ok else f"FAILED ({result.detail})"
        print(f"   {status} in {result.elapsed_ms}ms", file=sys.stderr, flush=True)
        results.append(result)

    by_slug = {result.slug: result for result in results}
    collision = None
    left, right = COLLISION_PAIR
    cases_by_slug = {case.slug: case for case in GOLDEN_ONBOARDING_CASES}
    if left in by_slug and right in by_slug and by_slug[left].ok and by_slug[right].ok:
        collision = collision_score(
            by_slug[left].prompts,
            by_slug[right].prompts,
            left_market_terms=cases_by_slug[left].market_terms,
            right_market_terms=cases_by_slug[right].market_terms,
        )

    payload = {
        "cases": [
            {
                "slug": r.slug,
                "brand": r.brand_name,
                "ok": r.ok,
                "detail": r.detail,
                "industry": f"{r.industry}/{r.subindustry}".rstrip("/"),
                "elapsed_ms": r.elapsed_ms,
                "issues": list(r.issues),
                "prompts": [{"text": p.text, "cohort": p.cohort} for p in r.prompts],
                "metrics": r.metrics,
            }
            for r in results
        ],
        "cross_brand_collision": collision,
    }
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(_markdown(results, collision))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
