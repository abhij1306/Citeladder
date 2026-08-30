"""Persistence, provenance, and tenancy for observed architecture."""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.domain.site_health.architecture as architecture_domain
from app.core.config.site_health_archetypes import (
    ARCHETYPE_POLICY_VERSION,
    ARCHITECTURE_FORMULA_VERSION,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    EXTRACTOR_VERSION,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_UNAVAILABLE,
    TASK_KIND_ARCHITECTURE,
)
from app.core.config.site_health_link_metrics import COVERAGE_STATE_PARTIAL
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.site_health.architecture import persist_observed_architecture
from app.domain.site_health.architecture_queue import enqueue_architecture_refresh
from app.models.site_health.analysis import SiteRuleEvaluation
from app.models.site_health.architecture import SiteObservedArchitecture
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from tests.component.site_health_worker_helpers import (
    _seed_analyze_phase_crawl,
    _worker,
)


@pytest.mark.asyncio
async def test_architecture_runs_after_link_metrics_with_exact_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/"
    product = "https://example.com/products/widget"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, product)
        )

    pages = {
        "/": (
            b"<html><head><title>Home</title></head><body><main>"
            b'<a href="/products/widget">Widget</a>'
            b"</main></body></html>"
        ),
        "/products/widget": (
            b"<html><head><title>Widget</title></head><body><main>"
            b'<nav aria-label="Breadcrumb"><a href="/">Home</a></nav>'
            b'<a href="/">Home</a>'
            b"</main></body></html>"
        ),
    }
    await _worker(session_factory, pages, owner="architecture").run_until_idle()

    async with session_factory() as session:
        architecture = await session.scalar(
            select(SiteObservedArchitecture).where(
                SiteObservedArchitecture.workspace_id == seed.workspace_id,
                SiteObservedArchitecture.project_id == seed.project_id,
                SiteObservedArchitecture.crawl_id == seed.crawl_id,
            )
        )
        assert architecture is not None
        assert architecture.coverage_state == COVERAGE_STATE_PARTIAL
        assert architecture.page_count == 2
        assert architecture.architecture_formula_version == ARCHITECTURE_FORMULA_VERSION
        assert architecture.archetype_policy_version == ARCHETYPE_POLICY_VERSION
        assert len(architecture.source_analysis_ids or []) == 2
        assert len(architecture.source_artifact_ids or []) == 2
        assert len(architecture.source_link_metric_ids or []) == 2
        assert len(architecture.source_evaluation_ids or []) == 2
        assert architecture.source_snapshot_id is not None
        assert architecture.source_brand_profile_id is None
        assert (architecture.archetype or {})["archetype"] == "other"
        assert (architecture.archetype or {})["reason"] == "profile_absent"

        task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ARCHITECTURE,
            )
        )
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED

        absence_evaluations = list(
            (
                await session.scalars(
                    select(SiteRuleEvaluation).where(
                        SiteRuleEvaluation.analysis_id.in_(
                            architecture.source_analysis_ids
                        ),
                        SiteRuleEvaluation.rule_id.in_(
                            {
                                "architecture.orphan_pages",
                                "architecture.parentless_detail_pages",
                                "architecture.unhubbed_page_kind",
                            }
                        ),
                    )
                )
            ).all()
        )
        assert len(absence_evaluations) == 3
        assert {row.outcome for row in absence_evaluations} == {
            RULE_OUTCOME_UNAVAILABLE
        }
        assert {(row.evidence or {}).get("reason") for row in absence_evaluations} == {
            "coverage_not_complete"
        }
        assert {row.source_architecture_id for row in absence_evaluations} == {
            architecture.id
        }

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert await persist_observed_architecture(session, crawl=crawl) == 0
        await session.commit()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SiteObservedArchitecture)
                .where(SiteObservedArchitecture.crawl_id == seed.crawl_id)
            )
            == 1
        )

        monkeypatch.setattr(
            architecture_domain, "ARCHITECTURE_FORMULA_VERSION", "sh-architecture-2"
        )
        assert await persist_observed_architecture(session, crawl=crawl) == 1
        await session.commit()
        architectures = list(
            (
                await session.scalars(
                    select(SiteObservedArchitecture).where(
                        SiteObservedArchitecture.crawl_id == seed.crawl_id
                    )
                )
            ).all()
        )
        architecture_ids = {row.id for row in architectures}
        structural_evaluations = list(
            (
                await session.scalars(
                    select(SiteRuleEvaluation).where(
                        SiteRuleEvaluation.analysis_id.in_(
                            architecture.source_analysis_ids
                        ),
                        SiteRuleEvaluation.category == "architecture",
                    )
                )
            ).all()
        )
        assert {row.architecture_formula_version for row in architectures} == {
            ARCHITECTURE_FORMULA_VERSION,
            "sh-architecture-2",
        }
        assert len(structural_evaluations) == 12
        assert {
            row.source_architecture_id for row in structural_evaluations
        } == architecture_ids


@pytest.mark.asyncio
async def test_architecture_queue_uses_effective_versions_for_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed, _ = await _seed_analyze_phase_crawl(
            session,
            root="https://example.com/",
            urls=("https://example.com/",),
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.extractor_version = ""
        crawl.analyzer_version = ""
        crawl.rule_catalog_version = ""
        await enqueue_architecture_refresh(session, crawl=crawl)
        await enqueue_architecture_refresh(session, crawl=crawl)
        await session.commit()

        tasks = list(
            (
                await session.scalars(
                    select(SiteCrawlTask).where(
                        SiteCrawlTask.crawl_id == seed.crawl_id,
                        SiteCrawlTask.task_kind == TASK_KIND_ARCHITECTURE,
                    )
                )
            ).all()
        )
        version = (
            f"{EXTRACTOR_VERSION}:{ANALYZER_VERSION}:{RULE_CATALOG_VERSION}:"
            f"{ARCHITECTURE_FORMULA_VERSION}:{ARCHETYPE_POLICY_VERSION}"
        )
        assert len(tasks) == 1
        assert tasks[0].idempotency_key == (
            f"{seed.crawl_id}:{TASK_KIND_ARCHITECTURE}:{version}"
        )
        assert (
            tasks[0].url_hash
            == hashlib.sha256(
                f"architecture:{seed.crawl_id}:{version}".encode()
            ).hexdigest()
        )


@pytest.mark.asyncio
async def test_architecture_composite_fk_rejects_cross_workspace_crawl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first, _ = await _seed_analyze_phase_crawl(
            session,
            root="https://first.example/",
            urls=("https://first.example/",),
        )
        second, _ = await _seed_analyze_phase_crawl(
            session,
            root="https://second.example/",
            urls=("https://second.example/",),
        )
        first_snapshot = SiteHealthSnapshot(
            workspace_id=first.workspace_id,
            project_id=first.project_id,
            crawl_id=first.crawl_id,
        )
        session.add(first_snapshot)
        await session.flush()
        session.add(
            SiteObservedArchitecture(
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                crawl_id=second.crawl_id,
                source_snapshot_id=first_snapshot.id,
                architecture_formula_version=ARCHITECTURE_FORMULA_VERSION,
                archetype_policy_version=ARCHETYPE_POLICY_VERSION,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
