# Content-generation domain service (workspace-scoped, invariant 5).
#
# Owns enqueue (race-safe workspace-scoped idempotency + provider-config
# check + frozen website-context/message snapshots), the bounded history
# list, detail, cancel, regenerate (context rebuilt) and try-again (frozen
# snapshot reused). Every query filters by the caller's workspace; a record
# in another workspace is indistinguishable from a missing one (404).
#
# The provider API key never appears here — the worker resolves it at call
# time from config (invariant 6).
from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.abuse import abuse_settings
from app.core.config.content import (
    CONTENT_GENERATOR_VERSION,
    CONTENT_KNOWN_PROVIDERS,
    CONTENT_LIST_MAX_LIMIT,
    FEEDBACK_ACCEPTED,
    FEEDBACK_REJECTED,
    content_settings,
)
from app.core.config.task_queue import (
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.abuse.service import reserve_workspace_capacity
from app.domain.content.grounding import (
    GroundingEnvelope,
    build_grounding_envelope,
)
from app.domain.content.message_builder import build_messages
from app.domain.content.schemas import (
    ContentGenerationDetail,
    ContentGenerationListItem,
    GroundingEnvelopeSummary,
    prompt_preview,
)
from app.models.content import ContentGeneration
from app.models.opportunity import Opportunity
from app.models.project import Project


class ContentGenerationNotFoundError(LookupError):
    """Record/project missing or owned by another workspace (-> 404)."""


class ProviderNotConfiguredError(RuntimeError):
    """The content provider key is not configured (-> 409)."""


class IdempotencyConflictError(RuntimeError):
    """Same idempotency key, different request fingerprint (-> 409)."""


class CancelNotAllowedError(RuntimeError):
    """Cancel requested on a terminal record (-> 409)."""


async def _reserve_content_capacity(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> None:
    await reserve_workspace_capacity(
        session,
        workspace_id=workspace_id,
        lock_namespace="content-enqueue",
        model=ContentGeneration,
        active_statuses=TASK_ACTIVE_STATUSES,
        active_limit=abuse_settings.active_content_jobs_per_workspace,
        active_operation="content.active_jobs",
        usage_operation="content.provider_jobs",
        usage_limit=abuse_settings.content_jobs_per_workspace_daily,
        retry_after_seconds=abuse_settings.active_job_retry_after_seconds,
    )


def request_fingerprint(
    *,
    project_id: uuid.UUID,
    prompt: str,
    output_type: str,
    skill_id: str = "article",
    opportunity_id: uuid.UUID | None = None,
) -> str:
    """Stable comparator for idempotency replay-vs-conflict decisions."""
    canonical = "\x1f".join(
        [
            str(project_id),
            prompt.strip(),
            output_type,
            skill_id,
            _optional_uuid(opportunity_id),
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _optional_uuid(value: uuid.UUID | None) -> str:
    return "" if value is None else str(value)


async def _project_in_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise ContentGenerationNotFoundError("Project not found")
    return project


def _summary_dto(row: ContentGeneration) -> GroundingEnvelopeSummary:
    envelope = row.grounding_envelope or {}
    refs = list(envelope.get("source_refs") or [])
    prohibited = list(envelope.get("prohibited_claims") or [])
    return GroundingEnvelopeSummary(
        version=str(envelope.get("version") or ""),
        allowed_fact_count=len(envelope.get("allowed_facts") or []),
        source_ref_count=len(refs),
        crawl_fragment_count=sum(
            item.get("source_kind") == "crawl_fragment" for item in refs
        ),
        prohibited_claim_classes=[
            str(item.get("claim_class") or "") for item in prohibited
        ],
        omissions=list(envelope.get("omissions") or []),
        budget=dict(envelope.get("budget") or {}),
    )


def to_list_item(row: ContentGeneration) -> ContentGenerationListItem:
    item = ContentGenerationListItem.model_validate(row)
    item.prompt_preview = prompt_preview(row.prompt)
    return item


def to_detail(row: ContentGeneration) -> ContentGenerationDetail:
    payload = {
        field_name: getattr(row, field_name)
        for field_name in ContentGenerationDetail.model_fields
        if field_name not in {"prompt_preview", "grounding_summary"}
    }
    payload["prompt_preview"] = prompt_preview(row.prompt)
    payload["grounding_summary"] = _summary_dto(row)
    return ContentGenerationDetail.model_validate(payload)


async def _insert_generation(
    session: AsyncSession,
    *,
    row: ContentGeneration,
    grounding_envelope: GroundingEnvelope,
) -> ContentGeneration:
    messages, digest, message_snapshot = build_messages(
        prompt=row.prompt,
        output_type=row.output_type,
        grounding_envelope=grounding_envelope,
        skill_id=row.skill_id,
    )
    # ``messages`` itself is never persisted — the worker rebuilds it from the
    # frozen prompt + snapshot; only the digest + safe snapshot are stored.
    del messages
    row.grounding_status = grounding_envelope.status
    row.grounding_envelope = grounding_envelope.snapshot()
    row.message_digest = digest
    row.message_snapshot = message_snapshot
    session.add(row)
    return row


def _require_provider_configured() -> None:
    # Readiness is provider-aware: an unknown provider name is just as
    # unconfigured as a missing key, and each known provider is checked for
    # the key it actually uses (only Mistral exists today).
    if content_settings.provider not in CONTENT_KNOWN_PROVIDERS:
        raise ProviderNotConfiguredError(
            f"unknown content provider: {content_settings.provider}"
        )
    if not content_settings.mistral_api_key.get_secret_value():
        raise ProviderNotConfiguredError(
            "content provider is not configured (missing API key)"
        )


async def enqueue_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    output_type: str,
    idempotency_key: str = "",
    skill_id: str = "article",
    opportunity_id: uuid.UUID | None = None,
) -> tuple[ContentGeneration, bool]:
    """Enqueue one generation. Returns ``(row, created)``.

    ``created`` is False on an idempotent replay (same workspace key + same
    fingerprint). A same-key different-fingerprint request raises
    ``IdempotencyConflictError``; a concurrent same-key insert converges via
    the IntegrityError reload/compare path.
    """
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )

    await _require_opportunity(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=opportunity_id,
    )
    fingerprint = request_fingerprint(
        project_id=project_id,
        prompt=prompt,
        output_type=output_type,
        skill_id=skill_id,
        opportunity_id=opportunity_id,
    )
    # A server-side key when the client sent none: the composite constraint is
    # always satisfied and keyless requests never collide with each other.
    key = idempotency_key or str(uuid.uuid4())

    # Replay before the provider-config check: a retry of an already-accepted
    # request must stay retrievable even if the provider was unconfigured (or
    # broken) in between.
    existing = await _idempotent_replay(
        session,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
        key=key,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return existing, False

    grounding_envelope = await build_grounding_envelope(
        session, workspace_id=workspace_id, project_id=project_id
    )
    _require_provider_configured()
    await _reserve_content_capacity(session, workspace_id=workspace_id)

    row = await _insert_generation(
        session,
        row=ContentGeneration(
            workspace_id=workspace_id,
            project_id=project_id,
            prompt=prompt,
            output_type=output_type,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            skill_id=skill_id,
            opportunity_id=opportunity_id,
            skill_version=CONTENT_GENERATOR_VERSION,
            provider=content_settings.provider,
            requested_model=content_settings.model,
            generator_version=CONTENT_GENERATOR_VERSION,
        ),
        grounding_envelope=grounding_envelope,
    )
    winner = await _commit_generation(
        session, workspace_id=workspace_id, key=key, fingerprint=fingerprint
    )
    if winner is not None:
        return winner, False
    await session.refresh(row)
    return row, True


async def _require_opportunity(session, *, workspace_id, project_id, opportunity_id):
    if opportunity_id is None:
        return None
    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
            Opportunity.project_id == project_id,
        )
    )
    if opportunity is None:
        raise ContentGenerationNotFoundError("Opportunity not found")
    return None


async def _idempotent_replay(
    session, *, workspace_id, idempotency_key, key, fingerprint
):
    if not idempotency_key:
        return None
    existing = await session.scalar(
        select(ContentGeneration).where(
            ContentGeneration.workspace_id == workspace_id,
            ContentGeneration.idempotency_key == key,
        )
    )
    if existing is None:
        return None
    if existing.request_fingerprint == fingerprint:
        return existing
    raise IdempotencyConflictError(
        "idempotency key was already used with a different request"
    )


async def _commit_generation(session, *, workspace_id, key, fingerprint):
    try:
        await session.commit()
        return None
    except IntegrityError as exc:
        await session.rollback()
        winner = await session.scalar(
            select(ContentGeneration).where(
                ContentGeneration.workspace_id == workspace_id,
                ContentGeneration.idempotency_key == key,
            )
        )
        if winner is None:
            raise exc
        if winner.request_fingerprint == fingerprint:
            return winner
        raise IdempotencyConflictError(
            "idempotency key was already used with a different request"
        ) from None


async def list_generations(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int,
) -> list[ContentGeneration]:
    """The project's generations, newest first, bounded (authorizes first)."""
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )
    capped = max(1, min(limit, CONTENT_LIST_MAX_LIMIT))
    rows = await session.scalars(
        select(ContentGeneration)
        .where(
            ContentGeneration.workspace_id == workspace_id,
            ContentGeneration.project_id == project_id,
        )
        .order_by(
            ContentGeneration.created_at.desc(),
            ContentGeneration.id.desc(),
        )
        .limit(capped)
    )
    return list(rows.all())


