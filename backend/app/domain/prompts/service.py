# Prompt-set + prompt service (workspace-scoped through the project).
#
# A prompt set belongs to a project, which is workspace-scoped, so every query
# joins through ``Project`` and filters by ``workspace_id`` (invariant 5). The
# service owns manual create + CSV bulk import + review-status transitions;
# AI generation lives in ``generation.py``.
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.entitlements import KEY_PROMPT_SLOTS
from app.core.config.projects import (
    PROMPT_ORIGIN_GENERATED,
    PROMPT_ORIGIN_IMPORTED,
    PROMPT_ORIGIN_MANUAL,
)
from app.core.config.prompts import PROMPT_STATUS_ACTIVE
from app.domain.entitlements.enforcement import (
    enforce_occupancy,
    lock_workspace_capacity,
)
from app.domain.projects.normalization import normalize_intent
from app.domain.prompts.locks import acquire_project_lock, acquire_prompt_set_lock
from app.domain.prompts.normalization import prompt_text_hash
from app.domain.prompts.receipts import verify_prompt_receipt
from app.domain.prompts.topical_binding import (
    BINDING_FAILURE_MESSAGES,
    TopicalBindingError,
    enforce_prompt_binding,
    load_project_vocabulary,
    validate_prompt_binding,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic


class PromptSetNotFoundError(LookupError):
    """Raised when a prompt set is missing or not in the caller's workspace."""


class PromptNotFoundError(LookupError):
    """Raised when a prompt is missing or not in the caller's workspace."""


class TopicNotFoundError(LookupError):
    """Raised when a topic is missing, cross-workspace, or not in the prompt's
    own project (a prompt can only be filed under a topic of its own
    project)."""


class DuplicatePromptError(ValueError):
    """Raised when a prompt's normalized text already exists in the set."""


# --------------------------------------------------------------------------
# Topical binding enforcement (validator lives in topical_binding.py)
# --------------------------------------------------------------------------
async def _enforce_activation_binding(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    prompt_ids: list[uuid.UUID],
    status: str,
) -> None:
    """Binding gate for any transition into active measurement eligibility.

    A transition INTO ``active`` (the audit-eligible status) re-validates
    every targeted prompt against the project vocabulary, so stale or
    bypassed content can never be promoted. Any failure rejects the whole
    bulk request before the scoped UPDATE runs (nothing is transitioned).
    Other statuses (archive) are not admissions and skip the gate.
    """
    if status != PROMPT_STATUS_ACTIVE:
        return
    rows = (
        await session.execute(
            select(Prompt.id, Prompt.text).where(
                Prompt.prompt_set_id == prompt_set_id,
                Prompt.id.in_(prompt_ids),
            )
        )
    ).all()
    vocabulary = await load_project_vocabulary(
        session, workspace_id=workspace_id, project_id=project_id
    )
    failures = []
    for row in rows:
        result = validate_prompt_binding(row.text or "", vocabulary)
        if not result.accepted:
            failures.append(
                {
                    "prompt_id": str(row.id),
                    "code": result.code,
                    "message": BINDING_FAILURE_MESSAGES[result.code],
                }
            )
    if failures:
        raise TopicalBindingError(
            f"{len(failures)} prompt(s) fail topical binding and cannot be activated",
            code=failures[0]["code"],
            details={"prompts": failures},
        )


async def _enforce_import_binding(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    texts: Sequence[str],
) -> None:
    """Per-row binding gate for CSV import (atomic: all rows or none).

    Every non-empty row must bind to the project vocabulary. Failures are
    collected per row and raised together BEFORE any insert or occupancy
    charge, so an invalid import inserts NO rows and the caller gets the
    row-specific reasons.
    """
    vocabulary = await load_project_vocabulary(
        session, workspace_id=workspace_id, project_id=project_id
    )
    # Mixed value types (``row`` is an int), so the entry type is spelled out —
    # otherwise the inferred value type is the common supertype and ``code``
    # comes back too wide to pass on as the error's code.
    failures: list[dict[str, Any]] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        result = validate_prompt_binding(text, vocabulary)
        if not result.accepted:
            failures.append(
                {
                    "row": index,
                    "code": result.code,
                    "message": BINDING_FAILURE_MESSAGES[result.code],
                }
            )
    if failures:
        raise TopicalBindingError(
            f"{len(failures)} imported prompt row(s) fail topical binding; "
            "no rows were imported",
            code=failures[0]["code"],
            details={"rows": failures},
        )


async def _prompt_set_project_id(
    session: AsyncSession, prompt_set_id: uuid.UUID
) -> uuid.UUID:
    """The set's project id, read as a scalar column (no ORM row materialized).

    Deliberately NOT read off a loaded ``PromptSet``: holding that instance
    would pin its already-loaded prompts collection in the identity map and the
    caller's post-write refresh would serve the stale collection (see the note
    in ``import_prompts``). A missing row means the set was deleted between the
    scope check and here, which is the same 404 the scope check raises.
    """
    project_id = await session.scalar(
        select(PromptSet.project_id).where(PromptSet.id == prompt_set_id)
    )
    if project_id is None:
        raise PromptSetNotFoundError("Prompt set not found")
    return project_id


async def _project_in_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    result = await session.execute(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise PromptSetNotFoundError("Project not found")
    return project


async def _get_prompt_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> PromptSet:
    """Resolve a prompt set (+ its prompts), enforcing workspace scope."""
    result = await session.execute(
        select(PromptSet)
        .join(Project, Project.id == PromptSet.project_id)
        .options(selectinload(PromptSet.prompts))
        .where(
            PromptSet.id == prompt_set_id,
            Project.workspace_id == workspace_id,
        )
    )
    prompt_set = result.scalars().unique().one_or_none()
    if prompt_set is None:
        raise PromptSetNotFoundError("Prompt set not found")
    return prompt_set


# --------------------------------------------------------------------------
# Prompt sets
# --------------------------------------------------------------------------
async def create_prompt_set(
    session: AsyncSession, *, workspace_id: uuid.UUID, payload: Any
) -> PromptSet:
    await _project_in_workspace(
        session, workspace_id=workspace_id, project_id=payload.project_id
    )
    prompt_set = PromptSet(
        project_id=payload.project_id,
        name=payload.name,
        description=payload.description,
    )
    session.add(prompt_set)
    await session.commit()
    return await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set.id
    )


async def list_prompt_sets(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
) -> list[PromptSet]:
    stmt = (
        select(PromptSet)
        .join(Project, Project.id == PromptSet.project_id)
        .options(selectinload(PromptSet.prompts))
        .where(Project.workspace_id == workspace_id)
        .order_by(PromptSet.created_at.desc())
    )
    if project_id is not None:
        stmt = stmt.where(PromptSet.project_id == project_id)
    result = await session.execute(stmt)
    return list(result.scalars().unique().all())


async def get_prompt_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> PromptSet:
    return await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )


