"""Deterministic answer-engine and Site Health fixtures for development seeding."""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import date

import httpx

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
    CitationResult,
    FinishReason,
    NormalizedUsage,
    SearchEventResult,
)
from app.connectors.web_evidence.contracts import (
    AcquisitionTransport,
    FetchRequest,
    FetchResult,
    ResolvedTarget,
)

_PUBLIC_IP = "93.184.216.34"
_WANDERLUST_CITATION_LABEL = "Wanderlust Gear"
# Monitored-URL allowance granted to the demo workspace so Site Health seeds a
# full-discovery crawl with user selection.
#
# Deliberately far above the tier-1 commercial allowance (50). This is a local
# development fixture, not a plan: a real storefront's crawl stopped at
# `partially_completed` with ~48 of its pages analyzed, which caps the catalog
# and therefore everything Commerce projects from it. Raising the PLAN would
# change what customers are sold; raising the dev seed only changes what a
# developer can exercise locally.
SEED_MONITORED_URL_ALLOWANCE = 500


@dataclass(frozen=True)
class _ProductSpec:
    """One seeded own-catalog product the fixture answers must name."""

    name: str
    sku: str
    url: str
    price: float
    attributes: dict[str, str]
    currency: str = "USD"


@dataclass(frozen=True)
class _CompetitorProductSpec:
    """The seeded competitor product the fixture answers must name."""

    name: str
    url: str
    price: float
    attributes: dict[str, str]
    currency: str = "USD"


# Demo catalog for the Wanderlust project (Agentic Commerce surface). The
# stub adapter's fixture answers name these exact products with these exact
# prices, so the deterministic product analyzer
# (analysis/product_scoring.py) produces non-zero ProductResponseAnalysis /
# ProductMention / ProductMetricSnapshot rows and the Commerce Visibility
# tab demonstrates real values (keep the answers below in sync - the unit
# test tests/unit/test_seed_dev_data.py guards the contract).
DEMO_PRODUCT_SPECS: tuple[_ProductSpec, ...] = (
    _ProductSpec(
        name="Summit 40L Trail Pack",
        sku="WGC-S40-BLK",
        url="https://wanderlustgear.com/backpacks/summit-40l",
        price=189.99,
        attributes={"gtin": "00850000000401", "brand": "Wanderlust Gear"},
    ),
    _ProductSpec(
        name="Voyager 25L Carry-On Pack",
        sku="WGC-V25-GRY",
        url="https://wanderlustgear.com/backpacks/voyager-25l",
        price=129.99,
        attributes={"gtin": "00850000000251", "brand": "Wanderlust Gear"},
    ),
)
DEMO_COMPETITOR_PRODUCT_SPEC = _CompetitorProductSpec(
    name="TrailBlaze Alpine 45",
    url="https://trailblazepacks.com/alpine-45",
    price=174.99,
    attributes={
        "gtin": "00860000000451",
        "brand": "TrailBlaze Packs",
        "material": "Recycled ripstop nylon",
        "warranty": "Lifetime",
        "weight": "1.4 kg",
    },
)

# Wanderlust prompt fixtures: (text, intent, status, origin) covering every
# intent (discovery/comparison/purchase/service/local) and every status
# (active/proposed/archived). Only "active" prompts enter the seeded audit.
PROMPT_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "best hiking backpack for a week-long trip",
        "discovery",
        "active",
        "manual",
    ),
    (
        "what is the most durable travel backpack under $200",
        "discovery",
        "active",
        "manual",
    ),
    (
        "Wanderlust Gear vs TrailBlaze Packs which is better",
        "comparison",
        "active",
        "manual",
    ),
    (
        "compare Summit Gear and Wanderlust Gear warranties",
        "comparison",
        "active",
        "imported",
    ),
    (
        "where can I buy a waterproof backpack online",
        "purchase",
        "active",
        "manual",
    ),
    (
        "best place to buy carry-on travel backpacks",
        "purchase",
        "active",
        "manual",
    ),
    ("does Wanderlust Gear offer free returns", "service", "active", "manual"),
    (
        "how do I file a warranty claim for a torn backpack",
        "service",
        "proposed",
        "generated",
    ),
    (
        "best outdoor gear shops near Denver Colorado",
        "local",
        "active",
        "manual",
    ),
    (
        "hiking backpack stores in Seattle Washington",
        "local",
        "proposed",
        "generated",
    ),
    (
        "old prompt about discontinued backpack line",
        "discovery",
        "archived",
        "manual",
    ),
)


