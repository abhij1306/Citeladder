# GSC / GA4 / Bing integrations configuration (invariant 1: config lives here).
#
# Owns every tunable + vocabulary token for the first-party data integrations
# surface (docs/roadmap/integrations.md): the provider/transport vocabulary and
# their compatibility map, the per-transport OAuth endpoints + minimal scopes,
# the grant/mapping status + sync-kind + lifecycle-event + error tokens, the
# dataset -> dimensions/metrics query templates (cross-workstream contract C1 —
# pinned so the analytics/traffic workstreams consume these ids unchanged), the
# sync worker knobs (``IntegrationSettings``, ``INTEGRATION_`` env prefix), the
# approved-endpoint allow-list (SSRF policy), and the ``PostgresQueueSpec``
# that parameterizes the shared generic queue over ``IntegrationSyncRun`` rows.
#
# Service/worker/connector code READS these values; it never hard-codes them.
# The OAuth client id/secret are env-injected deployment secrets declared on
# the central ``Settings`` (app/core/config/__init__.py) — never literals in
# this file and never logged (invariant 6).
from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlencode, urlsplit

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.task_queue import ERROR_MAX_ATTEMPTS, PostgresQueueSpec

if TYPE_CHECKING:
    # Type-only: config never imports a model at runtime (circular import).
    from app.models.integrations import IntegrationSyncRun

# --- Providers + OAuth transports -------------------------------------------
INTEGRATION_PROVIDER_GSC: Final = "gsc"
INTEGRATION_PROVIDER_GA4: Final = "ga4"
INTEGRATION_PROVIDER_BING: Final = "bing"
INTEGRATION_PROVIDER_SHOPIFY: Final = "shopify"
INTEGRATION_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        INTEGRATION_PROVIDER_GSC,
        INTEGRATION_PROVIDER_GA4,
        INTEGRATION_PROVIDER_BING,
        INTEGRATION_PROVIDER_SHOPIFY,
    }
)

INTEGRATION_TRANSPORT_GOOGLE: Final = "google_oauth"
INTEGRATION_TRANSPORT_MICROSOFT: Final = "microsoft_oauth"
INTEGRATION_TRANSPORT_SHOPIFY: Final = "shopify_oauth"
INTEGRATION_TRANSPORTS: Final[frozenset[str]] = frozenset(
    {
        INTEGRATION_TRANSPORT_GOOGLE,
        INTEGRATION_TRANSPORT_MICROSOFT,
        INTEGRATION_TRANSPORT_SHOPIFY,
    }
)

# Provider -> transport compatibility map (spec section 3): a connection's
# provider must be compatible with its grant's transport. GSC + GA4 share ONE
# Google consent (one grant carries both connections); Bing rides a Microsoft
# grant; Shopify rides its own per-shop offline-token grant.
INTEGRATION_PROVIDER_TRANSPORT: Final[dict[str, str]] = {
    INTEGRATION_PROVIDER_GSC: INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_PROVIDER_GA4: INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_PROVIDER_BING: INTEGRATION_TRANSPORT_MICROSOFT,
    INTEGRATION_PROVIDER_SHOPIFY: INTEGRATION_TRANSPORT_SHOPIFY,
}

# Whether a transport's grant carries a refreshable access token. Shopify's
# offline Admin API token never expires and has no refresh token: the sync
# worker returns it directly instead of attempting a refresh (a ``None``
# ``token_expires_at`` is NOT near-expiry for a non-refreshable transport).
INTEGRATION_OAUTH_REFRESHABLE: Final[dict[str, bool]] = {
    INTEGRATION_TRANSPORT_GOOGLE: True,
    INTEGRATION_TRANSPORT_MICROSOFT: True,
    INTEGRATION_TRANSPORT_SHOPIFY: False,
}

