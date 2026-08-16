"""Model-authored prompt portfolio, generated from the confirmed context.

This is the change the whole rebuild exists for. Previously
``_prepare_confirmed_portfolio`` passed an empty list as the model's prompts,
which always failed the count gate, so 100% of shipped prompts came from slot
templates -- and a measured discrimination test showed a judge could pick those
out of a lineup of real buyer queries essentially every time.

Here the model writes the portfolio from the confirmed business context, and the
deterministic templates become what they were always meant to be: a fallback for
when the model call fails.

The call is made once, after the user confirms the ICP, so the prompts reflect
what the user actually approved rather than what discovery guessed.
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import (
    BRAND_RELEVANT_PROMPT_MAX,
    BRANDED_PROMPT_MAX,
    MARKET_CONTEXT_TERMS,
    MARKET_VISIBILITY_PROMPT_MAX,
    ONBOARDING_PORTFOLIO_SYSTEM_PROMPT,
    PORTFOLIO_PROMPT_MIN,
    brand_discovery_settings,
)
from app.core.config.projects import PROMPT_INTENTS
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_DIAGNOSTIC,
    BRAND_RELEVANT,
    COMPARISON,
    MARKET_VISIBILITY,
)

PromptIntent = Literal["discovery", "comparison", "purchase", "service", "local"]
PromptCohort = Literal[
    "market_visibility", "brand_relevant", "brand_diagnostic", "comparison"
]
assert set(get_args(PromptIntent)) == set(PROMPT_INTENTS)
assert set(get_args(PromptCohort)) == {
    MARKET_VISIBILITY,
    BRAND_RELEVANT,
    BRAND_DIAGNOSTIC,
    COMPARISON,
}

# Few-shot exemplars showing the *register* we want, drawn from businesses that
# are deliberately not in the golden corpus -- using corpus cases here would leak
# the evaluation into the thing being evaluated.
_REGISTER_EXEMPLARS: dict[str, list[str]] = {
    "terse_transactional": [
        "cheapest place to buy running shoes online",
        "which store has same day delivery",
        "airfryer under 5000 worth it",
    ],
    "research_comparative": [
        "notion vs obsidian for research notes",
        "best crm for a 5 person agency",
        "is the paid tier actually worth it",
    ],
    "advice_seeking": [
        "how do i know if a broker is legit",
        "is it safe to keep savings in an app",
        "what should i check before signing up",
    ],
    "local_urgent": [
        "emergency locksmith near me open now",
        "how much does a plumber charge in pune",
        "same day ac repair near me",
    ],
}


class GeneratedPrompt(BaseModel):
    """One model-written prompt.

    `cohort` and `intent` are required Literals, not free strings: declared as
    optional `str` the model simply omitted them, and every prompt was then
    rejected for a missing cohort. Putting the enum in the JSON schema is what
    actually makes the model choose.
    """

    text: str = Field(min_length=1, max_length=300)
    theme: str = Field(min_length=1, max_length=120)
    intent: PromptIntent
    cohort: PromptCohort


class PortfolioEnvelope(BaseModel):
    """The schema advertised to the model.

    Sent as the JSON schema so `intent` and `cohort` arrive constrained, but the
    reply is parsed per-prompt rather than through this model -- see
    `_parse_prompts`.
    """

    prompts: list[GeneratedPrompt] = Field(default_factory=list)
    # The model's own account of why it produced fewer prompts than the ceiling.
    # Surfaced to the user rather than silently padded over.
    shortfall_reason: str = ""


def _parse_prompts(payload: dict) -> tuple[list[dict], str]:
    """Validate each prompt on its own, dropping only the rows that fail.

    Whole-envelope validation was catastrophically brittle: the model
    occasionally puts a cohort value such as 'brand_diagnostic' in `intent`, and
    that single bad row discarded thirteen good prompts alongside it. One
    confused field should cost one prompt, not the portfolio.
    """
    rows = payload.get("prompts")
    if not isinstance(rows, list):
        return [], ""
    prompts: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            item = GeneratedPrompt.model_validate(row)
        except ValidationError:
            continue
        prompts.append(
            {
                "text": " ".join(item.text.split()),
                "theme": item.theme.strip(),
                "intent": item.intent,
                "cohort": item.cohort,
            }
        )
    return prompts, str(payload.get("shortfall_reason") or "").strip()


async def generate_portfolio(
    *,
    brand_name: str,
    primary_market: str,
    profile: dict,
    competitors: list[str],
) -> tuple[list[dict], str]:
    """Ask the model for the portfolio. Returns (prompts, shortfall_reason).

    Never raises: an unavailable or malformed model response returns an empty
    list so the caller falls back to deterministic templates.
    """
    request = _portfolio_request(
        brand_name=brand_name,
        primary_market=primary_market,
        profile=profile,
        competitors=competitors,
    )
    best: list[dict] = []
    # ONE deadline for every attempt, not one per attempt. The caller holds a
    # FOR UPDATE row lock across this call, so the retry budget is what bounds
    # the lock -- a per-attempt timeout multiplied by `synthesis_max_attempts`
    # and quietly doubled the hold that the configured ceiling promises.
    try:
        async with asyncio.timeout(
            brand_discovery_settings.portfolio_generation_timeout_seconds
        ):
            for _attempt in range(brand_discovery_settings.synthesis_max_attempts):
                try:
                    payload = await _model_portfolio(request)
                except (
                    AgentNotConfiguredError,
                    ProviderError,
                    ValidationError,
                    # Covers `json.JSONDecodeError`, which subclasses it.
                    ValueError,
                ):
                    return best, ""
                prompts, shortfall = _parse_prompts(payload)
                # Retry a thin reply, not just an empty one. A reply of three
                # prompts cannot clear the portfolio floor, so accepting it
                # silently hands the portfolio to the templates -- which the
                # eval sees as template_tell snapping back to 1.0 for that
                # brand. An explicit shortfall_reason is the model saying it
                # knows little, and is taken at its word.
                if len(prompts) >= PORTFOLIO_PROMPT_MIN or (prompts and shortfall):
                    return prompts, shortfall
                best = max((best, prompts), key=len) if prompts else best
    except TimeoutError:
        # Whatever the earlier attempts produced beats nothing; the caller
        # falls back to the deterministic templates when it is empty.
        return best, ""
    return best, ""


_TEXT_FIELDS = {
    "category": "",
    "target_audience": "",
    "positioning": "",
    "business_model": "",
    "market_scope": "national",
    "knowledge_strength": "none",
}
_LIST_FIELDS = (
    "category_aliases",
    "category_terms",
    "products_services",
    "jobs_to_be_done",
    "secondary_business_models",
    "service_areas",
    "buyer_roles",
)


def _portfolio_request(
    *, brand_name: str, primary_market: str, profile: dict, competitors: list[str]
) -> str:
    register = str(profile.get("buyer_register") or "research_comparative")
    context: dict[str, object] = {
        key: str(profile.get(key) or default) for key, default in _TEXT_FIELDS.items()
    }
    context.update({key: list(profile.get(key) or []) for key in _LIST_FIELDS})
    return json.dumps(
        {
            **context,
            "brand_name": brand_name,
            "primary_market": primary_market,
            "market_names": list(
                MARKET_CONTEXT_TERMS.get(primary_market, (primary_market,))
            ),
            "buyer_type": str(profile.get("business_type") or "both"),
            "buyer_register": register,
            "competitors": competitors,
            "allowed_intents": list(PROMPT_INTENTS),
            "max_market_visibility": MARKET_VISIBILITY_PROMPT_MAX,
            "max_brand_relevant": BRAND_RELEVANT_PROMPT_MAX,
            "max_branded": BRANDED_PROMPT_MAX,
            "register_examples": _REGISTER_EXEMPLARS.get(register, []),
            "note": (
                "register_examples show the voice to imitate; they are from "
                "unrelated businesses, so never reuse their subject matter."
            ),
        },
        ensure_ascii=False,
    )


async def _model_portfolio(request: str) -> dict:
    """Return the decoded reply. The schema still constrains what we ask for."""
    client = create_model_gateway()
    raw = await client.complete_structured_json(
        system=ONBOARDING_PORTFOLIO_SYSTEM_PROMPT,
        user=request,
        schema_name="onboarding_prompt_portfolio",
        schema=PortfolioEnvelope.model_json_schema(),
    )
    payload = json.loads(raw)
    return payload if isinstance(payload, dict) else {}


def portfolio_shortfall_warning(accepted: int, reason: str) -> str:
    """A user-facing note when the portfolio is deliberately short.

    Reported rather than hidden: `unavailable` is not `zero`, and a brand the
    model cannot ground is a finding the user should see.
    """
    if accepted >= MARKET_VISIBILITY_PROMPT_MAX + BRAND_RELEVANT_PROMPT_MAX:
        return ""
    return reason or "limited_brand_knowledge"
