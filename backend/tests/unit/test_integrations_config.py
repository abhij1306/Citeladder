"""Integrations config: provider/transport vocabulary, OAuth endpoints,
pinned C1 dataset templates + dimension_key packing, sync-knob bounds, and
the queue spec (I1)."""

from __future__ import annotations

from urllib.parse import urlsplit

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.config.integrations_clients import (
    INTEGRATION_CLIENT_BUILDERS,
    INTEGRATION_QUEUE_SPEC,
    _integration_claim_order,
)
from app.core.config.integrations_contracts import (
    INTEGRATION_GRANT_STATUSES,
    INTEGRATION_IMPORTER_VERSION,
    INTEGRATION_SYNC_KINDS,
)
from app.core.config.integrations_datasets import (
    DATASET_BING_PAGE_DAILY,
    DATASET_BING_QUERY_DAILY,
    DATASET_GA4_CHANNEL_DAILY,
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_LANDING_DAILY,
    DATASET_GA4_REFERRER_DAILY,
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
    DATASET_GSC_COUNTRY_DAILY,
    DATASET_GSC_DEVICE_DAILY,
    DATASET_GSC_PAGE_DAILY,
    DATASET_GSC_QUERY_DAILY,
    DATASET_GSC_QUERY_PAGE_DAILY,
    DATASET_GSC_SEARCH_APPEARANCE_DAILY,
    DATASET_SHOPIFY_ORDERS,
    DATASET_SHOPIFY_PRODUCTS,
    GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
    GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
    INTEGRATION_DATASET_TEMPLATES,
    PAGING_MODE_CURSOR,
    PAGING_MODE_OFFSET,
    pack_dimension_key,
)
from app.core.config.integrations_settings import (
    IntegrationSettings,
)
from app.core.config.integrations_transport import (
    BING_API_BASE_URL,
    GA4_API_BASE_URL,
    GSC_API_BASE_URL,
    INTEGRATION_APPROVED_ENDPOINT_HOSTS,
    INTEGRATION_OAUTH_AUTHORIZE_URLS,
    INTEGRATION_OAUTH_REFRESHABLE,
    INTEGRATION_OAUTH_REVOKE_URLS,
    INTEGRATION_OAUTH_SCOPES,
    INTEGRATION_OAUTH_TOKEN_URLS,
    INTEGRATION_PROVIDER_BING,
    INTEGRATION_PROVIDER_GA4,
    INTEGRATION_PROVIDER_GSC,
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_PROVIDER_TRANSPORT,
    INTEGRATION_PROVIDERS,
    INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_TRANSPORT_MICROSOFT,
    INTEGRATION_TRANSPORT_SHOPIFY,
    INTEGRATION_TRANSPORTS,
    SHOPIFY_ADMIN_API_VERSION,
    is_shopify_shop_domain,
    normalize_shopify_shop_domain,
    shopify_admin_graphql_url,
    shopify_oauth_authorize_url,
    shopify_oauth_token_url,
)
from app.models.integrations import IntegrationSyncRun


def test_queue_spec_resolves_sync_run_model() -> None:
    assert INTEGRATION_QUEUE_SPEC.model is IntegrationSyncRun
    assert INTEGRATION_QUEUE_SPEC.lease_ttl() > 0
    assert INTEGRATION_QUEUE_SPEC.max_attempts_error == "max_attempts_exceeded"


def test_claim_order_mirrors_content_priority_fifo_position() -> None:
    order = _integration_claim_order(IntegrationSyncRun)
    assert len(order) == 3
    rendered = [str(clause) for clause in order]
    assert "priority DESC" in rendered[0]
    assert "available_at ASC" in rendered[1]
    assert "randomized_position ASC" in rendered[2]


