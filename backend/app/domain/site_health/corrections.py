"""Durable user corrections over recomputable Site knowledge projections."""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.knowledge import normalize_text
from app.core.config.industry_packs.catalog import canonical_json_bytes
from app.core.config.site_intelligence import (
    CORRECTION_SCOPE_ENTITY,
    CORRECTION_SCOPE_PROJECT,
    CORRECTION_STATE_ACTIVE,
    CORRECTION_STATE_WITHDRAWN,
    CORRECTION_TARGET_ASSERTION,
    CORRECTION_TARGET_ENTITY,
    CORRECTION_TARGET_RELATION,
    CORRECTION_TRANSITION_CREATED,
    CORRECTION_TRANSITION_WITHDRAWN,
    DEFAULT_CORRECTIONS_PAGE_SIZE,
    MAX_CORRECTION_REASON_CHARS,
    MAX_CORRECTIONS_PAGE_SIZE,
    VALUE_TYPE_BOOLEAN,
    VALUE_TYPE_MONEY,
    VALUE_TYPE_NUMBER,
    VALUE_TYPE_OBJECT,
    VALUE_TYPES,
)
from app.models.knowledge import (
    Correction,
    CorrectionTransition,
    KnowledgeAssertion,
    KnowledgeEntity,
    KnowledgeRelation,
)
from app.models.project import Project

__all__ = [
    "CorrectionConflictError",
    "CorrectionNotFoundError",
    "CorrectionValidationError",
    "active_corrections_by_target",
    "correction_payload",
    "create_correction",
    "assertion_target_ref",
    "entity_target_ref",
    "list_corrections",
    "relation_target_ref",
    "stable_target_key",
    "withdraw_correction",
]


class CorrectionNotFoundError(Exception):
    """A workspace-scoped correction or target does not exist."""


class CorrectionValidationError(Exception):
    """A correction does not satisfy its typed target/value contract."""


class CorrectionConflictError(Exception):
    """An active correction already owns the target and effective scope."""


def stable_target_key(target_ref: Mapping) -> str:
    """Hash a typed natural identity; crawl IDs never participate."""
    return hashlib.sha256(canonical_json_bytes(dict(target_ref))).hexdigest()


def entity_target_ref(entity_type_id: str, identity_key: str) -> dict:
    return {
        "entity_type_id": entity_type_id,
        "identity_key": identity_key,
    }


def assertion_target_ref(
    *,
    subject_entity_type_id: str,
    subject_identity_key: str,
    predicate_id: str,
    scope_key: str,
) -> dict:
    return {
        "subject": entity_target_ref(subject_entity_type_id, subject_identity_key),
        "predicate_id": predicate_id,
        "scope_key": scope_key,
    }


def relation_target_ref(
    *,
    relation_type_id: str,
    source_entity_type_id: str,
    source_identity_key: str,
    target_entity_type_id: str,
    target_identity_key: str,
) -> dict:
    return {
        "relation_type_id": relation_type_id,
        "source": entity_target_ref(source_entity_type_id, source_identity_key),
        "target": entity_target_ref(target_entity_type_id, target_identity_key),
    }


def _assertion_value(assertion: KnowledgeAssertion) -> dict:
    return {
        "raw_value": assertion.raw_value,
        "normalized_value": assertion.normalized_value,
        "numeric_value": assertion.numeric_value,
        "unit": assertion.unit or "",
        "currency": assertion.currency or "",
        "value_type": assertion.value_type,
    }


