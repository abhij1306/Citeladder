# AI prompt/topic generation service (flips the /generate 501 stub).
#
# Core and brand cohorts use the app-level default agent (``connectors/agent``)
# while Commerce derives its fixed two-prompt demo portfolio from the uploaded
# catalog without provider I/O. Suggestions persist with full
# ``generation_evidence`` provenance (invariant 4) via a conflict-safe upsert
# on the per-set normalized-text hash, so concurrent generations can never
# double-insert a concept. Validated rows enter the active portfolio directly;
# no provider measurement runs until the user explicitly runs or schedules an
# audit (the planner continues to filter status='active').
from __future__ import annotations

import hashlib
import json
import uuid
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.agent.gateway import ModelGateway
from app.core.config.projects import PROMPT_ORIGIN_GENERATED
from app.core.config.prompts import (
    COMMERCE_BUYER_DESTINATION_PROMPT_TEMPLATE,
    COMMERCE_MERCHANT_COMPARISON_PROMPT_TEMPLATE,
    GENERATOR_VERSION,
    PROMPT_NEAR_DUPLICATE_SIMILARITY,
    PROMPT_STATUS_ACTIVE,
    prompt_generation_settings,
)
from app.domain.projects.knowledge_base import build_brand_knowledge_data
from app.domain.projects.shim import project_scoring_identity
from app.domain.prompts.generation_contract import (
    GenerationOutput,
    GenerationOutputError,
    SuggestedPrompt,
    SuggestedTopic,
    build_generation_user_message,
    generation_model_call_budget,
    parse_generation_output,
)
from app.domain.prompts.generation_errors import (
    GenerationValidationError,
    reraise_scoped_integrity_error,
)
from app.domain.prompts.generation_filtering import (
    filter_for_cohort,
    generation_system_prompt,
)
from app.domain.prompts.generation_validation import validate_commerce_payload
from app.domain.prompts.locks import acquire_project_lock, acquire_prompt_set_lock
from app.domain.prompts.normalization import prompt_text_hash
from app.domain.prompts.service import PromptSetNotFoundError, prepare_prompt_inserts
from app.domain.prompts.topical_binding import (
    BindingVocabulary,
    build_project_vocabulary,
    validate_prompt_binding,
)
from app.models.brand import Brand
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic

__all__ = [
    "GenerationOutputError",
    "GenerationValidationError",
    "SuggestedPrompt",
    "SuggestedTopic",
    "build_generation_user_message",
    "generate_prompts",
    "parse_generation_output",
    "validate_generation_request",
]


def _brand_context_hash(brand_context: dict[str, Any]) -> str:
    canonical = json.dumps(brand_context, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------
async def _load_prompt_set_with_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    for_update: bool = False,
) -> PromptSet:
    stmt = (
        select(PromptSet)
        .join(Project, Project.id == PromptSet.project_id)
        .options(
            selectinload(PromptSet.prompts),
            selectinload(PromptSet.project)
            .selectinload(Project.brand)
            .selectinload(Brand.aliases),
            selectinload(PromptSet.project)
            .selectinload(Project.brand)
            .selectinload(Brand.profile),
            selectinload(PromptSet.project).selectinload(Project.competitors),
            selectinload(PromptSet.project).selectinload(Project.owned_domains),
            selectinload(PromptSet.project).selectinload(Project.unintended_domains),
            selectinload(PromptSet.project).selectinload(Project.topics),
            selectinload(PromptSet.project).selectinload(Project.products),
        )
        .where(PromptSet.id == prompt_set_id, Project.workspace_id == workspace_id)
    )
    if for_update:
        # Row-lock only the prompt-set row (never the joined project) so the
        # lock scope is minimal and the ordering — advisory lock first, then
        # this row lock — is identical to every other writer, so no deadlock.
        stmt = stmt.with_for_update(of=PromptSet)
    result = await session.execute(stmt)
    prompt_set = result.scalars().unique().one_or_none()
    if prompt_set is None:
        raise PromptSetNotFoundError("Prompt set not found")
    return prompt_set


def _prompt_count(suggestions: list[SuggestedTopic]) -> int:
    return sum(len(topic.prompts) for topic in suggestions)


