"""Workspace-scoped audit input and route resolution."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.entitlements import CREDENTIAL_MODE_BYOK, CREDENTIAL_MODE_FUNDED
from app.core.config.prompts import PROMPT_STATUS_ACTIVE
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_BYOK,
    LOGICAL_ENGINES,
    is_endpoint_approved,
    is_route_approved,
    measurement_route,
)
from app.domain.audits.errors import AuditValidationError
from app.models.brand import Brand
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.provider import ProviderConnection, ProviderRoute


@dataclass(frozen=True, slots=True)
class _ResolvedRoute:
    """One run's resolved route identity (never a key — invariant 6).

    BYOK runs point at the workspace's ``ProviderConnection``; funded runs
    resolve the catalog route here and get their concrete platform connection
    from per-task credential resolution (T11) at task creation.
    """

    logical_engine: str
    transport_provider: str
    transport_model: str
    connection_id: uuid.UUID | None
    base_url: str


def _normalize_seed(value: str | None) -> str:
    """Return a decimal string for a 64-bit unsigned seed.

    Accepts an explicit seed (any 64-bit-representable int, decimal string) or
    generates a fresh 64-bit one when omitted (invariant 9 — stored + replayed).
    """
    if value is None or not str(value).strip():
        return str(secrets.randbits(64))
    try:
        seed_int = int(str(value).strip())
    except ValueError as exc:
        raise AuditValidationError("random_seed must be an integer") from exc
    # Keep it in the unsigned 64-bit range so replay is exact.
    return str(seed_int & ((1 << 64) - 1))


def _prompt_panel_snapshot(rows: list[dict]) -> dict:
    """Stable hash of the frozen prompt panel (audit-scoping evidence)."""
    import json

    encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "panel_id": digest[:16],
        "panel_hash": digest,
        "prompt_hashes": [
            hashlib.sha256(str(r["text"]).encode("utf-8")).hexdigest() for r in rows
        ],
    }


async def _load_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    result = await session.execute(
        select(Project)
        .options(
            selectinload(Project.brand).selectinload(Brand.aliases),
            # Binding identity (topical admission): profile + topics are the
            # category side of the vocabulary; competitors are never loaded
            # into it.
            selectinload(Project.brand).selectinload(Brand.profile),
            selectinload(Project.topics),
            selectinload(Project.competitors),
            selectinload(Project.owned_domains),
            selectinload(Project.unintended_domains),
        )
        .where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    project = result.scalars().unique().one_or_none()
    if project is None:
        raise AuditValidationError("Project not found")
    return project


async def _resolve_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID | None,
    prompt_ids: list[uuid.UUID],
) -> list[Prompt]:
    """Resolve active, enabled prompts from a set or explicit ids, workspace-scoped."""
    stmt = (
        select(Prompt)
        .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
        .join(Project, Project.id == PromptSet.project_id)
        .where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
            Prompt.enabled.is_(True),
            # Proposed (unreviewed AI suggestions) and archived prompts are
            # never audit-eligible — only human-accepted active prompts run.
            Prompt.status == PROMPT_STATUS_ACTIVE,
        )
        .order_by(Prompt.created_at.asc(), Prompt.id.asc())
    )
    if prompt_ids:
        stmt = stmt.where(Prompt.id.in_(prompt_ids))
    elif prompt_set_id is not None:
        stmt = stmt.where(Prompt.prompt_set_id == prompt_set_id)
    else:
        raise AuditValidationError("Either prompt_set_id or prompt_ids is required")
    prompts = list((await session.scalars(stmt)).all())
    # For an explicit id list, reject the whole request if any requested prompt
    # is missing / disabled / from another project or workspace, rather than
    # silently auditing a smaller set than the caller asked for.
    if prompt_ids:
        requested = set(prompt_ids)
        resolved_ids = {prompt.id for prompt in prompts}
        unavailable = requested - resolved_ids
        if unavailable:
            missing = ", ".join(str(pid) for pid in sorted(map(str, unavailable)))
            raise AuditValidationError(
                f"Prompt(s) not found, disabled, not active, or not in this "
                f"project: {missing}"
            )
    if not prompts:
        raise AuditValidationError("No enabled prompts to audit")
    return prompts


def _normalize_engines(engines: list[str]) -> list[str]:
    """Validate + dedupe the requested logical engines (order-preserving)."""
    normalized = [str(e).strip().lower() for e in engines]
    seen: set[str] = set()
    unique_engines: list[str] = []
    for engine in normalized:
        if engine not in LOGICAL_ENGINES:
            raise AuditValidationError(f"Unknown logical engine: {engine}")
        if engine not in seen:
            seen.add(engine)
            unique_engines.append(engine)
    return unique_engines


async def _resolve_routes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    engines: list[str],
) -> dict[str, _ResolvedRoute]:
    """Pick one active BYOK route + connection per requested logical engine.

    Prefers a route flagged ``is_default`` for the engine, else the first
    active one. Raises if an engine is unknown or has no configured route.
    """
    unique_engines = _normalize_engines(engines)
    result = await session.execute(
        select(ProviderRoute, ProviderConnection)
        .join(
            ProviderConnection,
            ProviderConnection.id == ProviderRoute.connection_id,
        )
        .where(
            ProviderRoute.workspace_id == workspace_id,
            ProviderRoute.active.is_(True),
            ProviderConnection.active.is_(True),
            # Tenant route resolution is BYOK-only: a platform connection
            # must never resolve as a tenant route.
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_BYOK,
        )
        .order_by(
            ProviderRoute.is_default.desc(),
            ProviderRoute.created_at.asc(),
        )
    )
    routes: dict[str, _ResolvedRoute] = {}
    for route, connection in result.all():
        if not is_route_approved(route.logical_engine, route.transport_provider):
            continue
        if not is_endpoint_approved(
            connection.transport_provider, connection.base_url or ""
        ):
            continue
        routes.setdefault(
            route.logical_engine,
            _ResolvedRoute(
                logical_engine=route.logical_engine,
                transport_provider=route.transport_provider,
                transport_model=measurement_route(route.logical_engine).transport_model,
                connection_id=connection.id,
                base_url=connection.base_url or "",
            ),
        )

    resolved: dict[str, _ResolvedRoute] = {}
    missing: list[str] = []
    for engine in unique_engines:
        if engine in routes:
            resolved[engine] = routes[engine]
        else:
            missing.append(engine)
    if missing:
        raise AuditValidationError(
            "No active provider route configured for engine(s): " + ", ".join(missing)
        )
    return resolved


def _resolve_funded_routes(engines: list[str]) -> dict[str, _ResolvedRoute]:
    """Resolve the catalog-approved funded route per requested engine.

    Exactly one approved transport per engine exists (invariant 10), so a
    funded run needs no TENANT connection: per-task credential resolution
    (T11) binds the concrete platform connection in the system workspace once
    the task's reservation proves funded authorization.
    """
    resolved: dict[str, _ResolvedRoute] = {}
    for engine in _normalize_engines(engines):
        try:
            catalog_route = measurement_route(engine)
        except ValueError as exc:
            raise AuditValidationError(
                f"No approved funded route for engine: {engine}"
            ) from exc
        resolved[engine] = _ResolvedRoute(
            logical_engine=engine,
            transport_provider=catalog_route.transport_provider,
            transport_model=catalog_route.transport_model,
            connection_id=None,
            base_url="",
        )
    return resolved


async def _resolve_run_routes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    engines: list[str],
    credential_mode: str,
) -> dict[str, _ResolvedRoute]:
    """Route resolution for one run: BYOK workspace routes or funded catalog."""
    if credential_mode == CREDENTIAL_MODE_FUNDED:
        return _resolve_funded_routes(engines)
    if credential_mode != CREDENTIAL_MODE_BYOK:
        raise AuditValidationError(f"Unsupported credential_mode: {credential_mode}")
    return await _resolve_routes(
        session,
        workspace_id=workspace_id,
        engines=engines,
    )
