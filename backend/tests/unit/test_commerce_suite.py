from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.commerce.schemas import RecommendationSpan
from app.domain.commerce.shelf import _merchant, _price, _spans


def test_recommendation_parser_preserves_order_observability() -> None:
    spans = _spans("1. Acme One $19 https://shop.test/one\n- Rival Two")
    assert [(row.rank, row.order_observable) for row in spans] == [
        (1, True),
        (None, False),
    ]
    assert _price(spans[0].text) == (19.0, "USD")
    assert _merchant(spans[0].text) == (
        "https://shop.test/one",
        "shop.test",
    )


def test_unstructured_answer_remains_an_unordered_observation_span() -> None:
    assert _spans("Acme One is a useful option") == [
        type(_spans("")[0])(
            text="Acme One is a useful option",
            rank=None,
            order_observable=False,
        )
    ]


def test_rank_is_present_exactly_when_order_is_observable() -> None:
    RecommendationSpan(title="One", rank=1, order_observable=True)
    RecommendationSpan(title="One", rank=None, order_observable=False)
    with pytest.raises(ValidationError):
        RecommendationSpan(title="One", rank=1, order_observable=False)
    with pytest.raises(ValidationError):
        RecommendationSpan(title="One", rank=None, order_observable=True)
