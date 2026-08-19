"""Provider-page contracts and durable paging state for integration syncs.

The integration worker owns the queue lifecycle.  This module owns the
provider-neutral page protocol and the deterministic conversion between
immutable artifacts and a dataset's next paging position.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.connectors.integrations.bing import BingApiError
from app.connectors.integrations.ga4 import Ga4ApiError
from app.connectors.integrations.gsc import GscApiError
from app.connectors.integrations.shopify import ShopifyApiError
from app.core.config.integrations_contracts import (
    ERROR_PROVIDER_API,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
    INTEGRATION_DATASET_TEMPLATES,
    INTEGRATION_SYNC_EXCLUDED_DATASETS,
    IntegrationDatasetTemplate,
)
from app.core.config.integrations_transport import INTEGRATION_PROVIDER_GA4


class RunPreflightError(RuntimeError):
    """A deterministic condition which prevents a provider request."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class UnsupportedProviderError(RunPreflightError):
    """The run's provider has no registered data-API client."""

    def __init__(self, message: str) -> None:
        super().__init__(ERROR_PROVIDER_API, message)


class PayloadTooLargeError(RuntimeError):
    """A fetched page exceeds the inline-payload cap (never truncate it)."""


class MalformedProviderPageError(RuntimeError):
    """A cursor page's outer paging data is unsafe to persist or resume."""


class DataClientPage(Protocol):
    """One fetched provider page before any worker-side transformation."""

    @property
    def payload(self) -> dict: ...

    @property
    def rows(self) -> tuple[dict, ...]: ...

    @property
    def raw_row_count(self) -> int: ...


class DataClient(Protocol):
    """The provider-neutral client contract dispatched by the worker."""

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
    ) -> DataClientPage: ...


PROVIDER_API_ERRORS = (GscApiError, Ga4ApiError, BingApiError, ShopifyApiError)


@dataclass(frozen=True)
class WorkerPage:
    """A worker-sanitized provider page ready for immutable persistence."""

    payload: dict
    rows: tuple[dict, ...]
    raw_row_count: int


@dataclass(frozen=True)
class DatasetResume:
    """A dataset's durable resume position reconstructed from artifacts."""

    start_row: int
    page_cursor: str | None
    complete: bool


@dataclass(frozen=True)
class RunContext:
    """The immutable identity and captured state of one claimed sync run."""

    run_id: uuid.UUID
    workspace_id: uuid.UUID
    connection_id: uuid.UUID
    grant_id: uuid.UUID
    provider: str
    transport: str
    grant_status: str
    sync_kind: str
    window_start: date
    window_end: date
    resync_seq: int
    property_ref: str
    attempt_count: int
    max_attempts: int
    dataset_capabilities: dict


def provider_datasets(
    provider: str, capabilities: dict | None = None
) -> list[IntegrationDatasetTemplate]:
    """Return config-owned templates, selecting one GA4 item dataset."""
    templates = [
        template
        for template in INTEGRATION_DATASET_TEMPLATES.values()
        if template.provider == provider
        and template.dataset not in INTEGRATION_SYNC_EXCLUDED_DATASETS
    ]
    if provider != INTEGRATION_PROVIDER_GA4:
        return templates
    selected = selected_item_dataset(capabilities or {})
    omitted = (
        DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY
        if selected == DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY
        else DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY
    )
    return [template for template in templates if template.dataset != omitted]


def selected_item_dataset(capabilities: dict) -> str:
    """Choose the GA4 item dataset from versioned connection capability."""
    state = capabilities.get(GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY)
    if (
        isinstance(state, dict)
        and state.get("version") == GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION
        and state.get("selected_dataset") == DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY
    ):
        return DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY
    return DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY


@dataclass(frozen=True)
class NextDatasetPage:
    """The durable paging position after an artifact has been committed."""

    start_row: int
    page_cursor: str | None
    complete: bool


@dataclass(frozen=True)
class LastDatasetArtifact:
    """Only the latest artifact fields required for resume calculation."""

    start_row: int
    row_count: int
    snapshot: dict
    payload: dict


def next_dataset_page(
    *,
    cursor_mode: bool,
    page_info: dict | None,
    start_row: int,
    raw_row_count: int,
    page_size: int,
) -> NextDatasetPage:
    """Derive completion and next durable position from a written page."""
    if cursor_mode:
        if page_info is None:
            raise MalformedProviderPageError("cursor page is missing pageInfo")
        if not page_info["hasNextPage"]:
            return NextDatasetPage(start_row, None, complete=True)
        return NextDatasetPage(
            start_row + raw_row_count, page_info["endCursor"], complete=False
        )
    if raw_row_count < page_size:
        return NextDatasetPage(start_row, None, complete=True)
    return NextDatasetPage(start_row + page_size, None, complete=False)


def dataset_resume_from_artifacts(
    rows: Sequence[tuple[dict | None, int, dict | None]],
    *,
    cursor_mode: bool,
    page_size: int,
) -> DatasetResume:
    """Reconstruct a resume position exclusively from immutable artifacts."""
    if not rows:
        return DatasetResume(start_row=0, page_cursor=None, complete=False)
    latest = latest_dataset_artifact(rows)
    if cursor_mode:
        return cursor_resume_from_artifact(latest)
    return offset_resume_from_artifact(latest, page_size=page_size)


def latest_dataset_artifact(
    rows: Sequence[tuple[dict | None, int, dict | None]],
) -> LastDatasetArtifact:
    """Select the page with the greatest logical start row."""
    latest = LastDatasetArtifact(0, 0, {}, {})
    for query_snapshot, row_count, payload in rows:
        snapshot = query_snapshot or {}
        snapshot_start = int(snapshot.get("startRow") or 0)
        if snapshot_start >= latest.start_row:
            latest = LastDatasetArtifact(
                snapshot_start,
                row_count,
                snapshot,
                payload if isinstance(payload, dict) else {},
            )
    return latest


def cursor_resume_from_artifact(latest: LastDatasetArtifact) -> DatasetResume:
    """Resume from durable cursor state, rejecting incomplete snapshots."""
    page_info = latest.payload.get("pageInfo")
    if not (isinstance(page_info, dict) and page_info.get("hasNextPage") is True):
        return DatasetResume(start_row=0, page_cursor=None, complete=True)
    next_cursor = latest.snapshot.get("nextPageCursor")
    if not isinstance(next_cursor, str) or not next_cursor:
        raise MalformedProviderPageError(
            "durable cursor page is missing its nextPageCursor"
        )
    return DatasetResume(
        start_row=latest.start_row + latest.row_count,
        page_cursor=next_cursor,
        complete=False,
    )


def offset_resume_from_artifact(
    latest: LastDatasetArtifact, *, page_size: int
) -> DatasetResume:
    """Resume an offset dataset by the durable provider row count."""
    if latest.row_count < page_size:
        return DatasetResume(start_row=0, page_cursor=None, complete=True)
    return DatasetResume(
        start_row=latest.start_row + page_size, page_cursor=None, complete=False
    )
