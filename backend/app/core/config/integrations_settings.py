from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.integrations_transport import INTEGRATION_PROVIDERS


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
