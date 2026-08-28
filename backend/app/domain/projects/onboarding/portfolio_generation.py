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
from dataclasses import dataclass
from functools import partial
from math import floor

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.gateway import ModelGateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import (
    DISCOVERY_PROMPT_GENERATION_CONCURRENCY,
    brand_discovery_settings,
)
from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_CORE,
)
from app.core.config.visibility_prompts import (
    VISIBILITY_BRAND_PROMPT_COUNT,
    VISIBILITY_BRANDED_SHARE_WARNING,
    VISIBILITY_COMPARISON_PROMPT_COUNT,
    VISIBILITY_MAX_BRANDED_SHARE,
    VISIBILITY_MIN_BRANDED_PROMPTS,
    VISIBILITY_PROMPTS_PER_TOPIC,
    VISIBILITY_TOPIC_BATCH_SIZE,
    VISIBILITY_TOPIC_NAME_LIMIT,
    brand_cohort_system_prompt,
    prompt_system_prompt,
)
from app.domain.projects.discovery_schemas import DiscoveryTopic
from app.domain.prompts.generation_contract import (
    GenerationOutput,
    GenerationOutputError,
    build_generation_user_message,
    parse_planned_output,
)
from app.domain.prompts.generation_filtering import supported_qualifiers
from app.domain.prompts.portfolio_validation import (
    PortfolioValidator,
    market_terms,
    ordered_portfolio,
    positioning_shingles,
)
from app.domain.prompts.query_patterns import PromptSlot, build_prompt_slots

# The cohorts that name the tracked brand. Capped as a share of the final
# portfolio so a thin organic cohort cannot leave a set that only measures
# the brand answering about itself.
_NAMED_COHORTS = frozenset({PROMPT_COHORT_BRAND_DIAGNOSTIC, PROMPT_COHORT_COMPARISON})


@dataclass(frozen=True, slots=True)
class PortfolioResult:
    prompts: tuple[dict, ...] = ()
    errors: tuple[str, ...] = ()
    provider: str = ""
    model: str = ""


def _batches(topics: list[DiscoveryTopic]) -> list[list[DiscoveryTopic]]:
    size = VISIBILITY_TOPIC_BATCH_SIZE
    return [topics[start : start + size] for start in range(0, len(topics), size)]


def onboarding_brand_context(
    *,
    brand_name: str,
    primary_market: str,
    profile: dict,
    competitors: list[str],
) -> dict:
    """Onboarding's confirmed facts, in the shape the shared builder reads.

    There is no demand evidence yet at onboarding -- a demand snapshot needs
    connected Search Console data -- so that key is simply absent and the
    builder omits the block.
    """
    return {
        "brand_name": brand_name,
        "brand_aliases": [str(alias) for alias in profile.get("brand_aliases") or []],
        "competitors": [{"name": name} for name in competitors],
        "country_code": primary_market,
        "language_code": str(profile.get("language_code") or ""),
        "knowledge_base": {
            field: str(profile.get(field) or "")
            for field in ("description", "positioning", "target_audience")
        },
        "business_context": {
            field: profile.get(field)
            for field in (
                "business_model",
                "buyer_register",
                "category",
                "category_terms",
                "jobs_to_be_done",
                "service_areas",
                "buyer_roles",
            )
            if profile.get(field)
        },
    }


def _topic_request(
    *,
    brand_context: dict,
    topics: list[DiscoveryTopic],
    rejected: tuple[str, ...],
) -> tuple[str, list[PromptSlot]]:
    slots = build_prompt_slots(
        topics=topics,
        count=len(topics) * VISIBILITY_PROMPTS_PER_TOPIC,
        cohort=PROMPT_COHORT_CORE,
        brand_name=str(brand_context.get("brand_name") or ""),
        qualifiers=supported_qualifiers(brand_context),
    )
    return (
        build_generation_user_message(
            brand_context=brand_context,
            slots=slots,
            existing_prompts=[],
            rejected_reasons=rejected,
        ),
        slots,
    )


def _brand_request(
    *,
    brand_context: dict,
    competitors: list[str],
    topics: list[DiscoveryTopic],
    count: int,
    cohort: str,
    rejected: tuple[str, ...] = (),
) -> tuple[str, list[PromptSlot]]:
    slots = build_prompt_slots(
        topics=topics,
        count=count,
        cohort=cohort,
        brand_name=str(brand_context.get("brand_name") or ""),
        competitor_names=tuple(competitors),
        qualifiers=supported_qualifiers(brand_context),
        unbound_brand_diagnostic=cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC,
    )
    named_context = dict(brand_context)
    if cohort != PROMPT_COHORT_COMPARISON:
        named_context["competitors"] = []
    return (
        build_generation_user_message(
            brand_context=named_context,
            slots=slots,
            existing_prompts=[],
            rejected_reasons=rejected,
        ),
        slots,
    )


async def _call(
    client: ModelGateway, *, system: str, user: str, slots: list[PromptSlot]
) -> list[dict] | None:
    """One generation call. ``None`` means the provider itself failed."""
    try:
        raw = await client.complete_structured_json(
            system=system,
            user=user,
            schema_name="visibility_prompts",
            schema=GenerationOutput.model_json_schema(),
        )
        planned, _ = parse_planned_output(raw, slots=slots)
    except (ProviderError, GenerationOutputError, ValueError):
        return None
    return [
        {
            "slot_id": prompt.slot_id,
            "topic_id": str(prompt.topic_id) if prompt.topic_id is not None else None,
            "text": prompt.text,
            "intent": prompt.intent,
            "buyer_stage": prompt.buyer_stage,
            "prompt_intent": prompt.prompt_intent,
            "cohort": prompt.cohort,
            "archetype": prompt.archetype,
        }
        for prompt in planned
    ]