# --- OAuth endpoints (per transport) + redirect ------------------------------
# STATIC endpoint maps stay Google/Microsoft-only: Shopify's authorize/token
# endpoints are PER-SHOP (``https://{shop}.myshopify.com/admin/oauth/...``)
# and are resolved through the validated dynamic builders below.
INTEGRATION_OAUTH_AUTHORIZE_URLS: Final[dict[str, str]] = {
    INTEGRATION_TRANSPORT_GOOGLE: "https://accounts.google.com/o/oauth2/v2/auth",
    INTEGRATION_TRANSPORT_MICROSOFT: (
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    ),
}
INTEGRATION_OAUTH_TOKEN_URLS: Final[dict[str, str]] = {
    INTEGRATION_TRANSPORT_GOOGLE: "https://oauth2.googleapis.com/token",
    INTEGRATION_TRANSPORT_MICROSOFT: (
        "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    ),
}
# The Microsoft identity platform exposes no OAuth grant-revocation endpoint,
# so its entry is intentionally empty: remote revoke is Google-only and a
# Microsoft grant disconnects locally (spec section 5). Shopify likewise has
# no token-revocation endpoint for an offline Admin API grant — a Shopify
# disconnect is local-only (the merchant revokes in their admin).
INTEGRATION_OAUTH_REVOKE_URLS: Final[dict[str, str]] = {
    INTEGRATION_TRANSPORT_GOOGLE: "https://oauth2.googleapis.com/revoke",
    INTEGRATION_TRANSPORT_MICROSOFT: "",
    INTEGRATION_TRANSPORT_SHOPIFY: "",
}
# Minimal scope set per transport (spec section 7). The ONE Google grant
# combines the GSC + GA4 read scopes so a single consent yields both
# connections (spec section 2/3). The Microsoft grant carries the Bing
# Webmaster API scope pinned from Microsoft docs at I12 (plan R3):
# ``webmaster.manage`` on the ``https://webmaster.bing.com/api/`` audience —
# the delegated scope Microsoft documents for the Bing Webmaster API on the
# Microsoft identity platform (learn.microsoft.com Q&A #2337353; the Bing
# Webmaster OAuth doc learn.microsoft.com/bingwebmaster/oauth2 documents
# Bearer-token auth and the bare ``webmaster.manage`` form against Bing's
# own www.bing.com/webmasters/OAuth endpoints, which this transport does
# NOT use — the grant rides login.microsoftonline.com, so the v2.0
# fully-qualified form is required). Microsoft documents NO narrower
# read-only webmaster scope (``bingads.manage`` is the ADS API — rejected).
# ``offline_access`` stays: the identity platform v2.0 issues a refresh
# token only when it is requested.
INTEGRATION_OAUTH_SCOPES: Final[dict[str, tuple[str, ...]]] = {
    INTEGRATION_TRANSPORT_GOOGLE: (
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    ),
    INTEGRATION_TRANSPORT_MICROSOFT: (
        "offline_access",
        "https://webmaster.bing.com/api/webmaster.manage",
    ),
    # Shopify custom-app Admin API scopes: catalog + order READS only. No
    # write scope and no ``read_all_orders`` (the orders read scope is
    # sufficient for the app's own orders; requesting more would fail the
    # least-privilege rule).
    INTEGRATION_TRANSPORT_SHOPIFY: (
        "read_products",
        "read_orders",
    ),
}

# OAuth callback path (the provider-registered redirect target; ``provider``
# is interpolated by the connect flow) and the frontend landing the callback
# 302s to (contract C2).
INTEGRATION_OAUTH_CALLBACK_PATH: Final = (
    "/api/v1/integrations/oauth/{provider}/callback"
)
INTEGRATION_OAUTH_LANDING_PATH: Final = "/settings?tab=integrations"


def integration_oauth_redirect_uri(provider: str) -> str:
    """Absolute OAuth callback URL registered with the provider.

    Anchored on ``frontend_url`` — the APP origin — never on the incoming
    request's base URL. The browser reaches the backend through the Next
    ``rewrites()`` proxy, which sets ``changeOrigin`` (the backend sees its
    OWN host, not the app's), so a request-derived redirect URI sends the
    provider's post-consent navigation straight to the backend origin,
    bypassing the proxy. The session cookie is host-only on the app origin,
    so that navigation arrives with no cookie and the callback 401s
    ("Not authenticated") — and in production the backend origin is not
    browser-reachable at all.

    Routing the callback back through the app origin keeps it same-origin
    (invariant 12): the cookie always rides along and the proxy forwards it.
    The value is deployment-pinned rather than per-request because providers
    match ``redirect_uri`` EXACTLY against their registered value — and the
    same string must be reproducible at the token exchange.
    """
    # Lazy for the same reason as ``integration_oauth_landing_url`` below.
    from app.core.config import settings

    base = settings.frontend_url.rstrip("/")
    return f"{base}{INTEGRATION_OAUTH_CALLBACK_PATH.format(provider=provider)}"


def integration_oauth_landing_url(params: dict[str, str]) -> str:
    """Absolute frontend landing URL the OAuth callback 302s to (contract C2).

    The provider sends the user's browser straight to the backend callback, so
    the redirect target must be **absolute** and point at the frontend origin:
    a bare path would resolve against the backend origin, which serves no
    ``/settings`` route (the browser would land on a 404 even though the
    connect succeeded). ``frontend_url`` is the same setting that seeds the
    CORS allow-list, so the landing origin always matches the app the user
    came from.
    """
    # Imported lazily: ``app.core.config`` builds the Settings singleton at
    # module scope, so a top-level import here would run during that build.
    from app.core.config import settings

    base = settings.frontend_url.rstrip("/")
    return f"{base}{INTEGRATION_OAUTH_LANDING_PATH}&{urlencode(params)}"


# --- Provider data API endpoints (read-only) ---------------------------------
GSC_API_BASE_URL: Final = "https://www.googleapis.com"
GSC_SEARCH_ANALYTICS_PATH: Final = (
    "/webmasters/v3/sites/{property_ref}/searchAnalytics/query"
)
# The caller's verified-site list. Serves BOTH the property-discovery
# listing (which sites may be selected for a connection) and the cheap
# authenticated grant probe behind ``POST /integrations/{id}/test`` — one
# config-owned path, read by both (invariant 1 + 2).
GSC_SITES_PATH: Final = "/webmasters/v3/sites"
# ``siteEntry[].permissionLevel`` for a site the caller has NOT verified.
# Such sites cannot serve searchAnalytics, so discovery filters them out
# rather than offering a selection that would 403 at the first sync.
GSC_PERMISSION_UNVERIFIED: Final = "siteUnverifiedUser"
# GSC domain-wide property refs carry this provider literal prefix
# ("sc-domain:example.com"); URL-prefix properties are plain URLs. Used by
# the mapping service to resolve a property ref to its bare host.
GSC_DOMAIN_PROPERTY_PREFIX: Final = "sc-domain:"
GA4_API_BASE_URL: Final = "https://analyticsdata.googleapis.com"
GA4_RUN_REPORT_PATH: Final = "/v1beta/properties/{property_ref}:runReport"
# GA4 property DISCOVERY rides the Admin API, a different host from the
# Data API above. ``accountSummaries`` is the one call that returns every
# property the grant can read, already grouped by account, so property
# discovery costs a single request. Covered by the grant's existing
# ``analytics.readonly`` scope — no extra consent.
GA4_ADMIN_API_BASE_URL: Final = "https://analyticsadmin.googleapis.com"
GA4_ACCOUNT_SUMMARIES_PATH: Final = "/v1beta/accountSummaries"
# Admin API page size for the summaries listing (its documented maximum) and
# the bound on how many pages discovery will follow. The cap keeps a
# misbehaving ``nextPageToken`` from looping forever; reaching it is a
# provider error, never a silently truncated list.
GA4_ACCOUNT_SUMMARIES_PAGE_SIZE: Final = 200
GA4_ACCOUNT_SUMMARIES_MAX_PAGES: Final = 25
# GA4 property refs are NUMERIC property ids, optionally carrying the
# provider's ``properties/`` resource prefix (``123456789`` or
# ``properties/123456789``) — never domain-shaped, so the owned-domain
# mapping rule cannot apply to them (shape is validated on mapping writes;
# the connection test probes reachability). The CANONICAL stored form is
# the bare numeric id — mappings, metric rows, and the runReport URL all
# use it (``normalize_ga4_property_ref``) so the two spellings can never
# split owner identity or produce ``/v1beta/properties/properties%2F…``.
GA4_PROPERTY_REF_PATTERN: Final = re.compile(r"^(?:properties/)?\d+$")
GA4_PROPERTY_RESOURCE_PREFIX: Final = "properties/"


def is_ga4_property_ref(property_ref: str) -> bool:
    """True when ``property_ref`` is a well-formed GA4 numeric property id."""
    return bool(GA4_PROPERTY_REF_PATTERN.match(property_ref.strip()))


def normalize_ga4_property_ref(property_ref: str) -> str:
    """The canonical GA4 property ref: the bare numeric id.

    Idempotent — a bare numeric id passes through unchanged. Callers must
    validate with ``is_ga4_property_ref`` first when the value is
    user-supplied; this helper only normalizes spelling.
    """
    return property_ref.strip().removeprefix(GA4_PROPERTY_RESOURCE_PREFIX)


# --- Shopify per-shop endpoints (Admin GraphQL API only) ---------------------
# Shopify's OAuth authorize/token endpoints and the Admin GraphQL endpoint are
# PER-SHOP: ``https://{shop}.myshopify.com/...``. The shop host is therefore
# validated against this STRICT canonical pattern before it is ever
# interpolated into a URL — a single lowercase alnum/hyphen label on the
# ``myshopify.com`` suffix exactly. This rejects hostile suffixes
# (``shop.myshopify.com.evil.com``), the bare suffix (``myshopify.com``),
# multi-label hosts (``a.b.myshopify.com``), and any other scheme/host.
SHOPIFY_SHOP_DOMAIN_PATTERN: Final = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.myshopify\.com$"
)
SHOPIFY_SHOP_DOMAIN_SUFFIX: Final = ".myshopify.com"

