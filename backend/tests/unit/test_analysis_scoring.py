"""B6 scoring parity: deterministic mention/citation/domain/fanout scoring.

Adapted from the reference ``tests/unit/test_ai_visibility_scoring.py``. Since
CiteLadder has no ``ai_visibility.constants`` module, the Best&Less project
identity is inlined here as a plain scoring-identity dict (the same shape
``project_scoring_identity`` produces + ``ScoringConfig.from_project`` consumes).
Verifies the ported scorer matches the reference behavior exactly.
"""

from __future__ import annotations

import pytest

from app.analysis.scoring import (
    ScoringConfig,
    aggregate_run,
    classify_citation,
    classify_fanout,
    score_execution,
)

# Inlined Best&Less identity (same shape as project_scoring_identity output).
BEST_AND_LESS_PROJECT: dict = {
    "brand_name": "Best&Less",
    "brand_aliases": ["Best & Less", "Best and Less"],
    "owned_domains": ["bestandless.com.au"],
    "unintended_domains": [
        "bestlesscomau.zendesk.com",
        "jsapps.co6tqo-bestlesss1-p1-public.model-t.cc.commerce.ondemand.com",
    ],
    "competitors": [
        {"name": "Kmart", "aliases": ["Kmart Australia"], "domains": ["kmart.com.au"]},
        {
            "name": "Target",
            "aliases": ["Target Australia"],
            "domains": ["target.com.au"],
        },
        {"name": "BIG W", "aliases": ["Big W", "BigW"], "domains": ["bigw.com.au"]},
    ],
    "country_code": "AU",
    "language_code": "en-AU",
    "benchmark_mode": "controlled_localized",
}


def _config() -> ScoringConfig:
    return ScoringConfig.from_project(BEST_AND_LESS_PROJECT)


def _citation(domain: str) -> dict:
    return {
        "domain": domain,
        "title": domain,
        "url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x",
    }


@pytest.mark.parametrize(
    "answer",
    [
        "You can shop at Best&Less for cheap uniforms.",
        "Try Best & Less for value.",
        "Best and Less has affordable options.",
        "BEST&LESS is a good choice.",
    ],
)
def test_brand_alias_variants_all_match(answer: str) -> None:
    score = score_execution(
        answer_text=answer,
        search_events=[],
        citations=[],
        search_used=True,
        config=_config(),
    )
    assert score["brand_mentioned"] is True
    assert score["brand_first_offset"] is not None


def test_brand_not_mentioned() -> None:
    score = score_execution(
        answer_text="Kmart and Target are the cheapest.",
        search_events=[],
        citations=[],
        search_used=True,
        config=_config(),
    )
    assert score["brand_mentioned"] is False
    assert score["competitors_mentioned"] == ["Kmart", "Target"]


def test_ambiguous_target_semantic_use_is_not_retailer_mention() -> None:
    score = score_execution(
        answer_text="Keep your target audience and target price in mind.",
        search_events=[],
        citations=[],
        search_used=False,
        config=_config(),
    )
    assert "Target" not in score["competitors_mentioned"]


def test_prompt_class_and_injection_exclude_branded_input() -> None:
    score = score_execution(
        prompt_text="Is Best&Less cheaper than Kmart?",
        answer_text="Best&Less and Kmart both sell basics.",
        search_events=[{"query": "Best&Less Kmart price comparison"}],
        citations=[],
        search_used=True,
        config=_config(),
    )
    assert score["prompt_class"] == "comparison_branded"
    assert score["prompt_contains_brand"] is True
    assert score["prompt_contains_competitor"] is True
    assert score["brand_injected_in_search"] is False


def test_resolved_url_has_domain_authority_over_title() -> None:
    classified = classify_citation(
        {
            "resolved_url": "https://www.bestandless.com.au/products/uniform",
            "redirect_url": (
                "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x"
            ),
            "title": "unrelated.example",
            "domain": "unrelated.example",
        },
        _config(),
    )
    assert classified["domain"] == "bestandless.com.au"
    assert classified["is_owned"] is True


def test_direct_annotation_url_has_domain_authority_over_title() -> None:
    classified = classify_citation(
        {
            "url": "https://www.bestandless.com.au/schoolwear",
            "title": "Schoolwear",
            "domain": "schoolwear",
        },
        _config(),
    )
    assert classified["domain"] == "bestandless.com.au"
    assert classified["is_owned"] is True


