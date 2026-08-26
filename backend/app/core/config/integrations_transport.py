from __future__ import annotations

import re
from typing import Final
from urllib.parse import urlencode

INTEGRATION_PROVIDER_GSC: Final = "gsc"

INTEGRATION_PROVIDER_GA4: Final = "ga4"

INTEGRATION_PROVIDER_BING: Final = "bing"

INTEGRATION_PROVIDERS: Final[frozenset[str]] = frozenset(
    {
        INTEGRATION_PROVIDER_GSC,
        INTEGRATION_PROVIDER_GA4,
        INTEGRATION_PROVIDER_BING,
    }
)

INTEGRATION_TRANSPORT_GOOGLE: Final = "google_oauth"

INTEGRATION_TRANSPORT_MICROSOFT: Final = "microsoft_oauth"

INTEGRATION_TRANSPORTS: Final[frozenset[str]] = frozenset(
    {
        INTEGRATION_TRANSPORT_GOOGLE,
        INTEGRATION_TRANSPORT_MICROSOFT,
    }
)

INTEGRATION_PROVIDER_TRANSPORT: Final[dict[str, str]] = {
    INTEGRATION_PROVIDER_GSC: INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_PROVIDER_GA4: INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_PROVIDER_BING: INTEGRATION_TRANSPORT_MICROSOFT,
}

INTEGRATION_OAUTH_REFRESHABLE: Final[dict[str, bool]] = {
    INTEGRATION_TRANSPORT_GOOGLE: True,
    INTEGRATION_TRANSPORT_MICROSOFT: True,
}

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

INTEGRATION_OAUTH_REVOKE_URLS: Final[dict[str, str]] = {
    INTEGRATION_TRANSPORT_GOOGLE: "https://oauth2.googleapis.com/revoke",
    INTEGRATION_TRANSPORT_MICROSOFT: "",
}

INTEGRATION_OAUTH_SCOPES: Final[dict[str, tuple[str, ...]]] = {
    INTEGRATION_TRANSPORT_GOOGLE: (
        "https://www.googleapis.com/auth/webmasters.readonly",
        "https://www.googleapis.com/auth/analytics.readonly",
    ),
    INTEGRATION_TRANSPORT_MICROSOFT: (
        "offline_access",
        "https://webmaster.bing.com/api/webmaster.manage",
    ),
}

INTEGRATION_OAUTH_CALLBACK_PATH: Final = (
    "/api/v1/integrations/oauth/{provider}/callback"
)

INTEGRATION_OAUTH_LANDING_PATH: Final = "/settings?tab=integrations"

INTEGRATION_OAUTH_TRANSACTION_COOKIE: Final = "citeladder_integration_oauth"

INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH: Final = "/api/v1/integrations/oauth"


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


GSC_API_BASE_URL: Final = "https://www.googleapis.com"

GSC_SEARCH_ANALYTICS_PATH: Final = (
    "/webmasters/v3/sites/{property_ref}/searchAnalytics/query"
)

GSC_SITES_PATH: Final = "/webmasters/v3/sites"

GSC_PERMISSION_UNVERIFIED: Final = "siteUnverifiedUser"

GSC_DOMAIN_PROPERTY_PREFIX: Final = "sc-domain:"

GA4_API_BASE_URL: Final = "https://analyticsdata.googleapis.com"

GA4_RUN_REPORT_PATH: Final = "/v1beta/properties/{property_ref}:runReport"

GA4_ADMIN_API_BASE_URL: Final = "https://analyticsadmin.googleapis.com"

GA4_ACCOUNT_SUMMARIES_PATH: Final = "/v1beta/accountSummaries"

GA4_ACCOUNT_SUMMARIES_PAGE_SIZE: Final = 200

GA4_ACCOUNT_SUMMARIES_MAX_PAGES: Final = 25

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


BING_API_BASE_URL: Final = "https://ssl.bing.com"

BING_API_JSON_ROOT: Final = "/webmaster/api.svc/json/"

BING_SITES_PROBE_METHOD: Final = "GetSites"

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