# OAuth path templates interpolated onto a validated shop host.
SHOPIFY_OAUTH_AUTHORIZE_PATH: Final = "/admin/oauth/authorize"
SHOPIFY_OAUTH_TOKEN_PATH: Final = "/admin/oauth/access_token"

# The ONLY Shopify API surface this app calls: the Admin GraphQL endpoint
# (greenfield — there is no REST compatibility or fallback path). The API
# version literal lives HERE and nowhere else (invariant 1); connector code
# never owns it.
SHOPIFY_ADMIN_API_VERSION: Final[str] = "2026-07"
SHOPIFY_ADMIN_GRAPHQL_PATH: Final[str] = "/admin/api/{version}/graphql.json"


def normalize_shopify_shop_domain(value: str) -> str:
    """Canonicalize a user-supplied shop domain to its strict host form.

    Strips whitespace, lowercases, drops any scheme, and expands a bare
    single-label shop name (``my-shop``) to ``my-shop.myshopify.com``.
    Raises ``ValueError`` unless the result matches the canonical pattern
    exactly — callers map that to a 422; they never fall back to a guessed
    host.
    """
    candidate = value.strip().lower()
    if "://" in candidate:
        candidate = urlsplit(candidate).netloc
    # Drop a path/query fragment a user may have pasted after the host.
    candidate = candidate.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    # A bare single-label shop name expands onto the canonical suffix.
    if candidate and "." not in candidate:
        candidate = f"{candidate}{SHOPIFY_SHOP_DOMAIN_SUFFIX}"
    if not SHOPIFY_SHOP_DOMAIN_PATTERN.match(candidate):
        raise ValueError(f"invalid Shopify shop domain: {value!r}")
    return candidate


