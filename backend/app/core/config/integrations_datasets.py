from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_BING,
    INTEGRATION_PROVIDER_GA4,
    INTEGRATION_PROVIDER_GSC,
    INTEGRATION_PROVIDER_SHOPIFY,
)

DIMENSION_KEY_SEPARATOR: Final = " | "

DATASET_GSC_PAGE_DAILY: Final = "gsc_page_daily"

DATASET_GSC_QUERY_DAILY: Final = "gsc_query_daily"

DATASET_GSC_QUERY_PAGE_DAILY: Final = "gsc_query_page_daily"

DATASET_GSC_SEARCH_APPEARANCE_DAILY: Final = "gsc_search_appearance_daily"

DATASET_GSC_DEVICE_DAILY: Final = "gsc_device_daily"

DATASET_GSC_COUNTRY_DAILY: Final = "gsc_country_daily"

INTEGRATION_SYNC_EXCLUDED_DATASETS: Final[frozenset[str]] = frozenset(
    {DATASET_GSC_SEARCH_APPEARANCE_DAILY}
)

DATASET_GA4_CHANNEL_DAILY: Final = "ga4_channel_daily"

DATASET_GA4_SOURCE_MEDIUM_DAILY: Final = "ga4_source_medium_daily"

DATASET_GA4_REFERRER_DAILY: Final = "ga4_referrer_daily"

DATASET_GA4_LANDING_DAILY: Final = "ga4_landing_daily"

DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY: Final = "ga4_ecommerce_source_medium_daily"

DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY: Final = "ga4_item_source_medium_daily"

DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY: Final = "ga4_item_channel_group_daily"

DATASET_BING_PAGE_DAILY: Final = "bing_page_daily"

DATASET_BING_QUERY_DAILY: Final = "bing_query_daily"

DATASET_SHOPIFY_PRODUCTS: Final = "shopify.products"

DATASET_SHOPIFY_ORDERS: Final = "shopify.orders"

PAGING_MODE_OFFSET: Final = "offset"

PAGING_MODE_CURSOR: Final = "cursor"

PAGING_MODES: Final[frozenset[str]] = frozenset(
    {PAGING_MODE_OFFSET, PAGING_MODE_CURSOR}
)

SHOPIFY_GRAPHQL_PRODUCTS: Final = (
    "query ShopifyProducts($first: Int!, $after: String, $query: String!, "
    "$variantFirst: Int!) { shop { currencyCode } products(first: $first, "
    "after: $after, sortKey: UPDATED_AT, query: $query) { pageInfo { "
    "hasNextPage endCursor } nodes { id title handle description vendor "
    "productType status onlineStoreUrl updatedAt variants(first: "
    "$variantFirst) { pageInfo { hasNextPage endCursor } nodes { id title "
    "sku barcode price inventoryQuantity updatedAt } } } } }"
)

SHOPIFY_GRAPHQL_PRODUCT_VARIANTS: Final = (
    "query ShopifyProductVariants($id: ID!, $first: Int!, $after: String) { "
    "product(id: $id) { variants(first: $first, after: $after) { pageInfo { "
    "hasNextPage endCursor } nodes { id title sku barcode price "
    "inventoryQuantity updatedAt } } } }"
)

SHOPIFY_GRAPHQL_ORDERS: Final = (
    "query ShopifyOrders($first: Int!, $after: String, $query: String!, "
    "$lineItemFirst: Int!) { orders(first: $first, after: $after, sortKey: "
    "UPDATED_AT, query: $query) { pageInfo { hasNextPage endCursor } nodes { "
    "id createdAt updatedAt cancelledAt currencyCode currentTotalPriceSet { "
    "shopMoney { amount currencyCode } } displayFinancialStatus "
    "displayFulfillmentStatus customerJourneySummary { ready firstVisit { "
    "landingSiteUrl: landingPage referrerUrl referralCode source "
    "sourceDescription sourceType utmParameters { campaign content medium "
    "source term } } lastVisit { landingSiteUrl: landingPage referrerUrl "
    "referralCode source sourceDescription sourceType utmParameters { "
    "campaign content medium source term } } } lineItems(first: "
    "$lineItemFirst) { pageInfo { hasNextPage endCursor } nodes { id sku "
    "quantity currentQuantity originalUnitPriceSet { shopMoney { amount "
    "currencyCode } } } } } } }"
)

