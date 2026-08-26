# Centralized application settings (invariant 1: all config lives here).
from __future__ import annotations

import ipaddress
import logging
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

# `BASE_DIR` / `PROJECT_ROOT` are re-exported explicitly: they were defined
# here before `config/dotenv.py` took ownership of the .env decision, and other
# modules still import them from this package.
from app.core.config.dotenv import BASE_DIR as BASE_DIR
from app.core.config.dotenv import PROJECT_ROOT as PROJECT_ROOT
from app.core.config.dotenv import dotenv_sources

_INSECURE_DEFAULTS = {
    "change-me",
    "change-me-32-bytes-minimum-change-me",
    "replace-with-64-byte-random-secret",
    "replace-with-32-byte-minimum-secret",
}


class Settings(BaseSettings):
    """Application settings singleton, loaded from environment / .env.

    Values are read from the process environment first, then the repo-root and
    backend-local ``.env`` files. Every tunable knob (secrets, model ids,
    thresholds, timeouts) belongs here rather than inline in service code.
    """

    model_config = SettingsConfigDict(
        # Repo-root and backend-local .env, unless a test run disabled them.
        # `config/dotenv.py` owns that decision for every settings class here.
        env_file=dotenv_sources(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "CiteLadder"
    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "app_env"),
    )
    backend_host: str = "127.0.0.1"
    backend_port: int = Field(
        default=8000,
        validation_alias=AliasChoices("BACKEND_PORT", "backend_port"),
    )
    frontend_url: str = Field(
        default="http://127.0.0.1:3000",
        validation_alias=AliasChoices("FRONTEND_URL", "frontend_url"),
    )
    # Comma-separated explicit CORS origins; overrides frontend_url expansion.
    frontend_origins: str = ""
    # Comma-separated networks whose direct peers may supply a proxy chain.
    # Production traffic reaches the private API through Next.js/ALB, so auth
    # abuse controls must recover the first untrusted address without trusting
    # forwarding headers from arbitrary peers.
    trusted_proxy_cidrs: str = Field(
        default="",
        validation_alias=AliasChoices("TRUSTED_PROXY_CIDRS", "trusted_proxy_cidrs"),
    )

    # --- Auth / crypto (invariant 6) ---
    jwt_secret_key: str = Field(
        default="change-me-32-bytes-minimum-change-me",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "jwt_secret_key"),
    )
    # Pinned to the sole reviewed symmetric algorithm. Environment overrides
    # can no longer silently select another JWT algorithm.
    jwt_algorithm: Literal["HS256"] = Field(
        default="HS256",
        validation_alias=AliasChoices("JWT_ALGORITHM", "jwt_algorithm"),
    )
    jwt_expire_hours: int = Field(
        default=24,
        validation_alias=AliasChoices("JWT_EXPIRE_HOURS", "jwt_expire_hours"),
    )
    # Session cookie name for the HttpOnly JWT (set by B2).
    session_cookie_name: str = "citeladder_session"
    encryption_key: str = Field(
        default="replace-with-32-byte-minimum-secret",
        validation_alias=AliasChoices("ENCRYPTION_KEY", "encryption_key"),
    )
    # HMAC key for the opaque ``session_id_hash`` stamped on sanitized
    # referral events (AI Referrals, invariant 6). Env-injected deployment
    # secret — resolved only inside the referral sanitization pass, never
    # logged and never placed in a DTO.
    referral_hash_salt: str = Field(
        default="replace-with-64-byte-random-secret",
        validation_alias=AliasChoices("REFERRAL_HASH_SALT", "referral_hash_salt"),
    )

    # --- Integrations OAuth client credentials (GSC/GA4/Bing connect) ---
    # Env-injected deployment secrets for the integrations OAuth transports
    # (Google covers GSC+GA4 on one shared grant; Microsoft covers Bing).
    # Resolved only inside the OAuth exchange/refresh paths; never logged and
    # never placed in a DTO (invariant 6). Empty = provider not configured.
    integration_google_client_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "INTEGRATION_GOOGLE_CLIENT_ID", "integration_google_client_id"
        ),
    )
    integration_google_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "INTEGRATION_GOOGLE_CLIENT_SECRET", "integration_google_client_secret"
        ),
    )
    integration_microsoft_client_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "INTEGRATION_MICROSOFT_CLIENT_ID", "integration_microsoft_client_id"
        ),
    )
    integration_microsoft_client_secret: str = Field(
        default="",
        validation_alias=AliasChoices(
            "INTEGRATION_MICROSOFT_CLIENT_SECRET",
            "integration_microsoft_client_secret",
        ),
    )
    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/citeladder",
        validation_alias=AliasChoices("DATABASE_URL", "database_url"),
    )
    # Sized so the shared engine pool exactly covers the audit worker's peak
    # demand at the frozen T4 defaults: worker_max_inflight (10) x
    # worker_db_sessions_per_task (2) + operational_headroom (4) = 24 =
    # pool_size (20) + max_overflow (4). The audit worker ASSERTS this
    # invariant at startup (``assert_worker_pool_capacity`` raises), so any
    # deployment override of one side must rebalance the other from a tested
    # connection budget; a multi-service deployment still multiplies these, so
    # keep the per-service budget conservative when overriding.
    db_pool_size: int = Field(
        default=20,
        ge=1,
        le=50,
        validation_alias=AliasChoices("DB_POOL_SIZE", "db_pool_size"),
    )
    db_max_overflow: int = Field(
        default=4,
        ge=0,
        le=50,
        validation_alias=AliasChoices("DB_MAX_OVERFLOW", "db_max_overflow"),
    )
    db_pool_recycle_seconds: int = Field(
        default=600,
        validation_alias=AliasChoices(
            "DB_POOL_RECYCLE_SECONDS", "db_pool_recycle_seconds"
        ),
    )
    db_pool_timeout_seconds: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "DB_POOL_TIMEOUT_SECONDS", "db_pool_timeout_seconds"
        ),
    )
    db_pool_pre_ping: bool = Field(
        default=True,
        validation_alias=AliasChoices("DB_POOL_PRE_PING", "db_pool_pre_ping"),
    )
    db_connect_timeout_seconds: int = Field(
        default=10,
        ge=1,
        le=60,
        validation_alias=AliasChoices(
            "DB_CONNECT_TIMEOUT_SECONDS", "db_connect_timeout_seconds"
        ),
    )
    db_command_timeout_seconds: int = Field(
        default=30,
        ge=1,
        le=300,
        validation_alias=AliasChoices(
            "DB_COMMAND_TIMEOUT_SECONDS", "db_command_timeout_seconds"
        ),
    )
    db_statement_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=300_000,
        validation_alias=AliasChoices(
            "DB_STATEMENT_TIMEOUT_MS", "db_statement_timeout_ms"
        ),
    )
    db_lock_timeout_ms: int = Field(
        default=5_000,
        ge=100,
        le=60_000,
        validation_alias=AliasChoices("DB_LOCK_TIMEOUT_MS", "db_lock_timeout_ms"),
    )
    db_idle_transaction_timeout_ms: int = Field(
        default=30_000,
        ge=1_000,
        le=300_000,
        validation_alias=AliasChoices(
            "DB_IDLE_TRANSACTION_TIMEOUT_MS", "db_idle_transaction_timeout_ms"
        ),
    )
    db_ssl_mode: Literal["disable", "require"] = Field(
        default="disable",
        validation_alias=AliasChoices("DB_SSL_MODE", "db_ssl_mode"),
    )

    request_id_header: str = Field(
        default="X-Request-ID",
        validation_alias=AliasChoices("REQUEST_ID_HEADER", "request_id_header"),
    )

    # --- Dev-test login platform-credential gate (T11) --------------------
    # Escape hatch for Part B's dev-only fixed login: while disabled (the
    # default, fail closed) that session is treated like any tenant session —
    # it cannot resolve platform credentials or reach the reserved system
    # workspace. Enabling it outside development/test is a startup hard-fail
    # (``validate_production_security``).
    dev_test_login_allow_platform_credentials: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "DEV_TEST_LOGIN_ALLOW_PLATFORM_CREDENTIALS",
            "dev_test_login_allow_platform_credentials",
        ),
    )

    # --- Observability (optional Logfire) ---
    logfire_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("LOGFIRE_ENABLED", "logfire_enabled"),
    )
    logfire_token: str = Field(
        default="",
        validation_alias=AliasChoices("LOGFIRE_TOKEN", "logfire_token"),
    )
    # BASE name only. Each runnable process appends its own role suffix
    # (``citeladder-api``, ``citeladder-audit-worker``) in ``core/telemetry.py``,
    # because compose gives every service the same environment block.
    logfire_service_name: str = Field(
        default="citeladder",
        validation_alias=AliasChoices("LOGFIRE_SERVICE_NAME", "logfire_service_name"),
    )
    # Region-specific Logfire ingest endpoint. Configurable so a self-hosted or
    # EU deployment is an environment change, not a code change.
    logfire_base_url: str = Field(
        default="https://logfire-us.pydantic.dev",
        validation_alias=AliasChoices("LOGFIRE_BASE_URL", "logfire_base_url"),
    )
    logfire_environment: str = Field(
        default="",
        validation_alias=AliasChoices("LOGFIRE_ENVIRONMENT", "logfire_environment"),
    )
    # Unit tests remain locally observable unless this separate opt-in is set.
    logfire_enabled_in_tests: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "LOGFIRE_ENABLED_IN_TESTS", "logfire_enabled_in_tests"
        ),
    )


