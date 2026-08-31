"""Deterministic visible authorship signal policy."""

from __future__ import annotations

from typing import Final

BYLINE_PATTERN: Final = r"\b[Bb]y\s+[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){1,2}\b"
VISIBLE_AUTHOR_NAME_PATTERN: Final = r"^[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+){0,3}$"

# ISO, month-first, and day-first publication-shaped dates.
DATE_PATTERN: Final = (
    r"(?:\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?,?\s+\d{4}\b)"
)

VISIBLE_AUTHOR_NODE_TOKENS: Final[frozenset[str]] = frozenset({"author", "byline"})
VISIBLE_AUTHOR_HEADING_EXCLUSIONS: Final[frozenset[str]] = frozenset(
    {"about us", "contact us", "our team", "meet the team"}
)
VISIBLE_DATE_NODE_TOKENS: Final[frozenset[str]] = frozenset(
    {"byline", "date", "datemodified", "datepublished", "published", "updated"}
)