SHOPIFY_GRAPHQL_ORDER_LINE_ITEMS: Final = (
    "query ShopifyOrderLineItems($id: ID!, $first: Int!, $after: String) { "
    "order(id: $id) { lineItems(first: $first, after: $after) { pageInfo { "
    "hasNextPage endCursor } nodes { id sku quantity currentQuantity "
    "originalUnitPriceSet { shopMoney { amount currencyCode } } } } } }"
)

SHOPIFY_GRAPHQL_CONNECTION_PROBE: Final = "query ShopifyConnectionProbe { shop { id } }"

_GSC_SEARCH_ANALYTICS_METRICS: Final = ("clicks", "impressions", "ctr", "position")

_GA4_SESSION_METRICS: Final = ("sessions", "engagedSessions", "keyEvents")

_GA4_ECOMMERCE_METRICS: Final = ("transactions", "purchaseRevenue", "sessions")

_GA4_ITEM_ECOMMERCE_METRICS: Final = ("itemRevenue", "itemsPurchased")

_BING_STATS_METRICS: Final = ("clicks", "impressions")

GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY: Final = "ga4_item_attribution"

GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION: Final = "ga4-item-attribution-1"

GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM: Final = "session_source_medium"

GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP: Final = "default_channel_group"

GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS: Final = ("incompatib",)

GSC_SEARCH_ANALYTICS_METHOD: Final = "searchAnalytics.query"

@dataclass(frozen=True)
class IntegrationDatasetTemplate:
    """One provider dataset's config-owned query template (C1).

    ``dimensions`` is the DECLARED order: ``pack_dimension_key`` joins a row's
    dimension values in exactly this order, so the template is the single
    owner of ``dimension_key`` packing for both workstreams (integrations
    produces, analytics/traffic consumes).

    ``paging_mode`` selects the worker's paging/resume protocol (``offset``
    by default; Shopify's GraphQL entity feeds are ``cursor``).
    """

    dataset: str
    provider: str
    api_method: str
    dimensions: tuple[str, ...]
    metrics: tuple[str, ...]
    paging_mode: str = PAGING_MODE_OFFSET

