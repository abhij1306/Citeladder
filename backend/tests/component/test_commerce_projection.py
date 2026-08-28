from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.commerce.projector import (
    _project_category_source,
    _project_product_source,
)
from app.domain.commerce.service import enqueue_catalog_projection
from app.domain.site_health.normalization import canonical_identity
from app.models.analytics import AnalyticsTask
from app.models.brand import Brand, BrandProfile
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommerceProductCategory,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl
from tests.component.site_health_helpers import seed_site_crawl


@pytest.mark.asyncio
async def test_catalog_projection_enqueue_requires_commerce_business_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        commerce = await seed_site_crawl(session, email="commerce-model@example.com")
        saas = await seed_site_crawl(session, email="saas-model@example.com")
        for seed, business_model in ((commerce, "retail"), (saas, "b2b_saas")):
            brand = Brand(project_id=seed.project_id, name="Acme")
            session.add(brand)
            await session.flush()
            session.add(
                BrandProfile(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    brand_id=brand.id,
                    business_context={"business_model": business_model},
                )
            )
        await session.flush()
        commerce_analysis_id = uuid.uuid4()
        saas_analysis_id = uuid.uuid4()

        await enqueue_catalog_projection(
            session,
            workspace_id=commerce.workspace_id,
            project_id=commerce.project_id,
            source_analysis_id=commerce_analysis_id,
        )
        await enqueue_catalog_projection(
            session,
            workspace_id=saas.workspace_id,
            project_id=saas.project_id,
            source_analysis_id=saas_analysis_id,
        )
        await session.commit()

        rows = list(await session.scalars(select(AnalyticsTask)))
        assert [row.project_id for row in rows] == [commerce.project_id]


@pytest.mark.asyncio
async def test_category_projection_flushes_parent_before_core_membership_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert task is not None
        category_url, category_hash = canonical_identity(
            "https://example.com/collections/oral-care"
        )
        product_url, _product_hash = canonical_identity(
            "https://example.com/products/toothpaste"
        )
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=category_url,
            url_hash=category_hash,
            display_url=category_url,
            latest_title="Oral Care",
        )
        product = CommerceProduct(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            canonical_url=product_url,
            name="Toothpaste",
        )
        session.add_all([site_url, product])
        await session.flush()
        task.site_url_id = site_url.id
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="discover",
            requested_url=category_url,
            final_url=category_url,
            normalized_facts={
                "canonical_url": category_url,
                "headings": {"h1_texts": ["Oral Care"]},
                "commerce": {
                    "category_role": "leaf",
                    "product_cards": [{"url": product_url}],
                },
            },
        )
        session.add(artifact)
        await session.flush()
        analysis = SitePageAnalysis(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=seed.crawl_id,
            site_url_id=site_url.id,
            artifact_id=artifact.id,
            status="completed",
            page_kind="category",
        )
        session.add(analysis)
        await session.flush()

        await _project_category_source(
            session, analysis=analysis, artifact=artifact, site_url=site_url
        )
        await session.commit()

        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.project_id == seed.project_id,
                CommerceCategory.normalized_name == "oral care",
            )
        )
        assert category is not None
        membership = await session.scalar(
            select(CommerceProductCategory).where(
                CommerceProductCategory.product_id == product.id,
                CommerceProductCategory.category_id == category.id,
            )
        )
        assert membership is not None


