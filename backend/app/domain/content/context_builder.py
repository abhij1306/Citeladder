"""Plain-text generation context: brand + task + website + search.

Replaces the former grounding envelope. That design shipped a JSON blob of
facts, source refs, claim classes and prohibited claims, gated brand fields
behind manual review, and forced ``[[source:<id>]]`` markers whose validation
rejected otherwise-good output. It produced drafts that read like compliance
reports.

This module renders four readable text blocks instead. Grounding is now a
single instruction in the system prompt ("use this material, don't invent
specifics, write around gaps") rather than a machine-checked contract.

Crawl text still travels in its own separate message (see ``message_builder``)
and is never concatenated into the system or instruction message, so an
"ignore previous instructions" string embedded in a crawled page stays data.

Pure DB projection: no fetch, no provider call. The same inputs always render
the same blocks, so ``message_digest`` stays stable for provenance.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.content import (
    CONTENT_CONTEXT_VERSION,
    GROUNDING_STATUS_INCLUDED,
    GROUNDING_STATUS_UNAVAILABLE,
)
from app.domain.content.website_context import select_crawl_fragments
from app.models.brand import BrandProfile
from app.models.opportunity import Opportunity


@dataclass(frozen=True)
class ContentContext:
    """Rendered, immutable context for one generation.

    Every block is already-rendered text ("" when it has nothing to say), so
    the worker can rebuild the exact messages from the persisted snapshot
    without re-querying anything.
    """

    brand_block: str = ""
    task_block: str = ""
    website_block: str = ""
    search_block: str = ""
    summary: dict[str, Any] = field(default_factory=dict)
    version: str = CONTENT_CONTEXT_VERSION

    @property
    def status(self) -> str:
        """``included`` when any evidence was rendered, else ``unavailable``."""
        if self.brand_block or self.website_block or self.search_block:
            return GROUNDING_STATUS_INCLUDED
        return GROUNDING_STATUS_UNAVAILABLE

    def reference_blocks(self) -> list[str]:
        """The evidence blocks, in order, skipping empties."""
        return [
            block
            for block in (self.brand_block, self.website_block, self.search_block)
            if block
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "brand_block": self.brand_block,
            "task_block": self.task_block,
            "website_block": self.website_block,
            "search_block": self.search_block,
            "summary": self.summary,
        }

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> ContentContext:
        value = value or {}
        return cls(
            brand_block=str(value.get("brand_block") or ""),
            task_block=str(value.get("task_block") or ""),
            website_block=str(value.get("website_block") or ""),
            search_block=str(value.get("search_block") or ""),
            summary=dict(value.get("summary") or {}),
            version=str(value.get("version") or CONTENT_CONTEXT_VERSION),
        )


def _labelled(lines: list[tuple[str, object]]) -> list[str]:
    """Render ``Label: value`` lines, dropping every empty value."""
    rendered = []
    for label, value in lines:
        if isinstance(value, list):
            value = ", ".join(str(item).strip() for item in value if str(item).strip())
        text = str(value or "").strip()
        if text:
            rendered.append(f"{label}: {text}")
    return rendered


def _render_brand(
    profile: BrandProfile | None, *, brand_name: str, website: str, locale: str
) -> tuple[str, list[str]]:
    """Brand block plus the list of fields that contributed.

    Unconfirmed fields are included deliberately: this is context that helps
    the model use the right terminology and market, not a set of claims it is
    licensed to assert. The system prompt handles what may be asserted.
    """
    lines = [("Name", brand_name), ("Website", website), ("Market", locale)]
    fields: list[str] = []
    if profile is not None:
        for label, attribute in (
            ("What they do", "description"),
            ("Positioning", "positioning"),
            ("Products and services", "products_services"),
            ("Audience", "target_audience"),
        ):
            value = getattr(profile, attribute, None)
            lines.append((label, value))
            if value:
                fields.append(attribute)
    rendered = _labelled(lines)
    if not rendered:
        return "", fields
    return "BRAND\n" + "\n".join(rendered), fields


def _render_opportunity(opportunity: Opportunity | None) -> str:
    if opportunity is None:
        return ""
    lines = _labelled(
        [
            ("Issue", opportunity.title),
            ("Recommended action", opportunity.remediation),
            ("Target URL", opportunity.target_url),
            ("Target theme", opportunity.target_theme),
        ]
    )
    if not lines:
        return ""
    return "CONTENT OPPORTUNITY\n" + "\n".join(lines)


def _render_pages(pages: list[dict]) -> str:
    """Readable per-page text — the model parses this far better than JSON."""
    if not pages:
        return ""
    blocks = []
    for page in pages:
        lines = [f"SOURCE: {page.get('final_url') or ''}"]
        lines.extend(
            _labelled(
                [
                    ("Title", page.get("title")),
                    ("Description", page.get("meta_description")),
                    ("H1", page.get("h1")),
                    ("Sections", page.get("h2")),
                    ("Content", page.get("body_text")),
                ]
            )
        )
        blocks.append("\n".join(lines))
    return "RELEVANT WEBSITE CONTENT\n\n" + "\n\n".join(blocks)


async def build_content_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt: str,
    brand_name: str = "",
    website: str = "",
    locale: str = "",
    opportunity: Opportunity | None = None,
) -> ContentContext:
    """Assemble the rendered context for one generation.

    ``opportunity`` is passed in already-loaded by the caller (the service
    fetches it to authorize the request) rather than re-queried here.
    """
    profile = await session.scalar(
        select(BrandProfile).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    brand_block, brand_fields = _render_brand(
        profile, brand_name=brand_name, website=website, locale=locale
    )
    task_block = _render_opportunity(opportunity)

    # The opportunity's theme sharpens page ranking, and its target URL pins
    # the page being rewritten to the front of the context.
    target_url = (opportunity.target_url or "") if opportunity else ""
    query_text = " ".join(
        part
        for part in (prompt, (opportunity.target_theme or "") if opportunity else "")
        if part
    )
    selection = await select_crawl_fragments(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        query_text=query_text,
        target_url=target_url,
    )
    website_block = _render_pages(selection.pages)
    crawl_summary = selection.summary or {}

    summary = {
        "crawl_page_count": len(selection.pages),
        "crawl_urls": [str(page.get("final_url") or "") for page in selection.pages],
        "crawl_id": str(crawl_summary.get("crawl_id") or ""),
        "crawl_completed_at": crawl_summary.get("crawl_completed_at"),
        "brand_fields": brand_fields,
        "opportunity_id": str(opportunity.id) if opportunity else None,
        # GSC is not wired yet; the block stays empty and the flag stays False
        # so the UI can render "not connected" as a neutral state, not a fault.
        "search_connected": False,
        "selection_policy_version": str(
            crawl_summary.get("selection_policy_version") or ""
        ),
        "omissions": list(crawl_summary.get("omissions") or []),
    }
    return ContentContext(
        brand_block=brand_block,
        task_block=task_block,
        website_block=website_block,
        search_block="",
        summary=summary,
    )


async def content_context_availability(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict[str, Any]:
    """Cheap pre-flight answer for the composer's context indicator.

    Runs the same crawl selection but only reports counts — the caller needs
    to know whether a draft will be grounded, not what it will be grounded on.
    """
    selection = await select_crawl_fragments(
        session, workspace_id=workspace_id, project_id=project_id
    )
    profile = await session.scalar(
        select(BrandProfile).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    brand_fields = [
        attribute
        for attribute in (
            "description",
            "positioning",
            "products_services",
            "target_audience",
        )
        if profile is not None and getattr(profile, attribute, None)
    ]
    summary = selection.summary or {}
    return {
        "crawl_available": bool(selection.pages),
        "crawl_page_count": len(selection.pages),
        "crawl_completed_at": summary.get("crawl_completed_at"),
        "brand_fields": brand_fields,
        "search_connected": False,
    }
