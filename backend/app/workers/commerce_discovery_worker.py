"""Queue worker for deterministic, provenance-safe Commerce discovery.

The worker owns only acquired URL evidence.  Upload evidence is already
immutable at enqueue time and is acknowledged without a transport call.  URL
tasks use the Site Health ``SecureFetcher`` unchanged, so SSRF validation,
manual redirects, byte caps, TLS, and the server-owned acquisition ladder are
identical for Commerce and Site Health.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import uuid
from collections.abc import AsyncIterator, Iterable
from typing import Any
from urllib.parse import urlsplit

import httpx
from lxml import etree
from lxml import html as lxml_html
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    AcquisitionTransport,
    DnsResolver,
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.core.config.commerce import (
    COMMERCE_ACQUISITION_STATE_ACQUIRED,
    COMMERCE_CANDIDATE_KIND_COMPETITOR,
    COMMERCE_CANDIDATE_KIND_OWN,
    COMMERCE_CANDIDATE_KINDS,
    COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION,
    COMMERCE_DISCOVERY_ERROR_HTTP_STATUS,
    COMMERCE_DISCOVERY_ERROR_LEGACY_PLACEHOLDER,
    COMMERCE_DISCOVERY_ERROR_WORKER_CRASH,
    COMMERCE_DISCOVERY_INPUT_UPLOAD,
    COMMERCE_DISCOVERY_QUEUE_SPEC,
    COMMERCE_DISCOVERY_TASK_KIND_DISCOVER,
    COMMERCE_EVIDENCE_KIND_CRAWLED,
    COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING,
    COMMERCE_EVIDENCE_KIND_STRUCTURED,
    commerce_intelligence_settings,
)
from app.core.config.site_health import FETCH_PURPOSE_DISCOVER
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging
from app.domain.commerce.intelligence import (
    finalize_discovery_failure,
    finalize_discovery_success,
    mark_discovery_run_running,
    reconcile_discovery_run,
)
from app.models.commerce import (
    CommerceDiscoveryArtifact,
    CommerceDiscoveryRun,
    CommerceDiscoveryTask,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.drain import DrainableWorkerMixin

logger = logging.getLogger("app.workers.commerce_discovery")


def _text(value: Any) -> str:
    """Bound one extracted scalar without retaining page body text."""
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("name") or value.get("@id") or ""
    if isinstance(value, list):
        value = next((item for item in value if item), "")
    return " ".join(str(value).split())[
        : commerce_intelligence_settings.discovery_max_field_chars
    ]


def _first(values: Iterable[Any]) -> str:
    return next((text for value in values if (text := _text(value))), "")


def _schema_nodes(value: Any) -> list[dict[str, Any]]:
    """Walk bounded JSON-LD/structured JSON objects in document order."""
    nodes: list[dict[str, Any]] = []
    stack: list[Any] = [value]
    while (
        stack and len(nodes) < commerce_intelligence_settings.discovery_max_schema_nodes
    ):
        item = stack.pop(0)
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            nodes.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)
            for key in ("itemListElement", "offers", "hasVariant"):
                nested = item.get(key)
                if isinstance(nested, (dict, list)):
                    stack.append(nested)
    return nodes


def _has_type(node: dict[str, Any], expected: str) -> bool:
    raw = node.get("@type")
    values = raw if isinstance(raw, list) else [raw]
    return any(_text(value).casefold() == expected.casefold() for value in values)


def _mapping_value(mapping: dict[str, Any], *keys: str) -> str:
    return _first(mapping.get(key) for key in keys)


def _price(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _meta_values(root: Any) -> dict[str, str]:
    values: dict[str, str] = {}
    if root is None:
        return values
    for node in root.xpath("//meta[@content]"):
        key = _text(node.get("name") or node.get("property") or node.get("itemprop"))
        if key and key not in values:
            values[key.casefold()] = _text(node.get("content"))
    return values


def _host_matches(host: str, configured_hosts: tuple[str, ...]) -> bool:
    normalized = host.casefold().rstrip(".")
    return any(
        normalized == candidate.casefold().rstrip(".")
        or normalized.endswith(f".{candidate.casefold().rstrip('.')}")
        for candidate in configured_hosts
        if candidate.strip()
    )


def _evidence_kind(result: FetchResult) -> str:
    host = urlsplit(result.final_url).hostname or ""
    if _host_matches(
        host, commerce_intelligence_settings.discovery_google_shopping_source_hosts
    ):
        return COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING
    if result.content_type in {
        "application/json",
        "application/ld+json",
    } or _host_matches(
        host, commerce_intelligence_settings.discovery_structured_source_hosts
    ):
        return COMMERCE_EVIDENCE_KIND_STRUCTURED
    return COMMERCE_EVIDENCE_KIND_CRAWLED


def _configured_candidate_target(
    run: CommerceDiscoveryRun,
) -> tuple[str, uuid.UUID | None]:
    """Read a URL-run target from its frozen configuration, fail-closed to own."""
    configuration = run.configuration or {}
    candidate_kind = configuration.get("candidate_kind", COMMERCE_CANDIDATE_KIND_OWN)
    if candidate_kind not in COMMERCE_CANDIDATE_KINDS:
        return COMMERCE_CANDIDATE_KIND_OWN, None
    raw_competitor_id = configuration.get("competitor_id")
    try:
        competitor_id = uuid.UUID(str(raw_competitor_id)) if raw_competitor_id else None
    except (TypeError, ValueError):
        return COMMERCE_CANDIDATE_KIND_OWN, None
    if candidate_kind == COMMERCE_CANDIDATE_KIND_COMPETITOR and competitor_id is None:
        return COMMERCE_CANDIDATE_KIND_OWN, None
    return candidate_kind, competitor_id


def _candidate_conflict_identity(
    identity: dict[str, Any],
    *,
    candidate_kind: str,
    competitor_id: uuid.UUID | None,
    run_id: uuid.UUID,
    task_id: uuid.UUID,
    source_url: str,
) -> dict[str, Any]:
    """Add stable ownership/source context to the finalizer's hashed identity.

    The database uniqueness boundary is ``(run_id, candidate_hash)`` and the
    finalizer derives ``candidate_hash`` from the supplied identity.  Keeping
    this context in the identity makes one task retry idempotent while ensuring
    otherwise identical own and competitor discoveries cannot collapse.
    """
    source = urlsplit(source_url)
    normalized_source = source._replace(fragment="").geturl()
    conflict_context = {
        "candidate_kind": candidate_kind,
        "competitor_id": str(competitor_id) if competitor_id else "",
        "run_id": str(run_id),
        "task_id": str(task_id),
        "source_url": normalized_source,
    }
    return {**identity, "_commerce_discovery_conflict_context": conflict_context}


def _extract_product(
    result: FetchResult,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Extract a bounded Product/Offer identity from in-memory response bytes."""
    parsed = _schema_documents_and_root(result)
    if parsed is None:
        return None
    documents, root = parsed
    nodes = _bounded_schema_nodes(documents)
    product, offer = _product_and_offer(nodes)
    meta = _meta_values(root)
    name = _visible_product_name(root, product, meta)
    if not name:
        return None
    identity = _product_identity(result, product=product, offer=offer, name=name)
    extracted = {
        "identity": identity,
        "schema_types": _schema_type_names(nodes),
        "content_type": result.content_type,
        "status_code": result.status_code,
    }
    return identity, extracted


