"""Bounded evidence contracts shared by onboarding research phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from app.connectors.web_evidence.url_policy import UrlPolicyError, canonicalize


class ResearchEvidenceItem(BaseModel):
    evidence_ref: str
    source_url: str
    title: str = ""
    text: str = ""
    source_kind: Literal["first_party", "external_search", "external_fetch"]
    provider: str = ""
    query_ref: str = ""
    published_at: str = ""
    acquired_at: str = ""
    live: bool | None = None
    supports: list[Literal["profile", "competitors", "topics"]] = Field(
        default_factory=list
    )


class CompetitiveSignature(BaseModel):
    category: str = ""
    buyer: str = ""
    core_job: str = ""
    delivery_model: str = ""
    market_context: str = ""
    qualifiers: list[str] = Field(default_factory=list, max_length=5)
    adjacent_categories: list[str] = Field(default_factory=list, max_length=3)
    search_terms: list[str] = Field(default_factory=list, max_length=8)


@dataclass(slots=True)
class ResearchCallBudget:
    limit: int
    remaining: int = field(init=False)

    def __post_init__(self) -> None:
        self.limit = max(self.limit, 0)
        self.remaining = self.limit

    @property
    def used(self) -> int:
        return self.limit - self.remaining

    def take(self, requested: int) -> int:
        admitted = min(max(requested, 0), self.remaining)
        self.remaining -= admitted
        return admitted


def bounded_evidence(
    items: list[ResearchEvidenceItem] | tuple[ResearchEvidenceItem, ...],
    *,
    max_chars: int,
) -> tuple[ResearchEvidenceItem, ...]:
    """Share one text budget across distinct sources in caller priority order."""
    distinct: list[ResearchEvidenceItem] = []
    seen_urls: set[str] = set()
    for item in items:
        try:
            source_identity = canonicalize(item.source_url)
        except UrlPolicyError:
            source_identity = item.source_url.strip().casefold()
        if source_identity in seen_urls:
            continue
        seen_urls.add(source_identity)
        distinct.append(item)

    remaining = max_chars
    bounded: list[ResearchEvidenceItem] = []
    for index, item in enumerate(distinct):
        if remaining <= 0:
            break
        sources_left = len(distinct) - index
        text = item.text[: max(remaining // sources_left, 1)]
        remaining -= len(text)
        bounded.append(item.model_copy(update={"text": text}))
    return tuple(bounded)


def evidence_payload(items: list[ResearchEvidenceItem]) -> list[dict]:
    return [item.model_dump(mode="json") for item in items]