async def _target(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
) -> tuple[
    KnowledgeEntity | KnowledgeAssertion | KnowledgeRelation, dict, str, dict, str
]:
    filters = (
        ("id", target_id),
        ("workspace_id", workspace_id),
        ("project_id", project_id),
    )
    if target_kind == CORRECTION_TARGET_ENTITY:
        row = await session.scalar(
            select(KnowledgeEntity).where(
                *(getattr(KnowledgeEntity, name) == value for name, value in filters)
            )
        )
        if row is None:
            raise CorrectionNotFoundError("correction target not found")
        ref = entity_target_ref(row.entity_type_id, row.identity_key)
        return (
            row,
            ref,
            "canonical_name",
            {"canonical_name": row.canonical_name},
            "string",
        )

    if target_kind == CORRECTION_TARGET_ASSERTION:
        result = await session.execute(
            select(KnowledgeAssertion, KnowledgeEntity)
            .join(
                KnowledgeEntity,
                KnowledgeEntity.id == KnowledgeAssertion.subject_entity_id,
            )
            .where(
                *(getattr(KnowledgeAssertion, name) == value for name, value in filters)
            )
        )
        found = result.one_or_none()
        if found is None:
            raise CorrectionNotFoundError("correction target not found")
        row, subject = found
        ref = assertion_target_ref(
            subject_entity_type_id=subject.entity_type_id,
            subject_identity_key=subject.identity_key,
            predicate_id=row.predicate_id,
            scope_key=row.scope_key,
        )
        return row, ref, "value", _assertion_value(row), row.value_type

    if target_kind == CORRECTION_TARGET_RELATION:
        row = await session.scalar(
            select(KnowledgeRelation).where(
                *(getattr(KnowledgeRelation, name) == value for name, value in filters)
            )
        )
        if row is None:
            raise CorrectionNotFoundError("correction target not found")
        source = await session.scalar(
            select(KnowledgeEntity).where(
                KnowledgeEntity.id == row.source_entity_id,
                KnowledgeEntity.workspace_id == workspace_id,
                KnowledgeEntity.project_id == project_id,
            )
        )
        target = await session.scalar(
            select(KnowledgeEntity).where(
                KnowledgeEntity.id == row.target_entity_id,
                KnowledgeEntity.workspace_id == workspace_id,
                KnowledgeEntity.project_id == project_id,
            )
        )
        if source is None or target is None:
            raise CorrectionNotFoundError("correction target not found")
        ref = relation_target_ref(
            relation_type_id=row.relation_type_id,
            source_entity_type_id=source.entity_type_id,
            source_identity_key=source.identity_key,
            target_entity_type_id=target.entity_type_id,
            target_identity_key=target.identity_key,
        )
        return row, ref, "is_current", {"is_current": bool(row.is_current)}, "boolean"

    raise CorrectionValidationError("unsupported correction target kind")


def _corrected_value(
    *, target_kind: str, value_type: str, value: object, unit: str, currency: str
) -> dict:
    if target_kind == CORRECTION_TARGET_ENTITY:
        if not isinstance(value, str) or not normalize_text(value):
            raise CorrectionValidationError(
                "entity corrections require a non-empty string"
            )
        return {"canonical_name": normalize_text(value)}
    if target_kind == CORRECTION_TARGET_RELATION:
        if not isinstance(value, bool):
            raise CorrectionValidationError("relation corrections require a boolean")
        return {"is_current": value}
    if value_type not in VALUE_TYPES:
        raise CorrectionValidationError("target has an unsupported value type")
    if value_type == VALUE_TYPE_BOOLEAN:
        return _boolean_value(value)
    if value_type in {VALUE_TYPE_NUMBER, VALUE_TYPE_MONEY}:
        return _numeric_value(value_type, value, unit, currency)
    if value_type == VALUE_TYPE_OBJECT:
        return _object_value(value)
    return _text_value(value_type, value, unit, currency)


def _boolean_value(value: object) -> dict:
    if not isinstance(value, bool):
        raise CorrectionValidationError(
            "boolean assertion corrections require a boolean"
        )
    normalized = "true" if value else "false"
    return {
        "raw_value": normalized,
        "normalized_value": normalized,
        "numeric_value": None,
        "unit": "",
        "currency": "",
        "value_type": VALUE_TYPE_BOOLEAN,
    }