def is_shopify_shop_domain(host: str) -> bool:
    """True when ``host`` is a canonical ``{shop}.myshopify.com`` host.

    Used by the SSRF allow-list for the dynamic Shopify host: a dynamic
    host passes ONLY this exact pattern — there is deliberately no
    wildcard/suffix match.
    """
    return bool(SHOPIFY_SHOP_DOMAIN_PATTERN.match(host.strip().lower()))


def _shopify_shop_url(shop: str, path: str) -> str:
    """Absolute per-shop URL; the host is validated BEFORE interpolation."""
    canonical = normalize_shopify_shop_domain(shop)
    return f"https://{canonical}{path}"


def shopify_oauth_authorize_url(shop: str) -> str:
    """Per-shop OAuth authorize endpoint (validated canonical host only)."""
    return _shopify_shop_url(shop, SHOPIFY_OAUTH_AUTHORIZE_PATH)


def shopify_oauth_token_url(shop: str) -> str:
    """Per-shop OAuth token endpoint (validated canonical host only)."""
    return _shopify_shop_url(shop, SHOPIFY_OAUTH_TOKEN_PATH)


def shopify_admin_graphql_url(shop: str) -> str:
    """Per-shop Admin GraphQL endpoint at the config-owned API version."""
    return _shopify_shop_url(
        shop, SHOPIFY_ADMIN_GRAPHQL_PATH.format(version=SHOPIFY_ADMIN_API_VERSION)
    )


# Bing Webmaster API v1 literals, pinned from Microsoft docs at I12 (plan
# R3): host ``ssl.bing.com``, JSON endpoint root
# ``/webmaster/api.svc/json/`` (learn.microsoft.com
# /dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi and
# /bingwebmaster/getting-access). Read endpoints are GET
# ``{root}GetPageStats|GetQueryStats?siteUrl=...`` authenticated with the
# OAuth Bearer token (learn.microsoft.com/bingwebmaster/oauth2); the cheap
# authenticated grant probe is ``GetSites`` (the caller's verified-site
# list — the analogue of the GSC ``GET /webmasters/v3/sites`` probe).
BING_API_BASE_URL: Final = "https://ssl.bing.com"
BING_API_JSON_ROOT: Final = "/webmaster/api.svc/json/"
BING_SITES_PROBE_METHOD: Final = "GetSites"

# Approved-endpoint allow-list (SSRF policy, master plan section 15):
# integration clients must reject any URL whose host is not in this set.
INTEGRATION_APPROVED_ENDPOINT_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "accounts.google.com",
        "oauth2.googleapis.com",
        "www.googleapis.com",
        "analyticsdata.googleapis.com",
        # GA4 Admin API — property discovery only (see GA4_ADMIN_API_BASE_URL).
        "analyticsadmin.googleapis.com",
        "login.microsoftonline.com",
        "ssl.bing.com",
    }
)

# --- Grant + mapping statuses -------------------------------------------------
GRANT_STATUS_CONNECTED: Final = "connected"
GRANT_STATUS_NEEDS_REAUTH: Final = "needs_reauth"
GRANT_STATUS_PENDING_REVOCATION: Final = "pending_revocation"
GRANT_STATUS_REVOKED: Final = "revoked"
GRANT_STATUS_ERROR: Final = "error"
INTEGRATION_GRANT_STATUSES: Final[frozenset[str]] = frozenset(
    {
        GRANT_STATUS_CONNECTED,
        GRANT_STATUS_NEEDS_REAUTH,
        GRANT_STATUS_PENDING_REVOCATION,
        GRANT_STATUS_REVOKED,
        GRANT_STATUS_ERROR,
    }
)

MAPPING_STATUS_ACTIVE: Final = "active"
MAPPING_STATUS_DISABLED: Final = "disabled"
INTEGRATION_MAPPING_STATUSES: Final[frozenset[str]] = frozenset(
    {MAPPING_STATUS_ACTIVE, MAPPING_STATUS_DISABLED}
)

# --- Sync kinds ----------------------------------------------------------------
SYNC_KIND_SCHEDULED: Final = "scheduled"
SYNC_KIND_ON_DEMAND: Final = "on_demand"
SYNC_KIND_BACKFILL: Final = "backfill"
INTEGRATION_SYNC_KINDS: Final[frozenset[str]] = frozenset(
    {SYNC_KIND_SCHEDULED, SYNC_KIND_ON_DEMAND, SYNC_KIND_BACKFILL}
)

