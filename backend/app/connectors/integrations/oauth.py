"""Integration OAuth transport client (spec: docs/roadmap/integrations.md §2).

Performs the authorization-code exchange, refresh, remote revoke, and the
cheap authenticated grant probe behind ``POST /integrations/{id}/test`` — per
OAuth transport (``google_oauth`` covering the shared GSC+GA4 grant;
``microsoft_oauth`` covering Bing) over httpx with an injected transport
(test seam, mirroring ``connectors/discovery_models/factory.py``).

Invariant 6: access/refresh tokens and the env-injected client secret pass
through this module but are NEVER logged — error surfaces carry only HTTP
status codes and config-owned error tokens. Authorization headers are set
per-request and never logged. Endpoints come from
``app.core.config.integrations_transport`` and every URL is checked against the
approved-host allow-list before a request is issued (SSRF policy).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass, field

import httpx

from app.connectors.integrations._http import (
    IntegrationApiError,
    assert_approved_url,
    classify_status,
    oauth_error_detail,
)
from app.core.config import settings
from app.core.config.integrations_contracts import (
    ERROR_PROVIDER_API,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    GSC_API_BASE_URL,
    GSC_SITES_PATH,
    INTEGRATION_OAUTH_REVOKE_URLS,
    INTEGRATION_OAUTH_TOKEN_URLS,
    INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_TRANSPORT_MICROSOFT,
    INTEGRATION_TRANSPORT_SHOPIFY,
    INTEGRATION_TRANSPORTS,
    normalize_shopify_shop_domain,
    shopify_oauth_token_url,
)

# Cheap, read-only, scope-minimal probe path validating a Google grant's
# access token (the one shared Google grant carries ``webmasters.readonly``
# for both the GSC and the GA4 connection, so the site list validates the
# grant behind either connection). The host is config-owned
# (``GSC_API_BASE_URL``) and allow-listed. The Microsoft-grant probe
# (``GetSites``) lives with the Bing data-API client (I12).
_GSC_SITES_PROBE_PATH = GSC_SITES_PATH


class IntegrationOAuthError(IntegrationApiError):
    """An OAuth transport call failed; carries a config-owned error token."""


@dataclass(frozen=True)
class OAuthTokenBundle:
    """Tokens + metadata from an exchange/refresh. NEVER logged (invariant 6)."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_in: int | None = None
    granted_scopes: tuple[str, ...] = ()


def oauth_client_credentials(transport: str) -> tuple[str, str]:
    """Resolve the transport's env-injected client id/secret (never logged)."""
    if transport == INTEGRATION_TRANSPORT_GOOGLE:
        return (
            settings.integration_google_client_id,
            settings.integration_google_client_secret,
        )
    if transport == INTEGRATION_TRANSPORT_MICROSOFT:
        return (
            settings.integration_microsoft_client_id,
            settings.integration_microsoft_client_secret,
        )
    if transport == INTEGRATION_TRANSPORT_SHOPIFY:
        return (
            settings.integration_shopify_client_id,
            settings.integration_shopify_client_secret,
        )
    raise IntegrationOAuthError(
        f"unknown OAuth transport: {transport!r}", error_code=ERROR_PROVIDER_API
    )


def oauth_client_configured(transport: str) -> bool:
    """True when the transport's client id + secret are env-configured.

    Never logs the underlying values (invariant 6).
    """
    client_id, client_secret = oauth_client_credentials(transport)
    return bool(client_id and client_secret)


def _assert_approved_url(url: str) -> None:
    """SSRF guard: integration clients only call allow-listed hosts (config)."""
    assert_approved_url(url, label="OAuth", error_type=IntegrationOAuthError)


def verify_shopify_callback_hmac(params: Mapping[str, str]) -> bool:
    """Verify the Shopify OAuth callback's ``hmac`` query parameter.

    Shopify signs the callback query string with the app client secret:
    HMAC-SHA256 hex over the canonical parameter string (every query param
    EXCEPT ``hmac``, sorted by key, joined as ``key=value`` with ``&``).
    Comparison is constant-time. The client secret stays connector-owned:
    it is resolved here, used here, and never logged or returned
    (invariant 6). A missing secret or missing/malformed ``hmac`` fails
    closed (``False``).
    """
    provided = str(params.get("hmac") or "").strip()
    _, client_secret = oauth_client_credentials(INTEGRATION_TRANSPORT_SHOPIFY)
    if not provided or not client_secret:
        return False
    canonical = "&".join(
        f"{key}={value}" for key, value in sorted(params.items()) if key != "hmac"
    )
    expected = hmac.new(
        client_secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)