@pytest.mark.parametrize(
    "url",
    [
        "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x",
        # Subdomain of the redirect host.
        "https://eu.vertexaisearch.cloud.google.com/grounding-api-redirect/x",
        # Trailing-dot (fully qualified) form of the same host.
        "https://vertexaisearch.cloud.google.com./grounding-api-redirect/x",
        # The marker carried as a bare host.
        "https://grounding-api-redirect/xyz",
    ],
)
def test_google_redirect_url_never_becomes_the_citation_domain(url: str) -> None:
    """A redirect URL's own host must not be mistaken for the publisher."""
    classified = classify_citation(
        {"url": url, "title": "runnersworld.com", "domain": "runnersworld.com"},
        _config(),
    )
    assert classified["domain"] == "runnersworld.com"


@pytest.mark.parametrize(
    "url",
    [
        # Redirect markers in the QUERY of a real publisher URL: the publisher's
        # own hostname still wins. A substring match over the whole URL would
        # discard these and fall back to the (weaker) title/domain fields.
        "https://www.bestandless.com.au/a?ref=grounding-api-redirect",
        "https://www.bestandless.com.au/a?from=vertexaisearch.cloud.google.com",
        # The redirect host as a suffix of an unrelated registrable domain.
        "https://vertexaisearch.cloud.google.com.evil.example/a",
    ],
)
def test_publisher_url_survives_redirect_markers_outside_host_and_path(
    url: str,
) -> None:
    classified = classify_citation(
        {"url": url, "title": "unrelated.example", "domain": "unrelated.example"},
        _config(),
    )
    assert classified["domain"] != "unrelated.example"


def test_owned_domain_and_subdomain_cited() -> None:
    score = score_execution(
        answer_text="Best&Less has uniforms.",
        search_events=[],
        citations=[
            _citation("www.bestandless.com.au"),
            _citation("shop.bestandless.com.au"),
        ],
        search_used=True,
        config=_config(),
    )
    assert score["owned_domain_cited"] is True
    assert score["owned_citation_count"] == 2


def test_unintended_hosts_flagged() -> None:
    config = _config()
    for host in (
        "bestlesscomau.zendesk.com",
        "jsapps.co6tqo-bestlesss1-p1-public.model-t.cc.commerce.ondemand.com",
    ):
        score = score_execution(
            answer_text="Best&Less",
            search_events=[],
            citations=[_citation(host)],
            search_used=True,
            config=config,
        )
        assert score["unintended_domain_cited"] is True, host


def test_competitor_domains_cited() -> None:
    score = score_execution(
        answer_text="Several stores stock these.",
        search_events=[],
        citations=[_citation("kmart.com.au"), _citation("bigw.com.au")],
        search_used=True,
        config=_config(),
    )
    assert score["competitor_domains_cited"] == ["BIG W", "Kmart"]


def test_brand_and_competitor_injection_in_search_queries() -> None:
    score = score_execution(
        answer_text="Best&Less and Kmart both sell uniforms.",
        search_events=[
            {"query": "Best and Less school uniforms"},
            {"query": "Kmart school uniforms price"},
        ],
        citations=[],
        search_used=True,
        config=_config(),
    )
    assert score["brand_injected_in_search"] is True
    assert "Kmart" in score["competitors_injected_in_search"]


def test_fanout_feature_classification() -> None:
    assert "commercial" in classify_fanout("cheapest school uniforms price")
    assert "local" in classify_fanout("school uniforms near me sydney")
    assert "review" in classify_fanout("best school uniforms reviews")
    assert "service" in classify_fanout("stores with click and collect")
    assert classify_fanout("") == []


def test_aggregate_run_rates_and_stability() -> None:
    config = _config()
    executions = []
    for rep in range(3):
        executions.append(
            {
                "status": "completed",
                "prompt_index": 0,
                "prompt_text_snapshot": "school uniforms",
                "prompt_theme_snapshot": "Schoolwear",
                "citations": [_citation("bestandless.com.au")] if rep < 2 else [],
                "score": score_execution(
                    answer_text="Best&Less is great",
                    search_events=[{"query": "cheap uniforms"}],
                    citations=[_citation("bestandless.com.au")] if rep < 2 else [],
                    search_used=True,
                    config=config,
                ),
            }
        )
    for rep in range(3):
        mentioned = rep == 0
        executions.append(
            {
                "status": "completed",
                "prompt_index": 1,
                "prompt_text_snapshot": "womens basics",
                "prompt_theme_snapshot": "Womenswear",
                "citations": [],
                "score": score_execution(
                    answer_text="Best&Less basics" if mentioned else "Kmart basics",
                    search_events=[],
                    citations=[],
                    search_used=True,
                    config=config,
                ),
            }
        )

    summary = aggregate_run(executions, config)
    assert summary["total_completed"] == 6
    assert summary["brand_mention_rate"] == pytest.approx(round(4 / 6, 4))
    assert summary["owned_citation_rate"] == pytest.approx(round(2 / 6, 4))
    assert summary["mention_to_owned_citation_conversion"] == pytest.approx(
        round(2 / 4, 4)
    )
    assert summary["search_use_rate"] == 1.0

    prompt0 = next(p for p in summary["per_prompt"] if p["prompt_index"] == 0)
    assert prompt0["brand_mentioned_count"] == 3
    assert prompt0["mention_stability"] == 1.0
    assert prompt0["owned_cited_count"] == 2

    prompt1 = next(p for p in summary["per_prompt"] if p["prompt_index"] == 1)
    assert prompt1["brand_mentioned_count"] == 1
    assert prompt1["mention_stability"] == pytest.approx(round(2 / 3, 4))