async def update_prompt_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    payload: Any,
) -> PromptSet:
    prompt_set = await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        prompt_set.name = data["name"]
    if data.get("description") is not None:
        prompt_set.description = data["description"]
    await session.commit()
    return await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )


async def delete_prompt_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> None:
    prompt_set = await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    # Serialize against a concurrent generation for this set (which acquires
    # the same locks in the same order: project first, then set) so a delete
    # can't interleave between generation's re-resolution and its inserts.
    await acquire_project_lock(session, prompt_set.project_id)
    await acquire_prompt_set_lock(session, prompt_set_id)
    await session.delete(prompt_set)
    await session.commit()


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
async def prepare_prompt_inserts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    texts: Sequence[str],
) -> frozenset[str]:
    """Capacity-checked insert plan for candidate prompt texts.

    The ONE shared gate for every prompt-insert path (manual create, CSV
    import, AI-generation persistence). Under the account-capacity advisory
    lock: intra-request duplicates are removed, hashes already persisted in
    the set are queried, and ONLY the rows that can actually insert are
    charged against the account's ``prompt_slots`` allowance — a duplicate
    never consumes a slot, and the comparison runs in the same transaction
    as the inserts so concurrent writers can never exceed the grant. Returns
    the normalized hashes approved for insert; the per-set uniqueness
    constraint stays the final race guard.
    """
    unique_hashes = list(
        dict.fromkeys(prompt_text_hash(text) for text in texts if text.strip())
    )
    if not unique_hashes:
        return frozenset()
    account_id = await lock_workspace_capacity(session, workspace_id)
    existing = set(
        (
            await session.execute(
                select(Prompt.normalized_text_hash).where(
                    Prompt.prompt_set_id == prompt_set_id,
                    Prompt.normalized_text_hash.in_(unique_hashes),
                )
            )
        )
        .scalars()
        .all()
    )
    approved = frozenset(h for h in unique_hashes if h not in existing)
    await enforce_occupancy(
        session,
        account_id=account_id,
        key=KEY_PROMPT_SLOTS,
        requested_delta=len(approved),
        at=datetime.now(UTC),
    )
    return approved