def _drop_cross_batch_duplicates(
    existing: list[SuggestedTopic], incoming: list[SuggestedTopic]
) -> tuple[list[SuggestedTopic], int]:
    """Remove and count rows too similar to an earlier accepted batch."""
    previous = [
        " ".join(prompt.text.casefold().split())
        for topic in existing
        for prompt in topic.prompts
    ]
    retained: list[SuggestedTopic] = []
    dropped = 0
    for topic in incoming:
        prompts: list[SuggestedPrompt] = []
        for prompt in topic.prompts:
            normalized = " ".join(prompt.text.casefold().split())
            duplicate = any(
                SequenceMatcher(None, normalized, prior).ratio()
                >= PROMPT_NEAR_DUPLICATE_SIMILARITY
                for prior in previous
            )
            if duplicate:
                dropped += 1
            else:
                prompts.append(prompt)
        if prompts:
            retained.append(
                SuggestedTopic(
                    topic_id=topic.topic_id, name=topic.name, prompts=prompts
                )
            )
    return retained, dropped


def _resolve_target_topic(prompt_set: PromptSet, payload: Any) -> Topic | None:
    """Resolve ``payload.topic_id`` against the prompt set's project topics.

    Returns ``None`` for unscoped generation. Raises
    ``GenerationValidationError`` (422 at the API layer) when a ``topic_id`` is
    given but is not a topic of this set's project — including the case where a
    topic that existed at validation time was deleted before persistence, so a
    disappearance surfaces as a scoped 422 rather than an FK 500.
    """
    if payload.topic_id is None:
        return None
    target_topic = next(
        (t for t in prompt_set.project.topics if t.id == payload.topic_id), None
    )
    if target_topic is None:
        raise GenerationValidationError("topic_id is not a topic of this project")
    return target_topic


def _validate_generation_payload(prompt_set: PromptSet, payload: Any) -> Topic | None:
    """Bounds + topic-ownership checks (422 at the API layer).

    Returns the target topic when ``payload.topic_id`` is set.
    """
    max_count = prompt_generation_settings.max_count
    if payload.count > max_count:
        raise GenerationValidationError(
            f"count must be at most {max_count} (requested {payload.count})"
        )
    target_topic = _resolve_target_topic(prompt_set, payload)
    if payload.cohort == "commerce":
        validate_commerce_payload(prompt_set, payload, target_topic)
    if not prompt_set.project.topics:
        raise GenerationValidationError(
            "Add at least one topic before generating prompts"
        )
    return target_topic


async def validate_generation_request(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    payload: Any,
) -> PromptSet:
    """Scope + payload validation without touching the agent.

    Lets the API layer order guards as 404 -> 422 -> 503: an invalid payload
    must fail validation even when no agent is configured.
    """
    prompt_set = await _load_prompt_set_with_project(
        session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
    )
    _validate_generation_payload(prompt_set, payload)
    return prompt_set


def _cap_suggestions_to_count(
    suggestions: list[SuggestedTopic], count: int
) -> list[SuggestedTopic]:
    """Trim parsed suggestions to at most ``count`` prompts total.

    A misbehaving model can return more prompts than requested; enforce the
    cap before persistence, preserving topic grouping and response order
    (topics are truncated once the budget is spent, and an emptied topic is
    dropped).
    """
    if count <= 0:
        return []
    remaining = count
    capped: list[SuggestedTopic] = []
    for topic in suggestions:
        if remaining <= 0:
            break
        kept = topic.prompts[:remaining]
        if kept:
            capped.append(
                SuggestedTopic(topic_id=topic.topic_id, name=topic.name, prompts=kept)
            )
            remaining -= len(kept)
    return capped


def _drop_unbound_suggestions(
    suggestions: list[SuggestedTopic], vocabulary: BindingVocabulary
) -> list[SuggestedTopic]:
    """Drop suggested prompts that fail topical binding (model output is
    not trusted merely because a model produced it).

    Runs before any occupancy charge or insert: an off-domain suggestion is
    never persisted and never consumes a ``prompt_slots`` slot. Topics
    emptied by the drop are removed; when every suggestion is off-domain the
    generation persists nothing (an empty 201), matching the duplicate-drop
    sanitize semantics.
    """
    kept: list[SuggestedTopic] = []
    for topic in suggestions:
        prompts = [
            p
            for p in topic.prompts
            if validate_prompt_binding(p.text, vocabulary).accepted
        ]
        if prompts:
            kept.append(
                SuggestedTopic(
                    topic_id=topic.topic_id, name=topic.name, prompts=prompts
                )
            )
    return kept


