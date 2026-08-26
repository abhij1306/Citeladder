"""Site Health to Commerce catalog projection owner."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import COMMERCE_PROJECTOR_VERSION
from app.domain.commerce.service import (
    CommerceNotFoundError,
    _merge_categories,
)
from app.models.analytics import AnalyticsTask
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommerceProductObservation,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.urls import SiteUrl


def _first(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return str(next((value for value in values if value), ""))


def _crawl_values(facts: dict[str, Any], canonical_url: str) -> dict[str, Any]:
    structured = _dict_value(facts.get("structured_data"))
    product = _dict_value(structured.get("product"))
    headings = _dict_value(facts.get("headings"))
    names = _list_value(product.get("name"))
    if not names:
        names = _list_value(headings.get("h1_texts"))
    price_text = _first(product.get("price"))
    try:
        price = Decimal(price_text) if price_text else None
    except InvalidOperation:
        price = None
    return {
        "canonical_url": canonical_url,
        "name": _first(names) or str(facts.get("title") or ""),
        "description": _first(product.get("description"))
        or str(facts.get("meta_description") or ""),
        "brand": _first(product.get("brand")),
        "price": price,
        "currency": _first(product.get("price_currency")),
        "sku": _first(product.get("sku")),
        "gtin": _first(product.get("gtin")),
        "mpn": _first(product.get("mpn")),
        "variants": _list_value(product.get("variants")),
        "attributes": {"availability": _list_value(product.get("availability"))},
    }


def _json_observed_fields(values: dict[str, Any]) -> dict[str, Any]:
    observed = dict(values)
    if isinstance(observed.get("price"), Decimal):
        observed["price"] = float(observed["price"])
    return observed


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


async def project_catalog_analysis(session_factory, task: AnalyticsTask) -> None:
    """Idempotently project persisted Site Health analysis evidence."""
    raw_id = str((task.payload or {}).get("source_analysis_id") or "")
    source_analysis_id = uuid.UUID(raw_id)
    async with session_factory() as session:
        analysis, artifact, site_url = await _projection_source(
            session, task=task, source_analysis_id=source_analysis_id
        )
        if analysis.page_kind == "category":
            await _project_category_source(
                session, analysis=analysis, artifact=artifact, site_url=site_url
            )
        elif analysis.page_kind == "product":
            await _project_product_source(
                session, analysis=analysis, artifact=artifact, site_url=site_url
            )
        await session.commit()


async def _projection_source(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    source_analysis_id: uuid.UUID,
) -> tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]:
    row = (
        await session.execute(
            select(SitePageAnalysis, SiteFetchArtifact, SiteUrl)
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .where(
                SitePageAnalysis.id == source_analysis_id,
                SitePageAnalysis.workspace_id == task.workspace_id,
                SitePageAnalysis.project_id == task.project_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise CommerceNotFoundError("Source Site Health analysis not found")
    return row[0], row[1], row[2]


async def _project_category_source(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    site_url: SiteUrl,
) -> None:
    facts = dict(artifact.normalized_facts or {})
    commerce = _dict_value(facts.get("commerce"))
    await _category_from_analysis(
        session,
        analysis=analysis,
        canonical_url=site_url.normalized_url,
        title=str(facts.get("title") or site_url.latest_title or "Uncategorized"),
        role=str(commerce.get("category_role") or "unknown"),
    )


async def _project_product_source(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    site_url: SiteUrl,
) -> None:
    prior = await session.scalar(
        select(CommerceProductObservation.id).where(
            CommerceProductObservation.source_analysis_id == analysis.id,
            CommerceProductObservation.projector_version == COMMERCE_PROJECTOR_VERSION,
        )
    )
    if prior is not None:
        return
    values = _crawl_values(
        dict(artifact.normalized_facts or {}), site_url.normalized_url
    )
    product = await session.scalar(
        select(CommerceProduct).where(
            CommerceProduct.project_id == analysis.project_id,
            CommerceProduct.canonical_url == site_url.normalized_url,
        )
    )
    if product is None:
        product = CommerceProduct(
            workspace_id=analysis.workspace_id,
            project_id=analysis.project_id,
            canonical_url=site_url.normalized_url,
        )
        session.add(product)
        await session.flush()
    _apply_projected_values(
        product, values=values, analysis=analysis, artifact=artifact
    )
    observation = CommerceProductObservation(
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        product_id=product.id,
        source_kind="site_health",
        source_analysis_id=analysis.id,
        source_artifact_id=artifact.id,
        observed_fields=_json_observed_fields(values),
        extractor_version=artifact.extractor_version,
        classifier_version=analysis.classifier_version,
        projector_version=COMMERCE_PROJECTOR_VERSION,
    )
    session.add(observation)
    await session.flush()
    await _merge_projected_categories(
        session,
        analysis=analysis,
        artifact=artifact,
        product=product,
        observation=observation,
    )


def _apply_projected_values(
    product: CommerceProduct,
    *,
    values: dict[str, Any],
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
) -> None:
    sources = dict(product.field_sources or {})
    for field, value in values.items():
        source = _dict_value(sources.get(field))
        if source.get("kind") in {"csv", "edit"}:
            continue
        if value not in (None, "", [], {}):
            setattr(product, field, value)
            sources[field] = {
                "kind": "site_health",
                "source_id": str(analysis.id),
                "artifact_id": str(artifact.id),
                "version": COMMERCE_PROJECTOR_VERSION,
            }
    product.field_sources = sources


async def _merge_projected_categories(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    product: CommerceProduct,
    observation: CommerceProductObservation,
) -> None:
    facts = dict(artifact.normalized_facts or {})
    structured = _dict_value(_dict_value(facts.get("structured_data")).get("product"))
    names = [str(value) for value in _list_value(structured.get("category"))]
    commerce = _dict_value(facts.get("commerce"))
    breadcrumbs = [str(value) for value in _list_value(commerce.get("breadcrumbs"))]
    if len(breadcrumbs) > 2:
        names.extend(breadcrumbs[1:-1])
    await _merge_categories(
        session,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        product_id=product.id,
        names=list(dict.fromkeys(names)) or ["Uncategorized"],
        source_observation_id=observation.id,
    )


async def _category_from_analysis(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    canonical_url: str,
    title: str,
    role: str,
) -> None:
    normalized = " ".join(title.casefold().split())
    category = await session.scalar(
        select(CommerceCategory).where(
            CommerceCategory.project_id == analysis.project_id,
            CommerceCategory.canonical_url == canonical_url,
        )
    )
    if category is None:
        category = CommerceCategory(
            workspace_id=analysis.workspace_id,
            project_id=analysis.project_id,
            name=title[:255],
            normalized_name=normalized[:255],
            canonical_url=canonical_url,
        )
        session.add(category)
    category.role = role if role in {"hub", "leaf"} else "unknown"
    category.source_analysis_id = analysis.id
    category.projector_version = COMMERCE_PROJECTOR_VERSION
