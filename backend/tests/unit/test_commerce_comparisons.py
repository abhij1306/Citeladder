from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.domain.commerce.comparisons import _comparison_items


def _snapshot(
    *,
    product_id: uuid.UUID | None,
    competitor_id: uuid.UUID | None,
    mentions: int,
    rank: float,
):
    return SimpleNamespace(
        id=uuid.uuid4(),
        product_id=product_id,
        competitor_product_id=competitor_id,
        product_analyzer_version=PRODUCT_ANALYZER_VERSION,
        product_scoring_rule_version=PRODUCT_SCORING_RULE_VERSION,
        metrics={"per_engine": {"gemini": {"mention_count": mentions}}},
        mention_count=mentions,
        sov_share=0.5,
        avg_rank=rank,
        rank_distribution={"top_1": int(rank == 1)},
        price_mention_count=0,
        price_accuracy_rate=None,
        win_rate=0.5,
        price_mismatch_rate=None,
    )


def test_audit_comparison_matches_identity_and_projects_attribute_gaps() -> None:
    own_id = uuid.uuid4()
    competitor_id = uuid.uuid4()
    audit = SimpleNamespace(
        configuration={
            "products": [
                {"name": "Missing frozen identity"},
                {
                    "id": str(own_id),
                    "sku": "SUMMIT-40",
                    "name": "Summit 40L",
                    "price": 189.99,
                    "currency": "USD",
                    "attributes": {"gtin": "00850000000401"},
                },
            ],
            "competitor_products": [
                {"name": "Missing frozen identity"},
                {
                    "id": str(competitor_id),
                    "competitor_name": "TrailBlaze",
                    "name": "Alpine 45",
                    "price": 174.99,
                    "currency": "USD",
                    "attributes": {
                        "gtin": "00850000000401",
                        "material": "Recycled ripstop nylon",
                    },
                },
            ],
        }
    )
    items = _comparison_items(
        audit,
        [
            _snapshot(product_id=None, competitor_id=None, mentions=9, rank=1),
            _snapshot(product_id=own_id, competitor_id=None, mentions=1, rank=2),
            _snapshot(product_id=None, competitor_id=competitor_id, mentions=2, rank=1),
        ],
        total_analyses=4,
    )

    assert len(items) == 1
    item = items[0]
    assert item.match_reasons == ["gtin"]
    assert item.own_product.visibility_rate == 0.25
    assert item.competitor_product.visibility_rate == 0.5
    assert [(gap.field, gap.competitor_value) for gap in item.attribute_gaps] == [
        ("material", "Recycled ripstop nylon")
    ]