async def _apply_insert_capacity(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    suggestions: list[SuggestedTopic],
) -> tuple[list[SuggestedTopic], int]:
    """Enforce ``prompt_slots`` occupancy on parsed suggestions.

    Runs the shared insert-capacity plan in the write transaction (after the
    project and prompt-set locks; the account-capacity lock is always the
    last lock taken), drops suggestions whose text already persists in the
    set, and raises ``OccupancyLimitExceededError`` when the rows that can
    actually insert would exceed the account allowance. Returns the
    persistable suggestions plus the count dropped as already-persisted
    duplicates (folded into the response's ``dropped_duplicates``).
    """
    texts = [prompt.text for topic in suggestions for prompt in topic.prompts]
    approved = await prepare_prompt_inserts(
        session,
        workspace_id=workspace_id,
        prompt_set_id=prompt_set_id,
        texts=texts,
    )
    kept: list[SuggestedTopic] = []
    dropped = 0
    for topic in suggestions:
        prompts = [p for p in topic.prompts if prompt_text_hash(p.text) in approved]
        dropped += len(topic.prompts) - len(prompts)
        if prompts:
            kept.append(
                SuggestedTopic(
                    topic_id=topic.topic_id, name=topic.name, prompts=prompts
                )
            )
    return kept, dropped


async def _insert_prompts_returning(
    session: AsyncSession,
    *,
    prompt_set: PromptSet,
    topic: Topic,
    prompts: list[SuggestedPrompt],
    evidence_base: dict[str, Any],
    cohort: str,
) -> tuple[list[uuid.UUID], int]:
    """Conflict-safe multi-row insert for one validated active topic batch.

    The parse step already de-duplicated texts across the whole response, so
    rows within a batch can never conflict with each other — only with
    pre-existing prompts, which ``on_conflict_do_nothing`` silently skips.
    Returns ``(inserted_ids, dropped_count)`` where dropped = rows submitted
    minus ids the DB actually returned (in submitted order).
    """
    submitted_ids: list[uuid.UUID] = [uuid.uuid4() for _ in prompts]
    rows = [
        {
            "id": submitted_ids[idx],
            "prompt_set_id": prompt_set.id,
            "topic_id": topic.id,
            "text": prompt.text,
            "normalized_text_hash": prompt_text_hash(prompt.text),
            "theme": topic.name,
            "intent": prompt.intent,
            "cohort": cohort,
            "branded": cohort in {"comparison", "brand_diagnostic"},
            "enabled": True,
            "status": PROMPT_STATUS_ACTIVE,
            "origin": PROMPT_ORIGIN_GENERATED,
            "generation_evidence": evidence_base,
        }
        for idx, prompt in enumerate(prompts)
    ]
    stmt = (
        pg_insert(Prompt)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_prompt_set_normalized_text")
        .returning(Prompt.id)
    )
    returned = set((await session.execute(stmt)).scalars().all())
    # Preserve deterministic response order: keep submitted order, drop the
    # ids the DB rejected as conflicts.
    inserted_ids = [pid for pid in submitted_ids if pid in returned]
    return inserted_ids, len(rows) - len(inserted_ids)


async def _load_demand_grounding(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int,
) -> tuple[DemandSnapshot | None, list[DemandSignal]]:
    snapshot = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, []
    signals = list(
        (
            await session.scalars(
                select(DemandSignal)
                .where(
                    DemandSignal.workspace_id == workspace_id,
                    DemandSignal.project_id == project_id,
                    DemandSignal.snapshot_id == snapshot.id,
                )
                .order_by(
                    DemandSignal.priority_score.desc().nullslast(), DemandSignal.id
                )
                .limit(limit)
            )
        ).all()
    )
    return snapshot, signals


def _project_business_context(project: Project) -> dict[str, Any]:
    """The confirmed business facets, which live on the brand profile.

    `project_scoring_identity` is the scorer's projection and deliberately does
    not carry them; prompt generation needs `business_model` to pick the buyer
    register its exemplars demonstrate.
    """
    profile = project.brand.profile if project.brand is not None else None
    return dict(getattr(profile, "business_context", None) or {})


