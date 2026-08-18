"""Shared plumbing for the Site Health service package.

The pieces every read path needs and none of them owns: the two error types the
router maps to 404/400, the page-limit clamp, the workspace-scoped crawl/project
loaders (a foreign or missing id is a 404 here, never a cross-workspace leak),
and the typed keyset-cursor decoders.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.site_health.normalization import (
    CursorScopeError,
    decode_keyset_cursor,
)
from app.models.project import Project
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrlObservation

_MAX_PAGE_LIMIT = 200
_DEFAULT_PAGE_LIMIT = 50


class SiteHealthNotFoundError(Exception):
    """A workspace-scoped resource was missing / foreign (maps to 404)."""


# Single source for the repeated "crawl missing" detail (asserted by tests).
_CRAWL_NOT_FOUND = "Crawl not found"


class InvalidCursorError(Exception):
    """A cursor was tampered with or replayed cross-scope (maps to 400)."""


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return _DEFAULT_PAGE_LIMIT
    return max(1, min(int(limit), _MAX_PAGE_LIMIT))


async def _load_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl:
    crawl = await session.scalar(
        select(SiteCrawl).where(
            SiteCrawl.id == crawl_id,
            SiteCrawl.workspace_id == workspace_id,
        )
    )
    if crawl is None:
        raise SiteHealthNotFoundError(_CRAWL_NOT_FOUND)
    return crawl


async def _load_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if project is None:
        raise SiteHealthNotFoundError("Project not found")
    return project


def _admitted_site_url_subquery(crawl_id: uuid.UUID):
    """Scalar subquery of ``site_url_id`` admitted to (observed in) a crawl.

    A URL is "in" a crawl iff the discover worker wrote a
    ``SiteUrlObservation`` row for ``(crawl_id, site_url_id)`` (append-only
    admission provenance, unique per pair). Scoping ``SiteUrl`` queries through
    this set means a later (e.g. downgraded / different) crawl of the same
    project can only ever surface the URLs THAT crawl actually admitted — a
    Free sample crawl never exposes a prior Starter crawl's fuller catalog.
    """
    return (
        select(SiteUrlObservation.site_url_id)
        .where(SiteUrlObservation.crawl_id == crawl_id)
        .scalar_subquery()
    )


def _decode_url_keyset(
    cursor: str, *, scope: str, filters: dict
) -> tuple[str, uuid.UUID]:
    # Any typed-cursor failure (scope/filter mismatch, tamper, or a malformed
    # id payload) becomes an InvalidCursorError so the router returns 400.
    try:
        url_raw, id_raw = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        return url_raw, uuid.UUID(id_raw)
    except CursorScopeError as exc:
        raise InvalidCursorError(str(exc)) from exc
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc


def _decode_created_id_keyset(
    cursor: str, *, scope: str, filters: dict
) -> tuple[datetime, uuid.UUID]:
    """Decode a ``(created_at, id)`` keyset cursor (400 on any failure)."""
    try:
        created_raw, id_raw = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        return datetime.fromisoformat(created_raw), uuid.UUID(id_raw)
    except CursorScopeError as exc:
        raise InvalidCursorError(str(exc)) from exc
    except ValueError as exc:
        raise InvalidCursorError(str(exc)) from exc