def test_provider_transport_vocabulary_and_compatibility() -> None:
    assert INTEGRATION_PROVIDERS == frozenset({"gsc", "ga4", "bing", "shopify"})
    assert INTEGRATION_TRANSPORTS == frozenset(
        {"google_oauth", "microsoft_oauth", "shopify_oauth"}
    )
    # GSC + GA4 share the one Google grant; Bing rides the Microsoft grant;
    # Shopify rides its own per-shop offline-token grant.
    assert INTEGRATION_PROVIDER_TRANSPORT == {
        "gsc": INTEGRATION_TRANSPORT_GOOGLE,
        "ga4": INTEGRATION_TRANSPORT_GOOGLE,
        "bing": INTEGRATION_TRANSPORT_MICROSOFT,
        "shopify": INTEGRATION_TRANSPORT_SHOPIFY,
    }
    # Every provider maps to a known transport (no orphan vocabulary).
    assert set(INTEGRATION_PROVIDER_TRANSPORT) == INTEGRATION_PROVIDERS
    # Shopify's offline token is the one NON-refreshable transport.
    assert INTEGRATION_OAUTH_REFRESHABLE == {
        "google_oauth": True,
        "microsoft_oauth": True,
        "shopify_oauth": False,
    }


def test_status_and_kind_tokens() -> None:
    assert INTEGRATION_GRANT_STATUSES == frozenset(
        {"connected", "needs_reauth", "pending_revocation", "revoked", "error"}
    )
    assert INTEGRATION_SYNC_KINDS == frozenset({"scheduled", "on_demand", "backfill"})


def test_oauth_endpoints_per_transport_https_and_allow_listed() -> None:
    # The STATIC authorize/token maps stay single-tenant-only: Shopify's
    # endpoints are per-shop and resolved through the validated dynamic
    # builders. The revoke map covers every transport ("" = local-only).
    assert set(INTEGRATION_OAUTH_AUTHORIZE_URLS) == {
        INTEGRATION_TRANSPORT_GOOGLE,
        INTEGRATION_TRANSPORT_MICROSOFT,
    }
    assert set(INTEGRATION_OAUTH_TOKEN_URLS) == {
        INTEGRATION_TRANSPORT_GOOGLE,
        INTEGRATION_TRANSPORT_MICROSOFT,
    }
    assert set(INTEGRATION_OAUTH_REVOKE_URLS) == set(INTEGRATION_TRANSPORTS)
    for urls in (
        INTEGRATION_OAUTH_AUTHORIZE_URLS,
        INTEGRATION_OAUTH_TOKEN_URLS,
        INTEGRATION_OAUTH_REVOKE_URLS,
    ):
        for url in urls.values():
            if not url:
                continue
            parts = urlsplit(url)
            assert parts.scheme == "https"
            assert parts.hostname in INTEGRATION_APPROVED_ENDPOINT_HOSTS
    # Google supports remote revoke; Microsoft + Shopify do not (empty =
    # local-only disconnect).
    assert INTEGRATION_OAUTH_REVOKE_URLS[INTEGRATION_TRANSPORT_GOOGLE]
    assert INTEGRATION_OAUTH_REVOKE_URLS[INTEGRATION_TRANSPORT_MICROSOFT] == ""
    assert INTEGRATION_OAUTH_REVOKE_URLS[INTEGRATION_TRANSPORT_SHOPIFY] == ""


def test_shopify_dynamic_endpoint_builders_validate_the_shop_host() -> None:
    authorize = shopify_oauth_authorize_url("My-Shop")
    assert authorize == "https://my-shop.myshopify.com/admin/oauth/authorize"
    token = shopify_oauth_token_url("my-shop.myshopify.com")
    assert token == "https://my-shop.myshopify.com/admin/oauth/access_token"
    graphql = shopify_admin_graphql_url("my-shop")
    assert graphql == (
        f"https://my-shop.myshopify.com/admin/api/"
        f"{SHOPIFY_ADMIN_API_VERSION}/graphql.json"
    )
    # Hostile/non-canonical hosts are rejected before any URL is built.
    for hostile in (
        "shop.myshopify.com.evil.com",
        "myshopify.com",
        "a.b.myshopify.com",
        "",
    ):
        with pytest.raises(ValueError):
            normalize_shopify_shop_domain(hostile)
        with pytest.raises(ValueError):
            shopify_admin_graphql_url(hostile)
    # The dynamic-host allow-list check passes ONLY canonical shop hosts.
    assert is_shopify_shop_domain("a1.myshopify.com")
    assert not is_shopify_shop_domain("a1.myshopify.com.evil.com")
    assert not is_shopify_shop_domain("evil.myshopify.com.au")