def _load_settings() -> Settings:
    # BaseSettings reads values from environment/.env at runtime.
    return Settings()


settings = _load_settings()


_SECRET_FIELDS = (
    "jwt_secret_key",
    "encryption_key",
    "referral_hash_salt",
)


def _secret_is_weak(value: str) -> bool:
    normalized = value.strip().casefold()
    return (
        len(value.encode("utf-8")) < 32
        or len(set(value)) < 12
        or value in _INSECURE_DEFAULTS
        or normalized in {"password", "secret", "citeladder", "changeme"}
    )


# Environment names where deployment-security hard-fails do not apply (local
# dev + test). One vocabulary, shared by the startup check and the dev-gate
# policy below (invariant 2).
DEVELOPMENT_ENV_NAMES: frozenset[str] = frozenset(
    {"", "development", "dev", "local", "test", "testing"}
)


def _is_development_env(candidate: Settings) -> bool:
    env = str(candidate.app_env or "development").strip().lower()
    return env in DEVELOPMENT_ENV_NAMES


def encryption_key_configured(candidate: Settings) -> bool:
    """Whether the Fernet encryption key is really configured (fail closed).

    The shipped placeholder default counts as MISSING: a deployment that
    never set ``ENCRYPTION_KEY`` must not encrypt new credentials with a
    publicly known key (provisioning refuses to run, invariant 6).
    """
    value = candidate.encryption_key.strip()
    return bool(value) and value not in _INSECURE_DEFAULTS


