"""Pass C: generate prompts for the canonical topics, a few topics at a time.

Batching is the point. The old contract asked for twelve prompts covering five
topics in one call under a twelve-word ceiling, which leaves a small model no
move except applying one sentence frame to every topic name -- and that is
exactly what shipped. Four prompts for one named topic is a task it can do.

Failure is per topic, not per portfolio. The old selector returned nothing
unless it could assemble exactly eight organic and two brand prompts, so a
single malformed row voided the whole run.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.gateway import ModelGateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import (
    DISCOVERY_PROMPT_GENERATION_CONCURRENCY,
    brand_discovery_settings,
)
from app.core.config.projects import PROMPT_INTENTS
from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_CORE,
)
from app.core.config.visibility_prompts import (
    VISIBILITY_BRAND_PROMPT_COUNT,
    VISIBILITY_COMPARISON_PROMPT_COUNT,
    VISIBILITY_PROMPTS_PER_TOPIC,
    VISIBILITY_TOPIC_BATCH_SIZE,
    VISIBILITY_TOPIC_NAME_LIMIT,
    brand_cohort_system_prompt,
    prompt_system_prompt,
)
from app.domain.projects.discovery_schemas import DiscoveryTopic
from app.domain.projects.onboarding.prompt_validation import (
    PortfolioValidator,
    market_terms,
    ordered_portfolio,
    positioning_shingles,
)

PromptIntent = Literal["discovery", "comparison", "purchase", "service", "local"]


class GeneratedPrompt(BaseModel):
    model_config = ConfigDict(extra="ignore")

    topic_id: uuid.UUID | None = None
    text: str = Field(min_length=1, max_length=300)
    intent: PromptIntent


class PortfolioEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompts: list[GeneratedPrompt] = Field(default_factory=list, max_length=40)


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    prompts: tuple[dict, ...] = ()
    errors: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""


def _batches(topics: list[DiscoveryTopic]) -> list[list[DiscoveryTopic]]:
    size = VISIBILITY_TOPIC_BATCH_SIZE
    return [topics[start : start + size] for start in range(0, len(topics), size)]


def _topic_request(
    *,
    brand_name: str,
    market: str,
    business_model: str,
    buyer_register: str,
    topics: list[DiscoveryTopic],
    rejected: tuple[str, ...],
) -> str:
    payload: dict[str, object] = {
        "brand_name": brand_name,
        "market": market,
        "business_model": business_model,
        "buyer_register": buyer_register,
        "allowed_intents": sorted(PROMPT_INTENTS),
        "prompts_per_topic": VISIBILITY_PROMPTS_PER_TOPIC,
        "topics": [
            {
                "topic_id": str(topic.topic_id),
                "name": topic.name,
                "description": topic.description,
            }
            for topic in topics
        ],
    }
    if rejected:
        payload["previous_rejection_reasons"] = list(rejected)
    return json.dumps(payload, ensure_ascii=False)


def _brand_request(
    *,
    brand_name: str,
    market: str,
    business_model: str,
    competitors: list[str],
    topics: list[DiscoveryTopic],
    count: int,
    cohort: str,
    rejected: tuple[str, ...] = (),
) -> str:
    payload: dict[str, object] = {
        "brand_name": brand_name,
        "market": market,
        "business_model": business_model,
        "competitors": competitors if cohort == PROMPT_COHORT_COMPARISON else [],
        "allowed_intents": sorted(PROMPT_INTENTS),
        "prompts_per_topic": count,
        "topics": [
            {"topic_id": str(topic.topic_id), "name": topic.name} for topic in topics
        ],
    }
    if rejected:
        payload["previous_rejection_reasons"] = list(rejected)
    return json.dumps(payload, ensure_ascii=False)


def _salvaged_rows(raw: str) -> list[dict]:
    """Every well-formed row in a response, ignoring the rows that are not.

    Validating the envelope as a whole discarded all four prompts whenever one
    row echoed a topic name instead of an id, or invented an intent. The batch
    is the unit of generation, not the unit of correctness: a row that cannot
    be read is dropped and the rest are kept, and the deterministic validator
    still has the final say on every survivor.
    """
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    prompts = payload.get("prompts")
    if not isinstance(prompts, list):
        return []
    rows: list[dict] = []
    for item in prompts:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        rows.append(
            {
                "topic_id": str(item.get("topic_id") or "").strip(),
                "text": text,
                "intent": str(item.get("intent") or "").strip(),
            }
        )
    return rows


async def _call(client: ModelGateway, *, system: str, user: str) -> list[dict] | None:
    """One generation call. ``None`` means the provider itself failed."""
    try:
        raw = await client.complete_structured_json(
            system=system,
            user=user,
            schema_name="visibility_prompts",
            schema=PortfolioEnvelope.model_json_schema(),
        )
    except (ProviderError, ValidationError, ValueError):
        return None
    return _salvaged_rows(raw)


async def _gather_batches(
    client: ModelGateway,
    *,
    batches: list[list[DiscoveryTopic]],
    system: str,
    brand_name: str,
    market: str,
    business_model: str,
    buyer_register: str,
    rejected: tuple[str, ...] = (),
) -> list[tuple[list[DiscoveryTopic], list[dict] | None]]:
    semaphore = asyncio.Semaphore(DISCOVERY_PROMPT_GENERATION_CONCURRENCY)

    async def run(topics: list[DiscoveryTopic]) -> list[dict] | None:
        async with semaphore:
            return await _call(
                client,
                system=system,
                user=_topic_request(
                    brand_name=brand_name,
                    market=market,
                    business_model=business_model,
                    buyer_register=buyer_register,
                    topics=topics,
                    rejected=rejected,
                ),
            )

    results = await asyncio.gather(
        *(run(batch) for batch in batches), return_exceptions=True
    )
    return [
        (batch, None if isinstance(item, BaseException) else item)
        for batch, item in zip(batches, results, strict=True)
    ]


def _assigned_topic(
    rows: list[dict] | None, topics: list[DiscoveryTopic]
) -> list[dict] | None:
    """Stamp the batch's topic onto its rows when the batch names exactly one.

    Asking a small model to echo a UUID back is asking it to do the one thing
    it is worst at. It returned the topic NAME, or a truncated id, and every
    core prompt was rejected as `topic_id` -- which emptied the organic cohort
    and left a portfolio of two branded prompts. When a call covers a single
    topic, the association is already known here and does not need to survive
    a round trip through the model.
    """
    if rows is None or len(topics) != 1:
        return rows
    topic_id = str(topics[0].topic_id)
    return [{**row, "topic_id": topic_id} for row in rows]


@dataclass(frozen=True, slots=True)
class _Absorbed:
    """What ONE call admitted, separate from the shared validator's totals.

    The cohorts run concurrently against one validator, so ``accepted`` and
    ``topics_covered()`` answer for the whole portfolio, not for the caller.
    Reading them to decide "did my cohort produce anything?" let a core
    admission satisfy the named cohort's retry gate, and let the single
    comparison prompt -- which is stamped with the leading topic's id -- mark
    that topic as covered, so the organic cohort never retried it and never
    reported it missing. Each call now decides from its own admissions.
    """

    reasons: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()

    @property
    def admitted(self) -> int:
        return len(self.topics)


def _absorb(
    validator: PortfolioValidator,
    rows: list[dict] | None,
    *,
    cohort: str,
    limit: int | None = None,
) -> _Absorbed:
    reasons: list[str] = []
    topics: list[str] = []
    for row in rows or []:
        if limit is not None and len(topics) >= limit:
            break
        error = validator.offer(row, cohort=cohort)
        if error:
            reasons.append(error)
        else:
            topics.append(str(row.get("topic_id") or ""))
    return _Absorbed(tuple(reasons), tuple(topics))


async def _generate_core(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    market: str,
    business_model: str,
    buyer_register: str,
) -> tuple[list[str], list[str]]:
    """Generate for every topic, then retry only the topics that came up empty.

    Returns the per-topic coverage warnings and the raw rejection reasons. The
    reasons used to be consumed by the retry and then dropped, which is why a
    portfolio that lost its whole organic cohort reported nothing about why.
    """
    system = prompt_system_prompt(business_model)
    results = await _gather_batches(
        client,
        batches=_batches(topics),
        system=system,
        brand_name=brand_name,
        market=market,
        business_model=business_model,
        buyer_register=buyer_register,
    )
    reasons: list[str] = []
    covered: set[str] = set()
    for batch, rows in results:
        absorbed = _absorb(
            validator, _assigned_topic(rows, batch), cohort=PROMPT_COHORT_CORE
        )
        reasons.extend(absorbed.reasons)
        covered.update(absorbed.topics)

    missing = [topic for topic in topics if str(topic.topic_id) not in covered]
    if missing:
        retried = await _gather_batches(
            client,
            batches=_batches(missing),
            system=system,
            brand_name=brand_name,
            market=market,
            business_model=business_model,
            buyer_register=buyer_register,
            rejected=tuple(dict.fromkeys(reasons))[:8],
        )
        for batch, rows in retried:
            absorbed = _absorb(
                validator, _assigned_topic(rows, batch), cohort=PROMPT_COHORT_CORE
            )
            reasons.extend(absorbed.reasons)
            covered.update(absorbed.topics)

    warnings = [
        f"topic_without_prompts:{topic.name}"
        for topic in topics
        if str(topic.topic_id) not in covered
    ]
    if not covered:
        # The organic cohort is the portfolio: without it the user is left with
        # the two mandatory brand prompts and no explanation.
        warnings.append("core_prompts_empty")
    return warnings, reasons


def _named_topic(
    rows: list[dict] | None, topics: list[DiscoveryTopic], cohort: str
) -> list[dict] | None:
    """Resolve the topic for a brand or comparison row without the model's help.

    Same failure as the core cohort: the model returns the topic name, and the
    id gate then rejects the entire cohort. A brand-diagnostic prompt does not
    need a topic at all, so its id is cleared rather than guessed. A comparison
    prompt does need one, and there is only ever one comparison prompt, so it
    is attributed to the leading topic here instead of round-tripping a UUID.
    """
    if rows is None:
        return rows
    if cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC:
        return [{**row, "topic_id": ""} for row in rows]
    if cohort == PROMPT_COHORT_COMPARISON and topics:
        return [{**row, "topic_id": str(topics[0].topic_id)} for row in rows]
    return rows


async def _generate_named(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    market: str,
    business_model: str,
    competitors: list[str],
) -> list[str]:
    """Brand-diagnostic and comparison cohorts. Never scored, only reported."""
    cohorts: list[tuple[str, int]] = [
        (PROMPT_COHORT_BRAND_DIAGNOSTIC, VISIBILITY_BRAND_PROMPT_COUNT)
    ]
    if competitors:
        cohorts.append((PROMPT_COHORT_COMPARISON, VISIBILITY_COMPARISON_PROMPT_COUNT))
    reasons: list[str] = []
    for cohort, count in cohorts:
        attempt = partial(
            _named_attempt,
            client,
            validator,
            topics=topics,
            brand_name=brand_name,
            market=market,
            business_model=business_model,
            competitors=competitors,
            cohort=cohort,
            count=count,
        )
        rows, absorbed = await attempt()
        cohort_reasons = list(absorbed.reasons)
        # These cohorts had no retry at all, so a model that simply forgot to
        # name the brand lost the whole cohort -- and with the organic cohort
        # also empty that is a portfolio of nothing, which is what shipped as
        # "Initial prompt generation failed". One bounded retry, told what was
        # wrong, is the same deal the core cohort already gets. A provider
        # failure (``rows is None``) produces no rejection reasons at all, so
        # it has to arm the retry itself; a well-formed empty response is a
        # real answer and is left alone.
        if not absorbed.admitted and (rows is None or cohort_reasons):
            _, retried = await attempt(
                rejected=tuple(dict.fromkeys(cohort_reasons))[:8]
            )
            cohort_reasons.extend(retried.reasons)
        reasons.extend(cohort_reasons)
    return reasons


async def _named_attempt(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    market: str,
    business_model: str,
    competitors: list[str],
    cohort: str,
    count: int,
    rejected: tuple[str, ...] = (),
) -> tuple[list[dict] | None, _Absorbed]:
    """One call for one named cohort, with its raw rows and its own admissions.

    The rows come back so the caller can tell a provider failure (``None``)
    from a well-formed response that simply admitted nothing.
    """
    rows = await _call(
        client,
        system=brand_cohort_system_prompt(business_model, cohort),
        user=_brand_request(
            brand_name=brand_name,
            market=market,
            business_model=business_model,
            competitors=competitors,
            topics=topics[:VISIBILITY_TOPIC_NAME_LIMIT],
            count=count,
            cohort=cohort,
            rejected=rejected,
        ),
    )
    return rows, _absorb(
        validator, _named_topic(rows, topics, cohort), cohort=cohort, limit=count
    )


def _validator(
    *,
    brand_terms: list[str],
    competitors: list[str],
    competitor_terms: list[str] | None,
    topics: list[DiscoveryTopic],
    profile: dict,
    primary_market: str,
) -> PortfolioValidator:
    return PortfolioValidator(
        topic_ids=frozenset(str(topic.topic_id) for topic in topics),
        brand_terms=brand_terms,
        competitor_terms=competitor_terms or competitors,
        positioning=positioning_shingles(
            [
                str(profile.get("description") or ""),
                str(profile.get("positioning") or ""),
                str(profile.get("target_audience") or ""),
            ]
        ),
        market_words=market_terms(
            primary_market, list(profile.get("service_areas") or [])
        ),
    )


async def _generate_all(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    primary_market: str,
    profile: dict,
    competitors: list[str],
) -> list[str]:
    business_model = str(profile.get("business_model") or "")
    # Concurrent because the cohorts are independent, and because running them
    # in sequence meant a slow organic cohort could burn the whole budget and
    # leave the brand and comparison cohorts ungenerated.
    core, named = await asyncio.gather(
        _generate_core(
            client,
            validator,
            topics=topics,
            brand_name=brand_name,
            market=primary_market,
            business_model=business_model,
            buyer_register=str(profile.get("buyer_register") or ""),
        ),
        _generate_named(
            client,
            validator,
            topics=topics,
            brand_name=brand_name,
            market=primary_market,
            business_model=business_model,
            competitors=competitors,
        ),
    )
    warnings, core_reasons = core
    return [*warnings, *_reason_codes([*core_reasons, *named])]


def _reason_codes(reasons: list[str]) -> list[str]:
    """The distinct rejection reasons, bounded, as reportable codes."""
    return [f"prompt_rejected:{reason}" for reason in dict.fromkeys(reasons)][:5]


async def generate_portfolio(
    *,
    brand_name: str,
    brand_terms: list[str],
    primary_market: str,
    profile: dict,
    competitors: list[str],
    competitor_terms: list[str] | None,
    topics: list[DiscoveryTopic],
) -> PortfolioResult:
    """Build the initial portfolio. Fails only when no topic produced a prompt."""
    try:
        client = create_model_gateway()
    except AgentNotConfiguredError:
        return PortfolioResult(errors=("generation_unavailable",))

    validator = _validator(
        brand_terms=brand_terms,
        competitors=competitors,
        competitor_terms=competitor_terms,
        topics=topics,
        profile=profile,
        primary_market=primary_market,
    )
    warnings: list[str] = []
    try:
        async with asyncio.timeout(
            brand_discovery_settings.portfolio_generation_timeout_seconds
        ):
            warnings = await _generate_all(
                client,
                validator,
                topics=topics,
                brand_name=brand_name,
                primary_market=primary_market,
                profile=profile,
                competitors=competitors,
            )
    except TimeoutError:
        warnings.append("generation_timeout")

    accepted = validator.accepted
    if not accepted:
        return PortfolioResult(
            errors=tuple(warnings) or ("generation_failed",),
            provider=client.base_url_host,
            model=client.model,
        )
    return PortfolioResult(
        prompts=tuple(
            ordered_portfolio(
                accepted, topic_ids=[str(topic.topic_id) for topic in topics]
            )
        ),
        errors=tuple(dict.fromkeys(warnings)),
        provider=client.base_url_host,
        model=client.model,
    )
