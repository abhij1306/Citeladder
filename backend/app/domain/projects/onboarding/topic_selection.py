"""Pass B: select canonical topics from the site's published offering list.

Its own model call rather than another paragraph in the research prompt. That
prompt already resolves the category, classifies four facets and qualifies
competitors in roughly two thousand words, with topics getting one paragraph at
the end -- and topics were what it did worst. Selection from a supplied list is
the easiest task to give a small model; open-ended invention under a hard count
cap is the hardest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.visibility_prompts import (
    TOPIC_SELECTION_MODEL_PRIOR_CLAUSE,
    TOPIC_SELECTION_SYSTEM_PROMPT,
    VISIBILITY_TOPIC_MAX,
)
from app.domain.projects.discovery_schemas import DiscoveryTopic
from app.domain.projects.offering_harvest import OfferingHarvest
from app.domain.projects.onboarding.topic_admission import admit_topics

HARVEST_READY = "ready"
HARVEST_EMPTY = "empty"


class SelectedTopic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1024)
    source_refs: list[str] = Field(default_factory=list)


class TopicSelectionEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["ready", "insufficient_evidence"] = "ready"
    topics: list[SelectedTopic] = Field(
        default_factory=list, max_length=VISIBILITY_TOPIC_MAX
    )


@dataclass(frozen=True, slots=True)
class TopicSelectionResult:
    topics: list[DiscoveryTopic] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    warnings: tuple[str, ...] = ()


def build_request(
    *,
    brand_name: str,
    brand_aliases: list[str],
    business_category: str,
    business_model: str,
    market: str,
    harvest: OfferingHarvest,
    page_evidence: list[dict[str, str]],
) -> str:
    return json.dumps(
        {
            "brand_name": brand_name,
            "brand_aliases": brand_aliases,
            "business_category": business_category,
            "business_model": business_model,
            "market": market,
            "harvest_status": HARVEST_READY if harvest.is_ready else HARVEST_EMPTY,
            "offering_candidates": harvest.serialize() if harvest.is_ready else [],
            "page_evidence": page_evidence,
        },
        ensure_ascii=False,
    )


async def select_topics(
    *,
    brand_name: str,
    brand_aliases: list[str],
    competitors: list[str],
    business_category: str,
    business_aliases: list[str],
    sector: str,
    business_model: str,
    market: str,
    harvest: OfferingHarvest,
    page_evidence: list[dict[str, str]],
    allow_model_prior: bool = False,
) -> TopicSelectionResult:
    """Select and admit topics, or report why none could be.

    Never raises. An unavailable model, a malformed envelope, or evidence too
    thin to support the floor all resolve to an empty topic list with a warning,
    and onboarding reports that state.

    It never falls back to industry defaults or profile prose -- inventing a
    portfolio for a business we could not read is the failure this contract
    exists to prevent. ``allow_model_prior`` opens ONE narrow exception, for a
    brand the profile pass positively recognised (see ``ContextProfile.is_thin``
    for the same predicate): naming what the model knows adidas sells is not
    the failure mode above, which is fabricating a business from a name alone.
    Without it the pipeline contradicted itself -- confidently naming adidas's
    category and five competitors from prior knowledge, then reporting zero
    topics for the same brand in the same run. Prior-derived topics are stamped
    with ``MODEL_PRIOR_SOURCE_REF`` so they stay distinguishable.
    """
    try:
        client = create_model_gateway()
    except AgentNotConfiguredError:
        return TopicSelectionResult(warnings=("topic_selection_unavailable",))

    request = build_request(
        brand_name=brand_name,
        brand_aliases=brand_aliases,
        business_category=business_category,
        business_model=business_model,
        market=market,
        harvest=harvest,
        page_evidence=page_evidence,
    )
    try:
        raw = await client.complete_structured_json(
            system=(
                TOPIC_SELECTION_SYSTEM_PROMPT
                + (TOPIC_SELECTION_MODEL_PRIOR_CLAUSE if allow_model_prior else "")
            ),
            user=request,
            schema_name="visibility_topic_selection",
            schema=TopicSelectionEnvelope.model_json_schema(),
        )
        envelope = TopicSelectionEnvelope.model_validate_json(raw)
    except (
        AgentNotConfiguredError,
        ProviderError,
        TimeoutError,
        ValidationError,
        ValueError,
    ):
        return TopicSelectionResult(
            warnings=("topic_selection_unavailable",),
            provider=client.base_url_host,
            model=client.model,
        )

    # A recognised brand may still return topics alongside a non-ready status
    # (the site was unreadable, but it knows the brand); admit what came back
    # and let the floor in ``admit_topics`` decide. For an unrecognised brand a
    # non-ready status remains terminal.
    if envelope.status != "ready" and not allow_model_prior:
        return TopicSelectionResult(
            warnings=("insufficient_offering_evidence",),
            provider=client.base_url_host,
            model=client.model,
        )

    known_refs = {node.ref for node in harvest.nodes} | {
        str(item.get("evidence_ref") or "") for item in page_evidence
    }
    topics = admit_topics(
        [item.model_dump() for item in envelope.topics],
        known_refs=known_refs,
        forbidden_terms=[brand_name, *brand_aliases, *competitors],
        business_terms=[business_category, *business_aliases, sector],
        allow_model_prior=allow_model_prior,
    )
    return TopicSelectionResult(
        topics=topics,
        provider=client.base_url_host,
        model=client.model,
        warnings=() if topics else ("insufficient_offering_evidence",),
    )
