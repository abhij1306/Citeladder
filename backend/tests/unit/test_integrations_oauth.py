"""Integration OAuth connector: exchange / refresh / revoke / probe (mocked).

Fully offline — a fake OAuth server is injected via ``httpx.MockTransport``
(the established connector test seam). Asserts the token round-trip shape,
the config-owned error mapping, the approved-endpoint SSRF guard, and that
no token or client secret ever reaches a log line (invariant 6).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.connectors.integrations.oauth import (
    IntegrationOAuthClient,
    IntegrationOAuthError,
    build_oauth_client,
    oauth_client_configured,
    verify_shopify_callback_hmac,
)
from app.core.config import settings
from app.core.config.integrations_contracts import (
    ERROR_GRANT_AUTH_FAILED,
    ERROR_PROVIDER_API,
    ERROR_RATE_LIMITED,
    ERROR_UNAPPROVED_ENDPOINT,
)
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_TOKEN_URLS,
    INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_TRANSPORT_MICROSOFT,
    INTEGRATION_TRANSPORT_SHOPIFY,
    SHOPIFY_ADMIN_API_VERSION,
    is_shopify_shop_domain,
    normalize_shopify_shop_domain,
    shopify_admin_graphql_url,
    shopify_oauth_authorize_url,
    shopify_oauth_token_url,
)

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integrations"
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
_GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_GSC_SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"

_GOOGLE_CLIENT_ID = "test-google-client-id"
_GOOGLE_CLIENT_SECRET = "test-google-client-secret"  # pragma: allowlist secret
_AUTH_CODE = "fake-authorization-code"  # pragma: allowlist secret


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


@pytest.fixture
def _google_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "integration_google_client_id", _GOOGLE_CLIENT_ID)
    monkeypatch.setattr(
        settings, "integration_google_client_secret", _GOOGLE_CLIENT_SECRET
    )


def _token_transport(
    handler_payload: dict, *, status: int = 200, captured: list | None = None
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(status, json=handler_payload)

    return httpx.MockTransport(handler)


def _form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode("utf-8"))


@pytest.mark.asyncio
async def test_exchange_code_roundtrip(_google_credentials: None) -> None:
    captured: list[httpx.Request] = []
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=_token_transport(
            _fixture("google_token_response.json"), captured=captured
        ),
    )
    bundle = await client.exchange_code(
        code=_AUTH_CODE, redirect_uri="http://testserver/callback"
    )
    expected = _fixture("google_token_response.json")
    assert bundle.access_token == expected["access_token"]
    assert bundle.refresh_token == expected["refresh_token"]
    assert bundle.expires_in == 3600
    assert bundle.granted_scopes == (
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    )
    (request,) = captured
    assert str(request.url) == _GOOGLE_TOKEN_URL
    assert request.method == "POST"
    form = _form(request)
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == [_AUTH_CODE]
    assert form["redirect_uri"] == ["http://testserver/callback"]
    assert form["client_id"] == [_GOOGLE_CLIENT_ID]


@pytest.mark.asyncio
async def test_exchange_code_error_surfaces_code_not_secrets(
    _google_credentials: None, caplog: pytest.LogCaptureFixture
) -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=_token_transport(_fixture("google_token_error.json"), status=400),
    )
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(IntegrationOAuthError) as excinfo:
            await client.exchange_code(
                code=_AUTH_CODE, redirect_uri="http://testserver/callback"
            )
    exc = excinfo.value
    assert exc.error_code == ERROR_PROVIDER_API
    assert exc.retryable is False
    # The capped provider error detail is surfaced; secrets never are.
    assert "invalid_grant" in str(exc)
    assert _GOOGLE_CLIENT_SECRET not in str(exc)
    assert _AUTH_CODE not in str(exc)
    assert _GOOGLE_CLIENT_SECRET not in caplog.text
    assert _AUTH_CODE not in caplog.text


@pytest.mark.asyncio
async def test_exchange_code_rate_limited(_google_credentials: None) -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=_token_transport({"error": "rate_limit"}, status=429),
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.exchange_code(code=_AUTH_CODE, redirect_uri="http://t/cb")
    assert excinfo.value.error_code == ERROR_RATE_LIMITED
    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_exchange_code_missing_access_token(_google_credentials: None) -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=_token_transport({"token_type": "Bearer"}),
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.exchange_code(code=_AUTH_CODE, redirect_uri="http://t/cb")
    assert excinfo.value.error_code == ERROR_PROVIDER_API


@pytest.mark.asyncio
async def test_refresh_carries_rotated_refresh_token(_google_credentials: None) -> None:
    payload = {
        "access_token": "fake-new-access-token",  # pragma: allowlist secret
        "refresh_token": "fake-rotated-refresh-token",  # pragma: allowlist secret
        "expires_in": 1800,
        "scope": "scope-a scope-b",
    }
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE, transport=_token_transport(payload)
    )
    bundle = await client.refresh(refresh_token="fake-old-refresh-token")
    assert bundle.access_token == "fake-new-access-token"
    assert bundle.refresh_token == "fake-rotated-refresh-token"
    assert bundle.expires_in == 1800
    assert bundle.granted_scopes == ("scope-a", "scope-b")


@pytest.mark.asyncio
async def test_refresh_keeps_original_when_provider_omits_it(
    _google_credentials: None,
) -> None:
    payload = {"access_token": "fake-new-access-token", "expires_in": "3600"}
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE, transport=_token_transport(payload)
    )
    bundle = await client.refresh(refresh_token="fake-old-refresh-token")
    assert bundle.refresh_token == "fake-old-refresh-token"
    assert bundle.expires_in == 3600


@pytest.mark.asyncio
async def test_refresh_unauthorized_maps_to_grant_auth_failed(
    _google_credentials: None,
) -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=_token_transport(_fixture("google_token_error.json"), status=401),
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.refresh(refresh_token="fake-old-refresh-token")
    assert excinfo.value.error_code == ERROR_GRANT_AUTH_FAILED
    assert excinfo.value.retryable is False


@pytest.mark.asyncio
async def test_revoke_posts_token_to_config_url() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE, transport=httpx.MockTransport(handler)
    )
    await client.revoke(token="fake-refresh-token-to-revoke")
    (request,) = captured
    assert str(request.url) == _GOOGLE_REVOKE_URL
    assert _form(request)["token"] == ["fake-refresh-token-to-revoke"]


@pytest.mark.asyncio
async def test_revoke_failure_raises() -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=httpx.MockTransport(lambda _request: httpx.Response(500)),
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.revoke(token="fake-token")
    assert excinfo.value.error_code == ERROR_PROVIDER_API
    assert excinfo.value.retryable is True


@pytest.mark.asyncio
async def test_revoke_microsoft_has_no_remote_endpoint() -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP call may be issued for a Microsoft revoke")

    client = build_oauth_client(
        INTEGRATION_TRANSPORT_MICROSOFT, transport=httpx.MockTransport(fail)
    )
    with pytest.raises(IntegrationOAuthError, match="no remote revoke endpoint"):
        await client.revoke(token="fake-token")


@pytest.mark.asyncio
async def test_probe_access_token_sends_bearer_header() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_fixture("gsc_sites_response.json"))

    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE, transport=httpx.MockTransport(handler)
    )
    await client.probe_access_token(access_token="fake-probe-access-token")
    (request,) = captured
    assert str(request.url) == _GSC_SITES_URL
    assert request.method == "GET"
    assert request.headers["authorization"] == "Bearer fake-probe-access-token"


@pytest.mark.asyncio
async def test_probe_access_token_unauthorized() -> None:
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_GOOGLE,
        transport=httpx.MockTransport(lambda _request: httpx.Response(401)),
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.probe_access_token(access_token="fake-expired-token")
    assert excinfo.value.error_code == ERROR_GRANT_AUTH_FAILED


@pytest.mark.asyncio
async def test_unapproved_endpoint_host_rejected(
    _google_credentials: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may leave for an unapproved host")

    monkeypatch.setitem(
        INTEGRATION_OAUTH_TOKEN_URLS,
        INTEGRATION_TRANSPORT_GOOGLE,
        "https://169.254.169.254/latest/token",
    )
    client = IntegrationOAuthClient(
        INTEGRATION_TRANSPORT_GOOGLE, transport=httpx.MockTransport(fail)
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.exchange_code(code=_AUTH_CODE, redirect_uri="http://t/cb")
    assert excinfo.value.error_code == ERROR_UNAPPROVED_ENDPOINT


def test_oauth_client_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "integration_google_client_id", "id")
    monkeypatch.setattr(settings, "integration_google_client_secret", "secret")
    assert oauth_client_configured(INTEGRATION_TRANSPORT_GOOGLE) is True
    monkeypatch.setattr(settings, "integration_google_client_secret", "")
    assert oauth_client_configured(INTEGRATION_TRANSPORT_GOOGLE) is False


def test_unknown_transport_rejected() -> None:
    with pytest.raises(IntegrationOAuthError):
        IntegrationOAuthClient("netscape_oauth")


# ---------------------------------------------------------------------------
# Shopify transport: dynamic per-shop endpoints + non-refreshable offline
# token + callback HMAC (commerce suite WS-B task 2).
# ---------------------------------------------------------------------------

_SHOPIFY_CLIENT_ID = "test-shopify-client-id"
_SHOPIFY_CLIENT_SECRET = "test-shopify-client-secret"  # pragma: allowlist secret
_SHOP = "volt-city.myshopify.com"


@pytest.fixture
def _shopify_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "integration_shopify_client_id", _SHOPIFY_CLIENT_ID)
    monkeypatch.setattr(
        settings, "integration_shopify_client_secret", _SHOPIFY_CLIENT_SECRET
    )


def test_shopify_shop_domain_normalization() -> None:
    assert normalize_shopify_shop_domain("volt-city") == _SHOP
    assert normalize_shopify_shop_domain("  Volt-City.MyShopify.com ") == _SHOP
    assert normalize_shopify_shop_domain("https://volt-city.myshopify.com/admin") == (
        _SHOP
    )
    assert is_shopify_shop_domain(_SHOP) is True


def test_shopify_shop_domain_hostile_rejected() -> None:
    for hostile in (
        "",
        "myshopify.com",
        "shop.myshopify.com.evil.com",
        "a.b.myshopify.com",
        "volt_city.myshopify.com",
        "-volt.myshopify.com",
        "VOLT.myshopify.com.attacker.example",
    ):
        with pytest.raises(ValueError):
            normalize_shopify_shop_domain(hostile)
        assert is_shopify_shop_domain(hostile) is False


def test_shopify_dynamic_endpoint_builders() -> None:
    assert shopify_oauth_token_url("volt-city") == (
        f"https://{_SHOP}/admin/oauth/access_token"
    )
    assert shopify_oauth_authorize_url(_SHOP) == (
        f"https://{_SHOP}/admin/oauth/authorize"
    )
    assert shopify_admin_graphql_url(_SHOP) == (
        f"https://{_SHOP}/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json"
    )
    # The host is validated BEFORE interpolation — a hostile shop never
    # reaches a URL (SSRF policy for the one dynamic host).
    with pytest.raises(ValueError):
        shopify_oauth_token_url("shop.myshopify.com.evil.com")


def test_shopify_client_requires_canonical_shop(_shopify_credentials: None) -> None:
    with pytest.raises(IntegrationOAuthError) as excinfo:
        build_oauth_client(INTEGRATION_TRANSPORT_SHOPIFY, provider_account_ref="")
    assert excinfo.value.error_code == ERROR_PROVIDER_API
    with pytest.raises(IntegrationOAuthError):
        build_oauth_client(
            INTEGRATION_TRANSPORT_SHOPIFY,
            provider_account_ref="shop.myshopify.com.evil.com",
        )
    # A bare shop name is accepted and canonicalized eagerly.
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_SHOPIFY, provider_account_ref="Volt-City"
    )
    assert client._provider_account_ref == _SHOP


@pytest.mark.asyncio
async def test_shopify_exchange_form_is_exact(_shopify_credentials: None) -> None:
    captured: list[httpx.Request] = []
    payload = {
        "access_token": "shpat_fake-offline-token",  # pragma: allowlist secret
        "scope": "read_products,read_orders",
    }
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_SHOPIFY,
        transport=_token_transport(payload, captured=captured),
        provider_account_ref=_SHOP,
    )
    bundle = await client.exchange_code(
        code=_AUTH_CODE, redirect_uri="http://testserver/callback"
    )
    assert bundle.access_token == "shpat_fake-offline-token"
    # Offline token: no refresh token, no expiry, comma-joined scopes.
    assert bundle.refresh_token == ""
    assert bundle.expires_in is None
    assert bundle.granted_scopes == ("read_products", "read_orders")
    (request,) = captured
    assert str(request.url) == f"https://{_SHOP}/admin/oauth/access_token"
    form = _form(request)
    # Shopify's exchange form is EXACTLY client_id/client_secret/code — no
    # grant_type and no redirect_uri.
    assert set(form) == {"client_id", "client_secret", "code"}
    assert form["client_id"] == [_SHOPIFY_CLIENT_ID]
    assert form["client_secret"] == [_SHOPIFY_CLIENT_SECRET]
    assert form["code"] == [_AUTH_CODE]


@pytest.mark.asyncio
async def test_shopify_refresh_raises_without_any_request(
    _shopify_credentials: None,
) -> None:
    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Shopify offline tokens are never refreshed")

    client = build_oauth_client(
        INTEGRATION_TRANSPORT_SHOPIFY,
        transport=httpx.MockTransport(fail),
        provider_account_ref=_SHOP,
    )
    with pytest.raises(IntegrationOAuthError) as excinfo:
        await client.refresh(refresh_token="")
    assert excinfo.value.error_code == ERROR_PROVIDER_API


@pytest.mark.asyncio
async def test_shopify_token_url_passes_ssrf_guard(_shopify_credentials: None) -> None:
    # The per-shop token URL is the ONE dynamic host; it must pass the
    # allow-list via the strict canonical-domain check (not a wildcard).
    captured: list[httpx.Request] = []
    client = build_oauth_client(
        INTEGRATION_TRANSPORT_SHOPIFY,
        transport=_token_transport({"access_token": "shpat_x"}, captured=captured),
        provider_account_ref=_SHOP,
    )
    await client.exchange_code(code=_AUTH_CODE, redirect_uri="http://t/cb")
    assert len(captured) == 1


def _shopify_callback_params(secret: str, **params: str) -> dict[str, str]:
    canonical = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {**params, "hmac": signature}


def test_shopify_callback_hmac_verified(_shopify_credentials: None) -> None:
    params = _shopify_callback_params(
        _SHOPIFY_CLIENT_SECRET,
        code=_AUTH_CODE,
        shop=_SHOP,
        state="fake-state",
        timestamp="1700000000",
    )
    assert verify_shopify_callback_hmac(params) is True


def test_shopify_callback_hmac_tampered_param_fails(
    _shopify_credentials: None,
) -> None:
    params = _shopify_callback_params(
        _SHOPIFY_CLIENT_SECRET, code=_AUTH_CODE, shop=_SHOP, state="fake-state"
    )
    params["shop"] = "other-shop.myshopify.com"
    assert verify_shopify_callback_hmac(params) is False


def test_shopify_callback_hmac_missing_or_unsigned_fails(
    _shopify_credentials: None,
) -> None:
    assert verify_shopify_callback_hmac({"code": _AUTH_CODE, "shop": _SHOP}) is False
    assert (
        verify_shopify_callback_hmac(
            {"code": _AUTH_CODE, "shop": _SHOP, "hmac": "not-a-real-hmac"}
        )
        is False
    )


def test_shopify_callback_hmac_fails_closed_without_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "integration_shopify_client_secret", "")
    params = _shopify_callback_params("anything", code=_AUTH_CODE, shop=_SHOP)
    assert verify_shopify_callback_hmac(params) is False