def _numeric_value(value_type: str, value: object, unit: str, currency: str) -> dict:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CorrectionValidationError(
            "numeric assertion corrections require a number"
        )
    number = float(value)
    if not math.isfinite(number):
        raise CorrectionValidationError("numeric assertion corrections must be finite")
    normalized_currency = normalize_text(currency, limit=8).upper()
    if value_type == VALUE_TYPE_MONEY and not normalized_currency:
        raise CorrectionValidationError("money corrections require currency")
    normalized = (
        f"{normalized_currency} {number:.2f}"
        if value_type == VALUE_TYPE_MONEY
        else repr(number).removesuffix(".0")
    )
    return {
        "raw_value": str(value),
        "normalized_value": normalized,
        "numeric_value": number,
        "unit": normalize_text(unit, limit=32),
        "currency": normalized_currency,
        "value_type": value_type,
    }


def _object_value(value: object) -> dict:
    if not isinstance(value, dict):
        raise CorrectionValidationError(
            "object assertion corrections require an object"
        )
    raw = canonical_json_bytes(value).decode("utf-8")
    return {
        "raw_value": raw[:512],
        "normalized_value": hashlib.sha256(raw.encode()).hexdigest(),
        "numeric_value": None,
        "unit": "",
        "currency": "",
        "value_type": VALUE_TYPE_OBJECT,
        "object_value": value,
    }


def _text_value(value_type: str, value: object, unit: str, currency: str) -> dict:
    if not isinstance(value, str) or not normalize_text(value):
        raise CorrectionValidationError(
            "text assertion corrections require a non-empty string"
        )
    raw = normalize_text(value)
    return {
        "raw_value": raw,
        "normalized_value": raw.casefold(),
        "numeric_value": None,
        "unit": normalize_text(unit, limit=32),
        "currency": normalize_text(currency, limit=8).upper(),
        "value_type": value_type,
    }


async def _effective_scope(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    scope: str,
    scope_id: uuid.UUID | None,
) -> tuple[dict, str]:
    if scope == CORRECTION_SCOPE_PROJECT:
        if scope_id is not None:
            raise CorrectionValidationError(
                "project scope does not accept effective_scope_id"
            )
        return {}, CORRECTION_SCOPE_PROJECT
    if scope_id is None:
        raise CorrectionValidationError(f"{scope} scope requires effective_scope_id")
    if scope != CORRECTION_SCOPE_ENTITY:
        raise CorrectionValidationError("unsupported correction scope")
    row = await session.scalar(
        select(KnowledgeEntity).where(
            KnowledgeEntity.id == scope_id,
            KnowledgeEntity.workspace_id == workspace_id,
            KnowledgeEntity.project_id == project_id,
        )
    )
    if row is None:
        raise CorrectionNotFoundError("effective scope not found")
    if scope == CORRECTION_SCOPE_ENTITY:
        ref = entity_target_ref(row.entity_type_id, row.identity_key)
    return ref, f"{scope}:{stable_target_key(ref)}"


def _snapshot(correction: Correction) -> dict:
    return {
        "state": correction.state,
        "target_kind": correction.target_kind,
        "target_ref": dict(correction.target_ref),
        "target_field": correction.target_field,
        "corrected_value": dict(correction.corrected_value),
        "effective_scope": correction.effective_scope,
        "effective_scope_ref": dict(correction.effective_scope_ref),
    }