def _generation_brand_context(
    project: Project, demand_signals: list[DemandSignal]
) -> dict[str, Any]:
    context = project_scoring_identity(project)
    context["knowledge_base"] = build_brand_knowledge_data(project)
    context["business_context"] = _project_business_context(project)
    context["demand_signals"] = [
        {
            "id": str(signal.id),
            "type": signal.signal_type,
            "topic": signal.topic_cluster,
            "page": signal.page_url,
            "priority": signal.priority_score,
            "limitations": list(signal.limitations or []),
        }
        for signal in demand_signals
    ]
    context["commerce_products"] = [
        {
            "id": str(product.id),
            "sku": product.sku,
            "name": product.name,
            "aliases": list(product.aliases or []),
            "brand": str((product.attributes or {}).get("brand") or ""),
            "category": str((product.attributes or {}).get("category") or ""),
            "url": product.url,
        }
        for product in project.products
    ]
    return context


def _generation_evidence(
    *,
    agent: ModelGateway | None,
    payload: Any,
    brand_context: dict[str, Any],
    demand_snapshot: DemandSnapshot | None,
    demand_signals: list[DemandSignal],
) -> dict[str, Any]:
    return {
        "generation_mode": "deterministic" if agent is None else "model",
        "model_identity": (
            {
                "transport_host": agent.base_url_host,
                "transport_model": agent.model,
            }
            if agent is not None
            else None
        ),
        "generation_run_id": str(uuid.uuid4()),
        "generator_version": GENERATOR_VERSION,
        "brand_context_hash": _brand_context_hash(brand_context),
        "requested_count": payload.count,
        "requested_intents": [intent for intent in payload.intents if intent],
        "cohort": payload.cohort,
        "demand_snapshot_id": str(demand_snapshot.id) if demand_snapshot else None,
        "demand_signal_ids": [str(signal.id) for signal in demand_signals],
        "demand_signal_coverage": (
            dict(demand_snapshot.coverage or {}) if demand_snapshot else {}
        ),
    }


def _allowed_generation_topics(
    project: Project, target_topic: Topic | None
) -> list[dict[str, str]]:
    topics = [target_topic] if target_topic is not None else project.topics
    return [
        {
            "id": str(topic.id),
            "name": topic.name,
            "description": topic.description or "",
        }
        for topic in topics
    ]


def _existing_generation_context(
    prompt_set: PromptSet,
    suggestions: list[SuggestedTopic],
    *,
    limit: int,
) -> list[str]:
    if not limit:
        return []
    existing = [prompt.text for prompt in prompt_set.prompts]
    accumulated = [prompt.text for topic in suggestions for prompt in topic.prompts]
    return [*existing, *accumulated][-limit:]


def _deterministic_commerce_suggestions(
    allowed_topics: list[dict[str, str]],
    brand_context: dict[str, Any],
) -> list[SuggestedTopic]:
    """Build one named buyer-destination pair per product in the category."""
    topic = allowed_topics[0]
    category = topic["name"].strip()
    products = sorted(
        (
            product
            for product in brand_context.get("commerce_products", [])
            if str(product.get("category") or "").strip().casefold()
            == category.casefold()
        ),
        key=lambda product: (
            str(product.get("name") or "").casefold(),
            str(product.get("sku") or "").casefold(),
        ),
    )
    return [
        SuggestedTopic(
            topic_id=uuid.UUID(topic["id"]),
            name=category,
            prompts=[
                prompt
                for product in products
                for prompt in (
                    SuggestedPrompt(
                        text=COMMERCE_BUYER_DESTINATION_PROMPT_TEMPLATE.format(
                            product_name=str(product["name"]).strip()
                        ),
                        intent="discovery",
                    ),
                    SuggestedPrompt(
                        text=COMMERCE_MERCHANT_COMPARISON_PROMPT_TEMPLATE.format(
                            product_name=str(product["name"]).strip(),
                            category=category.casefold(),
                        ),
                        intent="comparison",
                    ),
                )
            ],
        )
    ]