def _receipt_proves_generated(
    payload: Any,
    text: str,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> bool:
    """Whether a backend receipt proves generation provenance for ``text``."""
    claimed_generated = getattr(payload, "origin", PROMPT_ORIGIN_MANUAL) == (
        PROMPT_ORIGIN_GENERATED
    )
    return claimed_generated and verify_prompt_receipt(
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        cohort=str(getattr(payload, "cohort", "")),
        text=text,
        receipt=getattr(payload, "generation_receipt", None),
    )


async def _resolve_origin_through_binding_gate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set: PromptSet,
    payload: Any,
    text: str,
) -> str:
    """Validate relevance for every prompt, then resolve provenance."""
    # A valid backend-issued receipt proves the text already passed the
    # generation pipeline's evidence and cohort validation. Free text still
    # binds against the PERSISTED topic, never the request body's theme.
    # (free text the caller chooses — binding against it would let any
    # client supply its own prompt's wording as the vocabulary).
    if _receipt_proves_generated(
        payload,
        text,
        workspace_id=workspace_id,
        project_id=prompt_set.project_id,
        prompt_set_id=prompt_set.id,
    ):
        return PROMPT_ORIGIN_GENERATED
    await enforce_prompt_binding(
        session,
        workspace_id=workspace_id,
        project_id=prompt_set.project_id,
        text=text,
        topic_text=await _scoped_topic_text(
            session,
            workspace_id=workspace_id,
            prompt_set_id=payload.prompt_set_id,
            topic_id=getattr(payload, "topic_id", None),
        ),
    )
    return PROMPT_ORIGIN_MANUAL


def _require_insertable(approved: frozenset[str], text_hash: str) -> None:
    """A single-create candidate the plan did not approve is a duplicate."""
    if text_hash not in approved:
        raise DuplicatePromptError("An equivalent prompt already exists in this set")


async def list_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> list[Prompt]:
    prompt_set = await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    return list(prompt_set.prompts)


async def create_prompt(
    session: AsyncSession, *, workspace_id: uuid.UUID, payload: Any
) -> Prompt:
    prompt_set = await _get_prompt_set(
        session,
        workspace_id=workspace_id,
        prompt_set_id=payload.prompt_set_id,
    )
    text = payload.text.strip()
    origin = await _resolve_origin_through_binding_gate(
        session,
        workspace_id=workspace_id,
        prompt_set=prompt_set,
        payload=payload,
        text=text,
    )
    # normalized_text_hash is set by the Prompt model's @validates("text") hook.
    prompt = Prompt(
        prompt_set_id=payload.prompt_set_id,
        text=text,
        theme=payload.theme.strip(),
        intent=normalize_intent(payload.intent),
        cohort=payload.cohort,
        branded=payload.cohort == "comparison",
        enabled=payload.enabled,
        origin=origin,
    )
    # Same scope rule as the update path: a topic must belong to the prompt's
    # own project. Validated before the insert so a cross-scope topic is a 404
    # rather than an FK violation surfacing as a 500.
    topic_id = getattr(payload, "topic_id", None)
    if topic_id is not None:
        await _validate_topic_scope(
            session,
            workspace_id=workspace_id,
            prompt=prompt,
            topic_id=topic_id,
        )
        prompt.topic_id = topic_id
    # Occupancy + duplicate plan under the account lock; the DB uniqueness
    # constraint below stays the final race guard.
    approved = await prepare_prompt_inserts(
        session,
        workspace_id=workspace_id,
        prompt_set_id=payload.prompt_set_id,
        texts=[text],
    )
    _require_insertable(approved, prompt.normalized_text_hash)
    session.add(prompt)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePromptError(
            "An equivalent prompt already exists in this set"
        ) from exc
    await session.refresh(prompt)
    return prompt


async def _get_prompt(
    session: AsyncSession, *, workspace_id: uuid.UUID, prompt_id: uuid.UUID
) -> Prompt:
    result = await session.execute(
        select(Prompt)
        .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
        .join(Project, Project.id == PromptSet.project_id)
        .where(
            Prompt.id == prompt_id,
            Project.workspace_id == workspace_id,
        )
    )
    prompt = result.scalar_one_or_none()
    if prompt is None:
        raise PromptNotFoundError("Prompt not found")
    return prompt


