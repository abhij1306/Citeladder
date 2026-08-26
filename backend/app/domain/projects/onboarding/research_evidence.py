"""Bounded evidence contracts shared by onboarding research phases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


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
    remaining: int

    def take(self, requested: int) -> int:
        admitted = min(max(requested, 0), self.remaining)
        self.remaining -= admitted
        return admitted


def evidence_payload(items: list[ResearchEvidenceItem]) -> list[dict]:
    return [item.model_dump(mode="json") for item in items]
