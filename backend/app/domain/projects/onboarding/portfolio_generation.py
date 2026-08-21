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
) -> str:
    return json.dumps(
        {
            "brand_name": brand_name,
            "market": market,
            "business_model": business_model,
            "competitors": competitors if cohort == PROMPT_COHORT_COMPARISON else [],
            "allowed_intents": sorted(PROMPT_INTENTS),
            "prompts_per_topic": count,
            "topics": [
                {"topic_id": str(topic.topic_id), "name": topic.name}
                for topic in topics
            ],
        },
        ensure_ascii=False,
    )


async def _call(client: ModelGateway, *, system: str, user: str) -> list[dict] | None:
    """One generation call. ``None`` means the provider itself failed."""
    try:
        raw = await client.complete_structured_json(
            system=system,
            user=user,
            schema_name="visibility_prompts",
            schema=PortfolioEnvelope.model_json_schema(),
        )
        envelope = PortfolioEnvelope.model_validate_json(raw)
    except (ProviderError, ValidationError, ValueError):
        return None
    return [
        {
            "topic_id": str(row.topic_id) if row.topic_id else "",
            "text": row.text,
            "intent": row.intent,
        }
        for row in envelope.prompts
    ]


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
) -> list[list[dict] | None]:
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
    return [None if isinstance(item, BaseException) else item for item in results]


def _absorb(
    validator: PortfolioValidator,
    rows: list[dict] | None,
    *,
    cohort: str,
    limit: int | None = None,
) -> list[str]:
    reasons: list[str] = []
    admitted = 0
    for row in rows or []:
        if limit is not None and admitted >= limit:
            break
        error = validator.offer(row, cohort=cohort)
        if error:
            reasons.append(error)
        else:
            admitted += 1
    return reasons


async def _generate_core(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    market: str,
    business_model: str,
    buyer_register: str,
) -> list[str]:
    """Generate for every topic, then retry only the topics that came up empty."""
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
    for rows in results:
        reasons.extend(_absorb(validator, rows, cohort=PROMPT_COHORT_CORE))

    covered = validator.topics_covered()
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
        for rows in retried:
            _absorb(validator, rows, cohort=PROMPT_COHORT_CORE)

    covered = validator.topics_covered()
    return [
        f"topic_without_prompts:{topic.name}"
        for topic in topics
        if str(topic.topic_id) not in covered
    ]


async def _generate_named(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_name: str,
    market: str,
    business_model: str,
    competitors: list[str],
) -> None:
    """Brand-diagnostic and comparison cohorts. Never scored, only reported."""
    cohorts: list[tuple[str, int]] = [
        (PROMPT_COHORT_BRAND_DIAGNOSTIC, VISIBILITY_BRAND_PROMPT_COUNT)
    ]
    if competitors:
        cohorts.append((PROMPT_COHORT_COMPARISON, VISIBILITY_COMPARISON_PROMPT_COUNT))
    for cohort, count in cohorts:
        rows = await _call(
            client,
            system=brand_cohort_system_prompt(business_model, cohort),
            user=_brand_request(
                brand_name=brand_name,
                market=market,
                business_model=business_model,
                competitors=competitors,
                topics=topics[:VISIBILITY_TOPIC_BATCH_SIZE],
                count=count,
                cohort=cohort,
            ),
        )
        _absorb(validator, rows, cohort=cohort, limit=count)


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
    warnings = await _generate_core(
        client,
        validator,
        topics=topics,
        brand_name=brand_name,
        market=primary_market,
        business_model=business_model,
        buyer_register=str(profile.get("buyer_register") or ""),
    )
    await _generate_named(
        client,
        validator,
        topics=topics,
        brand_name=brand_name,
        market=primary_market,
        business_model=business_model,
        competitors=competitors,
    )
    return warnings


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