def _split_scopes(value: object, *, transport_kind: str) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    # Shopify joins granted scopes with commas; Google/Microsoft use spaces.
    separator = "," if transport_kind == INTEGRATION_TRANSPORT_SHOPIFY else " "
    return tuple(scope for scope in value.split(separator) if scope)


def _coerce_expires_in(value: object) -> int | None:
    """Coerce a JSON ``expires_in`` (number or numeric string) to seconds.

    A JSON payload yields int/float/str for this field; anything else (or
    a negative value) means the provider sent no usable expiry — ``None``.
    """
    if isinstance(value, (int, float)):
        seconds = int(value)
    elif isinstance(value, str):
        try:
            seconds = int(value)
        except ValueError:
            return None
    else:
        return None
    return seconds if seconds >= 0 else None


class IntegrationOAuthClient:
    """OAuth client for one integration transport.

    ``transport`` is a test seam (``httpx.MockTransport``); production passes
    nothing and the client uses the real network.

    ``provider_account_ref`` carries the per-account OAuth target: for the
    Shopify transport it is the canonical ``{shop}.myshopify.com`` host and
    is REQUIRED (validated eagerly here — a missing or non-canonical shop
    fails construction rather than the first request). Google/Microsoft are
    single-tenant transports and pass the default empty ref.
    """

    def __init__(
        self,
        transport_kind: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        provider_account_ref: str = "",
    ) -> None:
        if transport_kind not in INTEGRATION_TRANSPORTS:
            raise IntegrationOAuthError(
                f"unknown OAuth transport: {transport_kind!r}",
                error_code=ERROR_PROVIDER_API,
            )
        if transport_kind == INTEGRATION_TRANSPORT_SHOPIFY:
            try:
                provider_account_ref = normalize_shopify_shop_domain(
                    provider_account_ref
                )
            except ValueError as exc:
                raise IntegrationOAuthError(
                    "Shopify OAuth client requires a canonical shop host",
                    error_code=ERROR_PROVIDER_API,
                ) from exc
        self._transport_kind = transport_kind
        self._transport = transport
        self._provider_account_ref = provider_account_ref

    def _token_url(self) -> str:
        """The transport's token endpoint (per-shop for Shopify)."""
        if self._transport_kind == INTEGRATION_TRANSPORT_SHOPIFY:
            return shopify_oauth_token_url(self._provider_account_ref)
        return INTEGRATION_OAUTH_TOKEN_URLS[self._transport_kind]

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            timeout=integration_settings.sync_request_timeout_seconds,
        )

    async def _post_form(self, url: str, data: dict[str, str], *, action: str) -> dict:
        """POST a form body and return the JSON object, raising on failure.

        The request carries credentials (client secret, codes, tokens) in
        ``data`` — none of it is ever logged; raised errors carry only the
        HTTP status and the provider's capped error code/description.
        """
        _assert_approved_url(url)
        try:
            async with self._http_client() as client:
                response = await client.post(url, data=data)
        except httpx.HTTPError as exc:
            raise IntegrationOAuthError(
                f"OAuth {action} request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            error_code, retryable = classify_status(response.status_code)
            try:
                detail = oauth_error_detail(response.json())
            except ValueError:
                detail = ""
            suffix = f" ({detail})" if detail else ""
            raise IntegrationOAuthError(
                f"OAuth {action} returned HTTP {response.status_code}{suffix}",
                error_code=error_code,
                retryable=retryable,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationOAuthError(
                f"OAuth {action} returned a non-JSON body",
                error_code=ERROR_PROVIDER_API,
            ) from exc
        if not isinstance(payload, dict):
            raise IntegrationOAuthError(
                f"OAuth {action} returned an unexpected body",
                error_code=ERROR_PROVIDER_API,
            )
        return payload

    async def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthTokenBundle:
        """Exchange an authorization code for tokens at the token endpoint.

        Shopify's exchange form is exactly ``client_id``/``client_secret``/
        ``code`` — NO ``grant_type`` and NO ``redirect_uri`` — and its
        offline token response carries no ``refresh_token``/``expires_in``;
        that token is usable as-is (the transport is non-refreshable, see
        ``INTEGRATION_OAUTH_REFRESHABLE``).
        """
        client_id, client_secret = oauth_client_credentials(self._transport_kind)
        if self._transport_kind == INTEGRATION_TRANSPORT_SHOPIFY:
            form = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            }
        else:
            form = {
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            }
        payload = await self._post_form(self._token_url(), form, action="code exchange")
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise IntegrationOAuthError(
                "OAuth code exchange returned no access_token",
                error_code=ERROR_PROVIDER_API,
            )
        return OAuthTokenBundle(
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or ""),
            expires_in=_coerce_expires_in(payload.get("expires_in")),
            granted_scopes=_split_scopes(
                payload.get("scope"), transport_kind=self._transport_kind
            ),
        )

    async def refresh(self, *, refresh_token: str) -> OAuthTokenBundle:
        """Exchange a refresh token for a fresh access token.

        A provider may omit ``refresh_token`` from the response (Google keeps
        the original grant); the passed token is carried over in that case.

        The Shopify transport is non-refreshable (its offline token never
        expires and carries no refresh token): calling this for Shopify is a
        programming error and raises instead of issuing a request.
        """
        if self._transport_kind == INTEGRATION_TRANSPORT_SHOPIFY:
            raise IntegrationOAuthError(
                "Shopify offline access tokens are not refreshable",
                error_code=ERROR_PROVIDER_API,
            )
        client_id, client_secret = oauth_client_credentials(self._transport_kind)
        payload = await self._post_form(
            self._token_url(),
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            action="token refresh",
        )
        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise IntegrationOAuthError(
                "OAuth token refresh returned no access_token",
                error_code=ERROR_PROVIDER_API,
            )
        return OAuthTokenBundle(
            access_token=access_token,
            refresh_token=str(payload.get("refresh_token") or "") or refresh_token,
            expires_in=_coerce_expires_in(payload.get("expires_in")),
            granted_scopes=_split_scopes(
                payload.get("scope"), transport_kind=self._transport_kind
            ),
        )

    async def revoke(self, *, token: str) -> None:
        """Remotely revoke a grant token (RFC 7009; Google-only).

        The Microsoft identity platform exposes no grant-revocation endpoint —
        its config URL is intentionally empty and the caller must take the
        documented local-only path instead of calling this.
        """
        url = INTEGRATION_OAUTH_REVOKE_URLS[self._transport_kind]
        if not url:
            raise IntegrationOAuthError(
                f"transport {self._transport_kind} has no remote revoke endpoint",
                error_code=ERROR_PROVIDER_API,
            )
        _assert_approved_url(url)
        try:
            async with self._http_client() as client:
                response = await client.post(url, data={"token": token})
        except httpx.HTTPError as exc:
            raise IntegrationOAuthError(
                f"OAuth revoke request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            error_code, retryable = classify_status(response.status_code)
            raise IntegrationOAuthError(
                f"OAuth revoke returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
            )

    async def probe_access_token(self, *, access_token: str) -> None:
        """Cheap authenticated probe validating a Google grant's access token.

        GETs the GSC site list with the Bearer token (never logged). Raises
        ``IntegrationOAuthError`` on any failure.
        """
        url = f"{GSC_API_BASE_URL}{_GSC_SITES_PROBE_PATH}"
        _assert_approved_url(url)
        try:
            async with self._http_client() as client:
                response = await client.get(
                    url, headers={"Authorization": f"Bearer {access_token}"}
                )
        except httpx.HTTPError as exc:
            raise IntegrationOAuthError(
                f"grant probe request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            error_code, retryable = classify_status(response.status_code)
            raise IntegrationOAuthError(
                f"grant probe returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
            )


def build_oauth_client(
    transport_kind: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    provider_account_ref: str = "",
) -> IntegrationOAuthClient:
    """Build an OAuth client for a transport (``transport`` = test seam).

    The domain service resolves clients through this factory so component
    tests can inject a ``httpx.MockTransport`` fake OAuth server.
    ``provider_account_ref`` is the per-account OAuth target (Shopify: the
    canonical shop host).
    """
    return IntegrationOAuthClient(
        transport_kind,
        transport=transport,
        provider_account_ref=provider_account_ref,
    )
