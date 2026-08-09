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
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.abuse import abuse_settings
from app.core.config.content import (
    CONTENT_GENERATOR_VERSION,
    CONTENT_KNOWN_PROVIDERS,
    CONTENT_LIST_MAX_LIMIT,
    CONTEXT_STATUS_DISABLED,
    CONTEXT_STATUS_INCLUDED,
    FEEDBACK_ACCEPTED,
    FEEDBACK_REJECTED,
    content_settings,
)
from app.core.config.content_intelligence import (
    CONTENT_SKILL_CATALOG,
    CONTENT_VALIDATOR_VERSION,
    ContentSkillDefinition,
)
from app.core.config.task_queue import (
    TASK_ACTIVE_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.abuse.service import reserve_workspace_capacity
from app.domain.content.intelligence import build_task_context, get_brief
from app.domain.content.message_builder import build_messages
from app.domain.content.schemas import (
    ContentGenerationDetail,
    ContentGenerationListItem,
    WebsiteContextSummary,
    prompt_preview,
)
from app.domain.content.website_context import (
    WebsiteContext,
    build_website_context,
)
from app.models.content import ContentBrief, ContentGeneration, TaskContextPackage
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
    website_context_enabled: bool,
    skill_id: str = "article",
    opportunity_id: uuid.UUID | None = None,
    brief_id: uuid.UUID | None = None,
    context_manifest_hash: str = "",
) -> str:
    """Stable comparator for idempotency replay-vs-conflict decisions."""
    canonical = "\x1f".join(
        [
            str(project_id),
            prompt.strip(),
            output_type,
            skill_id,
            _optional_uuid(opportunity_id),
            _optional_uuid(brief_id),
            context_manifest_hash,
            "1" if website_context_enabled else "0",
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


def _summary_dto(row: ContentGeneration) -> WebsiteContextSummary | None:
    summary = _persisted_crawl_summary(row)
    if summary is None:
        return None
    return WebsiteContextSummary(
        crawl_id=str(summary.get("crawl_id", "")),
        crawl_completed_at=summary.get("crawl_completed_at"),
        extractor_version=summary.get("extractor_version", ""),
        analyzer_version=summary.get("analyzer_version", ""),
        page_count=int(summary.get("page_count", 0)),
        char_count=int(summary.get("char_count", 0)),
        site_url_ids=list(summary.get("site_url_ids", [])),
        artifact_ids=list(summary.get("artifact_ids", [])),
        content_hashes=list(summary.get("content_hashes", [])),
    )


def _persisted_crawl_summary(row: ContentGeneration) -> dict | None:
    summary = (row.website_context_snapshot or {}).get("summary")
    if not summary or not summary.get("crawl_id"):
        return None
    return summary


def to_list_item(row: ContentGeneration) -> ContentGenerationListItem:
    item = ContentGenerationListItem.model_validate(row)
    item.prompt_preview = prompt_preview(row.prompt)
    return item


def to_detail(row: ContentGeneration) -> ContentGenerationDetail:
    detail = ContentGenerationDetail.model_validate(row)
    detail.prompt_preview = prompt_preview(row.prompt)
    detail.website_context_summary = _summary_dto(row)
    return detail


async def _insert_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    output_type: str,
    website_context_enabled: bool,
    website_context: WebsiteContext,
    idempotency_key: str,
    fingerprint: str,
    skill_id: str = "article",
    opportunity_id: uuid.UUID | None = None,
    evidence_context: dict | None = None,
    brief_id: uuid.UUID | None = None,
    context_package_id: uuid.UUID | None = None,
    skill_version: str = "content-v1",
    validator_snapshot: dict | None = None,
) -> ContentGeneration:
    messages, digest, message_snapshot = build_messages(
        prompt=prompt,
        output_type=output_type,
        website_context=website_context,
        skill_id=skill_id,
        evidence_context=evidence_context,
    )
    # ``messages`` itself is never persisted — the worker rebuilds it from the
    # frozen prompt + snapshot; only the digest + safe snapshot are stored.
    del messages
    row = ContentGeneration(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=opportunity_id,
        brief_id=brief_id,
        context_package_id=context_package_id,
        prompt=prompt,
        skill_id=skill_id,
        skill_version=skill_version,
        evidence_context=evidence_context,
        output_type=output_type,
        website_context_enabled=website_context_enabled,
        website_context_status=website_context.status,
        website_context_snapshot=website_context.snapshot(),
        request_fingerprint=fingerprint,
        message_digest=digest,
        message_snapshot=message_snapshot,
        idempotency_key=idempotency_key,
        provider=content_settings.provider,
        requested_model=content_settings.model,
        generator_version=CONTENT_GENERATOR_VERSION,
        validator_snapshot=validator_snapshot,
    )
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


@dataclass(frozen=True)
class _PreparedGeneration:
    prompt: str
    evidence_context: dict | None
    context_package: TaskContextPackage | None = None
    skill_version: str = "content-v1"
    validator_snapshot: dict | None = None

    @property
    def manifest_hash(self) -> str:
        if self.context_package is None:
            return ""
        return self.context_package.manifest_hash

    @property
    def context_package_id(self) -> uuid.UUID | None:
        if self.context_package is None:
            return None
        return self.context_package.id


def _skill_definition(brief: ContentBrief, skill_id: str) -> ContentSkillDefinition:
    definition = CONTENT_SKILL_CATALOG.get(skill_id)
    if definition is None or brief.kind not in definition["brief_kinds"]:
        raise ValueError("content_skill_incompatible")
    if brief.industry_pack_id not in definition["packs"]:
        raise ValueError("content_skill_pack_incompatible")
    return definition


async def _prepare_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    skill_id: str,
    opportunity_id: uuid.UUID | None,
    brief_id: uuid.UUID | None,
) -> _PreparedGeneration:
    evidence = await _opportunity_evidence(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=opportunity_id,
    )
    if brief_id is None:
        return _PreparedGeneration(prompt=prompt, evidence_context=evidence)
    brief = await get_brief(session, workspace_id=workspace_id, brief_id=brief_id)
    if brief.project_id != project_id:
        raise ContentGenerationNotFoundError("Content brief not found")
    definition = _skill_definition(brief, skill_id)
    context_package, _created = await build_task_context(
        session, workspace_id=workspace_id, brief_id=brief_id
    )
    skill_version = str(definition["version"])
    return _PreparedGeneration(
        prompt=_brief_prompt(brief),
        evidence_context=dict(context_package.rendered_context),
        context_package=context_package,
        skill_version=skill_version,
        validator_snapshot={
            "validator_version": CONTENT_VALIDATOR_VERSION,
            "skill_id": skill_id,
            "skill_version": skill_version,
            "output_format": definition["output_format"],
        },
    )


