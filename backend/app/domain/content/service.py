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
import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.abuse import abuse_settings
from app.core.config.content import (
    CONTENT_DEFAULT_SKILL,
    CONTENT_FEEDBACK_REASONS,
    CONTENT_GENERATOR_VERSION,
    CONTENT_LIST_MAX_LIMIT,
    CONTENT_SKILL_CATALOG_VERSION,
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
from app.domain.content.context_builder import (
    ContentContext,
    build_content_context,
    content_context_availability,
)
from app.domain.content.message_builder import build_messages
from app.domain.content.schemas import (
    ContentContextSummary,
    ContentGenerationDetail,
    ContentGenerationListItem,
    SiteHealthReference,
    prompt_preview,
)
from app.domain.site_health.service.aeo_readiness import get_content_handoff
from app.domain.site_health.service.common import SiteHealthNotFoundError
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
    skill_id: str = CONTENT_DEFAULT_SKILL,
    opportunity_id: uuid.UUID | None = None,
    site_health_reference: dict | None = None,
) -> str:
    """Stable comparator for idempotency replay-vs-conflict decisions."""
    canonical = "\x1f".join(
        [
            str(project_id),
            prompt.strip(),
            output_type,
            skill_id,
            _optional_uuid(opportunity_id),
            json.dumps(
                site_health_reference or {}, sort_keys=True, separators=(",", ":")
            ),
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


def _summary_dto(row: ContentGeneration) -> ContentContextSummary:
    """Bounded public provenance: counts and URLs, never the rendered blocks."""
    summary = (row.grounding_envelope or {}).get("summary") or {}
    return ContentContextSummary(
        version=str((row.grounding_envelope or {}).get("version") or ""),
        crawl_page_count=int(summary.get("crawl_page_count") or 0),
        crawl_urls=[str(url) for url in (summary.get("crawl_urls") or [])],
        crawl_completed_at=summary.get("crawl_completed_at"),
        brand_fields=[str(item) for item in (summary.get("brand_fields") or [])],
        search_connected=bool(summary.get("search_connected")),
        omissions=list(summary.get("omissions") or []),
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


def _insert_generation(
    session: AsyncSession,
    *,
    row: ContentGeneration,
    context: ContentContext,
) -> ContentGeneration:
    messages, digest, message_snapshot = build_messages(
        prompt=row.prompt,
        context=context,
        skill_id=row.skill_id,
    )
    # ``messages`` itself is never persisted — the worker rebuilds it from the
    # frozen prompt + snapshot; only the digest + safe snapshot are stored.
    del messages
    row.grounding_status = context.status
    row.grounding_envelope = context.snapshot()
    row.message_digest = digest
    row.message_snapshot = message_snapshot
    session.add(row)
    return row


def _require_provider_configured() -> None:
    # The transport is provider-neutral, so readiness is just: a provider name
    # and a key. Model/endpoint swaps are pure ``.env`` changes.
    if not content_settings.provider:
        raise ProviderNotConfiguredError("content provider is not configured")
    if not content_settings.resolved_api_key:
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
    skill_id: str = CONTENT_DEFAULT_SKILL,
    opportunity_id: uuid.UUID | None = None,
    site_health_reference: SiteHealthReference | None = None,
) -> tuple[ContentGeneration, bool]:
    """Enqueue one generation. Returns ``(row, created)``.

    ``created`` is False on an idempotent replay (same workspace key + same
    fingerprint). A same-key different-fingerprint request raises
    ``IdempotencyConflictError``; a concurrent same-key insert converges via
    the IntegrityError reload/compare path.
    """
    project = await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )

    opportunity = await _require_opportunity(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=opportunity_id,
    )
    reference_dict = (
        site_health_reference.model_dump(mode="json") if site_health_reference else None
    )
    if site_health_reference and site_health_reference.project_id != project_id:
        raise ContentGenerationNotFoundError("Site Health reference not found")
    try:
        site_health_handoff = (
            await get_content_handoff(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                crawl_id=site_health_reference.crawl_id,
                site_url_id=site_health_reference.site_url_id,
                source_analysis_id=site_health_reference.source_analysis_id,
                dimension=site_health_reference.dimension,
                checkpoint_ids=site_health_reference.checkpoint_ids,
            )
            if site_health_reference
            else None
        )
    except SiteHealthNotFoundError as exc:
        raise ContentGenerationNotFoundError(str(exc)) from exc
    fingerprint = request_fingerprint(
        project_id=project_id,
        prompt=prompt,
        output_type=output_type,
        skill_id=skill_id,
        opportunity_id=opportunity_id,
        site_health_reference=reference_dict,
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

    context = await build_content_context(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt=prompt,
        brand_name=project.brand_name or project.name,
        website=project.website_url,
        locale=_project_locale(project),
        opportunity=opportunity,
        site_health_handoff=site_health_handoff,
    )
    _require_provider_configured()
    await _reserve_content_capacity(session, workspace_id=workspace_id)

    row = _insert_generation(
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
            site_health_reference=reference_dict,
            # The skill catalog and the generator version independently: a
            # reworded directive changes what was asked for even when the
            # generator is untouched, so provenance must record both.
            skill_version=CONTENT_SKILL_CATALOG_VERSION,
            provider=content_settings.provider,
            requested_model=content_settings.resolved_model,
            generator_version=CONTENT_GENERATOR_VERSION,
        ),
        context=context,
    )
    winner = await _commit_generation(
        session, workspace_id=workspace_id, key=key, fingerprint=fingerprint
    )
    if winner is not None:
        return winner, False
    await session.refresh(row)
    return row, True


def _project_locale(project: Project) -> str:
    """Market/language hint so drafts stay in the project's locale."""
    return " ".join(
        part
        for part in (
            project.country_code or project.primary_market,
            project.language_code,
        )
        if part
    ).strip()


async def _require_opportunity(
    session, *, workspace_id, project_id, opportunity_id
) -> Opportunity | None:
    """Authorize and RETURN the opportunity so its text can reach the model."""
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
    return opportunity


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


async def context_preview(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """What would ground a draft for this project right now (authorizes first)."""
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=project_id
    )
    return await content_context_availability(
        session, workspace_id=workspace_id, project_id=project_id
    )


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
        site_health_reference=(
            SiteHealthReference.model_validate(source.site_health_reference)
            if source.site_health_reference
            else None
        ),
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
    frozen = ContentContext.from_snapshot(source.grounding_envelope or {})
    fingerprint = request_fingerprint(
        project_id=source.project_id,
        prompt=source.prompt,
        output_type=source.output_type,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
        site_health_reference=source.site_health_reference,
    )
    row = _insert_generation(
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
            site_health_reference=source.site_health_reference,
            skill_version=source.skill_version,
            provider=content_settings.provider,
            requested_model=content_settings.resolved_model,
            generator_version=CONTENT_GENERATOR_VERSION,
        ),
        context=frozen,
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
    reason: str = "",
) -> ContentGeneration:
    """Record an immutable accepted/rejected reaction on completed output.

    ``reason`` is an optional rejection category from the fixed vocabulary; it
    is meaningless on an acceptance and ignored there.
    """
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
    if reason and reason not in CONTENT_FEEDBACK_REASONS:
        raise ValueError("unknown content feedback reason")
    if row.status != TASK_STATUS_SUCCEEDED or not row.output_text:
        raise ValueError("only completed content can be reviewed")
    if row.feedback is not None and row.feedback != feedback:
        raise ValueError("content feedback cannot be changed once recorded")
    if row.feedback == feedback:
        await session.commit()
        return row
    row.feedback = feedback
    row.feedback_reason = reason if feedback == FEEDBACK_REJECTED else ""
    row.feedback_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    return row