def _schema_documents_and_root(
    result: FetchResult,
) -> tuple[list[Any], Any | None] | None:
    body = result.body[: commerce_intelligence_settings.discovery_max_extraction_bytes]
    if result.content_type in {"application/json", "application/ld+json"}:
        document = _decode_json_document(body, result.charset)
        return ([document], None) if document is not None else None
    return _html_schema_documents(body)


def _decode_json_document(body: bytes, charset: str | None) -> Any | None:
    try:
        return json.loads(body.decode(charset or "utf-8", "replace"))
    except json.JSONDecodeError:
        return None


def _html_schema_documents(body: bytes) -> tuple[list[Any], Any] | None:
    try:
        root = lxml_html.document_fromstring(
            body, parser=lxml_html.HTMLParser(recover=True, no_network=True)
        )
    except (etree.ParserError, ValueError):
        return None
    schema_scripts = root.xpath('//script[@type="application/ld+json"]')
    if not isinstance(schema_scripts, list):
        return None
    documents: list[Any] = []
    for script in schema_scripts[
        : commerce_intelligence_settings.discovery_max_schema_blocks
    ]:
        if not isinstance(script, etree._Element):
            continue
        document = _decode_json_document((script.text or "").encode("utf-8"), "utf-8")
        if document is not None:
            documents.append(document)
    return documents, root