async def _select_website_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    enabled: bool,
    context_package: TaskContextPackage | None,
) -> WebsiteContext:
    if context_package is None:
        return await _generation_website_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            enabled=enabled,
        )
    return _context_package_website_context(context_package, enabled=enabled)


def _context_package_website_context(
    context_package: TaskContextPackage, *, enabled: bool
) -> WebsiteContext:
    if not enabled:
        return WebsiteContext(status=CONTEXT_STATUS_DISABLED)
    return WebsiteContext(
        status=CONTEXT_STATUS_INCLUDED,
        pages=[],
        summary={
            "crawl_id": "",
            "page_count": 0,
            "char_count": context_package.char_count,
            "task_context_package_id": str(context_package.id),
            "manifest_hash": context_package.manifest_hash,
        },
    )


async def enqueue_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    output_type: str,
    website_context_enabled: bool,
    idempotency_key: str = "",
    skill_id: str = "article",
    opportunity_id: uuid.UUID | None = None,
    brief_id: uuid.UUID | None = None,
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

    prepared = await _prepare_generation(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt=prompt,
        skill_id=skill_id,
        opportunity_id=opportunity_id,
        brief_id=brief_id,
    )
    fingerprint = request_fingerprint(
        project_id=project_id,
        prompt=prepared.prompt,
        output_type=output_type,
        website_context_enabled=website_context_enabled,
        skill_id=skill_id,
        opportunity_id=opportunity_id,
        brief_id=brief_id,
        context_manifest_hash=prepared.manifest_hash,
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

    _require_provider_configured()
    await _reserve_content_capacity(session, workspace_id=workspace_id)

    website_context = await _select_website_context(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        enabled=website_context_enabled,
        context_package=prepared.context_package,
    )

    row = await _insert_generation(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt=prepared.prompt,
        output_type=output_type,
        website_context_enabled=website_context_enabled,
        website_context=website_context,
        idempotency_key=key,
        fingerprint=fingerprint,
        skill_id=skill_id,
        opportunity_id=opportunity_id,
        evidence_context=prepared.evidence_context,
        brief_id=brief_id,
        context_package_id=prepared.context_package_id,
        skill_version=prepared.skill_version,
        validator_snapshot=prepared.validator_snapshot,
    )
    winner = await _commit_generation(
        session, workspace_id=workspace_id, key=key, fingerprint=fingerprint
    )
    if winner is not None:
        return winner, False
    await session.refresh(row)
    return row, True


def _brief_prompt(brief: ContentBrief) -> str:
    questions = list((brief.requirements or {}).get("questions") or [])
    labels = [
        str(item.get("question") or item.get("label") or item.get("question_id") or "")
        for item in questions
    ]
    return (
        f"Create {brief.kind} content for {brief.title}. "
        f"Answer only these required questions: {', '.join(filter(None, labels))}. "
        "Use only allowed facts in the supplied task context; preserve unknowns and "
        "prohibitions."
    )


async def _opportunity_evidence(session, *, workspace_id, project_id, opportunity_id):
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
    return {
        "opportunity_id": str(opportunity.id),
        "rule_id": opportunity.rule_id,
        "title": opportunity.title,
        "evidence": opportunity.evidence or {},
        "source_analysis_ids": opportunity.source_analysis_ids or [],
        "source_metric_ids": opportunity.source_metric_ids or [],
    }


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


async def _generation_website_context(session, *, workspace_id, project_id, enabled):
    if not enabled:
        return WebsiteContext(status=CONTEXT_STATUS_DISABLED)
    return await build_website_context(
        session, workspace_id=workspace_id, project_id=project_id
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
        website_context_enabled=source.website_context_enabled,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
        brief_id=source.brief_id,
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
    snapshot = source.website_context_snapshot or {}
    frozen = WebsiteContext(
        status=source.website_context_status,
        pages=list(snapshot.get("pages") or []),
        summary=snapshot.get("summary"),
    )
    fingerprint = request_fingerprint(
        project_id=source.project_id,
        prompt=source.prompt,
        output_type=source.output_type,
        website_context_enabled=source.website_context_enabled,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
        brief_id=source.brief_id,
        context_manifest_hash=_snapshot_manifest_hash(snapshot),
    )
    row = await _insert_generation(
        session,
        workspace_id=workspace_id,
        project_id=source.project_id,
        prompt=source.prompt,
        output_type=source.output_type,
        website_context_enabled=source.website_context_enabled,
        website_context=frozen,
        idempotency_key=str(uuid.uuid4()),
        fingerprint=fingerprint,
        skill_id=source.skill_id,
        opportunity_id=source.opportunity_id,
        evidence_context=source.evidence_context,
        brief_id=source.brief_id,
        context_package_id=source.context_package_id,
        skill_version=source.skill_version,
        validator_snapshot=source.validator_snapshot,
    )
    await session.commit()
    await session.refresh(row)
    return row


def _snapshot_manifest_hash(snapshot: dict) -> str:
    summary = snapshot.get("summary") or {}
    return str(summary.get("manifest_hash") or "")


async def record_feedback(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
    feedback: str,
) -> ContentGeneration:
    """Record immutable reaction metadata; saving is owned by ContentRevision."""
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