# ---------------------------------------------------------------------------
# Stub answer-engine adapter (no network calls) - mirrors
# tests/component/test_analysis_api.py::_StubAdapter but varies the answer
# per engine/prompt so different prompts get different mention/citation
# outcomes (some brand-mentioning, some not, some citing competitor only).
# Answers are recommendation-style prose with numbered product picks that
# name the seeded catalog products + competitor product WITH prices (and
# buyer-destination links), so the deterministic product analyzer
# (analysis/product_scoring.py) produces non-zero ProductResponseAnalysis /
# ProductMention / ProductMetricSnapshot rows and the Commerce Visibility
# tab demonstrates real values.
# ---------------------------------------------------------------------------
def _prompt_bucket(prompt: str) -> int:
    """Stable per-prompt variety bucket (0, 1, or 2).

    md5 of the prompt text: Python's salted ``hash()`` varies per process,
    which made seeded mention/citation outcomes change on every reseed.
    """
    digest = hashlib.md5(prompt.encode("utf-8"), usedforsecurity=False)
    return int(digest.hexdigest(), 16) % 3


_seed_audit_generation = 0


def set_seed_audit_generation(value: int) -> None:
    global _seed_audit_generation
    _seed_audit_generation = value


def _citation_span(answer: str, cited_text: str) -> tuple[int, int]:
    start = answer.index(cited_text)
    return start, start + len(cited_text)


class _SeedStubAdapter:
    def __init__(
        self, *, logical_engine: str, transport_provider: str, **_: object
    ) -> None:
        self.logical_engine = logical_engine
        self.transport_provider = transport_provider
        self.generation = _seed_audit_generation

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        prompt = request.prompt
        summit, voyager = DEMO_PRODUCT_SPECS
        alpine = DEMO_COMPETITOR_PRODUCT_SPEC
        # Deterministic variety: bucket 0 is a real "lost" query (no brand
        # mention, competitor product only), bucket 1 mentions the brand and
        # ranks both own products above the competitor product, bucket 2
        # mentions the brand and its own products only. Every product pick
        # keeps its price + buyer-destination URL on the mention's own line
        # and close behind it: the analyzer's price/destination extraction
        # scans a line-clipped window centered on the mention
        # (PRODUCT_PRICE_WINDOW_CHARS=160, PRODUCT_ATTRIBUTE_WINDOW_CHARS=200).
        bucket = min(2, _prompt_bucket(prompt) + self.generation)
        if bucket == 0:
            answer = (
                f"For '{prompt}', popular options include TrailBlaze Packs and "
                "Summit Gear. Both offer solid warranties. Two packs come up "
                "most often:\n"
                f"1. {alpine.name} - ${alpine.price:.2f} ({alpine.url}) - "
                "two-year warranty, a 45-liter alpine pack.\n"
                "2. Summit Gear Ridgeline 50 - $159.99, a lightweight 50-liter "
                "pack for weekend trips."
            )
            start, end = _citation_span(answer, "TrailBlaze Packs")
            citations: tuple[CitationResult, ...] = (
                CitationResult(
                    ordinal=0,
                    url="https://trailblazepacks.com/",
                    title="TrailBlaze Packs",
                    domain="trailblazepacks.com",
                    start_index=start,
                    end_index=end,
                    cited_text="TrailBlaze Packs",
                ),
            )
        elif bucket == 1:
            answer = (
                f"When it comes to '{prompt}', Wanderlust Gear Co. is a strong "
                "choice thanks to its lifetime warranty, and TrailBlaze Packs is "
                "a solid alternative for budget shoppers. The top picks:\n"
                f"1. {summit.name} - ${summit.price:.2f} ({summit.url}) - "
                "lifetime warranty, a 40-liter trail pack.\n"
                f"2. {voyager.name} - ${voyager.price:.2f} ({voyager.url}) - "
                "lower price, a carry-on sized 25-liter pack.\n"
                f"3. {alpine.name} - ${alpine.price:.2f} ({alpine.url}) - "
                "two-year warranty, a 45-liter alpine alternative."
            )
            wanderlust_start, wanderlust_end = _citation_span(
                answer, _WANDERLUST_CITATION_LABEL
            )
            trailblaze_start, trailblaze_end = _citation_span(
                answer, "TrailBlaze Packs"
            )
            citations = (
                CitationResult(
                    ordinal=0,
                    url="https://wanderlustgear.com/backpacks",
                    title="Wanderlust Gear - Backpacks",
                    domain="wanderlustgear.com",
                    start_index=wanderlust_start,
                    end_index=wanderlust_end,
                    cited_text=_WANDERLUST_CITATION_LABEL,
                ),
                CitationResult(
                    ordinal=1,
                    url="https://trailblazepacks.com/",
                    title="TrailBlaze Packs",
                    domain="trailblazepacks.com",
                    start_index=trailblaze_start,
                    end_index=trailblaze_end,
                    cited_text="TrailBlaze Packs",
                ),
            )
        else:
            answer = (
                f"'{prompt}' - Wanderlust Gear Co. consistently ranks well in "
                "outdoor gear roundups for durability and customer service. Two "
                "packs stand out:\n"
                f"1. {summit.name} - ${summit.price:.2f} ({summit.url}) - "
                "lifetime warranty, the brand's 40-liter trail pack.\n"
                f"2. {voyager.name} - ${voyager.price:.2f} ({voyager.url}) - "
                "lower price, a compact 25-liter carry-on for weekend travel."
            )
            start, end = _citation_span(answer, _WANDERLUST_CITATION_LABEL)
            citations = (
                CitationResult(
                    ordinal=0,
                    url="https://wanderlustgear.com/reviews",
                    title="Wanderlust Gear Reviews",
                    domain="wanderlustgear.com",
                    start_index=start,
                    end_index=end,
                    cited_text=_WANDERLUST_CITATION_LABEL,
                ),
            )
        return AnswerEngineResponse(
            logical_engine=self.logical_engine,
            transport_provider=self.transport_provider,
            transport_model=request.model,
            answer_text=answer,
            search_used=True,
            search_events=(SearchEventResult(sequence=0, query=prompt),),
            citations=citations,
            provider_metadata={"query_text_available": True},
            # The typed usage contract (what the live parsers emit); the
            # cache/reasoning splits and provider cost are unknown for a
            # fixture, so they stay null rather than a fabricated zero.
            normalized_usage=NormalizedUsage(
                uncached_input_tokens=12,
                output_tokens=48,
                total_tokens=60,
                web_search_requests=1,
            ),
            finish_reason=FinishReason.STOP,
            latency_ms=850,
        )


