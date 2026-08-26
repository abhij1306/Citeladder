from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from app.domain.commerce.competitors import _precheck
from app.domain.commerce.schemas import CatalogEditRequest, RecommendationSpan
from app.domain.commerce.service import CommerceConflictError, _apply_edit_values
from app.domain.commerce.shelf import _frozen_target_ids, _merchant, _price, _spans
from app.models.commerce import CommerceProduct


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


def test_explicit_json_edit_clears_keep_column_types() -> None:
    product = cast(
        CommerceProduct,
        SimpleNamespace(canonical_url="https://shop.test/product"),
    )
    payload = CatalogEditRequest(variants=None, attributes=None, price=None)

    observed = _apply_edit_values(
        product, payload=payload, supplied=payload.model_fields_set
    )

    assert product.variants == []
    assert product.attributes == {}
    assert product.price is None
    assert observed == {"variants": [], "attributes": {}, "price": None}


def test_lifecycle_state_cannot_be_cleared() -> None:
    product = cast(
        CommerceProduct,
        SimpleNamespace(canonical_url="https://shop.test/product"),
    )
    payload = CatalogEditRequest(lifecycle_state=None)

    with pytest.raises(CommerceConflictError):
        _apply_edit_values(product, payload=payload, supplied=payload.model_fields_set)


def test_nested_collection_product_url_is_not_excluded() -> None:
    checked = _precheck(
        {
            "url": "https://rival.test/collections/shoes/products/trail-runner",
            "title": "Trail Runner",
        },
        owned_hosts=set(),
    )

    assert checked is not None


def test_frozen_target_ids_ignore_malformed_values() -> None:
    valid = "7d071880-9984-4c80-8596-f8f946030429"
    assert _frozen_target_ids({"prompt_target_ids": [valid, "bad", None]}) == [
        uuid.UUID(valid)
    ]
