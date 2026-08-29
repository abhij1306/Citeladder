"""Strict read DTOs for the persisted observed-architecture projection."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArchitecturePageKindResponse(_Model):
    page_kind: str
    page_count: int
    median_depth: float | None
    indexable_count: int
    duplicate_metadata_count: int
    orphan_count: int | None


class ArchitectureNodeResponse(_Model):
    site_url_id: uuid.UUID
    url: str
    title: str
    page_kind: str
    parent_site_url_id: uuid.UUID | None
    parent_source: Literal["breadcrumb", "explicit_structure", "url_parent", "unknown"]
    depth_from_home: int | None


class ArchitectureInternalLinkingResponse(_Model):
    internal_link_count: int
    pages_with_incoming_count: int
    pages_with_incoming_percentage: float | None
    orphan_page_count: int | None


class ArchitectureDepthBucketResponse(_Model):
    key: Literal["depth_0", "depth_1", "depth_2", "depth_3_plus"]
    page_count: int
    percentage: float | None


class ArchitectureStructureDepthResponse(_Model):
    measured_page_count: int
    unmeasured_page_count: int
    buckets: list[ArchitectureDepthBucketResponse]


class ArchitectureResponse(_Model):
    state: Literal["available", "unavailable"]
    crawl_id: uuid.UUID | None = None
    coverage_state: Literal["complete", "partial", "unknown"]
    page_count: int
    page_kinds: list[ArchitecturePageKindResponse]
    nodes: list[ArchitectureNodeResponse]
    internal_linking: ArchitectureInternalLinkingResponse
    structure_depth: ArchitectureStructureDepthResponse
    architecture_formula_version: str
    limitations: list[str]
