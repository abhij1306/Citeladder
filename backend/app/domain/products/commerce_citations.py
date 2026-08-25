"""Commerce citation comparisons projected from persisted audit evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.product_scoring import ProductScoringConfig
from app.domain.products.schemas import (
    CommerceCategoryCitations,
    CommerceCitationComparison,
    CommerceCitedSource,
    CommerceCompetitorMention,
)
from app.models.analysis import Citation, CompetitorMention, ResponseAnalysis
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask


@dataclass(frozen=True)
class AnalysisSlot:
    theme: str
    logical_engine: str
    prompt_index: int
    brand_mentioned: bool


AnalysisContext = dict[uuid.UUID, AnalysisSlot]


def _url_domain(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _citation_domain(citation: Citation) -> str:
    return (
        (citation.domain or _url_domain(citation.url)).casefold().removeprefix("www.")
    )


def _catalog_context(
    config: ProductScoringConfig,
) -> dict[str, list[str]]:
    products_by_category: dict[str, list[str]] = {}
    for product in config.products:
        category = str((product.attributes or {}).get("category") or "").strip()
        if category:
            products_by_category.setdefault(category, []).append(product.name)
    return products_by_category


async def _analysis_context(
    session: AsyncSession, audit_id: uuid.UUID, engine: str | None
) -> AnalysisContext:
    filters = [
        ResponseAnalysis.audit_id == audit_id,
        ResponseAnalysis.cohort == "commerce",
    ]
    if engine is not None:
        filters.append(ResponseAnalysis.logical_engine == engine)
    rows = (
        await session.execute(
            select(ResponseAnalysis, AuditPromptSnapshot)
            .join(AuditTask, AuditTask.id == ResponseAnalysis.task_id)
            .join(
                AuditPromptSnapshot,
                AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
            )
            .where(*filters)
        )
    ).all()
    return {
        analysis.id: AnalysisSlot(
            theme=prompt.theme,
            logical_engine=analysis.logical_engine,
            prompt_index=analysis.prompt_index,
            brand_mentioned=analysis.brand_mentioned,
        )
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


async def _competitor_mentions(
    session: AsyncSession, audit_id: uuid.UUID, context: AnalysisContext
) -> list[CompetitorMention]:
    if not context:
        return []
    return list(
        (
            await session.scalars(
                select(CompetitorMention).where(
                    CompetitorMention.audit_id == audit_id,
                    CompetitorMention.analysis_id.in_(context),
                )
            )
        ).all()
    )


def _source_rows(
    citations: list[Citation], context: AnalysisContext
) -> list[CommerceCitedSource]:
    grouped: dict[tuple[str, str, str, str | None], list[Citation]] = {}
    for citation in citations:
        domain = _citation_domain(citation)
        grouped.setdefault(
            (
                domain,
                citation.title or domain,
                citation.classification,
                citation.matched_competitor,
            ),
            [],
        ).append(citation)
    sources = [
        CommerceCitedSource(
            domain=domain,
            title=title,
            representative_url=rows[0].url,
            classification=classification,
            matched_competitor=matched_competitor,
            citation_count=len(rows),
            distinct_prompts=len(
                {context[row.analysis_id].prompt_index for row in rows}
            ),
            distinct_engines=len(
                {context[row.analysis_id].logical_engine for row in rows}
            ),
            citation_ids=[row.id for row in rows],
            analysis_ids=sorted({row.analysis_id for row in rows}, key=str),
            artifact_ids=sorted({row.artifact_id for row in rows}, key=str),
        )
        for (domain, title, classification, matched_competitor), rows in grouped.items()
    ]
    return sorted(
        sources,
        key=lambda source: (-source.citation_count, source.domain, source.title),
    )


def _competitor_rows(
    mentions: list[CompetitorMention], context: AnalysisContext
) -> list[CommerceCompetitorMention]:
    grouped: dict[str, list[CompetitorMention]] = {}
    for mention in mentions:
        grouped.setdefault(mention.competitor_name, []).append(mention)
    rows = [
        CommerceCompetitorMention(
            competitor_name=name,
            response_count=len({mention.analysis_id for mention in grouped_mentions}),
            distinct_prompts=len(
                {
                    context[mention.analysis_id].prompt_index
                    for mention in grouped_mentions
                }
            ),
            distinct_engines=len(
                {
                    context[mention.analysis_id].logical_engine
                    for mention in grouped_mentions
                }
            ),
            analysis_ids=sorted(
                {mention.analysis_id for mention in grouped_mentions}, key=str
            ),
            artifact_ids=sorted(
                {mention.artifact_id for mention in grouped_mentions}, key=str
            ),
        )
        for name, grouped_mentions in grouped.items()
    ]
    return sorted(rows, key=lambda row: (-row.response_count, row.competitor_name))


def _category_row(
    category: str,
    *,
    product_names: list[str],
    context: AnalysisContext,
    citations: list[Citation],
    competitor_mentions: list[CompetitorMention],
) -> CommerceCategoryCitations:
    analysis_ids = {
        analysis_id
        for analysis_id, values in context.items()
        if values.theme.casefold() == category.casefold()
    }
    category_citations = [
        citation for citation in citations if citation.analysis_id in analysis_ids
    ]
    category_mentions = [
        mention
        for mention in competitor_mentions
        if mention.analysis_id in analysis_ids
    ]
    owned_count = sum(citation.is_owned for citation in category_citations)
    competitor_count = sum(
        citation.classification == "competitor" for citation in category_citations
    )
    return CommerceCategoryCitations(
        category=category,
        response_count=len(analysis_ids),
        brand_response_count=sum(
            context[analysis_id].brand_mentioned for analysis_id in analysis_ids
        ),
        uploaded_products=sorted(product_names),
        uploaded_commerce_citation_count=owned_count,
        competitor_citation_count=competitor_count,
        third_party_citation_count=(
            len(category_citations) - owned_count - competitor_count
        ),
        competitor_mentions=_competitor_rows(category_mentions, context),
        cited_sources=_source_rows(category_citations, context),
    )


async def commerce_citation_comparison(
    session: AsyncSession,
    *,
    audit: Audit,
    config: ProductScoringConfig,
    engine: str | None = None,
) -> CommerceCitationComparison:
    products_by_category = _catalog_context(config)
    context = await _analysis_context(session, audit.id, engine)
    citations = await _citations(session, audit.id, context)
    competitor_mentions = await _competitor_mentions(session, audit.id, context)
    categories = [
        _category_row(
            category,
            product_names=products_by_category[category],
            context=context,
            citations=citations,
            competitor_mentions=competitor_mentions,
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