INTEGRATION_DATASET_TEMPLATES: Final[dict[str, IntegrationDatasetTemplate]] = {
    DATASET_GSC_PAGE_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_PAGE_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("page", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GSC_QUERY_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_QUERY_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("query", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GSC_QUERY_PAGE_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_QUERY_PAGE_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("query", "page", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GSC_SEARCH_APPEARANCE_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_SEARCH_APPEARANCE_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("searchAppearance", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GSC_DEVICE_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_DEVICE_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("device", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GSC_COUNTRY_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GSC_COUNTRY_DAILY,
        provider=INTEGRATION_PROVIDER_GSC,
        api_method=GSC_SEARCH_ANALYTICS_METHOD,
        dimensions=("country", "date"),
        metrics=_GSC_SEARCH_ANALYTICS_METRICS,
    ),
    DATASET_GA4_CHANNEL_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_CHANNEL_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("sessionDefaultChannelGroup", "date"),
        metrics=_GA4_SESSION_METRICS,
    ),
    DATASET_GA4_SOURCE_MEDIUM_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_SOURCE_MEDIUM_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("sessionSource", "sessionMedium", "date"),
        metrics=_GA4_SESSION_METRICS,
    ),
    DATASET_GA4_REFERRER_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_REFERRER_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        # ``pageReferrer``, NOT ``fullReferrer``: the latter is a Universal
        # Analytics name the GA4 Data API rejects outright ("Field
        # fullReferrer is not a valid dimension. Did you mean pageReferrer?"),
        # which failed EVERY ga4 sync at the first report.
        dimensions=("pageReferrer", "date"),
        metrics=_GA4_SESSION_METRICS,
    ),
    DATASET_GA4_LANDING_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_LANDING_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("landingPage", "sessionSource", "sessionMedium", "date"),
        metrics=_GA4_SESSION_METRICS,
    ),
    # A1 attribution slice (WS-B): the ecommerce reports. Both item
    # templates stay REGISTERED so normalization/derivation resolve them,
    # but the sync worker pages exactly ONE per run (the capability
    # selection in ``_provider_datasets``).
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("sessionSource", "sessionMedium", "date"),
        metrics=_GA4_ECOMMERCE_METRICS,
    ),
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("itemId", "sessionSource", "sessionMedium", "date"),
        metrics=_GA4_ITEM_ECOMMERCE_METRICS,
    ),
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
        provider=INTEGRATION_PROVIDER_GA4,
        api_method="runReport",
        dimensions=("itemId", "sessionDefaultChannelGroup", "date"),
        metrics=_GA4_ITEM_ECOMMERCE_METRICS,
    ),
    # Bing Webmaster stats (I12). ``api_method`` is the pinned endpoint
    # literal under ``BING_API_JSON_ROOT``; the Bing stats API takes no
    # date-range parameters, so derivation projects the imported rows onto
    # the run's window. The leading dimension is the page URL
    # (``GetPageStats``) or the query text (``GetQueryStats``) — both are
    # carried in the response's ``Query`` field.
    DATASET_BING_PAGE_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_BING_PAGE_DAILY,
        provider=INTEGRATION_PROVIDER_BING,
        api_method="GetPageStats",
        dimensions=("page", "date"),
        metrics=_BING_STATS_METRICS,
    ),
    DATASET_BING_QUERY_DAILY: IntegrationDatasetTemplate(
        dataset=DATASET_BING_QUERY_DAILY,
        provider=INTEGRATION_PROVIDER_BING,
        api_method="GetQueryStats",
        dimensions=("query", "date"),
        metrics=_BING_STATS_METRICS,
    ),
    # Shopify GraphQL entity feeds (commerce suite). Empty dimensions/metrics
    # — these are not metric reports; ``api_method`` names the config-owned
    # GraphQL operation the connector runs. Cursor paging: the worker
    # persists the resume cursor in each page's ``query_snapshot``.
    DATASET_SHOPIFY_PRODUCTS: IntegrationDatasetTemplate(
        dataset=DATASET_SHOPIFY_PRODUCTS,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        api_method="ShopifyProducts",
        dimensions=(),
        metrics=(),
        paging_mode=PAGING_MODE_CURSOR,
    ),
    DATASET_SHOPIFY_ORDERS: IntegrationDatasetTemplate(
        dataset=DATASET_SHOPIFY_ORDERS,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        api_method="ShopifyOrders",
        dimensions=(),
        metrics=(),
        paging_mode=PAGING_MODE_CURSOR,
    ),
}

def pack_dimension_key(values: Sequence[str]) -> str:
    """Pack one row's dimension values into its ``dimension_key`` (C1).

    ``values`` MUST be in the dataset template's declared dimension order;
    multi-dimension rows join with ``" | "`` and a single-dimension row uses
    the bare value (``str.join`` of one element).
    """
    return DIMENSION_KEY_SEPARATOR.join(values)

def unpack_dimension_key(dataset: str, dimension_key: str) -> tuple[str, ...] | None:
    """Inverse of ``pack_dimension_key`` for one dataset's declared template.

    This module owns the ``dimension_key`` packing format (contract C1,
    invariant 2), so the UNPACK lives here too. The key is split from the
    RIGHT against the template's declared arity, peeling the always-trailing
    ``date`` value without breaking on a ``" | "`` inside a free-form
    leading value (e.g. a ``pageReferrer``/page URL). Returns the FULL
    tuple in declared dimension order (the trailing element is the
    provider's date value; the parsed date already lives on the metric
    row), or ``None`` when the dataset is unknown or the key does not
    unpack into the declared arity — an un-mappable key is skipped by the
    caller, never guessed.
    """
    template = INTEGRATION_DATASET_TEMPLATES.get(dataset)
    if template is None:
        return None
    parts = dimension_key.rsplit(DIMENSION_KEY_SEPARATOR, len(template.dimensions) - 1)
    if len(parts) != len(template.dimensions):
        return None
    return tuple(parts)