# --- Lifecycle events (IntegrationEvent.event_type; AuditEvent convention) ----
EVENT_INTEGRATION_CONNECTED: Final = "integration.connected"
EVENT_INTEGRATION_TESTED: Final = "integration.tested"
EVENT_INTEGRATION_SYNC_STARTED: Final = "integration.sync_started"
EVENT_INTEGRATION_SYNC_FINISHED: Final = "integration.sync_finished"
EVENT_INTEGRATION_REAUTH_REQUIRED: Final = "integration.reauth_required"
EVENT_INTEGRATION_REVOKED: Final = "integration.revoked"
# A connection was removed while its shared grant stays live for the
# remaining connections (no remote revoke — spec section 5).
EVENT_INTEGRATION_DISCONNECTED: Final = "integration.disconnected"
# The remote revoke of the LAST connection's grant failed: tokens are
# retained and the grant moves to ``pending_revocation`` for a later retry.
EVENT_INTEGRATION_REVOKE_FAILED: Final = "integration.revoke_failed"

# --- Error tokens --------------------------------------------------------------
# The queue-level ``max_attempts_exceeded`` token stays shared in
# config/task_queue.py; these are the integrations-specific codes stamped on
# runs/grants.
ERROR_UNMAPPED_PROPERTY: Final = "unmapped_property"
ERROR_TOKEN_REFRESH_FAILED: Final = "token_refresh_failed"
ERROR_PROVIDER_API: Final = "provider_api_error"
ERROR_RATE_LIMITED: Final = "rate_limited"
ERROR_UNAPPROVED_ENDPOINT: Final = "unapproved_endpoint"
# A probe/exchange was rejected by the provider as unauthorized (HTTP
# 401/403): the grant token no longer validates.
ERROR_GRANT_AUTH_FAILED: Final = "grant_auth_failed"
# OAuth connect-flow callback codes (the ``error=<code>`` query param of the
# contract-C2 302 landing on /settings?tab=integrations).
ERROR_OAUTH_STATE_INVALID: Final = "oauth_state_invalid"
ERROR_OAUTH_EXCHANGE_FAILED: Final = "oauth_exchange_failed"
ERROR_OAUTH_NOT_CONFIGURED: Final = "oauth_not_configured"
# Shopify connect start: the required ``shop`` query param was missing,
# non-canonical, or was passed for a non-Shopify provider (422).
ERROR_OAUTH_SHOP_INVALID: Final = "oauth_shop_invalid"
# Sync enqueue (I5/I7): the window body failed validation (422) and the
# partial active-window index rejected a duplicate in-flight run (409).
ERROR_SYNC_WINDOW_INVALID: Final = "sync_window_invalid"
ERROR_SYNC_ACTIVE_WINDOW_CONFLICT: Final = "sync_active_window_conflict"
# Sync worker (I6): a fetched page exceeded the inline-payload cap — the
# payload is rejected, never truncated (see ``max_inline_payload_bytes``).
ERROR_PAYLOAD_TOO_LARGE: Final = "payload_too_large"
# Property-mapping writes (I8): provider != the referenced connection's
# provider (422), the property does not resolve to one of the project's
# owned domains (422), and the (workspace, provider, property_ref) slot
# already has an ACTIVE owner (409).
ERROR_MAPPING_PROVIDER_MISMATCH: Final = "mapping_provider_mismatch"
ERROR_MAPPING_PROPERTY_NOT_OWNED: Final = "mapping_property_not_owned"
ERROR_MAPPING_ACTIVE_OWNER_CONFLICT: Final = "mapping_active_owner_conflict"
# Property discovery (the picker): the connection's provider exposes no
# listable property set (Shopify's property is its shop; Bing has no
# listing this pass) — a 422, never an empty list that reads as "you own
# nothing".
ERROR_PROPERTY_DISCOVERY_UNSUPPORTED: Final = "property_discovery_unsupported"
# GA4 item-attribution fallback (WS-B A1): the property rejected the primary
# item source/medium dimension mix with an HTTP 400 whose capped detail
# explicitly names an incompatible dimension/metric combination. Raised as
# the connector's ``Ga4DimensionCompatibilityError``; the sync worker's
# NARROW handler switches the run to the channel-group item template.
ERROR_GA4_DIMENSION_INCOMPATIBLE: Final = "ga4_dimension_incompatible"

# --- Versioning ----------------------------------------------------------------
# Versions the artifact -> IntegrationMetricRow transform code (NOT the data
# run — that identity is the run's ``resync_seq``).
INTEGRATION_IMPORTER_VERSION: Final = "integrations-importer-1"

# --- Dataset -> dimensions/metrics query templates (contract C1) ---------------
DIMENSION_KEY_SEPARATOR: Final = " | "