def test_google_grant_combines_gsc_and_ga4_scopes() -> None:
    google_scopes = INTEGRATION_OAUTH_SCOPES[INTEGRATION_TRANSPORT_GOOGLE]
    assert "https://www.googleapis.com/auth/webmasters.readonly" in google_scopes
    assert "https://www.googleapis.com/auth/analytics.readonly" in google_scopes
    assert len(google_scopes) == 2
    # The Microsoft grant carries the pinned Bing Webmaster scope (I12)
    # and stays refreshable via offline_access.
    microsoft_scopes = INTEGRATION_OAUTH_SCOPES[INTEGRATION_TRANSPORT_MICROSOFT]
    assert "offline_access" in microsoft_scopes
    assert "https://webmaster.bing.com/api/webmaster.manage" in microsoft_scopes
    # bingads.manage is the ADS API scope — never requested here.
    assert all("bingads" not in scope for scope in microsoft_scopes)
    # The Shopify grant is read-only products + orders: no write scope and
    # no read_all_orders (least privilege).
    shopify_scopes = INTEGRATION_OAUTH_SCOPES[INTEGRATION_TRANSPORT_SHOPIFY]
    assert shopify_scopes == ("read_products", "read_orders")
    assert all("write" not in scope for scope in shopify_scopes)
    assert "read_all_orders" not in shopify_scopes


