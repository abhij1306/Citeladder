from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from app.core.config.integrations_settings import integration_settings
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_BING,
    INTEGRATION_PROVIDER_GA4,
    INTEGRATION_PROVIDER_GSC,
)
from app.core.config.task_queue import ERROR_MAX_ATTEMPTS, PostgresQueueSpec


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


INTEGRATION_QUEUE_SPEC: Final[PostgresQueueSpec[IntegrationSyncRun]] = (
    PostgresQueueSpec(
        model_ref=_integration_sync_run_model,
        lease_ttl=lambda: integration_settings.lease_ttl_seconds,
        claim_order=_integration_claim_order,
        max_attempts_error=ERROR_MAX_ATTEMPTS,
    )
)


def _gsc_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.gsc import build_gsc_client

    return build_gsc_client(transport=transport)


def _ga4_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.ga4 import build_ga4_client

    return build_ga4_client(transport=transport)


def _bing_client_builder(*, transport: Any = None) -> Any:
    from app.connectors.integrations.bing import build_bing_client

    return build_bing_client(transport=transport)


INTEGRATION_CLIENT_BUILDERS: Final[dict[str, Callable[..., Any]]] = {
    INTEGRATION_PROVIDER_GSC: _gsc_client_builder,
    INTEGRATION_PROVIDER_GA4: _ga4_client_builder,
    INTEGRATION_PROVIDER_BING: _bing_client_builder,
}

INTEGRATION_PROPERTY_DISCOVERY_PROVIDERS: Final[frozenset[str]] = frozenset(
    {INTEGRATION_PROVIDER_GSC, INTEGRATION_PROVIDER_GA4}
)

if TYPE_CHECKING:
    # Type-only: config never imports a model at runtime (circular import).
    from app.models.integrations import IntegrationSyncRun