DATASET_GSC_PAGE_DAILY: Final = "gsc_page_daily"
DATASET_GSC_QUERY_DAILY: Final = "gsc_query_daily"
DATASET_GSC_QUERY_PAGE_DAILY: Final = "gsc_query_page_daily"
DATASET_GSC_SEARCH_APPEARANCE_DAILY: Final = "gsc_search_appearance_daily"
DATASET_GSC_DEVICE_DAILY: Final = "gsc_device_daily"
DATASET_GSC_COUNTRY_DAILY: Final = "gsc_country_daily"
# Search Console rejects ``searchAppearance`` when it is grouped with any
# other dimension, including the date required by our daily metric-row
# contract. Keep the template registered so historical rows remain readable,
# but do not issue a request that the provider deterministically rejects and
# thereby discard the five valid GSC report families in the same sync.
INTEGRATION_SYNC_EXCLUDED_DATASETS: Final[frozenset[str]] = frozenset(
    {DATASET_GSC_SEARCH_APPEARANCE_DAILY}
)
DATASET_GA4_CHANNEL_DAILY: Final = "ga4_channel_daily"
DATASET_GA4_SOURCE_MEDIUM_DAILY: Final = "ga4_source_medium_daily"
DATASET_GA4_REFERRER_DAILY: Final = "ga4_referrer_daily"
DATASET_GA4_LANDING_DAILY: Final = "ga4_landing_daily"
# GA4 ecommerce datasets (WS-B A1 attribution slice). The source/medium
# ecommerce report shares its dimension tuple with ``ga4_source_medium_daily``
# and differs only in METRICS — template resolution therefore keys on the
# (dataset, dimensions) pair, never on dimensions alone. The channel-group
# item template is the FALLBACK for properties that reject the primary item
# source/medium dimension mix (HTTP 400 incompatible combination): exactly
# one item template runs per sync, selected by the per-connection
# capability state below.
DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY: Final = "ga4_ecommerce_source_medium_daily"
DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY: Final = "ga4_item_source_medium_daily"
DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY: Final = "ga4_item_channel_group_daily"
DATASET_BING_PAGE_DAILY: Final = "bing_page_daily"
DATASET_BING_QUERY_DAILY: Final = "bing_query_daily"
# Shopify Admin GraphQL datasets (commerce suite). These carry NO report
# dimensions/metrics: they are entity feeds (one catalog row per product
# variant; one sanitized order per order node), paged by GraphQL cursor.
DATASET_SHOPIFY_PRODUCTS: Final = "shopify.products"
DATASET_SHOPIFY_ORDERS: Final = "shopify.orders"

# --- Dataset paging modes ------------------------------------------------------
# How the sync worker pages a dataset. ``offset`` datasets use the provider's
# row-offset paging and terminate on a short page (``raw_row_count <
# sync_page_size``); ``cursor`` datasets are paged by an opaque provider
# cursor whose resume position is persisted per page in the immutable
# artifact's ``query_snapshot`` (``pagingMode``/``pageCursor``/
# ``nextPageCursor``) and terminate on ``pageInfo.hasNextPage == false``.
PAGING_MODE_OFFSET: Final = "offset"
PAGING_MODE_CURSOR: Final = "cursor"
PAGING_MODES: Final[frozenset[str]] = frozenset(
    {PAGING_MODE_OFFSET, PAGING_MODE_CURSOR}
)

# --- Shopify GraphQL operation texts (config-owned, invariant 1) -------------
# Every GraphQL query text lives HERE; the Shopify connector READS these
# constants and never declares query text of its own. Pinned selection sets:
# the products feed normalizes one safe catalog row per variant (no PII);
# the orders feed carries customer-journey attribution and line items the
# WORKER sanitizer allowlists before any persistence (the connector never
# sanitizes). ``landingSiteUrl: landingPage`` is a deliberate alias: it
# gives the sanitizer the source-spec key while reading Shopify's current
# ``CustomerVisit.landingPage`` field.
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
# Cheap authenticated probe for the connection test (NOT the Google GSC
# probe): proves the offline token validates against this shop.
SHOPIFY_GRAPHQL_CONNECTION_PROBE: Final = "query ShopifyConnectionProbe { shop { id } }"

_GSC_SEARCH_ANALYTICS_METRICS: Final = ("clicks", "impressions", "ctr", "position")
_GA4_SESSION_METRICS: Final = ("sessions", "engagedSessions", "keyEvents")
# GA4 ecommerce metric sets (A1): order-level measures on the source/medium
# report; item-level measures on both item reports. ``purchaseRevenue`` /
# ``itemRevenue`` are reported in the PROPERTY's single currency — the
# response's ``metadata.currencyCode`` is the ONLY currency source for A1
# (persisted on the sanitized page payload as ``currency_code``, never a
# report dimension — a dimension would change ``dimension_key`` identity
# and explode cardinality).
_GA4_ECOMMERCE_METRICS: Final = ("transactions", "purchaseRevenue", "sessions")
_GA4_ITEM_ECOMMERCE_METRICS: Final = ("itemRevenue", "itemsPurchased")
# Bing stats endpoints carry click/impression counts only in this pass
# (I12 derivation mapping; the average-position fields the API also
# returns are roadmap).
_BING_STATS_METRICS: Final = ("clicks", "impressions")

