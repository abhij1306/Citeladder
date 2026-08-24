"""Execution-cost configuration: pricing catalogues, formula versioning, and
the expected-cost estimates used by funded admission.

This module is the SOLE owner of expected execution costs (invariant 1): the
Part B funded-admission path imports ``expected_execution_cost`` from here
rather than defining a duplicate catalogue.

This module owns (a) the versioned unit-rate ``RoutePricing`` catalogue
  consumed by the append-only execution-cost projection, and (b) the
  route-keyed ``ExpectedExecutionCost`` catalogue consumed by funded
  admission ("what do we expect ONE execution of this route to cost").
  Both audit estimates and persisted execution projections read this one catalog.

Catalogue rate fields stay null until externally verified (frozen v8 plan): no
provider unit rates are invented from the aggregate T1 observations. With
rates null, persisted projections carry usage but no computed line costs
(``projection_status`` is then partial/unknown — never a fabricated zero), and
funded admission reads ``ExpectedExecutionCost.complete`` and fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Final

from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    measurement_route,
)

# Shared currency conversion: 1 USD = 1_000_000 micro-USD. Funded admission
# converts a minor-USD (cents) monthly budget to micro-USD through THIS
# constant (minor * MICRO_USD_PER_USD // 100) before comparing like units.
MICRO_USD_PER_USD: Final = 1_000_000

# Unit divisor for per-million-token rates. Kept separate from
# ``MICRO_USD_PER_USD`` (a currency conversion) and from analysis.py's
# scoring-only constant: the value coincidence carries no shared meaning.
TOKENS_PER_MILLION: Final = 1_000_000

# Version stamped on every persisted projection row. Bump when the line-cost
# arithmetic changes; old rows keep their frozen version (append-only).
EXECUTION_COST_FORMULA_VERSION: Final = "line-sum-v1"

# Version of the current unit-rate catalogue. ``unverified-rates-v1`` carries
# no verified rates — every rate field is null.
PRICING_CATALOG_VERSION: Final = "official-2026-08-03-v1"

# Projection completeness vocabulary (persisted; do not reuse for anything
# else). ``unknown`` never coerces to zero anywhere.
PROJECTION_STATUS_COMPLETE: Final = "complete"
PROJECTION_STATUS_PARTIAL: Final = "partial"
PROJECTION_STATUS_UNKNOWN: Final = "unknown"
PROJECTION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        PROJECTION_STATUS_COMPLETE,
        PROJECTION_STATUS_PARTIAL,
        PROJECTION_STATUS_UNKNOWN,
    }
)


@dataclass(frozen=True)
class RouteIdentity:
    """Immutable route triple an execution was performed on.

    Keyed on everywhere: pricing catalogue, expected-cost catalogue, and the
    worker's pricing lookup read the artifact's persisted provenance columns
    to rebuild exactly this identity.
    """

    logical_engine: str
    transport_provider: str
    transport_model: str


@dataclass(frozen=True)
class RoutePricing:
    """Versioned unit-rate card for one immutable route identity.

    Token rates are micro-USD per ONE MILLION tokens; ``search_fee_microusd``
    is micro-USD per search. A null rate is UNVERIFIED — it blocks the
    matching projected cost line and is never coerced to zero.
    ``effective_date`` stays empty while the card is unverified: an unverified
    card has no honest effective date.
    """

    uncached_input_microusd_per_million: int | None
    cached_input_microusd_per_million: int | None
    output_microusd_per_million: int | None
    reasoning_microusd_per_million: int | None
    search_fee_microusd: int | None
    currency: str
    effective_date: str
    pricing_version: str


@dataclass(frozen=True)
class ExpectedExecutionCost:
    """Route/retrieval-aware expected cost of ONE execution.

    ``complete`` is the funded-admission gate: admission fails closed on an
    incomplete estimate. With retrieval disabled the search fields are not
    applicable — they stay null (never zero) and completeness rides on the
    token estimate alone.
    """

    token_cost_microusd: int | None
    search_fee_microusd: int | None
    expected_searches: int | None
    complete: bool


@dataclass(frozen=True)
class _ExpectedCostEstimate:
    """Catalogue entry: frozen aggregate observations for one route."""

    token_cost_microusd: int | None
    search_fee_microusd: int | None
    expected_searches: int | None


def _approved_route(logical_engine: str) -> RouteIdentity:
    """Rebuild the immutable identity of an approved catalogue route."""

    route = measurement_route(logical_engine)
    return RouteIdentity(
        logical_engine=logical_engine,
        transport_provider=route.transport_provider,
        transport_model=route.transport_model,
    )


ROUTE_CHATGPT: Final = _approved_route(ENGINE_CHATGPT)

# Conservative, provider-free audit preview assumptions. They are estimate
# inputs, not runtime tuning knobs and never affect provider requests.
ESTIMATE_INPUT_CHARS_PER_TOKEN: Final = 4
ESTIMATE_SEARCH_CALLS: Final[dict[str, int]] = {
    ENGINE_CHATGPT: 1,
    ENGINE_CLAUDE: 3,
    ENGINE_GEMINI: 1,
}
ROUTE_CLAUDE: Final = _approved_route(ENGINE_CLAUDE)
ROUTE_GEMINI: Final = _approved_route(ENGINE_GEMINI)
APPROVED_ROUTE_IDENTITIES: Final[frozenset[RouteIdentity]] = frozenset(
    {
        ROUTE_CHATGPT,
        ROUTE_CLAUDE,
        ROUTE_GEMINI,
    }
)


def _unverified_pricing(pricing_version: str) -> RoutePricing:
    """The current rate card: every rate null until externally verified."""

    return RoutePricing(
        uncached_input_microusd_per_million=None,
        cached_input_microusd_per_million=None,
        output_microusd_per_million=None,
        reasoning_microusd_per_million=None,
        search_fee_microusd=None,
        currency="USD",
        effective_date="",
        pricing_version=pricing_version,
    )


def _pricing(
    input_rate: int | None,
    output_rate: int | None,
    *,
    cached_input_rate: int | None = None,
    search_fee: int | None = None,
) -> RoutePricing:
    return RoutePricing(
        uncached_input_microusd_per_million=input_rate,
        cached_input_microusd_per_million=cached_input_rate,
        output_microusd_per_million=output_rate,
        reasoning_microusd_per_million=None,
        search_fee_microusd=search_fee,
        currency="USD",
        effective_date="2026-08-03",
        pricing_version=PRICING_CATALOG_VERSION,
    )


# One unit-rate catalogue for the three approved citation-capable routes.
_ROUTE_PRICING_CATALOGS: Final[dict[str, dict[RouteIdentity, RoutePricing]]] = {
    PRICING_CATALOG_VERSION: {
        # GPT-5.6-sol pricing/search lines are intentionally unknown until the
        # complete official card is available.
        ROUTE_CHATGPT: _unverified_pricing(PRICING_CATALOG_VERSION),
        ROUTE_CLAUDE: _pricing(3_000_000, 15_000_000, search_fee=10_000),
        ROUTE_GEMINI: _pricing(1_500_000, 7_500_000, search_fee=14_000),
    }
}

# Expected per-execution costs stay empty until staging measurements exist.
# Published unit prices are not substituted for observed execution envelopes.
_EXPECTED_COST_CATALOG: Final[dict[RouteIdentity, _ExpectedCostEstimate]] = {}


def pricing_version_known(pricing_version: str) -> bool:
    """Return whether a pricing catalogue version exists (CLI validation)."""

    return pricing_version in _ROUTE_PRICING_CATALOGS


def route_pricing_for(
    route_identity: RouteIdentity, pricing_version: str
) -> RoutePricing | None:
    """Look up the rate card for one route under one pricing version.

    Returns None only when the pricing VERSION is unknown (nothing can be
    honestly stamped with it). A known version without a route entry yields an
    all-null unverified card: rates remain unknown, never zero-cost.
    """

    catalog = _ROUTE_PRICING_CATALOGS.get(pricing_version)
    if catalog is None:
        return None
    pricing = catalog.get(route_identity)
    if pricing is None:
        return _unverified_pricing(pricing_version)
    return pricing


def estimate_token_count(text: str) -> int:
    """Deterministic conservative token approximation for previews only."""
    return max(1, ceil(len(text) / ESTIMATE_INPUT_CHARS_PER_TOKEN))


def expected_execution_cost(
    route_identity: RouteIdentity,
    retrieval_enabled: bool,
) -> ExpectedExecutionCost:
    """Expected cost of one execution for admission control.

    - Missing token estimate is ALWAYS incomplete.
    - Retrieval enabled: missing per-search fee OR missing expected-search
      count is incomplete (both are required alongside the token estimate).
    - Retrieval disabled: search fields are not applicable — they stay null
      and neither become zero nor affect completeness.
    """

    estimate = _EXPECTED_COST_CATALOG.get(route_identity)
    token_cost = estimate.token_cost_microusd if estimate is not None else None
    if not retrieval_enabled:
        return ExpectedExecutionCost(
            token_cost_microusd=token_cost,
            search_fee_microusd=None,
            expected_searches=None,
            complete=token_cost is not None,
        )
    search_fee = estimate.search_fee_microusd if estimate is not None else None
    expected_searches = estimate.expected_searches if estimate is not None else None
    complete = (
        token_cost is not None
        and search_fee is not None
        and expected_searches is not None
    )
    return ExpectedExecutionCost(
        token_cost_microusd=token_cost,
        search_fee_microusd=search_fee,
        expected_searches=expected_searches,
        complete=complete,
    )
