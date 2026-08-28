"""Shape guards for persisted crawl facts.

``normalized_facts`` normally comes from our own extractor, but it is also read
back from JSON written by an OLDER extractor version. A field that is not the
shape we expect must contribute nothing rather than raise: partial facts simply
match fewer signals. Shared by the projector and the shelf-membership resolver
so both read stored evidence by the same rule.
"""

from __future__ import annotations

from typing import Any


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    """A nested fact as a list, or ``[]`` when it is the wrong shape.

    A bare string is deliberately NOT treated as a one-item sequence: iterating
    it would yield characters and fabricate values from nothing.
    """
    return value if isinstance(value, list) else []
