"""Commerce buyer-prompt generation over the shared Prompt owner."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.agent.gateway import ModelGateway
from app.core.config.commerce_catalog import COMMERCE_PROMPT_TEMPLATE_VERSION
from app.domain.commerce.schemas import (
    BuyerPromptResponse,
    CommerceTarget,
)
from app.domain.commerce.service import CommerceNotFoundError, require_project
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommercePromptTarget,
)
from app.models.prompt import Prompt, PromptSet, Topic


class BuyerPromptGenerationUnavailable(RuntimeError):
    pass


class _GeneratedPrompt(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class _GeneratedBatch(BaseModel):
    prompts: list[_GeneratedPrompt]


async def _target_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target: CommerceTarget,
) -> dict:
    model = CommerceCategory if target.kind == "category" else CommerceProduct
    row = await session.scalar(
        select(model).where(
            model.id == target.id,
            model.workspace_id == workspace_id,
            model.project_id == project_id,
        )
    )
    if row is None:
        raise CommerceNotFoundError(f"Commerce {target.kind} not found")
    name = row.name if isinstance(row, (CommerceCategory, CommerceProduct)) else ""
    context: dict[str, Any] = {
        "target_kind": target.kind,
        "name": name,
        "locale": "",
    }
    if isinstance(row, CommerceProduct):
        context.update(
            {
                "brand": row.brand,
                "description": row.description,
                "attributes": row.attributes,
                "price": float(row.price) if row.price is not None else None,
                "currency": row.currency,
            }
        )
    return context


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
    project = await require_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    generated: list[BuyerPromptResponse] = []
    for target in targets:
        context = await _target_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            target=target,
        )
        context["locale"] = "-".join(
            value for value in (project.language_code, project.country_code) if value
        )
        try:
            raw = await gateway.complete_structured_json(
                system=(
                    "Generate buyer discovery/comparison questions. Never name the "
                    "owned brand or intended product. Return only the schema."
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
        texts = [item.text.strip() for item in batch.prompts[:count]]
        if len(texts) != count or any(
            _leaks_owned_identity(text, context) for text in texts
        ):
            raise BuyerPromptGenerationUnavailable(
                "Buyer prompts were unavailable because identity leakage or "
                "count validation failed"
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
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    await _target_context(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target=target,
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
