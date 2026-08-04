"""Offline and mocked-network coverage for onboarding golden evaluation."""

from __future__ import annotations

import json

import httpx

from app.evaluations.onboarding_golden import (
    BRAND_DIAGNOSTIC_COUNT,
    GOLDEN_ONBOARDING_CASES,
    MARKET_VISIBILITY_COUNT,
    PORTFOLIO_SIZE,
    PortfolioPrompt,
    evaluate_competitors,
    evaluate_portfolio,
    evaluate_with_nvidia,
)


def _valid_portfolio(case) -> list[PortfolioPrompt]:
    market = case.primary_market
    products = case.products_or_services
    use_cases = case.use_cases
    return [
        PortfolioPrompt(
            f"What are the best {products[0]} options in {market}?",
            "market_visibility",
        ),
        PortfolioPrompt(
            f"Which {products[1]} providers serve buyers in {market}?",
            "market_visibility",
        ),
        PortfolioPrompt(
            f"How should buyers in {market} evaluate {products[2]}?",
            "market_visibility",
        ),
        PortfolioPrompt(
            f"What is the best way to {use_cases[0]} in {market}?",
            "market_visibility",
        ),
        PortfolioPrompt(
            f"Which tools help people {use_cases[1]} in {market}?",
            "market_visibility",
        ),
        PortfolioPrompt(
            f"How does {case.brand_name} support {use_cases[2]} in {market}?",
            "brand_diagnostic",
        ),
        PortfolioPrompt(
            f"Is {case.brand_name} good for {products[0]} in {market}?",
            "brand_diagnostic",
        ),
        PortfolioPrompt(
            (
                f"When should a buyer choose {case.brand_name} for "
                f"{products[1]} in {market}?"
            ),
            "brand_diagnostic",
        ),
        PortfolioPrompt(
            f"What {products[2]} strengths does {case.brand_name} offer in {market}?",
            "brand_diagnostic",
        ),
        PortfolioPrompt(
            f"Can {case.brand_name} help customers {use_cases[0]} in {market}?",
            "brand_diagnostic",
        ),
    ]


def test_golden_corpus_covers_the_agreed_five_market_cases() -> None:
    assert [case.slug for case in GOLDEN_ONBOARDING_CASES] == [
        "flipkart-india",
        "best-less-australia",
        "feedonomics-united-states",
        "canva-australia",
        "puma-india",
    ]
    assert all(case.primary_market for case in GOLDEN_ONBOARDING_CASES)
    assert all(case.expected_competitors for case in GOLDEN_ONBOARDING_CASES)


def test_portfolio_evaluation_accepts_a_balanced_market_aware_portfolio() -> None:
    for case in GOLDEN_ONBOARDING_CASES:
        result = evaluate_portfolio(case, _valid_portfolio(case))
        assert result.valid, (case.slug, result.issues)
        assert result.market_visibility_count == MARKET_VISIBILITY_COUNT
        assert result.brand_diagnostic_count == BRAND_DIAGNOSTIC_COUNT


def test_portfolio_evaluation_rejects_identity_duplicates_and_missing_coverage() -> (
    None
):
    case = GOLDEN_ONBOARDING_CASES[0]
    prompts = _valid_portfolio(case)
    prompts[0] = PortfolioPrompt(
        "Is Flipkart better than Amazon India in India?", "market_visibility"
    )
    prompts[-1] = PortfolioPrompt(prompts[-2].text, "brand_diagnostic")
    result = evaluate_portfolio(case, prompts)
    assert not result.valid
    assert "prompt portfolio contains duplicate questions" in result.issues
    assert (
        "market_visibility prompts must be brand and competitor neutral"
        in result.issues
    )


def test_competitor_evaluation_reports_overlap_and_unexpected_names() -> None:
    case = GOLDEN_ONBOARDING_CASES[0]
    result = evaluate_competitors(case, ["Amazon India", "Meesho", "Random Shop"])
    assert result.precision == 2 / 3
    assert result.recall == 2 / 5
    assert set(result.missing) == {"JioMart", "Myntra", "Tata CLiQ"}
    assert result.unexpected == ("Random Shop",)


async def test_nvidia_evaluation_skips_without_a_key(monkeypatch) -> None:
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr(
        "app.evaluations.onboarding_golden.default_agent_settings.api_key", ""
    )
    monkeypatch.setattr(
        "app.evaluations.onboarding_golden.default_agent_settings.nvidia_api_key", ""
    )
    monkeypatch.setattr(
        "app.evaluations.onboarding_golden.default_agent_settings.mistral_api_key", ""
    )
    result = await evaluate_with_nvidia(
        GOLDEN_ONBOARDING_CASES[0], _valid_portfolio(GOLDEN_ONBOARDING_CASES[0])
    )
    assert result.skipped
    assert result.quality_score is None


async def test_nvidia_evaluation_uses_json_mode_without_exposing_key() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"quality_score": 91, "findings": ["market-specific"]}
                            )
                        }
                    }
                ]
            },
        )

    case = GOLDEN_ONBOARDING_CASES[0]
    result = await evaluate_with_nvidia(
        case,
        _valid_portfolio(case),
        api_key="test-key",
        endpoint="https://mock.nvidia.test/v1/chat/completions",
        transport=httpx.MockTransport(handler),
    )
    assert not result.skipped
    assert result.quality_score == 91
    assert captured["authorization"] == "Bearer test-key"
    assert "test-key" not in json.dumps(captured["payload"])
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert len(captured["payload"]["messages"][1]["content"]) > PORTFOLIO_SIZE