async def create_correction(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
    value: object,
    effective_scope: str,
    effective_scope_id: uuid.UUID | None,
    effective_from: datetime | None,
    effective_to: datetime | None,
    unit: str,
    currency: str,
    reason: str,
) -> Correction:
    if effective_scope not in {CORRECTION_SCOPE_PROJECT, CORRECTION_SCOPE_ENTITY}:
        raise CorrectionValidationError("unsupported correction scope")
    normalized_reason = normalize_text(reason, limit=MAX_CORRECTION_REASON_CHARS)
    if not normalized_reason:
        raise CorrectionValidationError("correction reason is required")
    if effective_from and effective_to and effective_from > effective_to:
        raise CorrectionValidationError("effective_from must not be after effective_to")
    target, target_ref, target_field, derived_value, value_type = await _target(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=target_kind,
        target_id=target_id,
    )
    scope_ref, scope_key = await _effective_scope(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        scope=effective_scope,
        scope_id=effective_scope_id,
    )
    target_key = stable_target_key(target_ref)
    existing = await session.scalar(
        select(Correction.id).where(
            Correction.workspace_id == workspace_id,
            Correction.project_id == project_id,
            Correction.target_key == target_key,
            Correction.target_field == target_field,
            Correction.effective_scope_key == scope_key,
            Correction.state == CORRECTION_STATE_ACTIVE,
        )
    )
    if existing is not None:
        raise CorrectionConflictError(
            "an active correction already exists for this target and scope"
        )
    corrected_value = _corrected_value(
        target_kind=target_kind,
        value_type=value_type,
        value=value,
        unit=unit,
        currency=currency,
    )
    correction = Correction(
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=target_kind,
        target_key=target_key,
        target_ref=target_ref,
        target_field=target_field,
        source_crawl_id=target.crawl_id,
        source_target_id=target.id,
        derived_value=derived_value,
        corrected_value=corrected_value,
        value_type=value_type,
        effective_scope=effective_scope,
        effective_scope_ref=scope_ref,
        effective_scope_key=scope_key,
        effective_from=effective_from,
        effective_to=effective_to,
        author_user_id=actor_user_id,
        reason=normalized_reason,
        state=CORRECTION_STATE_ACTIVE,
    )
    session.add(correction)
    try:
        await session.flush()
        session.add(
            CorrectionTransition(
                workspace_id=workspace_id,
                project_id=project_id,
                correction_id=correction.id,
                sequence=1,
                transition_type=CORRECTION_TRANSITION_CREATED,
                actor_user_id=actor_user_id,
                reason=correction.reason,
                snapshot=_snapshot(correction),
            )
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if _constraint_name(exc) == "uq_correction_active_target_scope":
            raise CorrectionConflictError(
                "an active correction already exists for this target and scope"
            ) from exc
        raise
    await session.refresh(correction)
    return correction


async def withdraw_correction(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    correction_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str,
) -> Correction:
    normalized_reason = normalize_text(reason, limit=MAX_CORRECTION_REASON_CHARS)
    if not normalized_reason:
        raise CorrectionValidationError("withdrawal reason is required")
    correction = await session.scalar(
        select(Correction)
        .where(
            Correction.id == correction_id,
            Correction.workspace_id == workspace_id,
            Correction.project_id == project_id,
        )
        .with_for_update()
    )
    if correction is None:
        raise CorrectionNotFoundError("correction not found")
    if correction.state == CORRECTION_STATE_WITHDRAWN:
        await session.commit()
        return correction
    now = datetime.now(UTC)
    correction.state = CORRECTION_STATE_WITHDRAWN
    correction.withdrawn_at = now
    count = int(
        await session.scalar(
            select(func.count())
            .select_from(CorrectionTransition)
            .where(CorrectionTransition.correction_id == correction.id)
        )
        or 0
    )
    session.add(
        CorrectionTransition(
            workspace_id=workspace_id,
            project_id=project_id,
            correction_id=correction.id,
            sequence=count + 1,
            transition_type=CORRECTION_TRANSITION_WITHDRAWN,
            actor_user_id=actor_user_id,
            reason=normalized_reason,
            snapshot=_snapshot(correction),
        )
    )
    await session.commit()
    await session.refresh(correction)
    return correction


async def _transitions(
    session: AsyncSession, correction_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CorrectionTransition]]:
    if not correction_ids:
        return {}
    rows = (
        (
            await session.execute(
                select(CorrectionTransition)
                .where(CorrectionTransition.correction_id.in_(correction_ids))
                .order_by(
                    CorrectionTransition.correction_id, CorrectionTransition.sequence
                )
            )
        )
        .scalars()
        .all()
    )
    grouped: dict[uuid.UUID, list[CorrectionTransition]] = {}
    for row in rows:
        grouped.setdefault(row.correction_id, []).append(row)
    return grouped