def _bounded_schema_nodes(documents: list[Any]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for document in documents:
        nodes.extend(_schema_nodes(document))
        if len(nodes) >= commerce_intelligence_settings.discovery_max_schema_nodes:
            break
    return nodes


def _product_and_offer(
    nodes: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    product = next((node for node in nodes if _has_type(node, "Product")), {})
    offer = next((node for node in nodes if _has_type(node, "Offer")), {})
    offers = product.get("offers") if product else None
    if isinstance(offers, list):
        offer = next((item for item in offers if isinstance(item, dict)), offer)
    elif isinstance(offers, dict):
        offer = offers
    return product, offer


def _visible_product_name(root: Any | None, product: dict, meta: dict[str, str]) -> str:
    h1 = _first(root.xpath("//h1[1]//text()") if root is not None else ())
    title = _first(root.xpath("//title[1]//text()") if root is not None else ())
    return _first(
        (
            _mapping_value(product, "name"),
            meta.get("product:name", ""),
            meta.get("og:title", ""),
            h1,
            title,
        )
    )


def _product_variants(product: dict) -> list[dict[str, str]]:
    variants: list[dict[str, str]] = []
    raw_variants = product.get("hasVariant") if product else None
    for item in raw_variants if isinstance(raw_variants, list) else [raw_variants]:
        if not isinstance(item, dict):
            continue
        variant = {
            key: value
            for key, value in {
                "name": _mapping_value(item, "name"),
                "sku": _mapping_value(item, "sku"),
            }.items()
            if value
        }
        if variant:
            variants.append(variant)
        if len(variants) >= commerce_intelligence_settings.discovery_max_variants:
            break
    return variants


def _product_attributes(product: dict) -> dict[str, str]:
    attributes = {
        key: value
        for key, value in {
            "brand": _mapping_value(product, "brand"),
            "gtin": _mapping_value(product, "gtin", "gtin13", "gtin12", "gtin14"),
            "mpn": _mapping_value(product, "mpn"),
            "model": _mapping_value(product, "model"),
            "description": _mapping_value(product, "description"),
        }.items()
        if value
    }
    return dict(
        list(attributes.items())[
            : commerce_intelligence_settings.discovery_max_attribute_items
        ]
    )


def _product_identity(
    result: FetchResult, *, product: dict, offer: dict, name: str
) -> dict[str, Any]:
    mpn = _mapping_value(product, "mpn")
    model = _mapping_value(product, "model")
    sku = _mapping_value(product, "sku")
    price = _price(_mapping_value(offer, "price", "lowPrice"))
    currency = _mapping_value(offer, "priceCurrency")
    availability = _mapping_value(offer, "availability").rsplit("/", 1)[-1]
    aliases = [value for value in (model, mpn) if value][
        : commerce_intelligence_settings.discovery_max_aliases
    ]
    return {
        "name": name,
        "sku": sku,
        "aliases": aliases,
        "variants": _product_variants(product),
        "price": price,
        "currency": currency,
        "url": result.final_url,
        "attributes": _product_attributes(product),
        "availability": availability,
    }


def _schema_type_names(nodes: list[dict[str, Any]]) -> list[str]:
    schema_types: set[str] = set()
    for node in nodes:
        raw_type = node.get("@type")
        raw_types = raw_type if isinstance(raw_type, list) else [raw_type]
        for raw_type_value in raw_types:
            schema_type = _text(raw_type_value)
            if schema_type:
                schema_types.add(schema_type)
    return sorted(schema_types)[
        : commerce_intelligence_settings.discovery_max_schema_nodes
    ]


def _safe_provenance(provenance: AcquisitionProvenance | None) -> dict[str, Any]:
    if provenance is None:
        return {}
    return {
        "transport": provenance.transport,
        "rung": provenance.rung,
        "trigger": provenance.trigger,
        "impersonation_profile": provenance.impersonation_profile,
        "options": dict(provenance.options),
        "policy_version": provenance.policy_version,
    }


def _safe_acquisition(result: FetchResult) -> dict[str, Any]:
    """Keep credential-free ladder metadata, never raw HTML or request headers."""
    traces: list[dict[str, Any]] = []
    for trace in result.attempts[
        : commerce_intelligence_settings.discovery_max_trace_entries
    ]:
        traces.append(
            {
                "ordinal": trace.request_ordinal,
                "status_code": trace.status_code,
                "error_code": trace.error_code or "",
                "wire_bytes": trace.wire_bytes,
                "decoded_bytes": trace.decoded_bytes,
                "latency_ms": trace.latency_ms,
                "provenance": _safe_provenance(trace.acquisition),
            }
        )
    return {
        "state": COMMERCE_ACQUISITION_STATE_ACQUIRED,
        "provenance": _safe_provenance(result.acquisition),
        "attempts": traces,
    }


class CommerceDiscoveryWorker(DrainableWorkerMixin):
    """Claim, acquire, deterministically extract, and terminalize discovery tasks."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
        resolver: DnsResolver | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        browser_transport: AcquisitionTransport | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue = PostgresTaskQueue(
            self._session_factory, COMMERCE_DISCOVERY_QUEUE_SPEC
        )
        self.owner = owner or f"commerce-discovery-{uuid.uuid4().hex[:12]}"
        self._resolver = resolver or SystemDnsResolver()
        self._transport = transport
        self._browser_transport = browser_transport

    def _new_fetcher(self) -> SecureFetcher:
        return SecureFetcher(
            resolver=self._resolver,
            transport=self._transport,
            browser_transport=self._browser_transport,
        )

    async def run_once(self) -> int:
        sweep = await self._queue.release_expired_detailed(
            batch_size=commerce_intelligence_settings.discovery_lease_reclaim_batch_size
        )
        for run_id in sweep.failed_parent_ids:
            await self._reconcile(run_id)
        tasks = await self._queue.claim(
            owner=self.owner,
            limit=commerce_intelligence_settings.discovery_worker_batch_size,
            kinds=[COMMERCE_DISCOVERY_TASK_KIND_DISCOVER],
        )
        if tasks:
            await asyncio.gather(*(self._execute(task) for task in tasks))
        return len(tasks)

    async def run_forever(self) -> None:  # pragma: no cover - process loop
        logger.info("commerce discovery worker started", extra={"owner": self.owner})
        while True:
            try:
                ran = await self.run_once()
            except Exception:
                logger.exception("commerce discovery worker loop iteration failed")
                ran = 0
            if ran == 0:
                await asyncio.sleep(
                    commerce_intelligence_settings.discovery_poll_interval_seconds
                )

    async def _execute(self, claimed: CommerceDiscoveryTask) -> None:
        try:
            if not await self._queue.mark_running(task_id=claimed.id, owner=self.owner):
                return
            async with self._session_factory() as session:
                task = await session.get(CommerceDiscoveryTask, claimed.id)
                run = await session.get(CommerceDiscoveryRun, claimed.run_id)
                if task is None or run is None or task.workspace_id != run.workspace_id:
                    await session.rollback()
                    return
                await mark_discovery_run_running(session, run_id=run.id)
                await session.commit()
            if claimed.task_kind != COMMERCE_DISCOVERY_TASK_KIND_DISCOVER:
                return
            if await self._ack_upload_or_existing(claimed):
                return
            await self._acquire_and_finalize(claimed)
        except Exception as exc:
            logger.exception(
                "commerce discovery task crashed", extra={"task_id": str(claimed.id)}
            )
            await self._finalize_failure(
                claimed.id,
                error_code=COMMERCE_DISCOVERY_ERROR_WORKER_CRASH,
                error_detail=type(exc).__name__,
                retryable=False,
                consumed_network_attempt=False,
            )

    async def _ack_upload_or_existing(self, claimed: CommerceDiscoveryTask) -> bool:
        async with self._session_factory() as session:
            task = await session.get(CommerceDiscoveryTask, claimed.id)
            run = await session.get(CommerceDiscoveryRun, claimed.run_id)
            if task is None or run is None:
                return True
            if run.input_kind == COMMERCE_DISCOVERY_INPUT_UPLOAD:
                artifact_id = task.result_artifact_id
            else:
                artifact_id = await session.scalar(
                    select(CommerceDiscoveryArtifact.id).where(
                        CommerceDiscoveryArtifact.task_id == task.id
                    )
                )
                if artifact_id is not None:
                    await session.rollback()
                    await self._finalize_failure(
                        task.id,
                        error_code=COMMERCE_DISCOVERY_ERROR_LEGACY_PLACEHOLDER,
                        error_detail=COMMERCE_DISCOVERY_ERROR_LEGACY_PLACEHOLDER,
                        retryable=False,
                        consumed_network_attempt=False,
                    )
                    return True
            if artifact_id is None:
                return False
        acknowledged = await self._queue.succeed(
            task_id=claimed.id, owner=self.owner, result_artifact_id=artifact_id
        )
        if acknowledged:
            await self._reconcile(claimed.run_id)
        return True

    async def _acquire_and_finalize(self, claimed: CommerceDiscoveryTask) -> None:
        async with self._leased(claimed.id):
            request = FetchRequest(
                url=claimed.source_url,
                purpose=FETCH_PURPOSE_DISCOVER,
                allowed_content_types=frozenset(
                    commerce_intelligence_settings.discovery_allowed_content_types
                ),
            )
            try:
                async with self._new_fetcher() as fetcher:
                    result = await fetcher.fetch(request)
            except FetchError as exc:
                await self._finalize_failure(
                    claimed.id,
                    error_code=exc.error_code,
                    error_detail=exc.error_code,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                    consumed_network_attempt=bool(exc.attempts),
                )
                return
            if (
                result.status_code
                >= commerce_intelligence_settings.discovery_server_error_status_floor
                or result.status_code
                in commerce_intelligence_settings.discovery_retryable_http_statuses
                or result.status_code >= 400
            ):
                retryable = (
                    result.status_code
                    >= (
                        commerce_intelligence_settings.discovery_server_error_status_floor
                    )
                    or result.status_code
                    in commerce_intelligence_settings.discovery_retryable_http_statuses
                )
                await self._finalize_failure(
                    claimed.id,
                    error_code=COMMERCE_DISCOVERY_ERROR_HTTP_STATUS,
                    error_detail=str(result.status_code),
                    retryable=retryable,
                    consumed_network_attempt=True,
                )
                return
            extracted = _extract_product(result)
            if extracted is None:
                await self._finalize_failure(
                    claimed.id,
                    error_code=COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION,
                    error_detail=COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION,
                    retryable=False,
                    consumed_network_attempt=True,
                )
                return
            identity, evidence = extracted
            encoded = json.dumps(evidence, sort_keys=True, separators=(",", ":"))
            if (
                len(encoded)
                > commerce_intelligence_settings.discovery_max_artifact_payload_chars
            ):
                await self._finalize_failure(
                    claimed.id,
                    error_code=COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION,
                    error_detail=COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION,
                    retryable=False,
                    consumed_network_attempt=True,
                )
                return
            async with self._session_factory() as session:
                run = await session.get(CommerceDiscoveryRun, claimed.run_id)
                if run is None:
                    return
                candidate_kind, competitor_id = _configured_candidate_target(run)
                artifact_id = await finalize_discovery_success(
                    session,
                    task_id=claimed.id,
                    owner=self.owner,
                    evidence_kind=_evidence_kind(result),
                    source_url=result.final_url,
                    content_hash=hashlib.sha256(result.body).hexdigest(),
                    extracted=evidence,
                    acquisition=_safe_acquisition(result),
                    identity=_candidate_conflict_identity(
                        identity,
                        candidate_kind=candidate_kind,
                        competitor_id=competitor_id,
                        run_id=claimed.run_id,
                        task_id=claimed.id,
                        source_url=claimed.source_url,
                    ),
                    extraction_confidence=(
                        commerce_intelligence_settings.discovery_schema_confidence
                        if evidence["schema_types"]
                        else commerce_intelligence_settings.discovery_html_confidence
                    ),
                    candidate_kind=candidate_kind,
                    competitor_id=competitor_id,
                )
                await session.commit()
            if artifact_id is None:
                return

    async def _finalize_failure(
        self,
        task_id: uuid.UUID,
        *,
        error_code: str,
        error_detail: str,
        retryable: bool,
        consumed_network_attempt: bool,
        retry_after_seconds: float | None = None,
    ) -> None:
        run_id: uuid.UUID | None = None
        async with self._session_factory() as session:
            task = await session.get(CommerceDiscoveryTask, task_id)
            if task is not None:
                run_id = task.run_id
            finalized = await finalize_discovery_failure(
                session,
                task_id=task_id,
                owner=self.owner,
                error_code=error_code,
                error_detail=error_detail,
                retryable=retryable,
                retry_after_seconds=retry_after_seconds,
                consumed_network_attempt=consumed_network_attempt,
            )
            await session.commit()
        if finalized and run_id is not None:
            await self._reconcile(run_id)

    async def _reconcile(self, run_id: uuid.UUID) -> None:
        async with self._session_factory() as session:
            await reconcile_discovery_run(session, run_id=run_id)
            await session.commit()

    async def _heartbeat_loop(self, task_id: uuid.UUID) -> None:  # pragma: no cover
        while True:
            await asyncio.sleep(
                commerce_intelligence_settings.discovery_heartbeat_interval_seconds
            )
            try:
                await self._queue.heartbeat(task_id=task_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "commerce discovery heartbeat failed",
                    extra={"task_id": str(task_id)},
                )

    @contextlib.asynccontextmanager
    async def _leased(self, task_id: uuid.UUID) -> AsyncIterator[None]:
        heartbeat = asyncio.create_task(self._heartbeat_loop(task_id))
        try:
            yield
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    asyncio.run(CommerceDiscoveryWorker().run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
