"""The import-time guards that lock a ``Literal`` alias to its config vocabulary.

These ran as bare ``assert`` statements, which ``python -O`` strips: the one
check standing between an API literal and its persisted catalog would have
vanished in exactly the optimized build where a mismatch is hardest to
diagnose. ``lock_literal`` raises instead, and these tests hold that line.
"""

from __future__ import annotations

from typing import Literal

import pytest

from app.core.config.brand_discovery import BUSINESS_MODELS, PRICE_TIERS
from app.core.config.prompts import PROMPT_COHORTS, PROMPT_STATUSES
from app.core.literals import LiteralVocabularyError, lock_literal
from app.domain.projects.discovery_schemas import BusinessModel, PriceTier
from app.domain.prompts.schemas import PromptCohort, PromptStatus


def test_matching_alias_and_vocabulary_pass() -> None:
    Colour = Literal["red", "green"]

    lock_literal(Colour, {"red", "green"}, name="Colour")


def test_a_value_missing_from_the_alias_is_named() -> None:
    Colour = Literal["red"]

    with pytest.raises(LiteralVocabularyError) as excinfo:
        lock_literal(Colour, {"red", "green"}, name="Colour")

    message = str(excinfo.value)
    assert "Colour" in message
    assert "missing ['green']" in message


def test_a_value_absent_from_the_vocabulary_is_named() -> None:
    Colour = Literal["red", "blue"]

    with pytest.raises(LiteralVocabularyError) as excinfo:
        lock_literal(Colour, {"red"}, name="Colour")

    assert "unexpected ['blue']" in str(excinfo.value)


def test_the_guard_survives_assertions_being_stripped() -> None:
    """``python -O`` removes ``assert``; it does not remove ``raise``.

    Guarding this explicitly because the whole point of the change was that the
    previous form was a no-op under optimization.
    """
    Colour = Literal["red"]

    with pytest.raises(LiteralVocabularyError):
        lock_literal(Colour, {"red", "green"}, name="Colour")


@pytest.mark.parametrize(
    ("alias", "vocabulary", "name"),
    [
        (PriceTier, PRICE_TIERS, "PriceTier"),
        (BusinessModel, BUSINESS_MODELS, "BusinessModel"),
        (PromptStatus, PROMPT_STATUSES, "PromptStatus"),
        (PromptCohort, PROMPT_COHORTS, "PromptCohort"),
    ],
)
def test_shipped_aliases_match_their_catalogs(
    alias: object, vocabulary: object, name: str
) -> None:
    """The guards the schema modules run at import time, asserted here too.

    Importing the schema module already raises on drift; this makes the failure
    point at the specific alias instead of at a collection error.
    """
    lock_literal(alias, vocabulary, name=name)  # type: ignore[arg-type]