def correction_payload(
    correction: Correction, transitions: list[CorrectionTransition] | None = None
) -> dict:
    return {
        "id": str(correction.id),
        "target_kind": correction.target_kind,
        "target_ref": dict(correction.target_ref),
        "target_field": correction.target_field,
        "source_crawl_id": str(correction.source_crawl_id),
        "source_target_id": str(correction.source_target_id),
        "derived_value": dict(correction.derived_value),
        "corrected_value": dict(correction.corrected_value),
        "value_type": correction.value_type,
        "effective_scope": correction.effective_scope,
        "effective_scope_ref": dict(correction.effective_scope_ref),
        "effective_from": correction.effective_from.isoformat()
        if correction.effective_from
        else None,
        "effective_to": correction.effective_to.isoformat()
        if correction.effective_to
        else None,
        "author_user_id": str(correction.author_user_id),
        "reason": correction.reason,
        "state": correction.state,
        "withdrawn_at": correction.withdrawn_at.isoformat()
        if correction.withdrawn_at
        else None,
        "created_at": correction.created_at.isoformat(),
        "transitions": [
            {
                "id": str(row.id),
                "sequence": row.sequence,
                "transition_type": row.transition_type,
                "actor_user_id": str(row.actor_user_id),
                "reason": row.reason,
                "snapshot": dict(row.snapshot),
                "created_at": row.created_at.isoformat(),
            }
            for row in transitions or []
        ],
    }


async def list_corrections(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    include_withdrawn: bool = True,
    limit: int = DEFAULT_CORRECTIONS_PAGE_SIZE,
    offset: int = 0,
) -> dict:
    project_exists = await session.scalar(
        select(Project.id).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if project_exists is None:
        raise CorrectionNotFoundError("project not found")
    where = [
        Correction.workspace_id == workspace_id,
        Correction.project_id == project_id,
    ]
    if not include_withdrawn:
        where.append(Correction.state == CORRECTION_STATE_ACTIVE)
    total = int(
        await session.scalar(select(func.count()).select_from(Correction).where(*where))
        or 0
    )
    rows = (
        (
            await session.execute(
                select(Correction)
                .where(*where)
                .order_by(Correction.created_at, Correction.id)
                .offset(max(0, offset))
                .limit(min(max(1, limit), MAX_CORRECTIONS_PAGE_SIZE))
            )
        )
        .scalars()
        .all()
    )
    transitions = await _transitions(session, [row.id for row in rows])
    return {
        "total": total,
        "items": [correction_payload(row, transitions.get(row.id)) for row in rows],
    }


async def active_corrections_by_target(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    at: datetime | None = None,
) -> dict[str, Correction]:
    """Effective project/entity corrections keyed by stable target identity."""
    instant = at or datetime.now(UTC)
    scope_precedence = case(
        (Correction.effective_scope == CORRECTION_SCOPE_ENTITY, 0), else_=1
    )
    rows = (
        (
            await session.execute(
                select(Correction)
                .where(
                    Correction.workspace_id == workspace_id,
                    Correction.project_id == project_id,
                    Correction.target_kind == target_kind,
                    Correction.state == CORRECTION_STATE_ACTIVE,
                    Correction.effective_scope.in_(
                        (CORRECTION_SCOPE_PROJECT, CORRECTION_SCOPE_ENTITY)
                    ),
                    (
                        Correction.effective_from.is_(None)
                        | (Correction.effective_from <= instant)
                    ),
                    (
                        Correction.effective_to.is_(None)
                        | (Correction.effective_to >= instant)
                    ),
                )
                .order_by(
                    Correction.target_key,
                    scope_precedence,
                    Correction.created_at.desc(),
                    Correction.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    selected: dict[str, Correction] = {}
    for row in rows:
        selected.setdefault(row.target_key, row)
    return selected


def _constraint_name(error: IntegrityError) -> str | None:
    direct = getattr(error.orig, "constraint_name", None)
    cause = getattr(error.orig, "__cause__", None)
    return direct or getattr(cause, "constraint_name", None)
