"""Pass C must not depend on the model echoing a UUID back."""

from __future__ import annotations

import json
import uuid

import pytest

from app.domain.projects.discovery_schemas import DiscoveryTopic
from app.domain.projects.onboarding import portfolio_generation as pg


class _EchoesShortSlots:
    """The model echoes only short slot IDs; code owns every UUID and label."""

    base_url_host = "fake"
    model = "fake-small"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured_json(self, *, system, user, schema_name, schema):
        self.calls += 1
        payload = json.loads(user)
        brand = payload["brand_name"]
        rows = []
        for slot in payload["buyer_query_slots"]:
            topic = slot["topic"]
            competitors = slot.get("competitors") or []
            pattern = slot["pattern"]
            if pattern == "brand_comparison":
                text = f"{brand} vs {competitors[0]}"
            else:
                text = {
                    "what_is": f"What is {topic}?",
                    "best_for": f"Best {topic} for a winter commute",
                    "how_to": f"How to choose {topic} for winter",
                    "pricing": f"{topic} pricing",
                    "brand_overview": f"What is {brand}?",
                    "brand_fit": f"Is {brand} good for {topic}?",
                }[pattern]
            rows.append({"slot_id": slot["slot_id"], "text": text})
        return json.dumps({"prompts": rows})


def _topics(*names: str) -> list[DiscoveryTopic]:
    return [
        DiscoveryTopic(
            topic_id=uuid.uuid4(), name=name, description=name, source_refs=["s1"]
        )
        for name in names
    ]


@pytest.mark.asyncio
async def test_a_model_that_never_returns_a_uuid_still_yields_a_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every core prompt was rejected as `topic_id`, leaving two branded ones.

    Best&Less reported `core_prompts_empty` with `prompt_rejected:topic_id`
    for ten topics, and the run failed outright.
    """
    gateway = _EchoesShortSlots()
    monkeypatch.setattr(pg, "create_model_gateway", lambda: gateway)

    result = await pg.generate_portfolio(
        brand_name="Best&Less",
        brand_terms=["Best&Less"],
        primary_market="AU",
        profile={"business_model": "retail", "buyer_register": "terse_transactional"},
        competitors=["Kmart"],
        competitor_terms=["Kmart"],
        topics=_topics("school uniforms", "baby clothing", "winter coats"),
    )

    assert "prompt_rejected:topic_id" not in result.errors
    assert "core_prompts_empty" not in result.errors
    cohorts = {prompt["cohort"] for prompt in result.prompts}
    # The organic cohort is the portfolio; a branded-only result is the bug.
    assert "core" in cohorts
    assert cohorts >= {"core", "brand_diagnostic", "comparison"}
    unbranded = [
        prompt for prompt in result.prompts if "best&less" not in prompt["text"].lower()
    ]
    assert len(unbranded) >= 2