async def _generate_suggestions(
    session: AsyncSession,
    *,
    prompt_set: PromptSet,
    payload: Any,
    agent: ModelGateway | None,
    workspace_id: uuid.UUID,
) -> tuple[
    list[SuggestedTopic],
    int,
    dict[str, Any],
    DemandSnapshot | None,
    list[DemandSignal],
]:
    target_topic = _resolve_target_topic(prompt_set, payload)
    demand_snapshot, demand_signals = await _load_demand_grounding(
        session,
        workspace_id=workspace_id,
        project_id=prompt_set.project.id,
        limit=payload.count,
    )
    brand_context = _generation_brand_context(prompt_set.project, demand_signals)
    context_limit = prompt_generation_settings.existing_prompt_context_limit
    allowed_topics = _allowed_generation_topics(prompt_set.project, target_topic)
    await session.commit()
    if payload.cohort == "commerce":
        return (
            _deterministic_commerce_suggestions(allowed_topics, brand_context),
            0,
            brand_context,
            demand_snapshot,
            demand_signals,
        )
    if agent is None:
        raise GenerationOutputError("Model gateway is required for this cohort")
    system_prompt = generation_system_prompt(payload.cohort, brand_context)
    suggestions: list[SuggestedTopic] = []
    intra_duplicates = 0
    batch_size = min(prompt_generation_settings.model_batch_size, payload.count)
    maximum_calls = generation_model_call_budget(payload.count)
    for _call in range(maximum_calls):
        missing = payload.count - _prompt_count(suggestions)
        if missing <= 0:
            break
        requested = min(batch_size, missing)
        user_message = build_generation_user_message(
            brand_context=brand_context,
            topics=allowed_topics,
            existing_prompts=_existing_generation_context(
                prompt_set, suggestions, limit=context_limit
            ),
            count=requested,
            intents=[i for i in payload.intents if i],
        )
        raw = await agent.complete_structured_json(
            system=system_prompt,
            user=user_message,
            schema_name="prompt_generation",
            schema=GenerationOutput.model_json_schema(),
        )
        batch, batch_duplicates = parse_generation_output(
            raw,
            allowed_topics=allowed_topics,
            fallback_intents=tuple(i for i in payload.intents if i),
        )
        intra_duplicates += batch_duplicates
        batch = filter_for_cohort(batch, payload.cohort, brand_context)
        batch, cross_batch_duplicates = _drop_cross_batch_duplicates(suggestions, batch)
        intra_duplicates += cross_batch_duplicates
        suggestions.extend(batch)
    capped = _cap_suggestions_to_count(suggestions, payload.count)
    return (
        capped,
        intra_duplicates,
        brand_context,
        demand_snapshot,
        demand_signals,
    )


