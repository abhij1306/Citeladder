"""Seed-fixture contract tests (plan D3, evidence COM-1).

The demo seed's stub answer-engine adapter must stay deterministic across
processes (md5-bucketed, never Python's per-process salted ``hash()``) and
its fixture answers must keep naming the seeded catalog products WITH their
exact catalog prices inside the line-clipped windows the deterministic
product analyzer scans, so a freshly seeded project always demonstrates
non-zero Commerce Visibility data (ProductResponseAnalysis /
ProductMention / ProductMetricSnapshot rows). Pure functions + the real
analyzer — no DB, no provider calls.
"""

from __future__ import annotations

from app.analysis.product_scoring import (
    ProductScoringConfig,
    aggregate_product_run,
    score_product_execution,
)
from scripts.seed_dev_data import (
    DEMO_COMPETITOR_PRODUCT_SPEC,
    DEMO_PRODUCT_SPECS,
    PROMPT_SPECS,
    _prompt_bucket,
    _SeedStubAdapter,
)

ACTIVE_PROMPTS = [
    text for text, _intent, status, _origin in PROMPT_SPECS if status == "active"
]


def test_prompt_bucket_is_stable_and_in_range() -> None:
    for prompt in ACTIVE_PROMPTS:
        first = _prompt_bucket(prompt)
        assert 0 <= first <= 2
        # Repeated calls return the same bucket: the digest is a pure
        # function of the prompt text, so separate seed processes (where
        # the salted hash() seed would differ) agree on every outcome.
        assert _prompt_bucket(prompt) == first


def test_prompt_bucket_covers_all_outcomes() -> None:
    # The active prompt set must keep exercising every fixture variant:
    # competitor-only "lost" query, brand + competitor, and brand-only.
    buckets = {_prompt_bucket(prompt) for prompt in ACTIVE_PROMPTS}
    assert buckets == {0, 1, 2}


def _config() -> ProductScoringConfig:
    """Product-scorer config mirroring the catalog the seed freezes."""
    return ProductScoringConfig.from_project(
        {
            "products": [
                {
                    "id": f"product-{index}",
                    "sku": spec.sku,
                    "name": spec.name,
                    "aliases": [],
                    "variants": [],
                    "price": spec.price,
                    "currency": spec.currency,
                    "url": spec.url,
                    "attributes": {},
                }
                for index, spec in enumerate(DEMO_PRODUCT_SPECS)
            ],
            "competitor_products": [
                {
                    "id": "competitor-product-0",
                    "competitor_id": "competitor-0",
                    "competitor_name": "TrailBlaze Packs",
                    "name": DEMO_COMPETITOR_PRODUCT_SPEC.name,
                    "aliases": [],
                    "price": DEMO_COMPETITOR_PRODUCT_SPEC.price,
                    "currency": DEMO_COMPETITOR_PRODUCT_SPEC.currency,
                }
            ],
            "owned_domains": ["wanderlustgear.com"],
        }
    )


class _Request:
    def __init__(self, prompt: str) -> None:
        self.prompt = prompt
        self.model = "seed-model"


async def _fixture_answers() -> list[str]:
    adapter = _SeedStubAdapter(logical_engine="chatgpt", transport_provider="openai")
    return [
        (await adapter.execute(_Request(prompt))).answer_text
        for prompt in ACTIVE_PROMPTS
    ]


async def test_fixture_answers_yield_priced_product_mentions() -> None:
    config = _config()
    scores = [
        score_product_execution(answer_text=answer, config=config)
        for answer in await _fixture_answers()
    ]

    # Every execution mentions at least one catalog entry, and the "lost
    # query" bucket (no own-product mention) still exists for variety.
    assert all(
        score["own_product_mention_count"] + score["competitor_product_mention_count"]
        > 0
        for score in scores
    )
    assert any(score["own_product_mention_count"] == 0 for score in scores)

    # Every catalog entry (own + competitor) is mentioned, ranked, and
    # priced at its exact catalog price somewhere in the fixture set.
    aggregates = aggregate_product_run(scores, config)
    assert set(aggregates) == {"product-0", "product-1", "competitor-product-0"}
    for aggregate in aggregates.values():
        assert aggregate["mention_count"] > 0
        assert aggregate["sov_share"] > 0
        assert aggregate["avg_rank"] is not None
        assert aggregate["price_mention_count"] > 0
        assert aggregate["price_accuracy_rate"] == 1.0


async def test_fixture_citation_spans_match_the_answer_text() -> None:
    adapter = _SeedStubAdapter(logical_engine="chatgpt", transport_provider="openai")
    for prompt in ACTIVE_PROMPTS:
        response = await adapter.execute(_Request(prompt))
        for citation in response.citations:
            assert (
                response.answer_text[citation.start_index : citation.end_index]
                == citation.cited_text
            )
