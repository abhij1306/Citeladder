"""Import-time guards that lock a ``Literal`` alias to its config vocabulary.

Several API schemas declare their values inline as a ``Literal[...]`` (the type
checker cannot read a ``Literal`` built from a constant) while the persisted
catalog for the same field lives in ``app.core.config``. The two are kept in
lock-step by a check that runs when the schema module is imported.

That check used to be a bare ``assert``. ``python -O`` strips ``assert``
statements, so the one guard standing between an API literal and its persisted
catalog would silently disappear in exactly the optimized build where a
mismatch is hardest to diagnose. These raise instead.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, get_args


class LiteralVocabularyError(RuntimeError):
    """A ``Literal`` alias and its configured vocabulary have drifted apart."""


def lock_literal(alias: Any, vocabulary: Iterable[str], *, name: str) -> None:
    """Raise unless ``alias``'s members are exactly ``vocabulary``.

    ``name`` is the alias's source-level name; it is passed explicitly because a
    ``Literal`` alias carries no ``__name__`` to report in the failure.
    """
    declared = set(get_args(alias))
    expected = set(vocabulary)
    if declared == expected:
        return
    missing = sorted(expected - declared)
    unexpected = sorted(declared - expected)
    raise LiteralVocabularyError(
        f"{name} has drifted from its configured vocabulary: "
        f"missing {missing}, unexpected {unexpected}"
    )