# --- GA4 item-attribution capability fallback (WS-B A1) ----------------------
# Persisted per-connection under ``IntegrationConnection.dataset_capabilities``
# keyed by this token: which item dataset the property can serve, at which
# source granularity, and why. Non-secret provider capability state only.
GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY: Final = "ga4_item_attribution"
# Versions the capability DECISION logic: a persisted state whose version
# differs from the current token is stale — the next sync RE-PROBES the
# primary item template instead of trusting the old selection.
GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION: Final = "ga4-item-attribution-1"
# The item source-granularity literals. Owned HERE (not by the attribution
# config) so the config import graph stays acyclic
# (attribution -> analytics -> traffic -> integrations); the attribution
# config aliases these tokens, never re-literalizes them (invariant 2).
GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM: Final = "session_source_medium"
GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP: Final = "default_channel_group"
# Provider HTTP 400 detail substrings (casefolded) identifying a dimension
# compatibility rejection. The fallback classifier fires ONLY when one of
# these markers appears in the capped provider detail — a generic 400
# keeps the standard provider-error behavior (no fallback).
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


# Pinned C1 dataset ids + shapes. Both workstreams code against these exact
# tuples; changing one is a cross-workstream contract change.
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


class IntegrationSettings(BaseSettings):
    """Env-driven sync worker knobs (``INTEGRATION_`` env prefix).

    The OAuth client id/secret are deliberately NOT here: they are
    env-injected deployment secrets on the central ``Settings``, resolved
    only inside the OAuth exchange/refresh paths and never logged
    (invariant 6).
    """

    model_config = SettingsConfigDict(env_prefix="INTEGRATION_", extra="ignore")

    # --- Sync windows -----------------------------------------------------
    # Import the full Traffic reporting window on every normal sync. Provider
    # data still receives a separate short late-data revision pass below;
    # limiting the primary import to that revision span leaves new projects
    # with only one or two usable historical buckets after provider lag.
    sync_default_window_days: int = Field(default=28, gt=0)
    sync_backfill_max_days: int = Field(default=480, gt=0)
    # Dispatcher tick (default daily).
    sync_cadence_seconds: float = Field(default=86400.0, gt=0)
    # Recent trailing window re-synced (with a bumped resync_seq) to pick up
    # late provider revisions.
    sync_late_data_revision_days: int = Field(default=3, ge=0)

    # --- Provider paging + request budget ------------------------------------
    sync_page_size: int = Field(default=25000, gt=0)
    sync_request_timeout_seconds: float = Field(default=60.0, gt=0)
    sync_max_attempts: int = Field(default=4, gt=0)
    # Upper bound on resync_seq allocation retries after a unique conflict.
    # The connection-row FOR UPDATE lock makes a collision practically
    # unreachable; the bound guarantees the allocation loop terminates.
    sync_resync_alloc_max_attempts: int = Field(default=8, gt=0)

    # --- Queue lease/heartbeat -------------------------------------------------
    lease_ttl_seconds: float = Field(default=120.0, gt=0)
    heartbeat_interval_seconds: float = Field(default=30.0, gt=0)
    # Worker loop idle sleep (content/site-health poll knob analogue).
    poll_interval_seconds: float = Field(default=1.0, gt=0)
    # Retry backoff for retryable provider/refresh failures (I6).
    retry_base_delay_seconds: float = Field(default=30.0, gt=0)
    retry_max_delay_seconds: float = Field(default=900.0, gt=0)

    # --- Token refresh -----------------------------------------------------------
    # An access token expiring within this skew counts as near-expiry and is
    # refreshed (serialized per grant, spec section 2) before provider I/O.
    # (The OAuth state-nonce TTL lives with the OAuth transport settings in
    # ``config/oauth.py`` — ``oauth_settings.state_ttl_seconds``.)
    token_refresh_skew_seconds: float = Field(default=300.0, ge=0)

    # --- Import payload cap ------------------------------------------------------
    # Payloads are inline JSONB this pass (S3 offload keyed by payload_hash is
    # roadmap); over-cap payloads are rejected rather than truncated.
    max_inline_payload_bytes: int = Field(default=1_000_000, gt=0)

    # --- Per-provider rate limits (requests/minute) ------------------------------
    gsc_requests_per_minute: int = Field(default=200, gt=0)
    ga4_requests_per_minute: int = Field(default=60, gt=0)
    bing_requests_per_minute: int = Field(default=30, gt=0)
    shopify_requests_per_minute: int = Field(default=40, gt=0)

    # --- Shopify GraphQL page sizes ------------------------------------------------
    # Outer connection page size (products/orders per request) and the nested
    # first-page size for variants/line items. Nested continuation pages use
    # the nested size as well; every continuation call is paced.
    shopify_page_size: int = Field(default=50, gt=0)
    shopify_nested_page_size: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def _check_operational_bounds(self) -> IntegrationSettings:
        # Fail at startup, not mid-run: a heartbeat slower than the lease TTL
        # guarantees lease expiry during healthy work (same guard as content).
        if self.heartbeat_interval_seconds >= self.lease_ttl_seconds:
            raise ValueError(
                "heartbeat_interval_seconds must be shorter than lease_ttl_seconds"
            )
        if self.sync_default_window_days > self.sync_backfill_max_days:
            raise ValueError(
                "sync_default_window_days must not exceed sync_backfill_max_days"
            )
        if self.sync_late_data_revision_days > self.sync_backfill_max_days:
            raise ValueError(
                "sync_late_data_revision_days must not exceed sync_backfill_max_days"
            )
        if self.retry_max_delay_seconds < self.retry_base_delay_seconds:
            raise ValueError(
                "retry_max_delay_seconds must not be below retry_base_delay_seconds"
            )
        return self

    def requests_per_minute(self, provider: str) -> int:
        """Per-provider request budget; an unknown provider fails loud."""
        if provider not in INTEGRATION_PROVIDERS:
            raise ValueError(f"unknown integration provider: {provider!r}")
        return getattr(self, f"{provider}_requests_per_minute")

    def retry_delay(
        self, attempt: int, retry_after_seconds: float | None = None
    ) -> float:
        """Seconds before the next attempt: Retry-After if advised, else
        deterministic exponential backoff capped at the max (no RNG)."""
        cap = self.retry_max_delay_seconds
        if retry_after_seconds is not None:
            return min(retry_after_seconds, cap)
        return min(self.retry_base_delay_seconds * (2 ** max(0, attempt - 1)), cap)


