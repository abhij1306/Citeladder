"""Crawl snapshot selection and finalize-pass scenarios.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    TASK_KIND_ANALYZE,
)
from app.core.config.task_queue import (
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.workers.site_health.helpers import _is_crawl_finalize_rule
from tests.component.site_health_worker_helpers import (
    _analyses_by_page_url,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
    _worker,
)


@pytest.mark.asyncio
async def test_snapshot_uses_only_latest_completed_analysis_and_issues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Equal timestamps use UUID tie-break; stale scores/issues stay excluded."""
    from app.core.config.site_health_acquisition import (
        FETCH_PURPOSE_ANALYZE,
    )
    from app.core.config.site_health_contracts import (
        PAGE_ANALYSIS_STATUS_COMPLETED,
    )

    seed, site_url_id, first_task_id = await _seed_analyze_ready(session_factory)
    same_created_at = datetime.now(UTC)
    low_analysis_id = uuid.UUID(int=1)
    high_analysis_id = uuid.UUID(int=2)

    async with session_factory() as session:
        first_task = await session.get(SiteCrawlTask, first_task_id)
        assert first_task is not None
        first_task.status = TASK_STATUS_SUCCEEDED
        second_task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            site_url_id=site_url_id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url="https://example.com/rich",
            url_hash=first_task.url_hash,
            generation=1,
            idempotency_key=f"{seed.crawl_id}:analyze:latest:1",
            status=TASK_STATUS_SUCCEEDED,
            randomized_position=1,
        )
        session.add(second_task)
        await session.flush()

        artifacts = []
        for task in (first_task, second_task):
            artifact = SiteFetchArtifact(
                task_id=task.id,
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                fetch_purpose=FETCH_PURPOSE_ANALYZE,
                requested_url=task.requested_url,
                final_url=task.requested_url,
            )
            session.add(artifact)
            artifacts.append(artifact)
        await session.flush()

        analyses = []
        for analysis_id, artifact, score in (
            (low_analysis_id, artifacts[0], 10.0),
            (high_analysis_id, artifacts[1], 90.0),
        ):
            analysis = SitePageAnalysis(
                id=analysis_id,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                artifact_id=artifact.id,
                status=PAGE_ANALYSIS_STATUS_COMPLETED,
                technical_score=score,
                aeo_score=score,
                overall_score=score,
                is_current=analysis_id == high_analysis_id,
                created_at=same_created_at,
            )
            session.add(analysis)
            analyses.append(analysis)
        await session.flush()

        for index, (analysis, artifact) in enumerate(
            zip(analyses, artifacts, strict=True)
        ):
            evaluation = SiteRuleEvaluation(
                workspace_id=seed.workspace_id,
                analysis_id=analysis.id,
                source_artifact_id=artifact.id,
                rule_id=f"rule-{index}",
                dimension="technical",
                category="stale" if index == 0 else "fresh",
                severity="high",
                weight=1.0,
                outcome=RULE_OUTCOME_FAIL,
            )
            session.add(evaluation)
            await session.flush()
            session.add(
                SiteIssue(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    crawl_id=seed.crawl_id,
                    site_url_id=site_url_id,
                    analysis_id=analysis.id,
                    evaluation_id=evaluation.id,
                    source_artifact_id=artifact.id,
                    rule_id=evaluation.rule_id,
                    dimension="technical",
                    category=evaluation.category,
                    severity="high",
                )
            )
        # This block stands in for the finalize-pass writer, so it flushes the
        # way that writer does: the snapshot aggregates issues with a SELECT,
        # and sessions here (like production's) do not autoflush.
        await session.flush()

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        # The same call the worker's terminalization makes (its
        # ``_persist_snapshot`` is a thin ``persist_empty=True`` delegation).
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)
        latest_artifact_id = artifacts[1].id
        await session.commit()

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        assert snapshot.overall_score == 90.0
        assert snapshot.source_analysis_ids == [high_analysis_id]
        assert snapshot.source_artifact_ids == [latest_artifact_id]
        assert snapshot.issue_count == 1
        assert snapshot.category_counts == {"fresh": 1}


@pytest.mark.asyncio
async def test_finalize_pass_hreflang_conflict_end_to_end(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The finalize pass detects a missing hreflang return tag from page facts."""
    root = "https://example.com/rich"
    second = "https://example.com/fr"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, second)
        )

    root_html = (
        b"<html><head><title>Root page about widgets and gadgets</title>"
        b'<link rel="alternate" hreflang="fr" href="https://example.com/fr">'
        b"</head><body><h1>Root</h1>"
        b"<p>Root body text with enough words to matter for the checks.</p>"
        b'<a href="https://example.com/fr">fr</a>'
        b"</body></html>"
    )
    fr_html = b"<html><head><title>FR</title></head><body><p>bonjour</p></body></html>"
    pages = {"/rich": root_html, "/fr": fr_html}
    worker = _worker(session_factory, pages, owner="p2-hreflang")
    await worker.run_until_idle()

    async with session_factory() as session:
        by_url = await _analyses_by_page_url(session, seed)
        assert len(by_url) == 2
        root_analysis = by_url["https://example.com/rich"]
        fr_analysis = by_url["https://example.com/fr"]

        async def _evals(analysis_id):
            rows = (
                (
                    await session.execute(
                        select(SiteRuleEvaluation).where(
                            SiteRuleEvaluation.analysis_id == analysis_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return {row.rule_id: row for row in rows}

        root_evals = await _evals(root_analysis.id)
        hreflang = root_evals["technical.hreflang_conflict"]
        assert hreflang.outcome == RULE_OUTCOME_FAIL
        assert hreflang.evidence["alternate_count"] == 1
        assert hreflang.evidence["checked_count"] == 1
        assert hreflang.evidence["missing_return_tags"] == ["https://example.com/fr"]

        # The counterpart page's own finalize rows are clean N/As.
        fr_evals = await _evals(fr_analysis.id)
        fr_hreflang = fr_evals["technical.hreflang_conflict"]
        assert fr_hreflang.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert fr_hreflang.evidence["reason"] == "no_hreflang"

        # The failure surfaces as an issue and enters the snapshot rollup.
        issues = (
            (
                await session.execute(
                    select(SiteIssue.rule_id).where(SiteIssue.crawl_id == seed.crawl_id)
                )
            )
            .scalars()
            .all()
        )
        assert "technical.hreflang_conflict" in issues

        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 2
        # The crawl_finalize pass runs BEFORE the snapshot precisely so its
        # issues land in the rollup. It writes them with ``session.add`` and
        # production sessions do not autoflush, so without an explicit flush
        # the snapshot's SELECT could not see them and this count came back
        # short by exactly the finalize findings.
        assert snapshot.issue_count == len(issues)
        assert sum(1 for rule_id in issues if _is_crawl_finalize_rule(rule_id)) > 0, (
            "the finalize issues must be part of what issue_count counted"
        )
