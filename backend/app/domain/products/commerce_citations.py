"""Commerce citation comparisons projected from persisted audit evidence."""

from __future__ import annotations

import uuid
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.product_scoring import ProductScoringConfig
from app.domain.products.schemas import (
    CommerceCategoryCitations,
    CommerceCitationComparison,
    CommerceCitedSource,
)
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask

AnalysisContext = dict[uuid.UUID, tuple[str, str, int]]


def _url_domain(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _citation_domain(citation: Citation) -> str:
    return (
        citation.domain or _url_domain(citation.url)
    ).casefold().removeprefix("www.")


def _catalog_context(
    config: ProductScoringConfig,
) -> tuple[dict[str, list[str]], set[str]]:
    products_by_category: dict[str, list[str]] = {}
    owned_domains: set[str] = set()
    for product in config.products:
        category = str((product.attributes or {}).get("category") or "").strip()
        if category:
            products_by_category.setdefault(category, []).append(product.name)
        domain = _url_domain(product.url)
        if domain:
            owned_domains.add(domain)
    return products_by_category, owned_domains


async def _analysis_context(
    session: AsyncSession, audit_id: uuid.UUID
) -> AnalysisContext:
    rows = (
        await session.execute(
            select(ResponseAnalysis, AuditPromptSnapshot)
            .join(AuditTask, AuditTask.id == ResponseAnalysis.task_id)
            .join(
                AuditPromptSnapshot,
                AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
            )
            .where(
                ResponseAnalysis.audit_id == audit_id,
                ResponseAnalysis.cohort == "commerce",
            )
        )
    ).all()
    return {
        analysis.id: (prompt.theme, analysis.logical_engine, analysis.prompt_index)
        for analysis, prompt in rows
    }


async def _citations(
    session: AsyncSession, audit_id: uuid.UUID, context: AnalysisContext
) -> list[Citation]:
    if not context:
        return []
    return list(
        (
            await session.scalars(
                select(Citation).where(
                    Citation.audit_id == audit_id,
                    Citation.analysis_id.in_(context),
                )
            )
        ).all()
    )


def _source_rows(
    citations: list[Citation], context: AnalysisContext
) -> list[CommerceCitedSource]:
    grouped: dict[tuple[str, str], list[Citation]] = {}
    for citation in citations:
        domain = _citation_domain(citation)
        grouped.setdefault((domain, citation.title or domain), []).append(citation)
    sources = [
        CommerceCitedSource(
            domain=domain,
            title=title,
            representative_url=rows[0].url,
            citation_count=len(rows),
            distinct_prompts=len({context[row.analysis_id][2] for row in rows}),
            distinct_engines=len({context[row.analysis_id][1] for row in rows}),
            citation_ids=[row.id for row in rows],
            analysis_ids=sorted({row.analysis_id for row in rows}, key=str),
            artifact_ids=sorted({row.artifact_id for row in rows}, key=str),
        )
        for (domain, title), rows in grouped.items()
    ]
    return sorted(
        sources,
        key=lambda source: (-source.citation_count, source.domain, source.title),
    )


def _category_row(
    category: str,
    *,
    product_names: list[str],
    context: AnalysisContext,
    citations: list[Citation],
    owned_domains: set[str],
) -> CommerceCategoryCitations:
    analysis_ids = {
        analysis_id
        for analysis_id, values in context.items()
        if values[0].casefold() == category.casefold()
    }
    category_citations = [
        citation for citation in citations if citation.analysis_id in analysis_ids
    ]
    owned_count = sum(
        1
        for citation in category_citations
        if _citation_domain(citation) in owned_domains
    )
    return CommerceCategoryCitations(
        category=category,
        response_count=len(analysis_ids),
        uploaded_products=sorted(product_names),
        uploaded_commerce_citation_count=owned_count,
        third_party_citation_count=len(category_citations) - owned_count,
        cited_sources=_source_rows(category_citations, context),
    )


async def commerce_citation_comparison(
    session: AsyncSession, *, audit: Audit, config: ProductScoringConfig
) -> CommerceCitationComparison:
    products_by_category, owned_domains = _catalog_context(config)
    context = await _analysis_context(session, audit.id)
    citations = await _citations(session, audit.id, context)
    categories = [
        _category_row(
            category,
            product_names=products_by_category[category],
            context=context,
            citations=citations,
            owned_domains=owned_domains,
        )
        for category in sorted(products_by_category)
    ]
    has_citations = any(row.cited_sources for row in categories)
    limitation = (
        "Cited sources are alternatives observed in provider responses; "
        "they are not matched competitor SKUs."
        if has_citations
        else "No citations were returned for this audit. Retrieval-enabled "
        "providers can still return uncited answers."
    )
    return CommerceCitationComparison(
        status="available" if has_citations else "no_citations",
        limitation=limitation,
        categories=categories,
    )
