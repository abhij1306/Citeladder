"""Offline coverage for the onboarding golden corpus and its scoring."""

from __future__ import annotations

import json

import httpx

from app.core.config.brand_discovery import SERVICE_BUSINESS_MODELS
from app.domain.prompts.portfolio import contains_tracked_name
from evaluations.onboarding_cases import COLLISION_PAIR, GOLDEN_ONBOARDING_CASES
from evaluations.onboarding_corpus import (
    BUSINESS_MODELS,
    BUYER_REGISTERS,
    BUYER_TYPES,
    KNOWLEDGE_STRENGTHS,
    MARKET_SCOPES,
)
from evaluations.onboarding_golden import (
    CASES_BY_SLUG,
    PORTFOLIO_MAX,
    PORTFOLIO_MIN,
    PortfolioPrompt,
    collision_score,
    evaluate_competitors,
    evaluate_context,
    evaluate_portfolio,
    evaluate_realism,
    gold_overlap,
    template_tell,
)

FEEDONOMICS = CASES_BY_SLUG["feedonomics-united-states"]


def _valid_portfolio(case) -> list[PortfolioPrompt]:
    """A portfolio built from the case's own gold prompts, so it should pass."""
    neutral = [
        PortfolioPrompt(text, "market_visibility")
        for text in case.gold_buyer_prompts[:5]
    ]
    relevant = [
        PortfolioPrompt(text, "brand_relevant")
        for text in case.gold_buyer_prompts[5:10]
    ]
    branded = [
        PortfolioPrompt(text, "brand_diagnostic")
        for text in case.gold_branded_prompts[:5]
    ]
    return [*neutral, *relevant, *branded]


def test_corpus_covers_the_agreed_cases() -> None:
    # Membership is the contract, not ordering: the cases are assembled from the
    # commerce and services modules, so their order follows that split rather
    # than the sequence they were first written in. Sorted comparison still
    # fails on a missing, added, or duplicated case.
    slugs = [case.slug for case in GOLDEN_ONBOARDING_CASES]
    assert sorted(slugs) == sorted(
        [
            "flipkart-india",
            "best-less-australia",
            "feedonomics-united-states",
            "canva-australia",
            "puma-india",
            "urban-company-india",
            "jupiter-india",
            "zoho-india",
            "graza-united-states",
            "wakefit-india",
            "burrow-united-states",
            "valtech-global",
        ]
    )
    assert len(set(slugs)) == len(slugs)
    assert all(slug in CASES_BY_SLUG for slug in COLLISION_PAIR)


def test_corpus_covers_service_businesses_not_only_product_sellers() -> None:
    """A corpus of product sellers cannot catch a services firm read as a vendor.

    The pipeline shipped an ecommerce *agency* described as an ecommerce
    *platform*, with the platforms it implements returned as its competitors.
    Nothing in eleven cases could have failed on that, because every one of them
    sold a product.
    """
    models = {case.business_model for case in GOLDEN_ONBOARDING_CASES}
    assert models & SERVICE_BUSINESS_MODELS, (
        "no golden case is a service business, so agency/vendor confusion "
        "cannot be measured"
    )


def test_every_case_uses_the_closed_facet_vocabularies() -> None:
    for case in GOLDEN_ONBOARDING_CASES:
        assert case.business_model in BUSINESS_MODELS, case.slug
        assert case.market_scope in MARKET_SCOPES, case.slug
        assert case.buyer_type in BUYER_TYPES, case.slug
        assert case.knowledge_strength in KNOWLEDGE_STRENGTHS, case.slug
        assert case.buyer_register in BUYER_REGISTERS, case.slug


def test_every_case_carries_usable_gold_prompt_sets() -> None:
    for case in GOLDEN_ONBOARDING_CASES:
        assert len(case.gold_buyer_prompts) >= 10, case.slug
        assert len(case.gold_branded_prompts) >= 5, case.slug
        # Checked with the product's own identity rule, not an ad-hoc substring
        # test, so the corpus is validated against the gate it will be scored by.
        brand_terms = (case.brand_name,)
        assert not any(
            contains_tracked_name(prompt, brand_terms)
            for prompt in case.gold_buyer_prompts
        ), f"{case.slug}: a neutral gold prompt names the brand"
        assert all(
            contains_tracked_name(prompt, brand_terms)
            for prompt in case.gold_branded_prompts
        ), f"{case.slug}: a branded gold prompt does not name the brand"