def test_dataset_templates_match_pinned_c1() -> None:
    expected = {
        DATASET_GSC_PAGE_DAILY: (INTEGRATION_PROVIDER_GSC, ("page", "date")),
        DATASET_GSC_QUERY_DAILY: (INTEGRATION_PROVIDER_GSC, ("query", "date")),
        DATASET_GSC_QUERY_PAGE_DAILY: (
            INTEGRATION_PROVIDER_GSC,
            ("query", "page", "date"),
        ),
        DATASET_GSC_SEARCH_APPEARANCE_DAILY: (
            INTEGRATION_PROVIDER_GSC,
            ("searchAppearance", "date"),
        ),
        DATASET_GSC_DEVICE_DAILY: (
            INTEGRATION_PROVIDER_GSC,
            ("device", "date"),
        ),
        DATASET_GSC_COUNTRY_DAILY: (
            INTEGRATION_PROVIDER_GSC,
            ("country", "date"),
        ),
        DATASET_GA4_CHANNEL_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("sessionDefaultChannelGroup", "date"),
        ),
        DATASET_GA4_SOURCE_MEDIUM_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("sessionSource", "sessionMedium", "date"),
        ),
        DATASET_GA4_REFERRER_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("pageReferrer", "date"),
        ),
        DATASET_GA4_LANDING_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("landingPage", "sessionSource", "sessionMedium", "date"),
        ),
        DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("sessionSource", "sessionMedium", "date"),
        ),
        DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("itemId", "sessionSource", "sessionMedium", "date"),
        ),
        DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY: (
            INTEGRATION_PROVIDER_GA4,
            ("itemId", "sessionDefaultChannelGroup", "date"),
        ),
        DATASET_BING_PAGE_DAILY: (INTEGRATION_PROVIDER_BING, ("page", "date")),
        DATASET_BING_QUERY_DAILY: (INTEGRATION_PROVIDER_BING, ("query", "date")),
        # Shopify entity feeds declare NO report dimensions/metrics.
        DATASET_SHOPIFY_PRODUCTS: (INTEGRATION_PROVIDER_SHOPIFY, ()),
        DATASET_SHOPIFY_ORDERS: (INTEGRATION_PROVIDER_SHOPIFY, ()),
    }
    assert set(INTEGRATION_DATASET_TEMPLATES) == set(expected)
    ga4_session_datasets = {
        DATASET_GA4_CHANNEL_DAILY,
        DATASET_GA4_SOURCE_MEDIUM_DAILY,
        DATASET_GA4_REFERRER_DAILY,
        DATASET_GA4_LANDING_DAILY,
    }
    for dataset, (provider, dimensions) in expected.items():
        template = INTEGRATION_DATASET_TEMPLATES[dataset]
        assert template.dataset == dataset
        assert template.provider == provider
        assert template.dimensions == dimensions
        if provider == INTEGRATION_PROVIDER_GSC:
            assert template.metrics == ("clicks", "impressions", "ctr", "position")
        elif dataset in ga4_session_datasets:
            assert template.metrics == ("sessions", "engagedSessions", "keyEvents")
        elif dataset == DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY:
            assert template.metrics == ("transactions", "purchaseRevenue", "sessions")
        elif provider == INTEGRATION_PROVIDER_GA4:
            # Both item ecommerce templates carry the item metric set.
            assert template.metrics == ("itemRevenue", "itemsPurchased")
        elif provider == INTEGRATION_PROVIDER_SHOPIFY:
            assert template.metrics == ()
        else:
            assert template.metrics == ("clicks", "impressions")
    # The Bing api_method literals are the pinned endpoint names.
    assert (
        INTEGRATION_DATASET_TEMPLATES[DATASET_BING_PAGE_DAILY].api_method
        == "GetPageStats"
    )
    assert (
        INTEGRATION_DATASET_TEMPLATES[DATASET_BING_QUERY_DAILY].api_method
        == "GetQueryStats"
    )
    # Paging modes: every metric dataset pages by offset; the Shopify feeds
    # page by GraphQL cursor.
    for dataset, template in INTEGRATION_DATASET_TEMPLATES.items():
        expected_mode = (
            PAGING_MODE_CURSOR
            if dataset in {DATASET_SHOPIFY_PRODUCTS, DATASET_SHOPIFY_ORDERS}
            else PAGING_MODE_OFFSET
        )
        assert template.paging_mode == expected_mode
    assert (
        INTEGRATION_DATASET_TEMPLATES[DATASET_SHOPIFY_PRODUCTS].api_method
        == "ShopifyProducts"
    )
    assert (
        INTEGRATION_DATASET_TEMPLATES[DATASET_SHOPIFY_ORDERS].api_method
        == "ShopifyOrders"
    )


def test_ga4_item_attribution_capability_tokens() -> None:
    # The capability key/version + granularity + classifier markers are
    # config-owned vocabulary (never re-literalized by consumers).
    assert GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY
    assert GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION
    assert GA4_ITEM_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM == "session_source_medium"
    assert GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP == "default_channel_group"
    # The fallback classifier fires only on an explicit incompatibility
    # marker in the capped provider detail.
    assert GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS
    assert all(
        marker == marker.casefold()
        for marker in GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS
    )


def test_pack_dimension_key_single_bare_multi_joined_in_order() -> None:
    # Single-dimension rows use the bare value.
    assert pack_dimension_key(["https://example.com/page"]) == (
        "https://example.com/page"
    )
    # Multi-dimension rows join in the declared template order with " | ".
    landing = INTEGRATION_DATASET_TEMPLATES[DATASET_GA4_LANDING_DAILY]
    row = dict(
        zip(landing.dimensions, ["/lp", "google", "organic", "20260723"], strict=True)
    )
    assert pack_dimension_key([row[dim] for dim in landing.dimensions]) == (
        "/lp | google | organic | 20260723"
    )
    source_medium = INTEGRATION_DATASET_TEMPLATES[DATASET_GA4_SOURCE_MEDIUM_DAILY]
    row = dict(
        zip(source_medium.dimensions, ["chatgpt", "referral", "20260723"], strict=True)
    )
    assert pack_dimension_key([row[dim] for dim in source_medium.dimensions]) == (
        "chatgpt | referral | 20260723"
    )


