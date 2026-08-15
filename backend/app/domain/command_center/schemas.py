from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.opportunities.schemas import OpportunityItem


class CommandCenterProject(BaseModel):
    id: uuid.UUID
    name: str
    brand_name: str
    website_url: str


class CommandCenterCompetitor(BaseModel):
    id: uuid.UUID
    name: str
    domains: list[str] = Field(default_factory=list)


class CommandCenterFacts(BaseModel):
    industry: str = ""
    description: str = ""
    positioning: str = ""
    products_services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    competitors: list[CommandCenterCompetitor] = Field(default_factory=list)


class EvidenceState(BaseModel):
    state: Literal["observed", "partial", "not_run", "unavailable"]
    observed_at: datetime | None = None
    freshness: Literal["current", "unknown"]
    coverage: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class CommandCenterLoop(BaseModel):
    connected: EvidenceState
    analyzed: EvidenceState
    acted: EvidenceState
    tracked: EvidenceState


class CommandCenterNextAction(BaseModel):
    kind: Literal[
        "opportunity",
        "connect",
        "crawl",
        "configure_prompts",
        "audit",
        "monitor",
    ]
    title: str
    href: str
    opportunity_id: uuid.UUID | None = None


class CommandCenterMeasurement(BaseModel):
    audit_id: uuid.UUID
    completed_at: datetime
    measurement_mode: str
    benchmark_mode: str
    logical_engines: list[str] = Field(default_factory=list)
    comparable_audit_id: uuid.UUID | None = None


class CommandCenterMetric(BaseModel):
    value: float | int | None = None
    delta: float | int | None = None


class CommandCenterTrackSummary(BaseModel):
    citation_share: CommandCenterMetric
    engine_coverage: int = 0
    observed_at: datetime | None = None
    limitations: list[str] = Field(default_factory=list)


class CommandCenterState(BaseModel):
    visibility: CommandCenterMetric
    share_of_voice: CommandCenterMetric
    brand_rank: CommandCenterMetric


class CommandCenterMovement(BaseModel):
    label: str
    direction: str
    current: float | None = None
    previous: float | None = None
    delta: float | None = None


class ResolvedActionSummary(BaseModel):
    since_audit_id: uuid.UUID | None = None
    count: int = 0
    titles: list[str] = Field(default_factory=list)


class CommandCenterResponse(BaseModel):
    project: CommandCenterProject
    facts: CommandCenterFacts
    loop: CommandCenterLoop
    next_action: CommandCenterNextAction
    track: CommandCenterTrackSummary
    measurement: CommandCenterMeasurement | None = None
    state: CommandCenterState
    movements: list[CommandCenterMovement] = Field(default_factory=list)
    actions: list[OpportunityItem] = Field(default_factory=list)
    action_order_version: int = 0
    resolved_actions: ResolvedActionSummary
    report_available: bool = True
    stale: bool = False
