"""Google Analytics 4 (GA4) Data API client (I11).

Pages the ``runReport`` endpoint behind the sync worker
(``app/workers/integration_worker.py``) over httpx with an injected
transport (test seam), mirroring the GSC reference client
(``app/connectors/integrations/gsc.py``) contract-for-contract:

- Endpoints come from ``app.core.config.integrations`` and every URL is
  checked against the config-owned approved-host allow-list before a
  request is issued (SSRF policy). GA4 rides the ONE shared Google grant
  (no new OAuth) — the grant's access token authorizes both the GSC and
  the GA4 connection.
- Paging (``limit``/``offset``), timeout, and the per-provider
  requests/minute budget are read from ``integration_settings``
  (invariant 1); the caller (the worker) owns paging exactly as for GSC.
- The dataset templates are config-owned (contract C1): the request's
  dimensions/metrics are the template's declared tuples, resolved by
  matching the paged dimensions against the GA4 templates — never
  hard-coded here.
- The Bearer access token passes through this module but is NEVER logged
  (invariant 6): raised errors carry only HTTP status codes and
  config-owned error tokens, with provider error text length-capped.

**Row-shape mapping (the derivation contract):** the GA4 ``runReport``
response rows (``dimensionValues``/``metricValues``, all values strings)
are normalized into the SAME row shape the GSC client emits and the
worker/derivation consumes — ``{"rows": [{"keys": [...dims in declared
order...], "<metric>": <number>, ...}]}`` (the I9 derivation transform is
pinned against this shape). The page ``payload`` persisted on the
immutable import artifact is that faithful normalized document: every
returned row, every template metric, original values (GA4's compact
``"20260720"`` date form preserved), positional ``dimensionValues``/
``metricValues`` mapped by the config template. Metric strings are
coerced to numbers deterministically (integer-valued → ``int``, else
``float``); a row with the wrong arity or a non-numeric metric value is
dropped, never guessed. Rows with no data simply omit the ``rows`` key
(GA4 mirrors GSC's empty-result shape).

The cheap authenticated grant probe already exists as
``IntegrationOAuthClient.probe_access_token`` (I3 — the GSC site list
validates the ONE shared Google grant behind either connection) and is
deliberately NOT duplicated here (invariant 2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import NoReturn
from urllib.parse import quote

import httpx

from app.connectors.integrations._http import (
    IntegrationApiError,
    ProviderProperty,
    RequestPacer,
    assert_approved_url,
    classify_status,
    json_object_or_raise,
    nested_error_detail,
    parse_retry_after,
)
from app.core.config.attribution import ATTRIBUTION_CONSUMED_DATASETS
from app.core.config.integrations import (
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    ERROR_GA4_DIMENSION_INCOMPATIBLE,
    ERROR_PROVIDER_API,
    GA4_ACCOUNT_SUMMARIES_MAX_PAGES,
    GA4_ACCOUNT_SUMMARIES_PAGE_SIZE,
    GA4_ACCOUNT_SUMMARIES_PATH,
    GA4_ADMIN_API_BASE_URL,
    GA4_API_BASE_URL,
    GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS,
    GA4_PROPERTY_RESOURCE_PREFIX,
    GA4_RUN_REPORT_PATH,
    INTEGRATION_DATASET_TEMPLATES,
    INTEGRATION_PROVIDER_GA4,
    IntegrationDatasetTemplate,
    integration_settings,
    normalize_ga4_property_ref,
)


class Ga4ApiError(IntegrationApiError):
    """A GA4 API call failed; carries a config-owned error token."""


class Ga4DimensionCompatibilityError(Ga4ApiError):
    """The property rejected a capability-tested dataset's dimension mix.

    Raised for the primary item source/medium dataset when an HTTP
    400's capped provider detail explicitly identifies an incompatible
    dimension/metric combination — the sync worker's signal to fall back
    to the channel-group item template in the same run. Authentication,
    rate-limit, malformed-body, and generic 400 failures keep the
    base-class behavior (no fallback).
    """


def _is_compatibility_rejection(
    response: httpx.Response, template: IntegrationDatasetTemplate, detail: str
) -> bool:
    markers = GA4_DIMENSION_INCOMPATIBLE_DETAIL_MARKERS
    return (
        response.status_code == 400
        and template.dataset == DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY
        and any(marker in detail.casefold() for marker in markers)
    )


def _raise_run_report_error(
    response: httpx.Response, template: IntegrationDatasetTemplate
) -> NoReturn:
    error_code, retryable = classify_status(response.status_code)
    try:
        detail = nested_error_detail(response.json())
    except ValueError:
        detail = ""
    suffix = f" ({detail})" if detail else ""
    if _is_compatibility_rejection(response, template, detail):
        raise Ga4DimensionCompatibilityError(
            f"GA4 runReport rejected dataset {template.dataset}{suffix}",
            error_code=ERROR_GA4_DIMENSION_INCOMPATIBLE,
            retryable=False,
        )
    raise Ga4ApiError(
        f"GA4 runReport returned HTTP {response.status_code}{suffix}",
        error_code=error_code,
        retryable=retryable,
        retry_after_seconds=parse_retry_after(response),
    )


@dataclass(frozen=True)
class Ga4ReportPage:
    """One fetched ``runReport`` page (the worker/derivation contract).

    ``payload`` is the normalized report document the immutable import
    artifact persists + hashes; ``rows`` is its ``rows`` list (absent on
    an empty result) with each entry the normalized row dict
    (``keys`` + one entry per template metric). ``raw_row_count`` is the
    provider's row count for the page BEFORE normalization dropped any
    malformed rows — the worker's paging-termination measure (a full raw
    page with dropped rows must not look like a short final page).
    """

    payload: dict
    rows: tuple[dict, ...]
    raw_row_count: int


def _ga4_template(
    dataset: str, dimensions: Sequence[str]
) -> IntegrationDatasetTemplate:
    """Resolve + validate the config-owned GA4 dataset template being paged.

    The worker pages each config dataset by its id AND its declared
    dimensions; the matching template owns the request's metric set
    (contract C1). Keying on the (dataset, dimensions) PAIR — never on
    dimensions alone — because the ecommerce source/medium report shares
    its dimension tuple with ``ga4_source_medium_daily`` and differs only
    in metrics. An unknown dataset id or a dimension mismatch fails loud:
    the config templates are the only dataset vocabulary.
    """
    template = INTEGRATION_DATASET_TEMPLATES.get(dataset)
    if (
        template is None
        or template.provider != INTEGRATION_PROVIDER_GA4
        or tuple(template.dimensions) != tuple(dimensions)
    ):
        raise Ga4ApiError(
            f"no GA4 dataset template {dataset!r} for dimensions {tuple(dimensions)!r}",
            error_code=ERROR_PROVIDER_API,
        )
    return template


def _account_summaries(payload: dict) -> list:
    """The page's ``accountSummaries`` list; a non-list body fails loud.

    An account with no readable properties omits the key entirely, which is
    an empty page rather than an error.
    """
    summaries = payload.get("accountSummaries") or []
    if not isinstance(summaries, list):
        raise Ga4ApiError(
            "GA4 property list returned malformed account summaries",
            error_code=ERROR_PROVIDER_API,
        )
    return summaries


def _iter_ga4_properties(summaries: list) -> list[ProviderProperty]:
    """Flatten ``accountSummaries`` into selectable properties.

    Malformed entries are SKIPPED, never guessed: a summary without a
    usable ``property`` resource name cannot be selected safely. Labels
    fall back to the bare id when the provider omits a display name.
    """
    properties: list[ProviderProperty] = []
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        account_label = str(summary.get("displayName") or "").strip()
        for entry in summary.get("propertySummaries") or []:
            if not isinstance(entry, dict):
                continue
            resource = str(entry.get("property") or "").strip()
            property_ref = resource.removeprefix(GA4_PROPERTY_RESOURCE_PREFIX)
            if not property_ref.isdigit():
                continue
            name = str(entry.get("displayName") or "").strip() or property_ref
            label = f"{name} ({account_label})" if account_label else name
            properties.append(ProviderProperty(property_ref=property_ref, label=label))
    return properties


def _report_currency_code(report: dict) -> str | None:
    """The property's ISO currency from ``metadata.currencyCode``.

    A GA4 property is single-currency and the Data API reports that code
    on every ``runReport`` response — the ONLY currency source for the A1
    attribution slice (the Shopify ``shop.currencyCode`` cannot serve A1:
    A1 ships before Shopify). Normalized (strip + upper) and accepted only
    as exactly three ASCII letters; anything else degrades to ``None``
    (never guessed).
    """
    metadata = report.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("currencyCode")
    if not isinstance(raw, str):
        return None
    code = raw.strip().upper()
    if len(code) == 3 and code.isalpha() and code.isascii():
        return code
    return None


def _coerce_metric_value(raw: object) -> int | float | None:
    """Coerce one GA4 string metric value to a number (deterministic).

    GA4 ``metricValues`` are always strings. Integer-valued strings become
    ``int``, other numeric strings ``float``; a non-numeric value is
    malformed provider data — ``None`` drops the row, never guessed.
    """
    text = str(raw).strip()
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_row(row: object, template: IntegrationDatasetTemplate) -> dict | None:
    """Map one raw ``runReport`` row into the GSC-shaped contract row.

    Positional ``dimensionValues``/``metricValues`` are mapped by the
    template's declared tuples; the date dimension keeps GA4's compact
    raw value (the derivation transform parses it). Returns ``None`` for
    a row whose arity or metric values are malformed.
    """
    if not isinstance(row, dict):
        return None
    dimension_values = row.get("dimensionValues")
    metric_values = row.get("metricValues")
    if not isinstance(dimension_values, list) or not isinstance(metric_values, list):
        return None
    if len(dimension_values) != len(template.dimensions):
        return None
    if len(metric_values) < len(template.metrics):
        return None
    keys: list[str] = []
    for entry in dimension_values:
        if not isinstance(entry, dict) or "value" not in entry:
            return None
        keys.append(str(entry["value"]))
    normalized: dict = {"keys": keys}
    for index, name in enumerate(template.metrics):
        entry = metric_values[index]
        if not isinstance(entry, dict) or "value" not in entry:
            return None
        value = _coerce_metric_value(entry["value"])
        if value is None:
            return None
        normalized[name] = value
    return normalized


class Ga4Client:
    """GA4 ``runReport`` client with pacing + injected transport.

    ``transport`` is the test seam (``httpx.MockTransport`` or any
    ``httpx.AsyncBaseTransport``); production passes nothing and the client
    uses the real network.
    """

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._pacer = RequestPacer()

    async def list_properties(
        self, *, access_token: str
    ) -> tuple[ProviderProperty, ...]:
        """List the GA4 properties this grant can read (property discovery).

        Rides the Admin API's ``accountSummaries``, which returns every
        readable property grouped by account. Property refs are normalized
        to the CANONICAL bare numeric id (the Admin API returns the
        ``properties/123`` resource name) so a selection can never split
        owner identity against the bare spelling stored elsewhere. The
        label carries the account name for disambiguation — GA4 display
        names are not unique across accounts.

        FOLLOWS ``nextPageToken`` to completion: an agency grant can read
        more accounts than one page carries, and a truncated list silently
        hides properties the user owns — they would simply never appear in
        the picker. Paging is bounded by
        ``GA4_ACCOUNT_SUMMARIES_MAX_PAGES``; exhausting it raises rather
        than returning a partial list, because a partial list is
        indistinguishable from "that is all you have".
        """
        properties: list[ProviderProperty] = []
        page_token = ""
        for _page in range(GA4_ACCOUNT_SUMMARIES_MAX_PAGES):
            payload = await self._fetch_account_summaries(
                access_token=access_token, page_token=page_token
            )
            properties.extend(_iter_ga4_properties(_account_summaries(payload)))
            page_token = str(payload.get("nextPageToken") or "")
            if not page_token:
                return tuple(properties)
        raise Ga4ApiError(
            f"GA4 property list exceeded {GA4_ACCOUNT_SUMMARIES_MAX_PAGES} pages",
            error_code=ERROR_PROVIDER_API,
        )

    async def _fetch_account_summaries(
        self, *, access_token: str, page_token: str
    ) -> dict:
        """Fetch ONE ``accountSummaries`` page (paced, guarded, validated)."""
        url = (
            f"{GA4_ADMIN_API_BASE_URL}{GA4_ACCOUNT_SUMMARIES_PATH}"
            f"?pageSize={GA4_ACCOUNT_SUMMARIES_PAGE_SIZE}"
        )
        if page_token:
            url = f"{url}&pageToken={quote(page_token, safe='')}"
        assert_approved_url(url, label="GA4", error_type=Ga4ApiError)
        await self._pacer.wait(
            integration_settings.requests_per_minute(INTEGRATION_PROVIDER_GA4)
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=integration_settings.sync_request_timeout_seconds,
            ) as client:
                response = await client.get(
                    url,
                    # Set per-request and never logged (invariant 6).
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise Ga4ApiError(
                f"GA4 property list request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        return json_object_or_raise(
            response, label="GA4 property list", error_type=Ga4ApiError
        )

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
    ) -> Ga4ReportPage:
        """Fetch ONE page of report rows (the worker's uniform contract).

        The method name + signature mirror the GSC reference client — the
        worker pages every provider through this one seam; here it issues
        a GA4 ``runReport`` request. The caller owns paging: request pages
        at ``start_row`` offsets of ``sync_page_size`` until a page's RAW
        row count (``raw_row_count``, BEFORE normalization drops malformed
        rows) comes back short of the page size. Raises ``Ga4ApiError``
        on any failure (classified, never carrying the token) — including
        the narrowly classified ``Ga4DimensionCompatibilityError`` for the
        primary item dataset's incompatible-dimension HTTP 400.
        """
        template = _ga4_template(dataset, dimensions)
        # The path takes the BARE numeric id — a connection account_ref may
        # carry the provider's ``properties/`` resource-name spelling,
        # which would otherwise double the prefix in the URL.
        url = GA4_API_BASE_URL + GA4_RUN_REPORT_PATH.format(
            property_ref=quote(normalize_ga4_property_ref(property_ref), safe="")
        )
        assert_approved_url(url, label="GA4", error_type=Ga4ApiError)
        body = {
            "dateRanges": [
                {
                    "startDate": start_date.isoformat(),
                    "endDate": end_date.isoformat(),
                }
            ],
            "dimensions": [{"name": name} for name in template.dimensions],
            "metrics": [{"name": name} for name in template.metrics],
            "limit": integration_settings.sync_page_size,
            "offset": start_row,
        }
        await self._pacer.wait(
            integration_settings.requests_per_minute(INTEGRATION_PROVIDER_GA4)
        )
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=integration_settings.sync_request_timeout_seconds,
            ) as client:
                response = await client.post(
                    url,
                    json=body,
                    # Set per-request and never logged (invariant 6).
                    headers={"Authorization": f"Bearer {access_token}"},
                )
        except httpx.HTTPError as exc:
            raise Ga4ApiError(
                f"GA4 runReport request failed: {type(exc).__name__}",
                error_code=ERROR_PROVIDER_API,
                retryable=True,
            ) from exc
        if response.status_code != 200:
            _raise_run_report_error(response, template)
        try:
            report = response.json()
        except ValueError as exc:
            raise Ga4ApiError(
                "GA4 runReport returned a non-JSON body",
                error_code=ERROR_PROVIDER_API,
            ) from exc
        if not isinstance(report, dict):
            raise Ga4ApiError(
                "GA4 runReport returned an unexpected body",
                error_code=ERROR_PROVIDER_API,
            )
        raw_rows = report.get("rows") or []
        if not isinstance(raw_rows, list):
            raise Ga4ApiError(
                "GA4 runReport returned malformed rows",
                error_code=ERROR_PROVIDER_API,
            )
        rows = tuple(
            normalized
            for normalized in (_normalize_row(row, template) for row in raw_rows)
            if normalized is not None
        )
        # The persisted payload is the faithful normalized report document
        # (the derivation contract); ``rowCount`` is carried through when
        # the provider reports it.
        payload: dict = {"rows": list(rows)}
        if "rowCount" in report:
            payload["rowCount"] = report["rowCount"]
        metadata = report.get("metadata")
        if isinstance(metadata, dict):
            # Persist provider-declared thresholding/sampling/currency metadata
            # beside the immutable rows. Read APIs expose this verbatim as
            # limitations; they never infer complete coverage from row count.
            payload["metadata"] = metadata
        # Ecommerce datasets only: persist the property's ISO currency as a
        # TOP-LEVEL payload key (beside ``rows``/``rowCount``) — never a
        # report dimension, which would change ``dimension_key`` identity
        # and explode row cardinality. A1's only currency source (AC3).
        if template.dataset in ATTRIBUTION_CONSUMED_DATASETS:
            currency_code = _report_currency_code(report)
            if currency_code is not None:
                payload["currency_code"] = currency_code
        return Ga4ReportPage(payload=payload, rows=rows, raw_row_count=len(raw_rows))


def build_ga4_client(*, transport: httpx.AsyncBaseTransport | None = None) -> Ga4Client:
    """Build a GA4 client (``transport`` = test seam)."""
    return Ga4Client(transport=transport)
