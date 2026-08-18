"""Shopify Admin GraphQL API client (commerce suite).

Greenfield: the Admin **GraphQL** API is the ONLY Shopify surface — there is
no REST compatibility or fallback path here, in config, or in tests.

- Endpoints are per-shop (``https://{shop}.myshopify.com/...``) and built
  ONLY through the config-owned validated builders; every URL is checked
  against the approved-host guard before a request is issued (SSRF policy).
  ``property_ref`` (the canonical shop host) is re-validated before every
  request.
- Auth is the offline Admin API access token sent as the
  ``X-Shopify-Access-Token`` header (NEVER ``Authorization: Bearer``). The
  token passes through this module but is never logged (invariant 6):
  raised errors carry only HTTP status codes, config-owned error tokens,
  and the first length-capped GraphQL error message.
- Every GraphQL query text is config-owned (invariant 1): this module reads
  ``SHOPIFY_GRAPHQL_*`` and never declares query text of its own. Paging is
  cursor-based: the worker injects the resume cursor via
  ``set_page_cursor`` (sent as the GraphQL variable ``after``); the worker
  owns paging/resume exactly as for the offset providers.
- Top-level GraphQL ``errors`` on an HTTP 200 are provider failures
  (non-retryable — a deterministic rejection), classified WITHOUT
  persisting or surfacing the unrestricted error payload.
- Nested connections (product ``variants``, order ``lineItems``) are
  EXHAUSTED via paced continuation queries before the outer page returns —
  variants/line items are never truncated silently; malformed nested
  ``pageInfo`` fails the call.

**Layering:** the connector performs STRUCTURAL normalization only. Product
rows are already PII-free (title/handle/vendor/type/price/sku/barcode) and
the worker persists them directly; order nodes are returned structurally
normalized but RAW and the WORKER runs the domain sanitizer before the
immutable artifact write — this module never imports ``app.domain.*``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from app.connectors.integrations._http import (
    IntegrationApiError,
    RequestPacer,
    assert_approved_url,
    capped_error_text,
    classify_status,
    parse_retry_after,
)
from app.core.config.integrations_contracts import (
    ERROR_PROVIDER_API,
)
from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_ORDERS,
    DATASET_SHOPIFY_PRODUCTS,
    INTEGRATION_DATASET_TEMPLATES,
    SHOPIFY_GRAPHQL_CONNECTION_PROBE,
    SHOPIFY_GRAPHQL_ORDER_LINE_ITEMS,
    SHOPIFY_GRAPHQL_ORDERS,
    SHOPIFY_GRAPHQL_PRODUCT_VARIANTS,
    SHOPIFY_GRAPHQL_PRODUCTS,
    IntegrationDatasetTemplate,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
    normalize_shopify_shop_domain,
    shopify_admin_graphql_url,
)


class ShopifyApiError(IntegrationApiError):
    """A Shopify Admin GraphQL call failed; carries a config-owned token."""


@dataclass(frozen=True)
class ShopifyPage:
    """One fetched outer page (the worker/derivation contract).

    ``payload`` is the document the immutable import artifact persists +
    hashes — products: ``{"rows": [...], "pageInfo": {...}}``; orders (raw,
    worker-sanitized before the write): ``{"orders": [...], "pageInfo":
    {...}}``. ``pageInfo`` is the normalized outer ``{"hasNextPage": bool,
    "endCursor": str | None}`` pair the worker validates for the
    cursor-resume protocol. ``raw_row_count`` is the number of OUTER
    product/order nodes BEFORE row validation dropped any malformed rows.
    """

    payload: dict
    rows: tuple[dict, ...]
    raw_row_count: int


def _shopify_template(
    dataset: str, dimensions: Sequence[str]
) -> IntegrationDatasetTemplate:
    """Resolve + validate the config-owned Shopify dataset template.

    The Shopify feeds declare NO report dimensions/metrics; an unknown
    dataset id or a non-empty dimension request fails loud — the config
    templates are the only dataset vocabulary.
    """
    template = INTEGRATION_DATASET_TEMPLATES.get(dataset)
    if (
        template is None
        or template.provider != INTEGRATION_PROVIDER_SHOPIFY
        or tuple(template.dimensions) != tuple(dimensions)
    ):
        raise ShopifyApiError(
            f"no Shopify dataset template {dataset!r} for dimensions "
            f"{tuple(dimensions)!r}",
            error_code=ERROR_PROVIDER_API,
        )
    return template


def _malformed(detail: str) -> ShopifyApiError:
    """Malformed provider data: deterministic, never retryable."""
    return ShopifyApiError(
        f"Shopify GraphQL returned malformed data ({detail})",
        error_code=ERROR_PROVIDER_API,
        retryable=False,
    )


def _validated_page_info(value: object, *, label: str) -> dict[str, Any]:
    """Validate a ``pageInfo`` object: bool flag + cursor when continuing.

    ``hasNextPage`` must be a JSON bool; ``hasNextPage=true`` REQUIRES a
    non-empty ``endCursor`` (a continuation with no cursor would either
    loop on the same page or silently truncate — both are malformed
    provider data, never guessed).
    """
    if not isinstance(value, dict):
        raise _malformed(f"{label} pageInfo is missing or not an object")
    has_next = value.get("hasNextPage")
    if not isinstance(has_next, bool):
        raise _malformed(f"{label} pageInfo.hasNextPage is not a bool")
    end_cursor = value.get("endCursor")
    if end_cursor is not None and not isinstance(end_cursor, str):
        raise _malformed(f"{label} pageInfo.endCursor is not a string")
    if has_next and not end_cursor:
        raise _malformed(f"{label} pageInfo hasNextPage without an endCursor")
    return {"hasNextPage": has_next, "endCursor": end_cursor or None}


def _str_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _catalog_row(product: dict, variant: object, *, currency: str) -> dict | None:
    """Normalize ONE safe catalog row from a product node + variant node.

    PII-free by selection (title/handle/vendor/type/status/price/sku/
    barcode only). A node missing its opaque provider id is malformed and
    dropped, never guessed; every other field coerces to a safe default.
    """
    if not isinstance(variant, dict):
        return None
    product_ref = _str_or_empty(product.get("id"))
    variant_ref = _str_or_empty(variant.get("id"))
    if not product_ref or not variant_ref:
        return None
    inventory = variant.get("inventoryQuantity")
    return {
        "product_ref": product_ref,
        "variant_ref": variant_ref,
        "sku": _str_or_empty(variant.get("sku")),
        "barcode": _str_or_empty(variant.get("barcode")),
        "title": _str_or_empty(product.get("title")),
        "variant_title": _str_or_empty(variant.get("title")),
        "description": _str_or_empty(product.get("description")),
        "vendor": _str_or_empty(product.get("vendor")),
        "product_type": _str_or_empty(product.get("productType")),
        "status": _str_or_empty(product.get("status")),
        "url": _str_or_empty(product.get("onlineStoreUrl")),
        # The provider's price is a decimal STRING — preserved verbatim so
        # no float rounding ever enters the catalog.
        "price": _str_or_empty(variant.get("price")),
        "currency": currency,
        "inventory_quantity": inventory if isinstance(inventory, int) else None,
        "updated_at": _str_or_empty(variant.get("updatedAt")),
    }


class ShopifyClient:
    """Shopify Admin GraphQL client with pacing + injected transport.

    ``transport`` is the test seam (``httpx.MockTransport`` or any
    ``httpx.AsyncBaseTransport``); production passes nothing and the client
    uses the real network.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._pacer = RequestPacer()
        self._page_cursor: str | None = None

    def set_page_cursor(self, cursor: str | None) -> None:
        """Inject the resume cursor for the NEXT outer-page call.

        The worker's narrow cursor-resume seam: the value is sent as the
        GraphQL variable ``after`` on the next ``query_search_analytics``
        call. ``None`` requests the first page.
        """
        self._page_cursor = cursor

    async def _graphql(
        self,
        url: str,
        *,
        access_token: str,
        query: str,
        variables: dict[str, Any],
        label: str,
    ) -> dict:
        """POST one GraphQL operation and return its ``data`` object.

        Paced, SSRF-guarded, token-headered. A non-200 response classifies
        through the shared taxonomy; a top-level ``errors`` array on HTTP
        200 is a NON-retryable provider failure carrying only the first
        length-capped message — the unrestricted error payload is never
        persisted or surfaced.
        """
        assert_approved_url(url, label=label, error_type=ShopifyApiError)
        await self._pacer.wait(
            integration_settings.requests_per_minute(INTEGRATION_PROVIDER_SHOPIFY)
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=integration_settings.sync_request_timeout_seconds,
            ) as client:
                response = await client.post(
                    url,
                    json={"query": query, "variables": variables},
                    # Shopify's offline Admin API token header — NEVER a
                    # Bearer token. Set per-request, never logged.
                    headers={"X-Shopify-Access-Token": access_token},
                )
        except httpx.HTTPError as exc:
            raise ShopifyApiError(
                f"{label} request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            error_code, retryable = classify_status(response.status_code)
            raise ShopifyApiError(
                f"{label} returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=parse_retry_after(response),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ShopifyApiError(
                f"{label} returned a non-JSON body",
                error_code=ERROR_PROVIDER_API,
            ) from exc
        if not isinstance(body, dict):
            raise ShopifyApiError(
                f"{label} returned an unexpected body",
                error_code=ERROR_PROVIDER_API,
            )
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            message = (
                capped_error_text(first.get("message"))
                if isinstance(first, dict)
                else capped_error_text(first)
            )
            suffix = f": {message}" if message else ""
            raise ShopifyApiError(
                f"{label} returned GraphQL errors{suffix}",
                error_code=ERROR_PROVIDER_API,
                retryable=False,
            )
        data = body.get("data")
        if not isinstance(data, dict):
            raise _malformed(f"{label} response has no data object")
        return data

    async def _exhaust_nested(
        self,
        url: str,
        *,
        access_token: str,
        query: str,
        owner_key: str,
        owner_id: str,
        connection_key: str,
        first_nodes: list,
        first_page_info: object,
        label: str,
    ) -> list:
        """Exhaust a nested connection (variants/lineItems) to its end.

        Returns the first page's nodes plus every continuation page's
        nodes. Every continuation call is paced and its nested ``pageInfo``
        strictly validated — a nested connection is NEVER truncated
        silently.
        """
        nodes = list(first_nodes)
        page_info = _validated_page_info(first_page_info, label=label)
        while page_info["hasNextPage"]:
            data = await self._graphql(
                url,
                access_token=access_token,
                query=query,
                variables={
                    "id": owner_id,
                    "first": integration_settings.shopify_nested_page_size,
                    "after": page_info["endCursor"],
                },
                label=label,
            )
            owner = data.get(owner_key)
            if not isinstance(owner, dict):
                raise _malformed(f"{label} continuation has no {owner_key} node")
            connection = owner.get(connection_key)
            if not isinstance(connection, dict):
                raise _malformed(
                    f"{label} continuation has no {connection_key} connection"
                )
            continuation_nodes = connection.get("nodes")
            if not isinstance(continuation_nodes, list):
                raise _malformed(f"{label} continuation nodes are not a list")
            nodes.extend(continuation_nodes)
            page_info = _validated_page_info(connection.get("pageInfo"), label=label)
        return nodes

    def _validated_connection(
        self, data: dict, *, connection_key: str, label: str
    ) -> tuple[list, dict[str, Any]]:
        """Extract + validate one outer connection's nodes and pageInfo."""
        connection = data.get(connection_key)
        if not isinstance(connection, dict):
            raise _malformed(f"{label} response has no {connection_key} connection")
        nodes = connection.get("nodes")
        if not isinstance(nodes, list):
            raise _malformed(f"{label} {connection_key}.nodes is not a list")
        page_info = connection.get("pageInfo")
        # The OUTER pageInfo is normalized here and STRICTLY validated by
        # the worker after the call (its resume protocol owns the
        # malformed-page terminal decision). Non-dict input passes through
        # as {} so the worker's validator — the single owner — rejects it.
        if isinstance(page_info, dict):
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            normalized_page_info = {
                "hasNextPage": has_next if isinstance(has_next, bool) else None,
                "endCursor": end_cursor if isinstance(end_cursor, str) else None,
            }
        else:
            normalized_page_info = {}
        return nodes, normalized_page_info

    async def query_search_analytics(
        self,
        *,
        access_token: str,
        property_ref: str,
        dataset: str,
        dimensions: Sequence[str],
        start_date: date,
        end_date: date,
        start_row: int,
    ) -> ShopifyPage:
        """Fetch ONE outer cursor page (the worker's uniform contract).

        The method name + signature mirror the GSC reference client — the
        worker pages every provider through this one seam. ``start_row``
        stays the worker's logical page offset and is NOT translated into
        a Shopify offset; the resume cursor injected via
        ``set_page_cursor`` becomes the GraphQL ``after`` variable. The
        ``$query`` search filter is built ONLY from the sync window
        (``updated_at:>=<start> updated_at:<=<end>``) — no financial or
        fulfillment filters, so open/closed/cancelled/refunded/fulfilled
        revisions all remain eligible.
        """
        template = _shopify_template(dataset, dimensions)
        try:
            shop = normalize_shopify_shop_domain(property_ref)
        except ValueError as exc:
            raise ShopifyApiError(
                "Shopify connection account_ref is not a canonical shop host",
                error_code=ERROR_PROVIDER_API,
            ) from exc
        url = shopify_admin_graphql_url(shop)
        window_query = (
            f"updated_at:>={start_date.isoformat()} updated_at:<={end_date.isoformat()}"
        )
        if template.dataset == DATASET_SHOPIFY_PRODUCTS:
            return await self._products_page(
                url, access_token=access_token, window_query=window_query
            )
        if template.dataset == DATASET_SHOPIFY_ORDERS:
            return await self._orders_page(
                url, access_token=access_token, window_query=window_query
            )
        # Defensive: _shopify_template already constrained the provider;
        # a new Shopify dataset without a handler here fails loud.
        raise ShopifyApiError(
            f"no Shopify query handler for dataset {template.dataset!r}",
            error_code=ERROR_PROVIDER_API,
        )

    async def _products_page(
        self, url: str, *, access_token: str, window_query: str
    ) -> ShopifyPage:
        data = await self._graphql(
            url,
            access_token=access_token,
            query=SHOPIFY_GRAPHQL_PRODUCTS,
            variables={
                "first": integration_settings.shopify_page_size,
                "after": self._page_cursor,
                "query": window_query,
                "variantFirst": integration_settings.shopify_nested_page_size,
            },
            label="Shopify products",
        )
        nodes, page_info = self._validated_connection(
            data, connection_key="products", label="Shopify products"
        )
        shop = data.get("shop")
        currency = ""
        if isinstance(shop, dict):
            currency = _str_or_empty(shop.get("currencyCode"))
        rows: list[dict] = []
        for product in nodes:
            if not isinstance(product, dict):
                continue
            product_id = _str_or_empty(product.get("id"))
            variants = product.get("variants")
            if not isinstance(variants, dict) or not product_id:
                continue
            first_nodes = variants.get("nodes")
            if not isinstance(first_nodes, list):
                continue
            variant_nodes = await self._exhaust_nested(
                url,
                access_token=access_token,
                query=SHOPIFY_GRAPHQL_PRODUCT_VARIANTS,
                owner_key="product",
                owner_id=product_id,
                connection_key="variants",
                first_nodes=first_nodes,
                first_page_info=variants.get("pageInfo"),
                label="Shopify product variants",
            )
            rows.extend(
                row
                for row in (
                    _catalog_row(product, variant, currency=currency)
                    for variant in variant_nodes
                )
                if row is not None
            )
        payload = {"rows": rows, "pageInfo": page_info}
        return ShopifyPage(payload=payload, rows=tuple(rows), raw_row_count=len(nodes))

    async def _orders_page(
        self, url: str, *, access_token: str, window_query: str
    ) -> ShopifyPage:
        data = await self._graphql(
            url,
            access_token=access_token,
            query=SHOPIFY_GRAPHQL_ORDERS,
            variables={
                "first": integration_settings.shopify_page_size,
                "after": self._page_cursor,
                "query": window_query,
                "lineItemFirst": integration_settings.shopify_nested_page_size,
            },
            label="Shopify orders",
        )
        nodes, page_info = self._validated_connection(
            data, connection_key="orders", label="Shopify orders"
        )
        orders: list[dict] = []
        for order in nodes:
            if not isinstance(order, dict):
                continue
            order_id = _str_or_empty(order.get("id"))
            line_items = order.get("lineItems")
            if not order_id or not isinstance(line_items, dict):
                continue
            first_nodes = line_items.get("nodes")
            if not isinstance(first_nodes, list):
                continue
            item_nodes = await self._exhaust_nested(
                url,
                access_token=access_token,
                query=SHOPIFY_GRAPHQL_ORDER_LINE_ITEMS,
                owner_key="order",
                owner_id=order_id,
                connection_key="lineItems",
                first_nodes=first_nodes,
                first_page_info=line_items.get("pageInfo"),
                label="Shopify order line items",
            )
            # Structurally normalized but RAW: the raw order node with its
            # nested connection flattened to a plain node list. The WORKER
            # sanitizer allowlists this into a SanitizedOrder before any
            # persistence — the connector never sanitizes.
            normalized = dict(order)
            normalized["lineItems"] = [
                item for item in item_nodes if isinstance(item, dict)
            ]
            orders.append(normalized)
        payload = {"orders": orders, "pageInfo": page_info}
        return ShopifyPage(
            payload=payload, rows=tuple(orders), raw_row_count=len(nodes)
        )

    async def probe_access_token(self, *, access_token: str, property_ref: str) -> None:
        """Cheap authenticated probe validating a Shopify grant's token.

        POSTs the config-owned ``ShopifyConnectionProbe`` operation
        (``shop { id }``) — the provider-specific grant probe; the Google
        GSC probe is deliberately NOT reused. Raises ``ShopifyApiError``
        on any failure.
        """
        try:
            shop = normalize_shopify_shop_domain(property_ref)
        except ValueError as exc:
            raise ShopifyApiError(
                "Shopify connection account_ref is not a canonical shop host",
                error_code=ERROR_PROVIDER_API,
            ) from exc
        await self._graphql(
            shopify_admin_graphql_url(shop),
            access_token=access_token,
            query=SHOPIFY_GRAPHQL_CONNECTION_PROBE,
            variables={},
            label="Shopify connection probe",
        )


def build_shopify_client(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> ShopifyClient:
    """Build a Shopify client (``transport`` = test seam)."""
    return ShopifyClient(transport=transport)
