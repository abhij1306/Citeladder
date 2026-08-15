"""Frozen grounding envelope over confirmed profile facts and crawl evidence."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_profile import (
    BRAND_PROFILE_REVIEW_CONFIRMED,
    BRAND_PROFILE_REVIEW_EDITED,
)
from app.core.config.content import (
    CONTENT_GROUNDING_ENVELOPE_VERSION,
    CONTENT_GROUNDING_MAX_FACTS,
    CONTENT_GROUNDING_MAX_SOURCE_REFS,
    GROUNDING_STATUS_CONFLICTING,
    GROUNDING_STATUS_INCLUDED,
    GROUNDING_STATUS_UNAVAILABLE,
)
from app.domain.content.website_context import select_crawl_fragments
from app.models.brand import BrandProfile

GroundingStatus = Literal["included", "unavailable", "conflicting"]
_CONFIRMED_STATES = {BRAND_PROFILE_REVIEW_CONFIRMED, BRAND_PROFILE_REVIEW_EDITED}
_PROFILE_FIELDS = (
    ("description", "identity"),
    ("positioning", "positioning"),
    ("products_services", "offering"),
    ("target_audience", "audience"),
)
_RESTRICTED_CLASSES = (
    "numeric",
    "pricing",
    "policy",
    "regulated",
    "date",
    "safety",
    "identity",
)
_SOURCE_MARKER = re.compile(r"\[\[source:([a-f0-9]{64})\]\]")


@dataclass(frozen=True)
class GroundingBudget:
    selected_count: int
    omitted_count: int
    character_count: int


@dataclass(frozen=True)
class GroundingEnvelope:
    status: GroundingStatus
    version: str = CONTENT_GROUNDING_ENVELOPE_VERSION
    allowed_facts: list[dict[str, Any]] = field(default_factory=list)
    prohibited_claims: list[dict[str, str]] = field(default_factory=list)
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    omissions: list[dict[str, Any]] = field(default_factory=list)
    budget: GroundingBudget = field(default_factory=lambda: GroundingBudget(0, 0, 0))

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> GroundingEnvelope:
        budget = value.get("budget") or {}
        return cls(
            status=str(value.get("status") or GROUNDING_STATUS_UNAVAILABLE),  # type: ignore[arg-type]
            version=str(value.get("version") or CONTENT_GROUNDING_ENVELOPE_VERSION),
            allowed_facts=list(value.get("allowed_facts") or []),
            prohibited_claims=list(value.get("prohibited_claims") or []),
            source_refs=list(value.get("source_refs") or []),
            omissions=list(value.get("omissions") or []),
            budget=GroundingBudget(
                selected_count=int(budget.get("selected_count") or 0),
                omitted_count=int(budget.get("omitted_count") or 0),
                character_count=int(budget.get("character_count") or 0),
            ),
        )


def _stable_id(*parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _profile_fact(
    profile: BrandProfile, field_name: str, claim_class: str
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    provenance = (profile.sources or {}).get(field_name)
    if not isinstance(provenance, dict):
        return None
    review_state = str(provenance.get("review_state") or "")
    if review_state not in _CONFIRMED_STATES:
        return None
    value = getattr(profile, field_name)
    if value in (None, "", []):
        return None
    source_ref_id = _stable_id("profile", profile.id, field_name, value)
    source_ref = {
        "source_ref_id": source_ref_id,
        "source_kind": "profile_field",
        "source_id": str(profile.id),
        "field_or_fragment": field_name,
        "observed_at": provenance.get("reviewed_at") or profile.updated_at.isoformat(),
        "origin": str(provenance.get("origin") or "unknown"),
        "review_state": review_state,
    }
    fact = {
        "fact_id": _stable_id("fact", profile.id, field_name, value),
        "field": field_name,
        "value": value,
        "claim_class": claim_class,
        "source_ref_ids": [source_ref_id],
        "review_state": review_state,
        "limitations": [],
    }
    return fact, source_ref


def _crawl_source_refs(selection) -> list[dict[str, Any]]:
    summary = selection.summary or {}
    refs: list[dict[str, Any]] = []
    artifact_ids = list(summary.get("artifact_ids") or [])
    fetched_ats = list(summary.get("fetched_at") or [])
    content_hashes = list(summary.get("content_hashes") or [])
    for index, page in enumerate(selection.pages):
        if index >= len(artifact_ids):
            break
        fragment = json.dumps(
            page, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        artifact_id = str(artifact_ids[index])
        refs.append(
            {
                "source_ref_id": _stable_id("crawl", artifact_id, fragment),
                "source_kind": "crawl_fragment",
                "source_id": artifact_id,
                "field_or_fragment": fragment,
                "observed_at": fetched_ats[index] if index < len(fetched_ats) else None,
                "origin": "crawl_observed",
                "review_state": "observed_untrusted",
                "extractor_version": str(summary.get("extractor_version") or ""),
                "content_hash": content_hashes[index]
                if index < len(content_hashes)
                else "",
            }
        )
    return refs


def freeze_grounding_envelope(
    facts: list[dict[str, Any]],
    source_refs: list[dict[str, Any]],
    omissions: list[dict[str, Any]],
) -> GroundingEnvelope:
    """Bound, conflict-check, and validate an immutable envelope."""
    bounded_facts = facts[:CONTENT_GROUNDING_MAX_FACTS]
    bounded_refs = source_refs[:CONTENT_GROUNDING_MAX_SOURCE_REFS]
    omitted = len(facts) - len(bounded_facts) + len(source_refs) - len(bounded_refs)
    if omitted:
        omissions = [*omissions, {"reason_code": "grounding_budget", "count": omitted}]
    conflicts = _conflicting_classes(bounded_facts)
    if conflicts:
        bounded_facts = [
            item for item in bounded_facts if item["claim_class"] not in conflicts
        ]
    allowed_classes = {str(item["claim_class"]) for item in bounded_facts}
    prohibited = _prohibited_claims(allowed_classes, conflicts)
    status = _grounding_status(bounded_facts, bounded_refs, conflicts)
    character_count = sum(
        len(json.dumps(item, ensure_ascii=False))
        for item in [*bounded_facts, *bounded_refs]
    )
    envelope = GroundingEnvelope(
        status=status,
        allowed_facts=bounded_facts,
        prohibited_claims=prohibited,
        source_refs=bounded_refs,
        omissions=omissions,
        budget=GroundingBudget(
            len(bounded_facts) + len(bounded_refs), omitted, character_count
        ),
    )
    validate_grounding_envelope(envelope)
    return envelope


def _prohibited_claims(
    allowed_classes: set[str], conflicts: set[str]
) -> list[dict[str, str]]:
    return [
        {
            "claim_class": claim_class,
            "reason_code": (
                "conflicting_confirmed_facts"
                if claim_class in conflicts
                else "missing_confirmed_fact"
            ),
            "instruction": (
                "Omit this claim unless the envelope supplies one exact confirmed fact."
            ),
        }
        for claim_class in _RESTRICTED_CLASSES
        if claim_class not in allowed_classes or claim_class in conflicts
    ]


def _grounding_status(
    facts: list[dict[str, Any]], refs: list[dict[str, Any]], conflicts: set[str]
) -> GroundingStatus:
    if conflicts:
        return GROUNDING_STATUS_CONFLICTING
    if facts or refs:
        return GROUNDING_STATUS_INCLUDED
    return GROUNDING_STATUS_UNAVAILABLE


def _conflicting_classes(facts: list[dict[str, Any]]) -> set[str]:
    values: dict[str, set[str]] = {}
    for fact in facts:
        values.setdefault(str(fact["claim_class"]), set()).add(
            json.dumps(fact.get("value"), ensure_ascii=False, sort_keys=True)
        )
    return {claim_class for claim_class, items in values.items() if len(items) > 1}


def validate_grounding_envelope(envelope: GroundingEnvelope) -> None:
    ref_ids = {str(item.get("source_ref_id") or "") for item in envelope.source_refs}
    for fact in envelope.allowed_facts:
        cited = {str(value) for value in fact.get("source_ref_ids") or []}
        if not cited or not cited.issubset(ref_ids):
            raise ValueError("grounding fact cites an absent source reference")


def validate_provider_output(output_text: str, envelope: GroundingEnvelope) -> None:
    """Reject provider source metadata that cites anything outside the envelope."""
    available = {str(item.get("source_ref_id") or "") for item in envelope.source_refs}
    cited = set(_SOURCE_MARKER.findall(output_text))
    if not cited.issubset(available):
        raise ValueError("provider output cites an absent grounding source")


async def build_grounding_envelope(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> GroundingEnvelope:
    profile = await session.scalar(
        select(BrandProfile).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    facts: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    omissions: list[dict[str, Any]] = []
    if profile is None:
        omissions.append({"reason_code": "brand_profile_unavailable", "count": 1})
    else:
        for field_name, claim_class in _PROFILE_FIELDS:
            item = _profile_fact(profile, field_name, claim_class)
            if item is None:
                omissions.append(
                    {"reason_code": "profile_field_unconfirmed", "field": field_name}
                )
                continue
            fact, source_ref = item
            facts.append(fact)
            refs.append(source_ref)
    selection = await select_crawl_fragments(
        session, workspace_id=workspace_id, project_id=project_id
    )
    crawl_refs = _crawl_source_refs(selection)
    refs.extend(crawl_refs)
    if not crawl_refs:
        omissions.append({"reason_code": "crawl_evidence_unavailable", "count": 1})
    return freeze_grounding_envelope(facts, refs, omissions)
