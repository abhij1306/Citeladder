"""Pass C must not depend on the model echoing a UUID back."""

from __future__ import annotations

import uuid

import pytest

from app.domain.projects.discovery_schemas import DiscoveryTopic
from app.domain.projects.onboarding import portfolio_generation as pg
from tests.fixtures.archetype_text import response_for


class _EchoesShortSlots:
    """The model echoes only short slot IDs; code owns every UUID and label."""

    base_url_host = "fake"
    model = "fake-small"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_structured_json(self, *, system, user, schema_name, schema):
        self.calls += 1
        return response_for(user)


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