def test_allow_list_covers_provider_api_hosts_and_is_host_only() -> None:
    for host in INTEGRATION_APPROVED_ENDPOINT_HOSTS:
        assert "://" not in host and "/" not in host
    assert urlsplit(GSC_API_BASE_URL).hostname in INTEGRATION_APPROVED_ENDPOINT_HOSTS
    assert urlsplit(GA4_API_BASE_URL).hostname in INTEGRATION_APPROVED_ENDPOINT_HOSTS
    assert urlsplit(BING_API_BASE_URL).hostname in INTEGRATION_APPROVED_ENDPOINT_HOSTS


def test_client_builder_registry_covers_every_provider() -> None:
    # The worker's dispatch seam resolves through this config-owned map.
    assert set(INTEGRATION_CLIENT_BUILDERS) == INTEGRATION_PROVIDERS
    for provider, builder in INTEGRATION_CLIENT_BUILDERS.items():
        client = builder(transport=None)
        assert client is not None, provider


def test_importer_version_token() -> None:
    assert INTEGRATION_IMPORTER_VERSION
    assert isinstance(INTEGRATION_IMPORTER_VERSION, str)


def test_settings_env_prefix_and_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEGRATION_SYNC_PAGE_SIZE", "5000")
    configured = IntegrationSettings(_env_file=None)
    assert configured.sync_page_size == 5000
    assert configured.sync_default_window_days == 28
    assert configured.sync_max_attempts >= 1
    assert configured.lease_ttl_seconds > configured.heartbeat_interval_seconds

    # A heartbeat not strictly below the lease TTL fails at startup.
    monkeypatch.setenv("INTEGRATION_LEASE_TTL_SECONDS", "120")
    monkeypatch.setenv("INTEGRATION_HEARTBEAT_INTERVAL_SECONDS", "120")
    with pytest.raises(ValidationError):
        IntegrationSettings(_env_file=None)

    # A default window wider than the backfill clamp is nonsensical.
    monkeypatch.setenv("INTEGRATION_HEARTBEAT_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("INTEGRATION_SYNC_DEFAULT_WINDOW_DAYS", "999")
    monkeypatch.setenv("INTEGRATION_SYNC_BACKFILL_MAX_DAYS", "30")
    with pytest.raises(ValidationError):
        IntegrationSettings(_env_file=None)


def test_requests_per_minute_per_provider() -> None:
    settings = IntegrationSettings(_env_file=None)
    for provider in INTEGRATION_PROVIDERS:
        assert settings.requests_per_minute(provider) > 0
    with pytest.raises(ValueError, match="unknown integration provider"):
        settings.requests_per_minute("not-a-provider")


def test_settings_oauth_client_fields_env_injected_default_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A developer's real credentials must not leak into this test.
    for var in (
        "INTEGRATION_GOOGLE_CLIENT_ID",
        "INTEGRATION_GOOGLE_CLIENT_SECRET",
        "INTEGRATION_MICROSOFT_CLIENT_ID",
        "INTEGRATION_MICROSOFT_CLIENT_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)
    fresh = Settings(_env_file=None)
    assert fresh.integration_google_client_id == ""
    assert fresh.integration_google_client_secret == ""
    assert fresh.integration_microsoft_client_id == ""
    assert fresh.integration_microsoft_client_secret == ""

    monkeypatch.setenv("INTEGRATION_GOOGLE_CLIENT_ID", "gid")
    monkeypatch.setenv("INTEGRATION_GOOGLE_CLIENT_SECRET", "gsecret")
    monkeypatch.setenv("INTEGRATION_MICROSOFT_CLIENT_ID", "mid")
    monkeypatch.setenv("INTEGRATION_MICROSOFT_CLIENT_SECRET", "msecret")
    configured = Settings(_env_file=None)
    assert configured.integration_google_client_id == "gid"
    assert configured.integration_google_client_secret == "gsecret"
    assert configured.integration_microsoft_client_id == "mid"
    assert configured.integration_microsoft_client_secret == "msecret"