def test_collision_pair_shares_a_category_but_not_a_market() -> None:
    left, right = (CASES_BY_SLUG[slug] for slug in COLLISION_PAIR)
    assert left.business_model == right.business_model
    assert left.primary_market != right.primary_market


def test_portfolio_evaluation_accepts_gold_derived_portfolios() -> None:
    result = evaluate_portfolio(FEEDONOMICS, _valid_portfolio(FEEDONOMICS))
    assert result.valid, result.issues
    assert result.market_visibility_count == 5
    assert result.brand_relevant_count == 5
    assert result.branded_count == 5
    assert result.market_signal_rate > 0


def test_portfolio_counts_are_bounded_not_exact() -> None:
    """An honest short portfolio passes; padding beyond the ceiling does not."""
    short = _valid_portfolio(FEEDONOMICS)[:PORTFOLIO_MIN]
    assert len(evaluate_portfolio(FEEDONOMICS, short).issues) == 0

    too_many = _valid_portfolio(FEEDONOMICS) + [
        PortfolioPrompt("one prompt too many for the ceiling", "market_visibility")
    ]
    issues = evaluate_portfolio(FEEDONOMICS, too_many).issues
    assert any(str(PORTFOLIO_MAX) in issue for issue in issues)


def test_portfolio_rejects_duplicates_and_misplaced_identity() -> None:
    prompts = _valid_portfolio(FEEDONOMICS)
    prompts[0] = PortfolioPrompt("is feedonomics worth the price", "market_visibility")
    prompts[-1] = PortfolioPrompt(prompts[-2].text, "brand_diagnostic")
    result = evaluate_portfolio(FEEDONOMICS, prompts)
    assert not result.valid
    assert "prompt portfolio contains duplicate questions" in result.issues
    assert "neutral prompts must be brand and competitor neutral" in result.issues


def test_branded_cohort_must_actually_name_the_brand() -> None:
    prompts = _valid_portfolio(FEEDONOMICS)
    prompts[-1] = PortfolioPrompt("best feed tool for agencies", "brand_diagnostic")
    result = evaluate_portfolio(FEEDONOMICS, prompts)
    assert "branded prompts must name the brand" in result.issues


def test_competitor_evaluation_reports_overlap_and_unexpected_names() -> None:
    case = CASES_BY_SLUG["flipkart-india"]
    result = evaluate_competitors(case, ["Amazon India", "Meesho", "Random Shop"])
    assert result.precision == 2 / 3
    assert result.recall == 2 / 5
    assert set(result.missing) == {"JioMart", "Myntra", "Tata CLiQ"}
    assert result.unexpected == ("Random Shop",)


def test_competitor_matching_ignores_market_and_category_suffixes() -> None:
    """ "Nike" and "Nike India" are one company; "Gold" and "Fat Gold" are not."""
    case = CASES_BY_SLUG["puma-india"]
    result = evaluate_competitors(case, ["Nike", "Adidas", "Reebok"])
    # Exact matching scored this 0.0 and reported a correct discovery as a miss.
    assert result.recall == 2 / 5
    assert "Nike India" not in result.missing
    assert "Adidas India" not in result.missing

    graza = CASES_BY_SLUG["graza-united-states"]
    decoy = evaluate_competitors(graza, ["Gold"])
    assert decoy.recall == 0.0, "a bare token must not satisfy a two-word brand"


def test_template_tell_detects_slot_filled_prompts() -> None:
    templates = ["Which {category} options can help my team with {use_case}?"]
    prompts = [
        PortfolioPrompt(
            "Which analytics software options can help my team with automating "
            "workflows?",
            "market_visibility",
        ),
        PortfolioPrompt("best mattress for back pain india", "market_visibility"),
    ]
    assert template_tell(prompts, templates) == 0.5
    assert template_tell(prompts, []) == 0.0