def test_prompt_composite_uses_versioned_weights_and_sorts_strongest_first() -> None:
    config = _config()
    executions = [
        {
            "status": "completed",
            "prompt_index": 0,
            "logical_engine": "chatgpt",
            "score": {
                "brand_mentioned": True,
                "qualified_owned_cited": True,
                "competitors_mentioned": ["Kmart"],
            },
            "citations": [],
        },
        {
            "status": "completed",
            "prompt_index": 0,
            "logical_engine": "gemini",
            "score": {
                "brand_mentioned": True,
                "qualified_owned_cited": False,
                "competitors_mentioned": [],
            },
            "citations": [],
        },
        {
            "status": "completed",
            "prompt_index": 1,
            "logical_engine": "chatgpt",
            "score": {
                "brand_mentioned": False,
                "qualified_owned_cited": False,
                "competitors_mentioned": ["Kmart"],
            },
            "citations": [],
        },
    ]

    rows = aggregate_run(executions, config)["per_prompt"]

    assert [row["prompt_index"] for row in rows] == [0, 1]
    assert rows[0]["composite_score"] == pytest.approx(84.17)
    assert rows[0]["score_weights"] == {
        "visibility": 0.6,
        "owned_citations": 0.15,
        "competitive_position": 0.25,
    }
    assert rows[0]["per_engine_scores"] == {"chatgpt": 87.5, "gemini": 85.0}
    assert rows[0]["cross_engine_consistency"] == 0.975


def test_prompt_composite_normalizes_missing_competitive_component() -> None:
    project = {**BEST_AND_LESS_PROJECT, "competitors": []}
    config = ScoringConfig.from_project(project)
    executions = [
        {
            "status": "completed",
            "prompt_index": 0,
            "score": {
                "brand_mentioned": True,
                "qualified_owned_cited": True,
                "competitors_mentioned": [],
            },
            "citations": [],
        },
        {
            "status": "completed",
            "prompt_index": 0,
            "score": {
                "brand_mentioned": True,
                "qualified_owned_cited": False,
                "competitors_mentioned": [],
            },
            "citations": [],
        },
    ]

    prompt = aggregate_run(executions, config)["per_prompt"][0]

    assert prompt["competitive_share"] is None
    assert prompt["score_weights"] == {
        "visibility": 0.8,
        "owned_citations": 0.2,
    }
    assert prompt["composite_score"] == 90.0


def test_conversion_requires_mention_and_citation_in_same_execution() -> None:
    config = _config()
    executions = [
        {
            "status": "completed",
            "prompt_index": 0,
            "citations": [],
            "score": score_execution(
                answer_text="Best&Less is an option",
                search_events=[],
                citations=[],
                search_used=False,
                config=config,
            ),
        },
        {
            "status": "completed",
            "prompt_index": 1,
            "citations": [_citation("bestandless.com.au")],
            "score": score_execution(
                answer_text="This retailer is an option",
                search_events=[],
                citations=[_citation("bestandless.com.au")],
                search_used=False,
                config=config,
            ),
        },
    ]
    summary = aggregate_run(executions, config)
    assert summary["mention_to_owned_citation_conversion"] == 0.0


def _completed_with_usage(usage: dict) -> dict:
    config = _config()
    return {
        "status": "completed",
        "prompt_index": 0,
        "prompt_text_snapshot": "school uniforms",
        "prompt_theme_snapshot": "Schoolwear",
        "citations": [],
        "provider_metadata": {},
        "usage": usage,
        "score": score_execution(
            answer_text="Best&Less is great",
            search_events=[],
            citations=[],
            search_used=True,
            config=config,
        ),
    }


