"""Immutable fetch-attempt row construction for the Site Health worker."""

from __future__ import annotations

import uuid

from app.connectors.web_evidence.contracts import AcquisitionProvenance, FetchCallTrace
from app.connectors.web_evidence.url_policy import split_host_port
from app.core.config.site_health_acquisition import (
    FETCH_ATTEMPT_OUTCOME_ERROR,
    FETCH_ATTEMPT_OUTCOME_SUCCESS,
)
from app.models.site_health.acquisition import SiteFetchAttempt
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.outcomes import AnalyzeOutcome, DiscoverOutcome


def acquisition_values(
    acquisition: AcquisitionProvenance | None,
) -> dict[str, object]:
    if acquisition is None:
        return {
            "acquisition_transport": "",
            "acquisition_rung": None,
            "acquisition_trigger": "",
            "impersonation_profile": "",
            "acquisition_options": None,
            "acquisition_policy_version": "",
        }
    return {
        "acquisition_transport": acquisition.transport[:32],
        "acquisition_rung": acquisition.rung,
        "acquisition_trigger": acquisition.trigger[:32],
        "impersonation_profile": acquisition.impersonation_profile[:64],
        "acquisition_options": (
            dict(acquisition.options) if acquisition.options else None
        ),
        "acquisition_policy_version": acquisition.policy_version[:32],
    }


def _attempt_host(url: str) -> str:
    try:
        host, _port = split_host_port(url)
    except ValueError:
        return ""
    return host[:255]


def _trace_outcome(
    entry: FetchCallTrace, *, is_final: bool, succeeded: bool, error_code: str
) -> tuple[str, str]:
    if entry.error_code:
        return FETCH_ATTEMPT_OUTCOME_ERROR, entry.error_code
    if is_final and not succeeded:
        return FETCH_ATTEMPT_OUTCOME_ERROR, error_code
    if entry.status_code is not None and entry.status_code >= 400:
        return FETCH_ATTEMPT_OUTCOME_ERROR, ""
    return FETCH_ATTEMPT_OUTCOME_SUCCESS, ""


def diagnostic_attempt(
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    outcome: DiscoverOutcome | AnalyzeOutcome,
    succeeded: bool,
    requested_url: str,
    artifact_id: uuid.UUID | None,
    attempt_number: int,
) -> SiteFetchAttempt:
    result = outcome.result
    return SiteFetchAttempt(
        task_id=task.id,
        crawl_id=crawl.id,
        workspace_id=crawl.workspace_id,
        attempt_number=attempt_number,
        request_ordinal=0,
        method="GET",
        target_host=_attempt_host(requested_url),
        outcome=(
            FETCH_ATTEMPT_OUTCOME_SUCCESS if succeeded else FETCH_ATTEMPT_OUTCOME_ERROR
        ),
        error_code=outcome.error_code,
        status_code=outcome.status_code,
        latency_ms=outcome.latency_ms,
        wire_bytes=result.wire_bytes if result is not None else None,
        decoded_bytes=result.decoded_bytes if result is not None else None,
        **acquisition_values(result.acquisition if result is not None else None),
        artifact_id=artifact_id,
    )


def traced_attempt(
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    outcome: DiscoverOutcome | AnalyzeOutcome,
    entry: FetchCallTrace,
    succeeded: bool,
    is_final: bool,
    artifact_id: uuid.UUID | None,
    attempt_number: int,
) -> SiteFetchAttempt:
    row_outcome, row_error = _trace_outcome(
        entry,
        is_final=is_final,
        succeeded=succeeded,
        error_code=outcome.error_code,
    )
    return SiteFetchAttempt(
        task_id=task.id,
        crawl_id=crawl.id,
        workspace_id=crawl.workspace_id,
        attempt_number=attempt_number,
        request_ordinal=entry.request_ordinal,
        method=(entry.method or "GET")[:8],
        target_host=_attempt_host(entry.url),
        outcome=row_outcome,
        error_code=row_error,
        status_code=entry.status_code,
        latency_ms=entry.latency_ms,
        wire_bytes=entry.wire_bytes,
        decoded_bytes=entry.decoded_bytes,
        **acquisition_values(entry.acquisition),
        artifact_id=artifact_id if is_final and succeeded else None,
    )
