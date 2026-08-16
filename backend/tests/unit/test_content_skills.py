"""Reusable content-skill catalog: rendering, integrity, and projection."""

from __future__ import annotations

import pytest

from app.core.config.content import (
    CONTENT_DEFAULT_SKILL,
    CONTENT_SKILL_CATALOG_VERSION,
    CONTENT_SKILL_DIRECTIVES,
    CONTENT_SKILL_IDS,
    CONTENT_SKILL_REGISTRY,
    CONTENT_SKILLS,
    skill_directive,
)
from app.core.config.content_skills import CONTENT_CHANNELS
from app.domain.content.schemas import ContentGenerationCreate, skill_catalog

# Ids persisted on existing ``ContentGeneration`` rows. Removing or renaming
# one silently orphans that history, so the catalog must keep carrying them.
_LEGACY_SKILL_IDS = ("article", "blog", "youtube", "reddit")


def test_legacy_skill_ids_survive_catalog_expansion() -> None:
    for skill_id in _LEGACY_SKILL_IDS:
        assert skill_id in CONTENT_SKILLS


def test_default_skill_is_the_website_content_page() -> None:
    # The product's one output type is `website_page`, so an unqualified
    # request means a page — and it is the default selection in the picker.
    assert CONTENT_DEFAULT_SKILL == "content_page"
    assert CONTENT_DEFAULT_SKILL in CONTENT_SKILL_REGISTRY


def test_every_skill_declares_a_known_channel() -> None:
    for definition in CONTENT_SKILL_REGISTRY.values():
        assert definition.channel in CONTENT_CHANNELS


def test_every_skill_carries_the_shared_evidence_rules() -> None:
    # A format that omitted these would be free to invent pricing or stats on
    # a page published under the customer's own domain.
    for skill_id in CONTENT_SKILL_IDS:
        rendered = skill_directive(skill_id)
        assert "Never invent facts" in rendered
        assert "not available rather than filling the gap" in rendered


def test_content_page_directive_specifies_a_publishable_page_spec() -> None:
    rendered = skill_directive("content_page")
    for required in (
        "## Meta",
        "Meta title",
        "Canonical route",
        "Primary CTA",
        "## Sources",
    ):
        assert required in rendered


def test_platform_skills_state_their_posting_constraints() -> None:
    # The point of a platform skill: the model is told where the content will
    # be posted and what that surface actually renders.
    assert "under 280 characters" in skill_directive("x")
    assert "renders no Markdown" in skill_directive("linkedin")
    assert "subreddit" in skill_directive("reddit")
    assert "Instagram renders no Markdown" in skill_directive("instagram")


def test_directive_carries_format_structure_tone_and_length() -> None:
    # The point of a skill is that the model is told the craft constraints,
    # not just the topic — a one-line directive is what made it clueless.
    rendered = skill_directive("linkedin")
    assert "Follow this structure:" in rendered
    assert "Tone:" in rendered
    assert "Length:" in rendered
    assert "1. An opening line" in rendered


def test_directive_rendering_is_deterministic() -> None:
    # The digest over the built messages is provenance; a directive that
    # rendered differently per call would make it meaningless.
    assert skill_directive("faq") == skill_directive("faq")


@pytest.mark.parametrize("unknown", ["", "does-not-exist", None])
def test_unknown_skill_falls_back_to_the_default_directive(unknown: str | None) -> None:
    assert skill_directive(unknown) == skill_directive(CONTENT_DEFAULT_SKILL)


def test_flat_directive_view_matches_the_registry() -> None:
    assert set(CONTENT_SKILL_DIRECTIVES) == set(CONTENT_SKILL_REGISTRY)
    for skill_id, directive in CONTENT_SKILL_DIRECTIVES.items():
        assert directive == CONTENT_SKILL_REGISTRY[skill_id].render_directive()


def test_catalog_projection_preserves_registry_order() -> None:
    catalog = skill_catalog()
    assert [skill.id for skill in catalog.skills] == list(CONTENT_SKILL_IDS)
    # The default is offered first, so the picker's initial selection is also
    # the first thing the user reads.
    assert catalog.skills[0].id == CONTENT_DEFAULT_SKILL
    assert catalog.default_skill_id == CONTENT_DEFAULT_SKILL


def test_catalog_never_leaks_directive_text() -> None:
    # The picker explains a skill with `description`/`structure`; the raw
    # directive is prompt-engineering and stays server-side.
    for skill in skill_catalog().skills:
        assert not hasattr(skill, "directive")


def test_create_rejects_a_skill_outside_the_catalog() -> None:
    with pytest.raises(ValueError):
        ContentGenerationCreate(
            project_id="00000000-0000-0000-0000-000000000001",
            prompt="Write something",
            skill_id="not-a-skill",
        )


def test_create_accepts_a_newly_added_skill() -> None:
    payload = ContentGenerationCreate(
        project_id="00000000-0000-0000-0000-000000000001",
        prompt="Write something",
        skill_id="linkedin",
    )
    assert payload.skill_id == "linkedin"


def test_skill_version_records_the_catalog_not_the_generator() -> None:
    # `skill_version` and `generator_version` are separate columns for a
    # reason: a reworded directive changes what was asked for even when the
    # generator is untouched, so stamping both with the generator version
    # would lose that half of the provenance.
    from app.core.config.content import CONTENT_GENERATOR_VERSION

    assert CONTENT_SKILL_CATALOG_VERSION != CONTENT_GENERATOR_VERSION
