"""Commerce buyer-prompt generation over the shared Prompt owner."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.agent.gateway import ModelGateway
from app.core.config.commerce_catalog import (
    COMMERCE_PROMPT_CONTEXT_PRODUCT_LIMIT,
    COMMERCE_PROMPT_CONTEXT_TERM_LIMIT,
    COMMERCE_PROMPT_TEMPLATE_VERSION,
    commerce_buyer_prompt_system,
)
from app.core.config.visibility_prompts import (
    BUYER_STAGE_CONSIDERATION,
    PROMPT_INTENT_RECOMMEND,
)
from app.domain.commerce.buyer_prompt_validation import admitted_buyer_prompts
from app.domain.commerce.schemas import (
    BuyerPromptResponse,
    CommerceTarget,
)
from app.domain.commerce.service import CommerceNotFoundError, require_project
from app.domain.prompts.topical_binding import binding_tokens
from app.models.brand import Brand
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommerceProductCategory,
    CommercePromptTarget,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic


class BuyerPromptGenerationUnavailable(RuntimeError):
    pass


class _GeneratedPrompt(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class _GeneratedBatch(BaseModel):
    prompts: list[_GeneratedPrompt]


async def _project_with_brand(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    """Load the project with the brand profile the prompt context reads.

    ``require_project`` returns a bare row, so reaching for
    ``project.brand.profile`` on it lazy-loads inside an async session and
    raises. The profile is where the confirmed business context lives, and
    that context is the whole point of this path.
    """
    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .options(selectinload(Project.brand).selectinload(Brand.profile))
    )
    if project is None:
        raise CommerceNotFoundError("Project not found")
    return project


async def _category_products(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    category_id: uuid.UUID,
) -> list[CommerceProduct]:
    return list(
        (
            await session.scalars(
                select(CommerceProduct)
                .join(
                    CommerceProductCategory,
                    CommerceProductCategory.product_id == CommerceProduct.id,
                )
                .where(
                    CommerceProductCategory.category_id == category_id,
                    CommerceProduct.workspace_id == workspace_id,
                    CommerceProduct.project_id == project_id,
                )
                .order_by(CommerceProduct.name)
                .limit(COMMERCE_PROMPT_CONTEXT_PRODUCT_LIMIT)
            )
        ).all()
    )


async def _target_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target: CommerceTarget,
    project: Project,
) -> dict:
    """Everything the model needs to know what this shelf actually sells.

    A category target used to be sent as nothing but its own name -- no brand,
    no vertical, no products, not even the collection URL. Handed the bare word
    "ACCESORIES" and an exemplar bank of gadgets, the model wrote what generic
    e-commerce training data says accessories are: phone cases, screen
    protectors, laptop sleeves. For a linen-fashion label. It was not leaking
    examples; it had no way to know what the shop sold.
    """
    profile = project.brand.profile if project.brand is not None else None
    business_context = dict(getattr(profile, "business_context", None) or {})
    row: CommerceProduct | CommerceCategory | None
    if target.kind == "product":
        row = await session.scalar(
            select(CommerceProduct).where(
                CommerceProduct.id == target.id,
                CommerceProduct.workspace_id == workspace_id,
                CommerceProduct.project_id == project_id,
            )
        )
    else:
        row = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.id == target.id,
                CommerceCategory.workspace_id == workspace_id,
                CommerceCategory.project_id == project_id,
            )
        )
    if row is None:
        raise CommerceNotFoundError(f"Commerce {target.kind} not found")
    context = _base_target_context(
        target=target,
        name=row.name,
        project=project,
        business_context=business_context,
        audience=str(getattr(profile, "target_audience", "") or ""),
    )
    if isinstance(row, CommerceProduct):
        context.update(
            {
                "description": row.description,
                "attributes": row.attributes,
                "price": float(row.price) if row.price is not None else None,
                "currency": row.currency,
            }
        )
        return context
    context["category_url"] = row.canonical_url or ""
    context["category_role"] = row.role or ""
    products = await _category_products(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        category_id=row.id,
    )
    context["products_on_this_shelf"] = [product.name for product in products]
    return context


def _base_target_context(
    *,
    target: CommerceTarget,
    name: str,
    project: Project,
    business_context: dict[str, Any],
    audience: str,
) -> dict[str, Any]:
    return {
        "target_kind": target.kind,
        "name": name,
        "locale": "",
        "brand": project.brand_name or "",
        "sells": str(business_context.get("category") or ""),
        "category_terms": list(business_context.get("category_terms") or [])[
            :COMMERCE_PROMPT_CONTEXT_TERM_LIMIT
        ],
        "business_model": str(business_context.get("business_model") or ""),
        "audience": audience,
    }


async def _prompt_owner(
    session: AsyncSession, *, project_id: uuid.UUID, target: CommerceTarget
) -> tuple[PromptSet, Topic]:
    prompt_set = await session.scalar(
        select(PromptSet).where(
            PromptSet.project_id == project_id,
            PromptSet.name == "Commerce Buyer Prompts",
        )
    )
    if prompt_set is None:
        prompt_set = PromptSet(
            project_id=project_id,
            name="Commerce Buyer Prompts",
            description="Reviewed buyer-intent prompts linked to Commerce targets.",
        )
        session.add(prompt_set)
        await session.flush()
    topic_name = f"Commerce {target.kind} {target.id}"
    topic = await session.scalar(
        select(Topic).where(Topic.project_id == project_id, Topic.name == topic_name)
    )
    if topic is None:
        topic = Topic(
            project_id=project_id,
            name=topic_name,
            description="Commerce target-bound buyer intent",
            origin="generated",
        )
        session.add(topic)
        await session.flush()
    return prompt_set, topic


def _target_vocabulary(context: dict) -> frozenset[str]:
    """The words this target's own shelf uses.

    Built from the products actually on the shelf plus the confirmed category
    language -- never from the category NAME alone, which is the ambiguous
    thing ("accessories", "clearance", "layers" say nothing about a vertical).
    Returns empty when there is nothing to judge against, which disables the
    topicality rule rather than rejecting every prompt.
    """
    sources = [
        *[str(name) for name in context.get("products_on_this_shelf") or []],
        *[str(term) for term in context.get("category_terms") or []],
        str(context.get("sells") or ""),
    ]
    if context.get("target_kind") == "product":
        sources.extend(
            [str(context.get("name") or ""), str(context.get("description") or "")]
        )
    vocabulary: set[str] = set()
    for value in sources:
        vocabulary |= binding_tokens(value)
    return frozenset(vocabulary)


def _leaks_owned_identity(text: str, context: dict) -> bool:
    normalized = " ".join(text.casefold().split())
    protected = {str(context.get("brand") or "").casefold().strip()}
    if context.get("target_kind") == "product":
        protected.add(str(context.get("name") or "").casefold().strip())
    return any(value and value in normalized for value in protected)


async def generate_buyer_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[CommerceTarget],
    count: int,
    gateway: ModelGateway,
) -> list[BuyerPromptResponse]:
    project = await _project_with_brand(
        session, workspace_id=workspace_id, project_id=project_id
    )
    generated: list[BuyerPromptResponse] = []
    for target in targets:
        context = await _target_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            target=target,
            project=project,
        )
        context["locale"] = "-".join(
            value for value in (project.language_code, project.country_code) if value
        )
        try:
            raw = await gateway.complete_structured_json(
                system=commerce_buyer_prompt_system(
                    str(context.get("business_model") or "")
                ),
                user=json.dumps({"count": count, "context": context}, default=str),
                schema_name="commerce_buyer_prompts",
                schema=_GeneratedBatch.model_json_schema(),
            )
            batch = _GeneratedBatch.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise BuyerPromptGenerationUnavailable(
                "The configured model returned unusable buyer prompts"
            ) from exc
        # Style admission BEFORE the identity gate: a survey question that also
        # happens to avoid the brand name is still not a buyer prompt, and the
        # count check below must count only prompts that survived both.
        texts, _rejected = admitted_buyer_prompts(
            [item.text for item in batch.prompts],
            vocabulary=_target_vocabulary(context),
        )
        texts = [text for text in texts if not _leaks_owned_identity(text, context)][
            :count
        ]
        if len(texts) != count:
            raise BuyerPromptGenerationUnavailable(
                "Buyer prompts were unavailable because identity leakage or "
                "style validation left too few usable prompts"
            )
        prompt_set, topic = await _prompt_owner(
            session, project_id=project_id, target=target
        )
        for text in texts:
            prompt = Prompt(
                prompt_set_id=prompt_set.id,
                topic_id=topic.id,
                text=text,
                theme=str(context["name"])[:255],
                intent="comparison",
                # Commerce prompts are buyer prompts, so they belong in the
                # same buyer-stage taxonomy as the visibility portfolio. Left
                # blank they sat outside every downstream stage rollup.
                buyer_stage=BUYER_STAGE_CONSIDERATION,
                prompt_intent=PROMPT_INTENT_RECOMMEND,
                cohort="commerce",
                branded=False,
                enabled=False,
                status="active",
                origin="generated",
                generation_evidence={
                    "target": target.model_dump(mode="json"),
                    "template_version": COMMERCE_PROMPT_TEMPLATE_VERSION,
                    "model": gateway.model,
                },
            )
            session.add(prompt)
            await session.flush()
            relation = CommercePromptTarget(
                workspace_id=workspace_id,
                project_id=project_id,
                prompt_id=prompt.id,
                target_kind=target.kind,
                target_id=target.id,
            )
            session.add(relation)
            await session.flush()
            generated.append(_prompt_response(prompt, relation))
    await session.commit()
    return generated


async def add_manual_buyer_prompt(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target: CommerceTarget,
    text: str,
) -> BuyerPromptResponse:
    project = await _project_with_brand(
        session, workspace_id=workspace_id, project_id=project_id
    )
    # Called for its side effect: it 404s an unknown target before anything is
    # written. It needs the brand-loaded project like every other caller.
    await _target_context(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target=target,
        project=project,
    )
    prompt_set, topic = await _prompt_owner(
        session, project_id=project_id, target=target
    )
    prompt = Prompt(
        prompt_set_id=prompt_set.id,
        topic_id=topic.id,
        text=text.strip(),
        theme="Commerce",
        intent="comparison",
        cohort="commerce",
        branded=False,
        enabled=False,
        status="active",
        origin="manual",
    )
    session.add(prompt)
    await session.flush()
    relation = CommercePromptTarget(
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_id=prompt.id,
        target_kind=target.kind,
        target_id=target.id,
    )
    session.add(relation)
    await session.commit()
    return _prompt_response(prompt, relation)


async def list_buyer_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[BuyerPromptResponse]:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    rows = (
        await session.execute(
            select(Prompt, CommercePromptTarget)
            .join(CommercePromptTarget, CommercePromptTarget.prompt_id == Prompt.id)
            .where(
                CommercePromptTarget.workspace_id == workspace_id,
                CommercePromptTarget.project_id == project_id,
            )
            .order_by(Prompt.created_at)
        )
    ).all()
    return [_prompt_response(prompt, relation) for prompt, relation in rows]


async def decide_buyer_prompt(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_id: uuid.UUID,
    approved: bool,
) -> BuyerPromptResponse:
    row = (
        await session.execute(
            select(Prompt, CommercePromptTarget)
            .join(CommercePromptTarget, CommercePromptTarget.prompt_id == Prompt.id)
            .where(
                Prompt.id == prompt_id,
                CommercePromptTarget.workspace_id == workspace_id,
                CommercePromptTarget.project_id == project_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise CommerceNotFoundError("Buyer prompt not found")
    prompt, relation = row
    prompt.enabled = approved
    relation.approved_at = datetime.now(UTC) if approved else None
    await session.commit()
    return _prompt_response(prompt, relation)


def _prompt_response(
    prompt: Prompt, relation: CommercePromptTarget
) -> BuyerPromptResponse:
    return BuyerPromptResponse(
        id=prompt.id,
        prompt_set_id=prompt.prompt_set_id,
        target=CommerceTarget(kind=relation.target_kind, id=relation.target_id),
        text=prompt.text,
        enabled=prompt.enabled,
        approved_at=relation.approved_at,
    )