def _build_seed_adapter(
    *, logical_engine: str, transport_provider: str, **kwargs: object
):
    return _SeedStubAdapter(
        logical_engine=logical_engine, transport_provider=transport_provider, **kwargs
    )


# ---------------------------------------------------------------------------
# Site Health mock HTTP transport (no network calls)
# ---------------------------------------------------------------------------
class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aiter__(self):
        yield self._data

    async def aclose(self) -> None:
        return None


class _FakeResolver:
    async def resolve(self, host: str, port: int) -> list[str]:
        return [_PUBLIC_IP]


def _rich_html(path: str, title: str, links: list[str]) -> bytes:
    words = " ".join(f"word{i}" for i in range(140))
    anchors = "".join(f'<a href="{link}">{link}</a>' for link in links)
    return (
        f"<html><head><title>{title}</title>"
        f'<meta name="description" content="A detailed page about {title}.">'
        f'<link rel="canonical" href="https://wanderlustgear.com{path}">'
        f'<meta property="og:title" content="{title}">'
        '<meta name="author" content="Wanderlust Editorial">'
        '<meta property="article:published_time" content="2026-06-01T00:00:00Z">'
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"Wanderlust Gear Co.",'
        '"url":"https://wanderlustgear.com","sameAs":["https://twitter.com/wanderlustgear"]}'
        "</script></head><body>"
        f"<h1>{title}</h1><p>{words}</p>"
        "<h2>What makes this reliable?</h2>"
        f"{anchors}"
        '<a href="https://external.org/review">external review</a>'
        "</body></html>"
    ).encode()


def _thin_html(title: str) -> bytes:
    return (
        f"<html><head><title>{title}</title></head><body><p>too short</p></body></html>"
    ).encode()


def _site_pages() -> dict[str, bytes | tuple[bytes, dict[str, str]]]:
    rich = _rich_html("/", "Wanderlust Gear Co. - Home", ["/backpacks", "/reviews"])
    backpacks = _rich_html("/backpacks", "Backpacks Catalog", ["/"])
    reviews = _rich_html("/reviews", "Customer Reviews", ["/"])
    thin = _thin_html("Contact")
    return {
        "/": (
            gzip.compress(rich),
            {
                "content-encoding": "gzip",
                "strict-transport-security": "max-age=63072000; includeSubDomains",
            },
        ),
        "/backpacks": backpacks,
        "/reviews": reviews,
        "/contact": thin,
    }


