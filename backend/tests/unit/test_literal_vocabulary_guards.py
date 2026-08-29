"""The import-time guards that lock a ``Literal`` alias to its config vocabulary.

These ran as bare ``assert`` statements, which ``python -O`` strips: the one
check standing between an API literal and its persisted catalog would have
vanished in exactly the optimized build where a mismatch is hardest to
diagnose. ``lock_literal`` raises instead, and these tests hold that line.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path
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


def test_the_guard_still_fires_under_python_O() -> None:
    """``python -O`` removes ``assert``; it does not remove ``raise``.

    This is the whole point of the change, so it is checked in a real
    optimized interpreter rather than asserted in this one -- the suite runs
    unoptimized, where the old ``assert`` form would have passed too.
    """
    program = textwrap.dedent(
        """
        from typing import Literal

        from app.core.literals import LiteralVocabularyError, lock_literal

        assert False, "this suite is not running under -O"  # noqa: S101, B011

        try:
            lock_literal(Literal["red"], {"red", "green"}, name="Colour")
        except LiteralVocabularyError:
            print("raised")
        """
    )

    result = subprocess.run(  # noqa: S603 - fixed argv, this interpreter
        [sys.executable, "-O", "-c", program],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
    )

    # The bare `assert False` above proves -O really is in effect: unoptimized,
    # it would abort the program before reaching the guard.
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "raised"


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