async def _gather_batches(
    client: ModelGateway,
    *,
    batches: list[list[DiscoveryTopic]],
    system: str,
    brand_context: dict,
    rejected: tuple[str, ...] = (),
) -> list[tuple[list[DiscoveryTopic], list[dict] | None]]:
    semaphore = asyncio.Semaphore(DISCOVERY_PROMPT_GENERATION_CONCURRENCY)

    async def run(topics: list[DiscoveryTopic]) -> list[dict] | None:
        async with semaphore:
            user, slots = _topic_request(
                brand_context=brand_context,
                topics=topics,
                rejected=rejected,
            )
            return await _call(
                client,
                system=system,
                user=user,
                slots=slots,
            )

    results = await asyncio.gather(
        *(run(batch) for batch in batches), return_exceptions=True
    )
    return [
        (batch, None if isinstance(item, BaseException) else item)
        for batch, item in zip(batches, results, strict=True)
    ]


@dataclass(frozen=True, slots=True)
class _Absorbed:
    """What ONE call admitted, separate from the shared validator's totals.

    The cohorts run concurrently against one validator, so its accepted rows
    answer for the whole portfolio, not for the caller.
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
    brand_context: dict,
    business_model: str,
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
        brand_context=brand_context,
    )
    reasons: list[str] = []
    covered: set[str] = set()
    for _batch, rows in results:
        absorbed = _absorb(validator, rows, cohort=PROMPT_COHORT_CORE)
        reasons.extend(absorbed.reasons)
        covered.update(absorbed.topics)

    missing = [topic for topic in topics if str(topic.topic_id) not in covered]
    if missing:
        retried = await _gather_batches(
            client,
            batches=_batches(missing),
            system=system,
            brand_context=brand_context,
            rejected=tuple(dict.fromkeys(reasons))[:8],
        )
        for _batch, rows in retried:
            absorbed = _absorb(validator, rows, cohort=PROMPT_COHORT_CORE)
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


async def _generate_named(
    client: ModelGateway,
    validator: PortfolioValidator,
    *,
    topics: list[DiscoveryTopic],
    brand_context: dict,
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
            brand_context=brand_context,
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
    brand_context: dict,
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
    user, slots = _brand_request(
        brand_context=brand_context,
        competitors=competitors,
        topics=topics[:VISIBILITY_TOPIC_NAME_LIMIT],
        count=count,
        cohort=cohort,
        rejected=rejected,
    )
    rows = await _call(
        client,
        system=brand_cohort_system_prompt(business_model, cohort),
        user=user,
        slots=slots,
    )
    return rows, _absorb(validator, rows, cohort=cohort, limit=count)


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
    brand_context = onboarding_brand_context(
        brand_name=brand_name,
        primary_market=primary_market,
        profile=profile,
        competitors=competitors,
    )
    # Concurrent because the cohorts are independent, and because running them
    # in sequence meant a slow organic cohort could burn the whole budget and
    # leave the brand and comparison cohorts ungenerated.
    core, named = await asyncio.gather(
        _generate_core(
            client,
            validator,
            topics=topics,
            brand_context=brand_context,
            business_model=business_model,
        ),
        _generate_named(
            client,
            validator,
            topics=topics,
            brand_context=brand_context,
            business_model=business_model,
            competitors=competitors,
        ),
    )
    warnings, core_reasons = core
    return [*warnings, *_reason_codes([*core_reasons, *named])]


def _reason_codes(reasons: list[str]) -> list[str]:
    """The distinct rejection reasons, bounded, as reportable codes."""
    return [f"prompt_rejected:{reason}" for reason in dict.fromkeys(reasons)][:5]


def _cap_branded_share(accepted: list[dict]) -> tuple[list[dict], bool]:
    """Trim the named cohorts so they never dominate a thin organic portfolio.

    The named counts are fixed and the organic count is not, so a portfolio
    that lost most of its organic cohort shipped as mostly brand prompts --
    a set that measures the brand answering about itself. Capping the SHARE
    (rather than raising or lowering the fixed counts) keeps a healthy
    portfolio exactly as it is today and only bites when the organic side came
    back thin.

    The share is of the FINAL portfolio -- organic plus branded -- which is
    what "a third of the set is brand prompts" means to anyone reading it.
    Taking it as a fraction of the organic count alone made the cap markedly
    tighter than documented: six organic prompts allowed only two branded when
    three of nine is 33%, comfortably inside the limit, so a healthy portfolio
    was trimmed and flagged for no reason.

    Trims from the end so the deterministic generation order decides which
    named prompts survive, and never drops below the diagnostic floor.
    """
    named = [row for row in accepted if row.get("cohort") in _NAMED_COHORTS]
    organic = [row for row in accepted if row.get("cohort") not in _NAMED_COHORTS]
    if not named:
        return accepted, False
    # Largest n with n / (organic + n) <= share, rearranged so the division is
    # by the constant rather than by a total that depends on n.
    allowed = max(
        VISIBILITY_MIN_BRANDED_PROMPTS,
        floor(
            len(organic)
            * VISIBILITY_MAX_BRANDED_SHARE
            / (1 - VISIBILITY_MAX_BRANDED_SHARE)
        ),
    )
    if len(named) <= allowed:
        return accepted, False
    keep = {id(row) for row in named[:allowed]}
    return [
        row
        for row in accepted
        if row.get("cohort") not in _NAMED_COHORTS or id(row) in keep
    ], True


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

    accepted, capped = _cap_branded_share(validator.accepted)
    if capped:
        warnings.append(VISIBILITY_BRANDED_SHARE_WARNING)
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
