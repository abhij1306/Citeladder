"""Observed-architecture API DTOs.

Split out of ``api_schemas`` for the same reason as the change DTOs: the
architecture read/correction surface is its own contract, and keeping it here
lets the shapes carry the conservatism rules they encode without burying them
in the general Site Health response module.

Every response model mirrors the checked-in strict frontend zod schema
(``frontend/lib/api/schemas/site-health/architecture.ts``) field-for-field.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


ArchitectureState = Literal["available", "unavailable"]
CoverageState = Literal["complete", "partial", "unknown"]
Archetype = Literal["commerce", "software", "services", "other"]


class CommonStructureRow(_Model):
    key: str
    label: str


class ArchetypeAssessmentResponse(_Model):
    """The archetype, where it came from, and what was/was not observed.

    ``source`` is ``onboarding_profile``, ``abstained``, or ``user_override``.
    This layer EXPECTS, it does not classify: it can never produce a defect and
    never affects a score. ``not_observed`` is empty unless the crawl proved
    complete coverage — a partial crawl cannot prove absence.
    """

    archetype: Archetype
    source: Literal["onboarding_profile", "abstained", "user_override"]
    reason: str
    business_model: str
    market_scope: str
    observed: list[CommonStructureRow]
    not_observed: list[CommonStructureRow]


class ArchitectureFamilyResponse(_Model):
    family: str
    url_count: int
    page_kind_distribution: dict[str, int]
    median_depth: float | None
    indexable_count: int
    metadata_duplication_rate: float
    # None unless coverage is complete — orphan status is an absence claim.
    orphan_count: int | None


class ArchitectureNodeResponse(_Model):
    site_url_id: uuid.UUID
    url: str
    title: str
    page_kind: str
    family: str
    # None = no evidence resolved a parent. The node renders under its family
    # rather than being attached somewhere plausible.
    parent_site_url_id: uuid.UUID | None
    parent_source: Literal["breadcrumb", "explicit_structure", "url_family", "unknown"]
    depth_from_home: int | None


class ArchitectureResponse(_Model):
    state: ArchitectureState
    crawl_id: uuid.UUID | None = None
    coverage_state: CoverageState
    page_count: int
    page_kind_counts: dict[str, int]
    archetype: ArchetypeAssessmentResponse
    families: list[ArchitectureFamilyResponse]
    nodes: list[ArchitectureNodeResponse]
    architecture_formula_version: str
    archetype_policy_version: str
    limitations: list[str]


class SetArchetypeRequest(_Model):
    """The entire architecture correction surface: one field, or null to clear."""

    archetype: Archetype | None = None


class ArchetypeOverrideResponse(_Model):
    project_id: uuid.UUID
    archetype_override: Archetype | None