@pytest.mark.asyncio
async def test_redirected_declarations_use_final_url_for_catalog_and_membership(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=2)
        tasks = list(
            await session.scalars(
                select(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == seed.crawl_id)
                .order_by(SiteCrawlTask.randomized_position)
            )
        )
        product_requested = "https://example.com/redirect/toothpaste"
        product_final = "https://shop.example.com/store/toothpaste"
        product_identity = "https://shop.example.com/products/toothpaste"
        category_requested = "https://example.com/redirect/oral-care"
        category_final = "https://shop.example.com/store/oral-care"
        category_identity = "https://shop.example.com/collections/oral-care"
        sources = (
            (
                tasks[0],
                product_requested,
                product_final,
                {
                    "canonical_url": "/products/toothpaste",
                    "structured_data": {
                        "product": {"name": ["Toothpaste"], "sku": ["TP-1"]}
                    },
                },
                "product",
            ),
            (
                tasks[1],
                category_requested,
                category_final,
                {
                    "canonical_url": "/collections/oral-care",
                    "headings": {"h1_texts": ["Oral Care"]},
                    "commerce": {
                        "category_role": "leaf",
                        "product_cards": [{"url": product_requested}],
                    },
                },
                "category",
            ),
        )
        projected_sources: dict[
            str, tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]
        ] = {}
        for task, requested_url, final_url, facts, page_kind in sources:
            normalized_url, url_hash = canonical_identity(requested_url)
            site_url = SiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                normalized_url=normalized_url,
                url_hash=url_hash,
                display_url=normalized_url,
                latest_title=str(facts.get("canonical_url") or ""),
            )
            session.add(site_url)
            await session.flush()
            task.site_url_id = site_url.id
            task.requested_url = normalized_url
            task.url_hash = url_hash
            artifact = SiteFetchArtifact(
                task_id=task.id,
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                fetch_purpose="discover",
                requested_url=normalized_url,
                final_url=final_url,
                normalized_facts=facts,
            )
            session.add(artifact)
            await session.flush()
            analysis = SitePageAnalysis(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url.id,
                artifact_id=artifact.id,
                status="completed",
                page_kind=page_kind,
            )
            session.add(analysis)
            projected_sources[page_kind] = (analysis, artifact, site_url)
        await session.flush()

        product_analysis, product_artifact, product_site_url = projected_sources[
            "product"
        ]
        await _project_product_source(
            session,
            analysis=product_analysis,
            artifact=product_artifact,
            site_url=product_site_url,
        )
        category_analysis, category_artifact, category_site_url = projected_sources[
            "category"
        ]
        await _project_category_source(
            session,
            analysis=category_analysis,
            artifact=category_artifact,
            site_url=category_site_url,
        )
        await session.commit()

        product = await session.scalar(
            select(CommerceProduct).where(
                CommerceProduct.workspace_id == seed.workspace_id,
                CommerceProduct.project_id == seed.project_id,
                CommerceProduct.canonical_url == product_identity,
            )
        )
        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.workspace_id == seed.workspace_id,
                CommerceCategory.project_id == seed.project_id,
                CommerceCategory.canonical_url == category_identity,
            )
        )
        assert product is not None
        assert category is not None
        membership = await session.scalar(
            select(CommerceProductCategory).where(
                CommerceProductCategory.workspace_id == seed.workspace_id,
                CommerceProductCategory.project_id == seed.project_id,
                CommerceProductCategory.product_id == product.id,
                CommerceProductCategory.category_id == category.id,
            )
        )
        assert membership is not None


@pytest.mark.asyncio
async def test_shelf_membership_falls_back_to_main_region_anchors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A theme the card extractor cannot read still yields real membership.

    Every one of a Shopify store's 19 collection pages came back with
    ``product_cards: []`` while carrying 24 main-region anchors each, one per
    product on that shelf. Membership was derived from nothing, so all 413
    products landed in one synthetic bucket and every real collection reported
    zero. The anchors are the same evidence read one level lower, and they are
    relative -- they must be resolved against the shelf page to mean anything.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=2)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        product_task = await session.get(SiteCrawlTask, seed.task_ids[1])
        assert task is not None and product_task is not None
        category_url, category_hash = canonical_identity(
            "https://example.com/collections/dresses"
        )
        product_url, _product_hash = canonical_identity(
            "https://example.com/products/linen-dress"
        )
        alias_url, alias_hash = canonical_identity(
            "https://example.com/collections/dresses/products/linen-dress"
        )
        category_site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=category_url,
            url_hash=category_hash,
            display_url=category_url,
            latest_title="Dresses",
        )
        # The product was crawled through the shelf path and declared the
        # identity the catalog keys it on.
        product_site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=alias_url,
            url_hash=alias_hash,
            display_url=alias_url,
            latest_title="Linen Dress",
        )
        product = CommerceProduct(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            canonical_url=product_url,
            name="Linen Dress",
        )
        session.add_all([category_site_url, product_site_url, product])
        await session.flush()
        task.site_url_id = category_site_url.id
        product_task.site_url_id = product_site_url.id

        product_artifact = SiteFetchArtifact(
            task_id=product_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="discover",
            requested_url=alias_url,
            final_url=alias_url,
            normalized_facts={"canonical_url": product_url},
        )
        shelf_artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="discover",
            requested_url=category_url,
            final_url=category_url,
            normalized_facts={
                "canonical_url": category_url,
                "headings": {"h1_texts": ["Dresses"]},
                # No cards at all -- the theme the extractor cannot read.
                "commerce": {"category_role": "leaf", "product_cards": []},
                "links": {
                    "anchors": [
                        {
                            "url": "/collections/dresses/products/linen-dress",
                            "region": "main",
                        },
                        # A nav link to another shelf contributes nothing.
                        {"url": "/collections/tops", "region": "header"},
                    ]
                },
            },
        )
        session.add_all([product_artifact, shelf_artifact])
        await session.flush()
        product_analysis = SitePageAnalysis(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=seed.crawl_id,
            site_url_id=product_site_url.id,
            artifact_id=product_artifact.id,
            status="completed",
            page_kind="product",
        )
        shelf_analysis = SitePageAnalysis(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=seed.crawl_id,
            site_url_id=category_site_url.id,
            artifact_id=shelf_artifact.id,
            status="completed",
            page_kind="category",
        )
        session.add_all([product_analysis, shelf_analysis])
        await session.flush()

        await _project_category_source(
            session,
            analysis=shelf_analysis,
            artifact=shelf_artifact,
            site_url=category_site_url,
        )
        await session.commit()

        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.project_id == seed.project_id,
                CommerceCategory.normalized_name == "dresses",
            )
        )
        assert category is not None
        membership = await session.scalar(
            select(CommerceProductCategory).where(
                CommerceProductCategory.product_id == product.id,
                CommerceProductCategory.category_id == category.id,
            )
        )
        assert membership is not None