def test_template_sentinel_survives_alias_normalization() -> None:
    """Regression: a control-character sentinel was stripped, silencing the metric."""
    templates = ["What should I consider before choosing {category} in {market}?"]
    prompt = PortfolioPrompt(
        "What should I consider before choosing mattresses in India?",
        "brand_relevant",
    )
    assert template_tell([prompt], templates) == 1.0


def test_category_match_requires_more_than_a_shared_generic_word() -> None:
    """'software' must not satisfy 'feed management software'."""
    loose = evaluate_context(FEEDONOMICS, {"category": "Software"})
    assert not loose.category_match

    exact = evaluate_context(FEEDONOMICS, {"category": "product feed management"})
    assert exact.category_match


def test_context_evaluation_scores_facets_and_reports_mismatches() -> None:
    result = evaluate_context(
        FEEDONOMICS,
        {
            "category": "product feed management platform",
            "business_model": "b2b_saas",
            "market_scope": "global",
            "buyer_type": "consumer",
            "category_terms": ["product feed management", "marketplace integrations"],
        },
    )
    assert result.facet_accuracy == 2 / 3
    assert any("buyer_type" in mismatch for mismatch in result.mismatches)
    assert result.jtbd_coverage > 0.0


def test_collision_score_ignores_the_market_token() -> None:
    """Swapping only the country name is one portfolio, not two."""
    left = [PortfolioPrompt("where can i buy homewares in India", "market_visibility")]
    right = [
        PortfolioPrompt(
            "where can i buy homewares in United States", "market_visibility"
        )
    ]
    assert collision_score(left, right) < 1.0
    assert (
        collision_score(
            left,
            right,
            left_market_terms=("india",),
            right_market_terms=("united states",),
        )
        == 1.0
    )


def test_gold_overlap_rewards_talking_about_the_same_things() -> None:
    gold = ["best product feed management software for ecommerce"]
    close = [PortfolioPrompt("best product feed management software", "brand_relevant")]
    far = [PortfolioPrompt("cheap school uniforms australia", "brand_relevant")]
    assert gold_overlap(close, gold) > gold_overlap(far, gold)
    assert gold_overlap([], gold) == 0.0


async def test_realism_evaluation_skips_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    result = await evaluate_realism(FEEDONOMICS, _valid_portfolio(FEEDONOMICS))
    assert result.skipped
    assert result.score is None


async def test_realism_scores_perfect_discrimination_as_zero() -> None:
    """Judge catches every generated prompt and no gold prompt."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        payload = json.loads(request.content)
        captured["payload"] = payload
        listed = json.loads(payload["messages"][1]["content"])["prompts"]
        generated = {
            item["id"] for item in listed if item["text"] in {p.text for p in prompts}
        }
        labels = [
            {
                "id": item["id"],
                "source": "machine" if item["id"] in generated else "human",
            }
            for item in listed
        ]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"labels": labels})}}]
            },
        )

    # Prompts absent from the gold set, so "generated" is unambiguous.
    prompts = [
        PortfolioPrompt(
            f"which zzz option number {index} should i consider", "brand_relevant"
        )
        for index in range(5)
    ]
    result = await evaluate_realism(
        FEEDONOMICS,
        prompts,
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    assert not result.skipped
    assert result.score == 0.0
    assert result.machine_detection_rate == 1.0
    assert result.false_positive_rate == 0.0
    assert captured["authorization"] == "Bearer test-key"
    assert "test-key" not in json.dumps(captured["payload"])
    assert captured["payload"]["response_format"] == {"type": "json_object"}


async def test_realism_cancels_a_judge_that_calls_everything_machine() -> None:
    """A biased judge must not be able to drive the score to zero."""

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        listed = json.loads(payload["messages"][1]["content"])["prompts"]
        labels = [{"id": item["id"], "source": "machine"} for item in listed]
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": json.dumps({"labels": labels})}}]
            },
        )

    result = await evaluate_realism(
        FEEDONOMICS,
        _valid_portfolio(FEEDONOMICS),
        api_key="test-key",
        transport=httpx.MockTransport(handler),
    )
    assert result.machine_detection_rate == 1.0
    assert result.false_positive_rate == 1.0
    assert result.score == 100.0