def trusted_proxy_networks(
    value: str,
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Parse and normalize the configured direct-proxy networks."""
    return tuple(
        ipaddress.ip_network(candidate.strip(), strict=False)
        for candidate in value.split(",")
        if candidate.strip()
    )


def _trusted_proxy_problems(value: str) -> list[str]:
    try:
        networks = trusted_proxy_networks(value)
    except ValueError:
        return [
            "trusted_proxy_cidrs must contain valid IP networks",
            "trusted_proxy_cidrs must be configured in production",
        ]
    if any(network.prefixlen == 0 for network in networks):
        return [
            "trusted_proxy_cidrs must not contain catch-all networks",
            "trusted_proxy_cidrs must be configured in production",
        ]
    if not networks:
        return ["trusted_proxy_cidrs must be configured in production"]
    return []


def _dev_gate_problems(candidate: Settings) -> list[str]:
    """The dev-test login's platform-credential escape hatch is a development/
    test-only tool: enabled anywhere else it is a hard deployment failure."""
    if candidate.dev_test_login_allow_platform_credentials and not _is_development_env(
        candidate
    ):
        return [
            "dev_test_login_allow_platform_credentials must be disabled "
            "outside development/test"
        ]
    return []


def validate_production_security(candidate: Settings) -> list[str]:
    """Return non-secret deployment-policy violations for ``candidate``."""
    issues: list[str] = []
    values = {name: getattr(candidate, name) for name in _SECRET_FIELDS}
    for name, value in values.items():
        if _secret_is_weak(value):
            issues.append(f"{name} does not meet the production strength policy")
    if len(set(values.values())) != len(values):
        issues.append("application secrets must be independent")

    try:
        database_password = make_url(candidate.database_url).password or ""
    except Exception:  # noqa: BLE001 - invalid URL is reported without its value
        database_password = ""
    if _secret_is_weak(database_password):
        issues.append("database password does not meet the production strength policy")
    if database_password and database_password in values.values():
        issues.append("database password must be independent of application secrets")
    if candidate.db_ssl_mode != "require":
        issues.append("db_ssl_mode must be require in production")
    issues.extend(_trusted_proxy_problems(candidate.trusted_proxy_cidrs))
    issues.extend(_dev_gate_problems(candidate))
    return issues


def _check_secret_defaults() -> None:
    """Warn in development and refuse weak production deployment secrets."""
    logger = logging.getLogger("app.core.config")
    is_non_dev = not _is_development_env(settings)
    issues = (
        validate_production_security(settings)
        if is_non_dev
        else [
            f"{name} is set to a default value"
            for name in _SECRET_FIELDS
            if getattr(settings, name) in _INSECURE_DEFAULTS
        ]
    )
    if not issues:
        return
    msg = (
        "SECURITY WARNING: insecure default secrets detected: "
        + "; ".join(issues)
        + ". Generate secure values: "
        + 'python -c "import secrets; print(secrets.token_urlsafe(64))"'
    )
    if is_non_dev:
        raise RuntimeError(msg)
    logger.warning(msg)


_check_secret_defaults()


def get_frontend_origins() -> list[str]:
    """Resolve the allowed CORS origins for the FastAPI CORS middleware."""
    if settings.frontend_origins.strip():
        return [
            origin.strip()
            for origin in settings.frontend_origins.split(",")
            if origin.strip()
        ]

    origin = settings.frontend_url.rstrip("/")
    variants = {origin}
    if "127.0.0.1" in origin:
        variants.add(origin.replace("127.0.0.1", "localhost"))
    if "localhost" in origin:
        variants.add(origin.replace("localhost", "127.0.0.1"))
    return sorted(variants)