async def _scoped_topic_text(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    topic_id: uuid.UUID | None,
) -> str:
    """Persisted name + description of ``topic_id``, scoped to the set's project.

    Returns "" when no topic is referenced or it is out of scope. This is the
    ONLY admissible source of topic text for binding: the request body's
    ``theme`` is a free-text string the caller chooses, so binding against it
    would let any client widen the vocabulary with its own prompt's wording and
    defeat the gate entirely.
    """
    if topic_id is None:
        return ""
    row = (
        await session.execute(
            select(Topic.name, Topic.description)
            .join(Project, Project.id == Topic.project_id)
            .join(PromptSet, PromptSet.project_id == Project.id)
            .where(
                Topic.id == topic_id,
                PromptSet.id == prompt_set_id,
                Project.workspace_id == workspace_id,
            )
        )
    ).one_or_none()
    if row is None:
        return ""
    return " ".join(part for part in (row.name, row.description) if part)


async def _validate_topic_scope(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt: Prompt,
    topic_id: uuid.UUID | None,
) -> None:
    """Ensure ``topic_id`` names a topic of the prompt's own project.

    A prompt may only be filed under a topic that belongs to the same project
    as the prompt's set (topics are per-project, and projects are
    workspace-scoped, invariant 5). ``None`` (detach) is always allowed.
    Anything else — an unknown topic, a topic in a sibling project, or a topic
    in another workspace — raises ``TopicNotFoundError`` (404 at the API
    layer, no existence oracle) instead of committing a cross-scope FK.
    """
    if topic_id is None:
        return
    result = await session.execute(
        select(Topic.id)
        .join(Project, Project.id == Topic.project_id)
        .join(PromptSet, PromptSet.project_id == Project.id)
        .where(
            Topic.id == topic_id,
            PromptSet.id == prompt.prompt_set_id,
            Project.workspace_id == workspace_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise TopicNotFoundError("Topic not found in this prompt's project")


async def _enforce_update_binding(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt: Prompt,
    data: dict[str, Any],
) -> None:
    """Binding gate for the update path (text edits + activation transitions).

    Re-validates when the text is being replaced OR the prompt is
    transitioning INTO ``active`` — against the text it would carry after
    the update — so an off-domain edit or a stale prompt can never
    become audit-eligible. Raises BEFORE any field is mutated.
    """
    new_text = data.get("text")
    activates = (
        data.get("status") == PROMPT_STATUS_ACTIVE
        and prompt.status != PROMPT_STATUS_ACTIVE
    )
    if new_text is None and not activates:
        return
    project_id = await _prompt_set_project_id(session, prompt.prompt_set_id)
    text = (new_text if new_text is not None else prompt.text).strip()
    await enforce_prompt_binding(
        session, workspace_id=workspace_id, project_id=project_id, text=text
    )


async def update_prompt(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_id: uuid.UUID,
    payload: Any,
) -> Prompt:
    prompt = await _get_prompt(session, workspace_id=workspace_id, prompt_id=prompt_id)
    data = payload.model_dump(exclude_unset=True)
    await _enforce_update_binding(
        session, workspace_id=workspace_id, prompt=prompt, data=data
    )
    if data.get("text") is not None:
        prompt.text = data["text"].strip()
    if data.get("theme") is not None:
        prompt.theme = data["theme"].strip()
    if "intent" in data and data["intent"] is not None:
        prompt.intent = normalize_intent(data["intent"])
    if data.get("cohort") is not None:
        prompt.cohort = data["cohort"]
        prompt.branded = data["cohort"] == "comparison"
    if data.get("enabled") is not None:
        prompt.enabled = data["enabled"]
    if data.get("status") is not None:
        prompt.status = data["status"]
    if "topic_id" in data:
        await _validate_topic_scope(
            session,
            workspace_id=workspace_id,
            prompt=prompt,
            topic_id=data["topic_id"],
        )
        prompt.topic_id = data["topic_id"]
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePromptError(
            "An equivalent prompt already exists in this set"
        ) from exc
    await session.refresh(prompt)
    return prompt


async def delete_prompt(
    session: AsyncSession, *, workspace_id: uuid.UUID, prompt_id: uuid.UUID
) -> None:
    prompt = await _get_prompt(session, workspace_id=workspace_id, prompt_id=prompt_id)
    await session.delete(prompt)
    await session.commit()


def _import_texts(rows: Sequence[Any]) -> list[str]:
    """Strip every row's text (empty strings are filtered downstream)."""
    return [str(row.text or "").strip() for row in rows]


async def _insert_imported_row(
    session: AsyncSession, *, prompt_set_id: uuid.UUID, row: Any, text: str
) -> None:
    """Persist one capacity-approved import row as ``imported``.

    ``ON CONFLICT DO NOTHING`` on the per-set hash constraint stays the
    final race guard — a duplicate is dropped by the DB, never a failure.
    """
    stmt = (
        pg_insert(Prompt)
        .values(
            id=uuid.uuid4(),
            prompt_set_id=prompt_set_id,
            text=text,
            normalized_text_hash=prompt_text_hash(text),
            theme=str(row.theme or "").strip(),
            intent=normalize_intent(row.intent),
            branded=row.cohort == "comparison",
            enabled=bool(row.enabled),
            origin=PROMPT_ORIGIN_IMPORTED,
        )
        .on_conflict_do_nothing(constraint="uq_prompt_set_normalized_text")
    )
    await session.execute(stmt)


async def import_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    rows: list[Any],
) -> PromptSet:
    """CSV bulk-create: persist already-parsed prompt rows as ``imported``.

    Rows with empty text are skipped; intents are casefolded + validated.
    Duplicates (same normalized text as an existing prompt in the set, or a
    repeat within the upload) are dropped — never a request failure — and
    are filtered BEFORE occupancy is charged, so a duplicate never consumes
    a ``prompt_slots`` slot. Every non-empty row must pass topical binding:
    row-specific failures are raised together and, since the import is
    atomic, an invalid upload inserts NO rows. The insert runs under the
    account-capacity lock; the whole import is atomic, so an over-allowance
    upload inserts nothing either. Returns the refreshed prompt set (with
    all prompts) so the caller can project the whole set back — matching
    the frontend import contract.
    """
    # NOTE: the scope check's result is deliberately DISCARDED (never held in
    # a local): keeping the instance alive would pin it in the identity map
    # with its already-loaded (empty) prompts collection, and the refresh at
    # the end of the import would serve that stale collection. The binding
    # gate reads the project id through a scalar column select instead, which
    # materializes no ORM instance.
    await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    project_id = await _prompt_set_project_id(session, prompt_set_id)
    texts = _import_texts(rows)
    await _enforce_import_binding(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        texts=texts,
    )
    approved = await prepare_prompt_inserts(
        session,
        workspace_id=workspace_id,
        prompt_set_id=prompt_set_id,
        texts=texts,
    )
    for row, text in zip(rows, texts, strict=True):
        if text and prompt_text_hash(text) in approved:
            await _insert_imported_row(
                session, prompt_set_id=prompt_set_id, row=row, text=text
            )
    await session.commit()
    return await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )


async def bulk_set_status(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    prompt_ids: list[uuid.UUID],
    status: str,
) -> PromptSet:
    """Review transition for many prompts at once (accept-all / archive).

    Scoped to one set: ids outside the set (or workspace) are rejected as a
    whole so the caller never silently transitions fewer prompts than asked.
    A transition INTO ``active`` first passes the topical-binding gate
    (off-domain or unbound prompts are never promoted; the whole request
    fails before any write). The scoped UPDATE runs first and its rowcount
    is compared to the request (no check-then-act window); on any mismatch
    we raise before committing, so no partial transition ever persists.
    """
    # Discarded scope check (see import_prompts: holding the instance pins a
    # stale prompts collection for the post-transition refresh); the binding
    # gate gets the project id from a scalar column select instead.
    await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    project_id = await _prompt_set_project_id(session, prompt_set_id)
    await _enforce_activation_binding(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        prompt_ids=prompt_ids,
        status=status,
    )
    result = await session.execute(
        sa_update(Prompt)
        .where(Prompt.prompt_set_id == prompt_set_id, Prompt.id.in_(prompt_ids))
        .values(status=status)
    )
    # An UPDATE always yields a CursorResult (which has rowcount); the broad
    # ``Result`` annotation on ``execute`` hides that.
    if cast(CursorResult[Any], result).rowcount != len(set(prompt_ids)):
        await session.rollback()
        raise PromptNotFoundError("Prompt(s) not found in this set")
    await session.commit()
    return await _get_prompt_set(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
