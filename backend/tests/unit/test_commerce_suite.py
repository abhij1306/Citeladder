from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from app.connectors import commerce_competitors as competitor_connector
from app.connectors.commerce_competitors import CompetitorProviderUnavailable
from app.core.config.commerce_catalog import COMMERCE_IMPORT_MAX_BYTES
from app.domain.commerce import competitors
from app.domain.commerce.audit_context import (
    CommerceContextError,
    freeze_commerce_context,
)
from app.domain.commerce.competitors import (
    _discovery_query,
    _host,
    _precheck,
    _validated_results,
)
from app.domain.commerce.projector import _category_from_analysis, _crawl_values
from app.domain.commerce.prompts import _leaks_owned_identity
from app.domain.commerce.schemas import (
    CatalogEditRequest,
    CatalogImportRequest,
    CategoryEditRequest,
    CommerceTarget,
    RecommendationSpan,
)
from app.domain.commerce.service import (
    CommerceConflictError,
    _apply_edit_values,
    _import_response,
    edit_category,
)
from app.domain.commerce.shelf import (
    _first_position_rate,
    _frozen_target_ids,
    _merchant,
    _price,
    _spans,
)
from app.models.commerce import CommerceProduct


@pytest.mark.asyncio
async def test_tavily_connector_uses_bounded_locale_aware_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict = {}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"results": [{"url": "https://rival.test/p"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def post(self, url: str, *, json: dict, headers: dict) -> Response:
            seen.update(url=url, json=json, headers=headers)
            return Response()

    monkeypatch.setattr(
        competitor_connector.commerce_settings, "tavily_api_key", "secret"
    )
    monkeypatch.setattr(competitor_connector.httpx, "AsyncClient", lambda **_: Client())

    results = await competitor_connector.tavily_search("trail shoes", locale="en-AU")

    assert results == [{"url": "https://rival.test/p"}]
    assert seen["json"]["query"] == "trail shoes en-AU"
    assert seen["json"]["max_results"] == 10
    assert seen["headers"] == {"Authorization": "Bearer secret"}


@pytest.mark.asyncio
async def test_tavily_connector_is_explicitly_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(competitor_connector.commerce_settings, "tavily_api_key", "")
    with pytest.raises(CompetitorProviderUnavailable):
        await competitor_connector.tavily_search("trail shoes", locale="en-AU")


@pytest.mark.asyncio
async def test_audit_context_batches_target_evidence_queries() -> None:
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    product_id = uuid.uuid4()
    category_id = uuid.uuid4()
    product_target = SimpleNamespace(
        id=uuid.uuid4(), target_kind="product", target_id=product_id
    )
    category_target = SimpleNamespace(
        id=uuid.uuid4(), target_kind="category", target_id=category_id
    )
    product = SimpleNamespace(
        id=product_id,
        canonical_url="https://shop.test/p",
        name="Trail Runner",
        brand="Acme",
        sku=None,
        gtin=None,
        mpn=None,
        price=None,
        currency="",
        attributes={},
        field_sources={},
    )
    category = SimpleNamespace(id=category_id, name="Running shoes")
    candidate = SimpleNamespace(
        id=uuid.uuid4(),
        target_kind="category",
        target_id=category_id,
        canonical_url="https://rival.test/p",
        product_name="Rival Runner",
        brand_name="Rival",
    )

    class Rows:
        def __init__(self, rows: list) -> None:
            self.rows = rows

        def all(self) -> list:
            return self.rows

        def __iter__(self):
            return iter(self.rows)

    class Session:
        def __init__(self) -> None:
            self.scalar_results = iter(
                [
                    Rows([product_target, category_target]),
                    Rows([product]),
                    Rows([category]),
                    Rows([candidate]),
                ]
            )
            self.scalar_calls = 0
            self.execute_calls = 0

        async def scalars(self, *_: object) -> Rows:
            self.scalar_calls += 1
            return next(self.scalar_results)

        async def execute(self, *_: object) -> Rows:
            self.execute_calls += 1
            return Rows([(category_id, product)])

    session = Session()

    context = await freeze_commerce_context(
        session,  # type: ignore[arg-type]
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_ids=[uuid.uuid4(), uuid.uuid4()],
    )

    assert session.scalar_calls == 4
    assert session.execute_calls == 1
    assert context["targets"][0]["products"][0]["id"] == str(product_id)
    assert context["targets"][1]["category"]["name"] == "Running shoes"


@pytest.mark.asyncio
async def test_audit_context_rejects_a_target_without_frozen_product_evidence() -> None:
    target = SimpleNamespace(
        id=uuid.uuid4(), target_kind="product", target_id=uuid.uuid4()
    )

    class Rows:
        def __init__(self, rows: list) -> None:
            self.rows = rows

        def all(self) -> list:
            return self.rows

        def __iter__(self):
            return iter(self.rows)

    class Session:
        def __init__(self) -> None:
            self.results = iter((Rows([target]), Rows([]), Rows([])))

        async def scalars(self, *_: object) -> Rows:
            return next(self.results)

    with pytest.raises(CommerceContextError, match="no active product evidence"):
        await freeze_commerce_context(
            Session(),  # type: ignore[arg-type]
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            prompt_ids=[uuid.uuid4()],
        )


def test_recommendation_parser_preserves_order_observability() -> None:
    spans = _spans("1. Acme One $19 https://shop.test/one\n- Rival Two")
    assert [(row.rank, row.order_observable) for row in spans] == [
        (1, True),
        (None, False),
    ]
    assert _price(spans[0].text) == (19.0, "")
    assert _price(spans[0].text, locale="en-US") == (19.0, "USD")
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


def test_recommendation_spans_retain_continuation_lines() -> None:
    spans = _spans(
        "1. Trail Runner\nPrice $1.234,56 at https://shop.test/runner\n"
        "- City Runner\nAvailable in blue"
    )
    assert spans[0].text.endswith("https://shop.test/runner")
    assert spans[1].text.endswith("Available in blue")


@pytest.mark.parametrize(
    ("text", "locale", "expected"),
    [
        ("€1.234,56", "de-DE", (1234.56, "EUR")),
        ("USD 1,234.56", "en-US", (1234.56, "USD")),
        ("$1.234", "en-AU", (1234.0, "AUD")),
        ("$19.99", "en-CA", (19.99, "CAD")),
        ("$19.99", "en-GB", (19.99, "")),
        ("USD 12,34,56", "en-US", (None, "USD")),
    ],
)
def test_price_parsing_is_locale_safe(
    text: str, locale: str, expected: tuple[float | None, str]
) -> None:
    assert _price(text, locale=locale) == expected


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


def test_explicit_json_edit_clears_nullable_identifiers_to_null() -> None:
    product = cast(
        CommerceProduct,
        SimpleNamespace(canonical_url="https://shop.test/product"),
    )
    payload = CatalogEditRequest(sku=None, gtin=None, mpn=None)

    observed = _apply_edit_values(
        product, payload=payload, supplied=payload.model_fields_set
    )

    assert (product.sku, product.gtin, product.mpn) == (None, None, None)
    assert observed == {"sku": None, "gtin": None, "mpn": None}


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


@pytest.mark.asyncio
async def test_competitor_validation_is_bounded_and_records_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def verify(url: str) -> bool:
        return "dead" not in url

    monkeypatch.setattr(competitors, "_verify_url", verify)
    results = [
        {"url": "https://owned.test/p", "title": "Owned"},
        {"url": "https://rival.test/blog/guide", "title": "Guide"},
        {"url": "https://rival.test/dead", "title": "Dead"},
        {"url": "https://rival.test/p", "title": "Rival"},
        {"url": "https://rival.test/p", "title": "Duplicate"},
    ]

    outcomes, survivors = await _validated_results(results, owned_hosts={"owned.test"})

    assert [row[0] for row in survivors] == ["https://rival.test/p"]
    assert [row["validation_outcome"] for row in outcomes] == [
        "excluded_owned_domain",
        "excluded_editorial",
        "excluded_unavailable",
        "accepted",
        "excluded_duplicate",
    ]


def test_owned_host_normalization_accepts_urls_and_bare_domains() -> None:
    assert _host("https://www.Example.com/catalog") == "example.com"
    assert _host("WWW.Example.com") == "example.com"


def test_discovery_queries_distinguish_product_and_category_targets() -> None:
    target_id = uuid.uuid4()
    product = CommerceTarget(kind="product", id=target_id)
    category = CommerceTarget(kind="category", id=target_id)
    assert (
        _discovery_query(product, "Trail Runner") == "products similar to Trail Runner"
    )
    assert _discovery_query(category, "Running shoes") == (
        "leading Running shoes brands and representative products"
    )


def test_projector_omits_empty_availability_attributes() -> None:
    values = _crawl_values({"structured_data": {"product": {}}}, "https://shop.test/p")
    assert values["attributes"] == {}
    values = _crawl_values(
        {"structured_data": {"product": {"availability": ["InStock"]}}},
        "https://shop.test/p",
    )
    assert values["attributes"] == {"availability": ["InStock"]}


def test_projector_falls_back_to_visible_price_without_structured_price() -> None:
    values = _crawl_values(
        {
            "structured_data": {"product": {"price_currency": ["AUD"]}},
            "commerce": {"visible_price": "$1,299.95"},
        },
        "https://shop.test/p",
    )

    assert values["price"] == Decimal("1299.95")
    assert values["currency"] == "AUD"


@pytest.mark.parametrize(
    "visible_price",
    [
        "From $19.99",
        "$19.99 - $29.99",
        "10% off orders over $50",
        "$12,34,56",
    ],
)
def test_projector_rejects_ambiguous_visible_prices(visible_price: str) -> None:
    values = _crawl_values(
        {"commerce": {"visible_price": visible_price}}, "https://shop.test/p"
    )

    assert values["price"] is None
    assert values["currency"] == ""


@pytest.mark.asyncio
async def test_projector_refreshes_non_edited_category_name() -> None:
    category = SimpleNamespace(
        name="Old name",
        normalized_name="old name",
        role="unknown",
        field_sources={},
        source_analysis_id=None,
        projector_version="old",
    )

    class Session:
        async def scalar(self, *_: object):
            return category

        def add(self, _: object) -> None:
            raise AssertionError("existing category should be updated")

    analysis = SimpleNamespace(
        id=uuid.uuid4(), workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
    )
    await _category_from_analysis(
        Session(),  # type: ignore[arg-type]
        analysis=analysis,
        canonical_url="https://shop.test/category",
        title="New Name",
        role="leaf",
    )

    assert category.name == "New Name"
    assert category.normalized_name == "new name"
    assert category.field_sources["name"]["source_id"] == str(analysis.id)


@pytest.mark.asyncio
async def test_concurrent_category_name_conflict_is_translated() -> None:
    class UniqueViolation(Exception):
        constraint_name = "uq_commerce_category_name"

    category = SimpleNamespace(
        id=uuid.uuid4(), name="Old", normalized_name="old", field_sources={}
    )

    class Session:
        def __init__(self) -> None:
            self.results = iter((SimpleNamespace(), category, None))
            self.rolled_back = False

        async def scalar(self, *_: object):
            return next(self.results)

        def add(self, _: object) -> None:
            return None

        async def flush(self) -> None:
            return None

        async def commit(self) -> None:
            raise IntegrityError("update", {}, UniqueViolation())

        async def rollback(self) -> None:
            self.rolled_back = True

    session = Session()
    with pytest.raises(CommerceConflictError, match="category name already exists"):
        await edit_category(
            session,  # type: ignore[arg-type]
            workspace_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            category_id=category.id,
            payload=CategoryEditRequest(name="Duplicate"),
        )

    assert session.rolled_back is True


def test_structured_price_remains_authoritative_over_visible_price() -> None:
    values = _crawl_values(
        {
            "structured_data": {
                "product": {"price": ["20.00"], "price_currency": ["USD"]}
            },
            "commerce": {"visible_price": "$19.00"},
        },
        "https://shop.test/p",
    )

    assert values["price"] == 20
    assert values["currency"] == "USD"


def test_catalog_import_limit_counts_utf8_bytes() -> None:
    with pytest.raises(ValidationError):
        CatalogImportRequest(content="é" * (COMMERCE_IMPORT_MAX_BYTES // 2 + 1))


def test_import_response_tolerates_historical_null_outcomes() -> None:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        created_count=1,
        updated_count=2,
        unchanged_count=3,
        rejected_count=4,
        row_outcomes=None,
    )
    assert _import_response(row).row_outcomes == []


def test_category_prompt_leakage_does_not_protect_generic_category_name() -> None:
    context = {"target_kind": "category", "name": "Running shoes", "brand": "Acme"}
    assert _leaks_owned_identity("Which running shoes are best?", context) is False
    assert _leaks_owned_identity("Is Acme best?", context) is True
    context["target_kind"] = "product"
    assert _leaks_owned_identity("Which running shoes are best?", context) is True


def test_first_position_win_requires_an_explicit_rank_one() -> None:
    owned_at_two = SimpleNamespace(rank=2, classification="owned")
    owned_at_one = SimpleNamespace(rank=1, classification="owned")
    assert _first_position_rate([[owned_at_two], [owned_at_one]]) == 0.5


def test_frozen_target_ids_ignore_malformed_values() -> None:
    valid = "7d071880-9984-4c80-8596-f8f946030429"
    assert _frozen_target_ids({"prompt_target_ids": [valid, "bad", None]}) == [
        uuid.UUID(valid)
    ]