integration_settings = IntegrationSettings()


def _integration_sync_run_model() -> type[IntegrationSyncRun]:
    # Imported lazily so this config module never imports a model at import
    # time (would create a config <-> models circular import).
    from app.models.integrations import IntegrationSyncRun

    return IntegrationSyncRun


def _integration_claim_order(model: type[IntegrationSyncRun]) -> tuple:
    # Deterministic claim order mirroring ``CONTENT_QUEUE_SPEC`` exactly:
    # priority, then FIFO by availability, then the randomized position.
    return (
        model.priority.desc(),
        model.available_at.asc(),
        model.randomized_position.asc(),
    )


# Parameterizes the one generic ``PostgresTaskQueue`` over
# ``IntegrationSyncRun`` rows with the integrations lease TTL + claim order.
INTEGRATION_QUEUE_SPEC: Final[PostgresQueueSpec[IntegrationSyncRun]] = (
    PostgresQueueSpec(
        model_ref=_integration_sync_run_model,
        lease_ttl=lambda: integration_settings.lease_ttl_seconds,
        claim_order=_integration_claim_order,
        max_attempts_error=ERROR_MAX_ATTEMPTS,
    )
)


# --- Provider -> data-API client dispatch registry (I11/I12) -----------------
# The integration worker's ``_build_client`` seam resolves each provider's
# data-API client through THIS config-owned registry (invariant 1: the
# provider vocabulary + dispatch live here, not in worker code). Builders
# are lazy so this config module never imports a connector at runtime (the
# same circular-import guard as ``_integration_sync_run_model``). Each
# builder accepts the ``transport`` test seam and returns a client exposing
# the shared paging contract — ``query_search_analytics(access_token=,
# property_ref=, dimensions=, start_date=, end_date=, start_row=)`` ->
# a page carrying ``payload`` + ``rows`` — mirroring the GSC reference
# client (app/connectors/integrations/gsc.py).


def _gsc_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.gsc import build_gsc_client

    return build_gsc_client(transport=transport)


def _ga4_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.ga4 import build_ga4_client

    return build_ga4_client(transport=transport)


def _bing_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.bing import build_bing_client

    return build_bing_client(transport=transport)


def _shopify_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.shopify import build_shopify_client

    return build_shopify_client(transport=transport)


INTEGRATION_CLIENT_BUILDERS: Final[dict[str, Callable[..., Any]]] = {
    INTEGRATION_PROVIDER_GSC: _gsc_client_builder,
    INTEGRATION_PROVIDER_GA4: _ga4_client_builder,
    INTEGRATION_PROVIDER_BING: _bing_client_builder,
    INTEGRATION_PROVIDER_SHOPIFY: _shopify_client_builder,
}

# Providers whose client also implements ``list_properties(access_token=)``
# — the property picker's discovery seam. Shopify is absent by design: its
# property IS the shop the grant was authorized for, already pinned onto
# ``account_ref`` by the connect flow. Bing is absent this pass (no
# property listing implemented against the Webmaster API).
INTEGRATION_PROPERTY_DISCOVERY_PROVIDERS: Final[frozenset[str]] = frozenset(
    {INTEGRATION_PROVIDER_GSC, INTEGRATION_PROVIDER_GA4}
)


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