async def generate_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    payload: Any,
    agent: ModelGateway | None,
    prompt_set: PromptSet | None = None,
) -> tuple[list[Prompt], list[Topic], int]:
    """Generate topic-organized prompt suggestions into the set.

    Returns ``(inserted_prompts, touched_topics, dropped_duplicate_count)``.
    Caller (the API layer) resolves the agent client for model-backed cohorts;
    Commerce passes ``None`` because its prompts are derived from the catalog.
    ``prompt_set`` may be passed pre-loaded (from
    ``validate_generation_request``) to avoid a second scope query; the
    payload checks always re-run here so direct service calls stay guarded.

    Every validated generated prompt is active immediately. Running or
    scheduling an audit remains the explicit measurement decision; generation
    never initiates provider measurement.
    """
    # Scope first (404 before anything runs), then confirmation + bounds.
    if prompt_set is None:
        prompt_set = await _load_prompt_set_with_project(
            session, workspace_id=workspace_id, prompt_set_id=prompt_set_id
        )
    _validate_generation_payload(prompt_set, payload)
    project_id = prompt_set.project.id
    (
        suggestions,
        intra_duplicates,
        brand_context,
        demand_snapshot,
        demand_signals,
    ) = await _generate_suggestions(
        session,
        prompt_set=prompt_set,
        payload=payload,
        agent=agent,
        workspace_id=workspace_id,
    )

    # 4. Re-open the write transaction. The objects loaded before the provider
    #    call are now stale (the set/project/topic could have been renamed or
    #    deleted mid-request), so acquire the SHARED prompt-set advisory lock
    #    (the same one the delete paths take) and then re-resolve everything
    #    fresh, row-locking the set. Deletes block on the advisory lock until we
    #    commit, so nothing can vanish between re-resolution and insertion. A
    #    disappearance that slipped in before we took the lock maps to the same
    #    scoped domain errors the endpoint already handles (404 / 422) — and an
    #    FK violation at insert (belt-and-suspenders) is mapped the same way,
    #    never an unhandled 500.
    #
    #    Lock order is fixed everywhere to preclude deadlock: PROJECT lock
    #    first (serializes topic deletes), then the PROMPT-SET lock.
    await acquire_project_lock(session, project_id)
    await acquire_prompt_set_lock(session, prompt_set_id)
    # Drop every identity-map instance loaded in the pre-provider transaction so
    # the re-resolution below reads committed state from the DB. Without this the
    # selectin-loaded ``project.topics`` collection can be served from the stale
    # identity map, letting a topic deleted mid-request appear to still exist.
    session.expire_all()
    prompt_set = await _load_prompt_set_with_project(
        session,
        workspace_id=workspace_id,
        prompt_set_id=prompt_set_id,
        for_update=True,
    )
    _resolve_target_topic(prompt_set, payload)
    project = prompt_set.project
    topics_by_id = {topic.id: topic for topic in project.topics}

    # 5. Persist prompts only under topics that still exist after provider I/O.
    evidence_base = _generation_evidence(
        agent=agent,
        payload=payload,
        brand_context=brand_context,
        demand_snapshot=demand_snapshot,
        demand_signals=demand_signals,
    )

    try:
        # Topical binding gate: generated text is not trusted merely because
        # a model produced it — off-domain suggestions are dropped before any
        # occupancy charge or insert (empty vocabulary fails closed).
        suggestions = _drop_unbound_suggestions(
            suggestions, build_project_vocabulary(project)
        )
        # Occupancy gate: filter already-persisted texts and charge ONLY the
        # rows that can actually insert, under the account-capacity lock, in
        # this same transaction. Over-allowance raises before any insert.
        suggestions, capacity_dropped = await _apply_insert_capacity(
            session,
            workspace_id=workspace_id,
            prompt_set_id=prompt_set.id,
            suggestions=suggestions,
        )
        touched_topics: list[Topic] = []
        inserted_ids: list[uuid.UUID] = []
        dropped = intra_duplicates + capacity_dropped
        for suggestion in suggestions:
            topic = topics_by_id.get(suggestion.topic_id)
            if topic is None:
                dropped += len(suggestion.prompts)
                continue
            if topic not in touched_topics:
                touched_topics.append(topic)

            batch_ids, batch_dropped = await _insert_prompts_returning(
                session,
                prompt_set=prompt_set,
                topic=topic,
                prompts=suggestion.prompts,
                evidence_base=evidence_base,
                cohort=payload.cohort,
            )
            inserted_ids.extend(batch_ids)
            dropped += batch_dropped

        # Hydrate the response BEFORE commit so nothing has to be refreshed
        # afterward (a post-commit refresh could itself race a delete). With
        # ``expire_on_commit=False`` these instances stay usable to the caller.
        inserted = await _hydrate_inserted(session, inserted_ids)
        for topic in touched_topics:
            await session.refresh(topic)

        await session.commit()
    except IntegrityError as exc:
        # A referenced set/topic may have disappeared despite the advisory
        # lock (e.g. lock skipped on a non-PostgreSQL dialect). Rather than
        # blindly mapping EVERY integrity error to a 404 — which would mask
        # genuine constraint bugs (unique/check/unrelated FK violations) as a
        # phantom "prompt set not found" — roll back and re-check ONLY the
        # scoped entities this request depends on. A disappeared set maps to a
        # scoped 404; a disappeared target topic maps to a scoped 422; any
        # other integrity error is unrelated and re-raised unchanged (500).
        await session.rollback()
        await reraise_scoped_integrity_error(
            session,
            workspace_id=workspace_id,
            prompt_set_id=prompt_set_id,
            topic_id=payload.topic_id,
            exc=exc,
        )

    return inserted, touched_topics, dropped


async def _hydrate_inserted(
    session: AsyncSession, inserted_ids: list[uuid.UUID]
) -> list[Prompt]:
    """Load the freshly inserted prompts in deterministic response order."""
    if not inserted_ids:
        return []
    by_id = {
        prompt.id: prompt
        for prompt in (
            await session.execute(select(Prompt).where(Prompt.id.in_(inserted_ids)))
        )
        .scalars()
        .all()
    }
    return [by_id[pid] for pid in inserted_ids if pid in by_id]