async def get_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> ContentGeneration:
    row = await session.scalar(
        select(ContentGeneration).where(
            ContentGeneration.id == generation_id,
            ContentGeneration.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise ContentGenerationNotFoundError("Content generation not found")
    return row


async def cancel_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> ContentGeneration:
    """Cooperative cancel: allowed for any non-terminal status.

    Sets ``cancelled`` + clears the lease under ``FOR UPDATE`` so a worker's
    later terminal write (which re-checks owner + status under its own lock)
    discards the in-flight result (invariant 3/9).
    """
    await get_generation(
        session, workspace_id=workspace_id, generation_id=generation_id
    )
    locked = await session.get(ContentGeneration, generation_id, with_for_update=True)
    if locked is None:
        raise ContentGenerationNotFoundError("Content generation not found")
    if locked.status in TASK_TERMINAL_STATUSES:
        # Capture before rollback: rollback expires the instance and a later
        # attribute access would trigger sync lazy-loading (MissingGreenlet).
        terminal_status = locked.status
        await session.rollback()
        raise CancelNotAllowedError(f"cannot cancel a {terminal_status} generation")
    locked.status = TASK_STATUS_CANCELLED
    locked.lease_owner = None
    locked.lease_expires_at = None
    locked.completed_at = datetime.now(UTC)
    if not locked.error_code:
        locked.error_code = "cancelled"
    await session.commit()
    await session.refresh(locked)
    return locked


async def regenerate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> ContentGeneration:
    """New record from an existing one, context REBUILT from the newest
    eligible crawl. The original is never mutated."""
    source = await get_generation(
        session, workspace_id=workspace_id, generation_id=generation_id
    )
    row, _created = await enqueue_generation(
        session,
        workspace_id=workspace_id,
        project_id=source.project_id,
        prompt=source.prompt,
        output_type=source.output_type,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
    )
    return row


async def try_again(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
) -> ContentGeneration:
    """New record re-using the source's exact frozen context snapshot
    (reproducible; no rebuild). The original is never mutated."""
    source = await get_generation(
        session, workspace_id=workspace_id, generation_id=generation_id
    )
    _require_provider_configured()
    await _reserve_content_capacity(session, workspace_id=workspace_id)
    frozen = GroundingEnvelope.from_snapshot(source.grounding_envelope or {})
    fingerprint = request_fingerprint(
        project_id=source.project_id,
        prompt=source.prompt,
        output_type=source.output_type,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
    )
    row = await _insert_generation(
        session,
        row=ContentGeneration(
            workspace_id=workspace_id,
            project_id=source.project_id,
            prompt=source.prompt,
            output_type=source.output_type,
            idempotency_key=str(uuid.uuid4()),
            request_fingerprint=fingerprint,
            skill_id=source.skill_id,
            opportunity_id=source.opportunity_id,
            skill_version=source.skill_version,
            provider=content_settings.provider,
            requested_model=content_settings.model,
            generator_version=CONTENT_GENERATOR_VERSION,
        ),
        grounding_envelope=frozen,
    )
    await session.commit()
    await session.refresh(row)
    return row


async def record_feedback(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
    feedback: str,
) -> ContentGeneration:
    """Record an immutable accepted/rejected reaction on completed output."""
    row = await session.scalar(
        select(ContentGeneration)
        .where(
            ContentGeneration.id == generation_id,
            ContentGeneration.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if row is None:
        raise ContentGenerationNotFoundError("Content generation not found")
    if feedback not in {FEEDBACK_ACCEPTED, FEEDBACK_REJECTED}:
        raise ValueError("unknown content feedback")
    if row.status != TASK_STATUS_SUCCEEDED or not row.output_text:
        raise ValueError("only completed content can be reviewed")
    if row.feedback is not None and row.feedback != feedback:
        raise ValueError("content feedback cannot be changed once recorded")
    if row.feedback == feedback:
        await session.commit()
        return row
    row.feedback = feedback
    row.feedback_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row
