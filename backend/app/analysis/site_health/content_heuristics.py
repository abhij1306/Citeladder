"""Content-derived page-kind signals.

This leaf owns only the bounded FAQ/product/article heuristic.  URL and
structured-data signals remain in the classifier coordinator, so precedence is
still resolved in one place.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.config import site_health_authorship as _authorship_config
from app.core.config import site_health_taxonomy as _config

_BYLINE_RE = re.compile(_authorship_config.BYLINE_PATTERN)
_DATE_RE = re.compile(_authorship_config.DATE_PATTERN, re.IGNORECASE)


def visible_byline(text: str) -> str:
    """The first visible "By <Name>" byline in ``text``, or "".

    Shared with the extractor's author fact so the classifier's notion of a
    byline and the analyzer's notion of one cannot drift apart.
    """
    match = _BYLINE_RE.search(str(text or ""))
    return match.group(0).strip() if match else ""


def visible_date(text: str) -> str:
    """The first visible publication-shaped date in ``text``, or ""."""
    match = _DATE_RE.search(str(text or ""))
    return match.group(0).strip() if match else ""


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str_sequence(value: Any) -> list[str]:
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _is_question_heading(text: str) -> bool:
    normalized = " ".join(str(text or "").split()).lower()
    if not normalized:
        return False
    if normalized.endswith("?"):
        return True
    first_word = normalized.split(" ", 1)[0].strip("¿?¡!.,:;\"'")
    return first_word in _config.PAGE_KIND_QUESTION_WORDS


def _faq_signal(facts: dict[str, Any]) -> dict[str, Any] | None:
    headings = _mapping(facts.get("headings"))
    heading_texts = _str_sequence(headings.get("h2_texts"))
    heading_texts += _str_sequence(headings.get("h3_texts"))
    if len(heading_texts) < _config.PAGE_KIND_FAQ_MIN_HEADINGS:
        return None
    question_count = sum(1 for text in heading_texts if _is_question_heading(text))
    if question_count / len(heading_texts) < _config.PAGE_KIND_FAQ_QUESTION_RATIO:
        return None
    return {
        "signal": _config.PAGE_KIND_SIGNAL_CONTENT_HEURISTIC,
        "page_kind": _config.PAGE_KIND_FAQ,
        "detail": f"question_headings:{question_count}/{len(heading_texts)}",
    }


def _article_signal(facts: dict[str, Any]) -> dict[str, Any] | None:
    authorship = _mapping(facts.get("authorship"))
    if not (authorship.get("visible_byline") and authorship.get("visible_date")):
        return None
    return {
        "signal": _config.PAGE_KIND_SIGNAL_CONTENT_HEURISTIC,
        "page_kind": _config.PAGE_KIND_ARTICLE,
        "detail": "byline_and_date",
    }


def content_heuristic(facts: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first FAQ or article content signal.

    The product heuristic that lived here read the WHOLE body for a price plus
    a cart marker. On a real store that fired on a returns-policy page, because
    its "You May Also Like" carousel carries both. Product evidence now comes
    from ``fact_entity``, scoped to the page's own region and to structures
    outside every repeated card list, so this leaf keeps only the two signals
    that were never region-sensitive: question headings and a byline + date.
    """
    return _faq_signal(facts) or _article_signal(facts)