def test_aggregate_run_sums_token_usage() -> None:
    config = ScoringConfig.from_project(
        {**BEST_AND_LESS_PROJECT, "provider": "gemini", "model": "gemini-3.6-flash"}
    )
    executions = [
        _completed_with_usage(
            {"uncached_input_tokens": 10, "output_tokens": 500, "total_tokens": 800}
        ),
        _completed_with_usage(
            {"uncached_input_tokens": 20, "output_tokens": 300, "total_tokens": 600}
        ),
    ]

    summary = aggregate_run(executions, config)
    usage = summary["token_usage"]
    assert usage["input_tokens"] == 30
    assert usage["output_tokens"] == 800
    assert usage["total_tokens"] == 1400
    cost = summary["cost"]
    assert cost["grounded_requests"] == 2
    assert cost["paid_list_token_estimate_usd"] == pytest.approx(0.006045)
    assert cost["grounding_cost_if_billable_usd"] == pytest.approx(0.028)


def test_aggregate_run_token_usage_defaults_to_zero() -> None:
    config = _config()
    executions = [_completed_with_usage({})]

    summary = aggregate_run(executions, config)
    assert summary["token_usage"] == {
        "input_tokens": 0,
        "uncached_input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def test_aggregate_run_keeps_usage_when_current_route_pricing_is_unverified() -> None:
    config = ScoringConfig.from_project(
        {
            **BEST_AND_LESS_PROJECT,
            "provider": "chatgpt",
            "model": "gpt-5.6-sol",
        }
    )
    execution = _completed_with_usage(
        {
            "uncached_input_tokens": 1_000_000,
            "cached_input_tokens": 1_000_000,
            "output_tokens": 1_000_000,
            "total_tokens": 3_000_000,
        }
    )

    summary = aggregate_run([execution], config)

    assert summary["token_usage"]["cached_input_tokens"] == 1_000_000
    assert summary["cost"]["paid_list_token_estimate_usd"] is None


def test_provider_reported_cost_publishes_partial_and_missing_coverage() -> None:
    config = _config()
    partial = aggregate_run(
        [
            _completed_with_usage({"provider_cost_microusd": 250_000}),
            _completed_with_usage({}),
        ],
        config,
    )["cost"]

    assert partial["provider_reported_cost_usd"] == pytest.approx(0.25)
    assert partial["provider_reported_cost_coverage"] == {
        "reported_executions": 1,
        "total_executions": 2,
    }

    missing = aggregate_run([_completed_with_usage({})], config)["cost"]
    assert missing["provider_reported_cost_usd"] is None
    assert missing["provider_reported_cost_coverage"] == {
        "reported_executions": 0,
        "total_executions": 1,
    }


def test_share_of_voice_and_roadmap_fields() -> None:
    """SOV is populated; sentiment + avg position are present but null (B-2)."""
    config = _config()
    executions = [
        {
            "status": "completed",
            "prompt_index": 0,
            "citations": [],
            "score": score_execution(
                answer_text="Best&Less beats Kmart on value",
                search_events=[],
                citations=[],
                search_used=False,
                config=config,
            ),
        },
        {
            "status": "completed",
            "prompt_index": 1,
            "citations": [],
            "score": score_execution(
                answer_text="Kmart is cheapest",
                search_events=[],
                citations=[],
                search_used=False,
                config=config,
            ),
        },
    ]
    summary = aggregate_run(executions, config)
    sov = summary["share_of_voice"]
    # Brand mentioned once, Kmart twice -> total 3 mentions.
    assert sov["total_mentions"] == 3
    assert sov["mention_counts"]["Best&Less"] == 1
    assert sov["mention_counts"]["Kmart"] == 2
    assert sov["share"]["Kmart"] == pytest.approx(round(2 / 3, 4))
    # Roadmap metrics present but null (decision B-2, invariant 9).
    assert summary["sentiment"] is None
    assert summary["avg_position"] is None


def test_classify_citation_labels() -> None:
    """Owned / unintended / competitor / third-party classification (invariant 4)."""
    config = _config()
    assert classify_citation(_citation("bestandless.com.au"), config)["is_owned"]
    assert classify_citation(_citation("bestlesscomau.zendesk.com"), config)[
        "is_unintended"
    ]
    assert (
        classify_citation(_citation("kmart.com.au"), config)["matched_competitor"]
        == "Kmart"
    )
    third = classify_citation(_citation("wikipedia.org"), config)
    assert not third["is_owned"]
    assert not third["is_unintended"]
    assert third["matched_competitor"] is None