@pytest.mark.asyncio
async def test_breadcrumb_separator_never_becomes_a_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Themes mark a breadcrumb trail up as one node per crumb AND separator.

    "Home / DRESSES" is read as ["Home", "/", "DRESSES"], and the middle slice
    this path takes is the bare separator. Passed through, it created a catalog
    category literally named "/" that all 413 of a site's products hung off
    while every one of its 19 real collections reported zero.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert task is not None
        product_url, product_hash = canonical_identity(
            "https://example.com/products/linen-dress"
        )
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=product_url,
            url_hash=product_hash,
            display_url=product_url,
            latest_title="Linen Dress",
        )
        session.add(site_url)
        await session.flush()
        task.site_url_id = site_url.id
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="discover",
            requested_url=product_url,
            final_url=product_url,
            normalized_facts={
                "canonical_url": product_url,
                "title": "Linen Dress",
                "headings": {"h1_texts": ["Linen Dress"]},
                "structured_data": {
                    "product": {
                        "name": ["Linen Dress"],
                        "sku": ["LD-1"],
                        "price": ["120.00"],
                        "price_currency": ["USD"],
                    }
                },
                "commerce": {
                    "breadcrumbs": ["Home", "/", "DRESSES", "/", "Linen Dress"]
                },
            },
        )
        session.add(artifact)
        await session.flush()
        analysis = SitePageAnalysis(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=seed.crawl_id,
            site_url_id=site_url.id,
            artifact_id=artifact.id,
            status="completed",
            page_kind="product",
        )
        session.add(analysis)
        await session.flush()

        await _project_product_source(
            session, analysis=analysis, artifact=artifact, site_url=site_url
        )
        await session.commit()

        names = set(
            (
                await session.scalars(
                    select(CommerceCategory.name).where(
                        CommerceCategory.project_id == seed.project_id
                    )
                )
            ).all()
        )
        assert "/" not in names
        assert "DRESSES" in names


@pytest.mark.asyncio
async def test_shelf_links_products_the_crawl_reached_only_by_canonical_url(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A shelf-scoped alias links its product even when never crawled itself.

    A sitemap offers the canonical `/products/<slug>` form, so the frontier
    fills with those and `/collections/<shelf>/products/<slug>` is never
    admitted at all -- there is no stored artifact to resolve it through. The
    shelf page still links only the alias, so matching stopped dead and all 19
    of a storefront's collections reported zero products while each shelf
    named 25 of them.

    The un-shelfed form is derived as a CANDIDATE and matched against the
    catalog like any other, so a URL no product claims still links nothing.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert task is not None
        category_url, category_hash = canonical_identity(
            "https://example.com/collections/dresses"
        )
        product_url, _hash = canonical_identity(
            "https://example.com/products/linen-dress"
        )
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=category_url,
            url_hash=category_hash,
            display_url=category_url,
            latest_title="Dresses",
        )
        product = CommerceProduct(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            canonical_url=product_url,
            name="Linen Dress",
        )
        session.add_all([site_url, product])
        await session.flush()
        task.site_url_id = site_url.id
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="discover",
            requested_url=category_url,
            final_url=category_url,
            normalized_facts={
                "canonical_url": category_url,
                "headings": {"h1_texts": ["Dresses"]},
                "commerce": {"category_role": "leaf", "product_cards": []},
                "links": {
                    "anchors": [
                        # Only the shelf-scoped alias is ever linked, and it
                        # has no SiteUrl row of its own.
                        {
                            "url": "/collections/dresses/products/linen-dress",
                            "region": "main",
                        },
                        # A shelf-scoped URL no product claims links nothing.
                        {
                            "url": "/collections/dresses/products/not-in-catalog",
                            "region": "main",
                        },
                    ]
                },
            },
        )
        session.add(artifact)
        await session.flush()
        analysis = SitePageAnalysis(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=seed.crawl_id,
            site_url_id=site_url.id,
            artifact_id=artifact.id,
            status="completed",
            page_kind="category",
        )
        session.add(analysis)
        await session.flush()

        await _project_category_source(
            session, analysis=analysis, artifact=artifact, site_url=site_url
        )
        await session.commit()

        category = await session.scalar(
            select(CommerceCategory).where(
                CommerceCategory.project_id == seed.project_id,
                CommerceCategory.normalized_name == "dresses",
            )
        )
        assert category is not None
        memberships = list(
            (
                await session.scalars(
                    select(CommerceProductCategory.product_id).where(
                        CommerceProductCategory.category_id == category.id
                    )
                )
            ).all()
        )
        assert memberships == [product.id]
