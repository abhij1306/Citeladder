"""Persisted commerce-category citation evidence for opportunity detection."""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import CategoryCitationEvidence
from app.analysis.product_scoring import ProductScoringConfig
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit, AuditPromptSnapshot


def _citation_domain(citation: Citation) -> str:
    domain = citation.domain or (urlparse(citation.url).hostname or "")
    return domain.casefold().removeprefix("www.")


async def _load_rows(
    session: AsyncSession, audit_id: uuid.UUID
) -> tuple[dict[int, str], list[ResponseAnalysis], list[Citation]]:
    prompts = {
        row.prompt_index: row.theme
        for row in (
            await session.scalars(
                select(AuditPromptSnapshot).where(
                    AuditPromptSnapshot.audit_id == audit_id
                )
            )
        ).all()
    }
    analyses = list(
        (
            await session.scalars(
                select(ResponseAnalysis).where(
                    ResponseAnalysis.audit_id == audit_id,
                    ResponseAnalysis.cohort == "commerce",
                )
            )
        ).all()
    )
    analysis_ids = {row.id for row in analyses}
    if not analysis_ids:
        return prompts, analyses, []
    citations = list(
        (
            await session.scalars(
                select(Citation).where(Citation.analysis_id.in_(analysis_ids))
            )
        ).all()
    )
    return prompts, analyses, citations


def _project_category(
    category: str,
    *,
    prompts: dict[int, str],
    analyses: list[ResponseAnalysis],
    citations: list[Citation],
    uploaded_domains: set[str],
) -> CategoryCitationEvidence:
    analysis_ids = {
        row.id
        for row in analyses
        if prompts.get(row.prompt_index, "").casefold() == category.casefold()
    }
    rows = [row for row in citations if row.analysis_id in analysis_ids]
    owned = sum(1 for row in rows if _citation_domain(row) in uploaded_domains)
    return CategoryCitationEvidence(
        category=category,
        third_party_citation_count=len(rows) - owned,
        uploaded_destination_citation_count=owned,
        source_analysis_ids=tuple(sorted(str(value) for value in analysis_ids)),
    )


async def load_category_citation_evidence(
    session: AsyncSession, *, audit: Audit, config: ProductScoringConfig
) -> tuple[CategoryCitationEvidence, ...]:
    prompts, analyses, citations = await _load_rows(session, audit.id)
    uploaded_domains = {
        (urlparse(product.url).hostname or "").casefold().removeprefix("www.")
        for product in config.products
        if product.url
    }
    categories = sorted(
        {product.category for product in config.products if product.category}
    )
    return tuple(
        _project_category(
            category,
            prompts=prompts,
            analyses=analyses,
            citations=citations,
            uploaded_domains=uploaded_domains,
        )
        for category in categories
    )