class _SeedAcquisitionTransport(AcquisitionTransport):
    """Adapt the offline page handler to the Site Health acquisition contract.

    ``SiteHealthWorker``/``SecureFetcher`` consume an ``AcquisitionTransport``
    (``fetch(request, target, ...) -> FetchResult``), not an
    ``httpx.MockTransport``. The seeder handed over the raw ``MockTransport``,
    so every seeded crawl fetch raised ``AttributeError`` on the missing
    ``fetch``. Mirrors ``tests/component/site_health_worker_helpers.py``.
    """

    def __init__(self, handler) -> None:
        self._handler = handler

    async def fetch(
        self,
        request: FetchRequest,
        target: ResolvedTarget,
        *,
        max_wire_bytes: int,
        max_decoded_bytes: int,
        timeout_seconds: float,
    ) -> FetchResult:
        del timeout_seconds
        response = self._handler(
            httpx.Request(request.method, target.url, headers=request.headers)
        )
        body = await response.aread()
        if len(body) > max_wire_bytes or len(body) > max_decoded_bytes:
            raise AssertionError("seed response exceeded configured crawl bounds")
        content_type = response.headers.get("content-type", "").split(";", 1)[0]
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            status_code=response.status_code,
            redacted_headers=dict(response.headers),
            content_type=content_type,
            http_version=response.http_version or "HTTP/1.1",
            body=body,
            wire_bytes=len(body),
            decoded_bytes=len(body),
            ttfb_ms=1,
            latency_ms=1,
            redirect_location=response.headers.get("location", ""),
        )

    async def aclose(self) -> None:
        return None


def _site_transport() -> AcquisitionTransport:
    pages = _site_pages()

    def handler(request: httpx.Request) -> httpx.Response:
        entry = pages.get(request.url.path)
        if entry is None:
            return httpx.Response(
                404,
                headers={"content-type": "text/html"},
                stream=_ByteStream(b"not found"),
            )
        if isinstance(entry, tuple):
            body, extra_headers = entry
            headers = {"content-type": "text/html", **extra_headers}
        else:
            body, headers = entry, {"content-type": "text/html"}
        return httpx.Response(200, headers=headers, stream=_ByteStream(body))

    return _SeedAcquisitionTransport(handler)


def _gsc_rows_response(body: dict, metric_date: date) -> httpx.Response:
    """One deterministic Search Analytics row, keyed by the requested dimensions."""
    values = {
        "query": "best hiking backpack",
        "page": "https://wanderlustgear.com/backpacks",
        "searchAppearance": "WEB",
        "device": "MOBILE",
        "country": "usa",
        "date": metric_date.isoformat(),
    }
    dimensions = body.get("dimensions") or []
    return httpx.Response(
        200,
        json={
            "rows": [
                {
                    "keys": [values[item] for item in dimensions],
                    "clicks": 12,
                    "impressions": 240,
                    "ctr": 0.05,
                    "position": 6.0,
                }
            ]
        },
    )


def _ga4_report_response(body: dict, metric_date: date) -> httpx.Response:
    """One deterministic runReport row, keyed by the requested dimensions."""
    dimension_values = {
        "date": metric_date.strftime("%Y%m%d"),
        "sessionDefaultChannelGroup": "Organic Search",
        "sessionSource": "google",
        "sessionMedium": "organic",
        "fullReferrer": "https://google.com/",
        "landingPage": "/backpacks",
        "itemId": "WGC-S40-BLK",
        "itemName": "Summit 40L Trail Pack",
    }
    dimensions = [item["name"] for item in body.get("dimensions") or []]
    metrics = [item["name"] for item in body.get("metrics") or []]
    return httpx.Response(
        200,
        json={
            "dimensionHeaders": [{"name": item} for item in dimensions],
            "metricHeaders": [
                {"name": item, "type": "TYPE_INTEGER"} for item in metrics
            ],
            "rows": [
                {
                    "dimensionValues": [
                        {"value": dimension_values.get(item, "seed")}
                        for item in dimensions
                    ],
                    "metricValues": [{"value": "12"} for _ in metrics],
                }
            ],
            "rowCount": 1,
        },
    )


#: Provider host -> deterministic response builder for the seeded sync run.
_INTEGRATION_RESPONSES = {
    "www.googleapis.com": _gsc_rows_response,
    "analyticsdata.googleapis.com": _ga4_report_response,
}


def _integration_transport(metric_date: date) -> httpx.MockTransport:
    """Deterministic GSC/GA4 provider fixture used by the real sync worker."""

    def handler(request: httpx.Request) -> httpx.Response:
        build = _INTEGRATION_RESPONSES.get(request.url.host)
        if build is None:
            raise AssertionError(f"unexpected integration request: {request.url.host}")
        return build(json.loads(request.content or b"{}"), metric_date)

    return httpx.MockTransport(handler)
