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
    APPLICABILITY_CRAWL_FINALIZE,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.core.config.task_queue import (
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.score_summary import (
    load_crawl_measurement_projection,
    refresh_live_score_summary,
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
from app.workers.site_health.lifecycle_finalize import (
    _canonical_resolution_evaluations,
)
from tests.component.site_health_worker_helpers import (
    _analyses_by_page_url,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
    _worker,
)


def test_canonical_resolution_is_persisted_for_each_shared_artifact_analysis() -> None:
    artifact_id = uuid.uuid4()
    analysis_ids = [uuid.uuid4(), uuid.uuid4()]
    target = "https://example.com/shared"
    source_ids = (uuid.uuid4(), uuid.uuid4(), None)

    evaluations = _canonical_resolution_evaluations(
        [(artifact_id, target, {"canonical_url": target})],
        analysis_ids_by_artifact={artifact_id: analysis_ids},
        resolutions={target: (200, target, False, *source_ids)},
    )

    assert [analysis_id for analysis_id, _evaluation in evaluations] == analysis_ids


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
                web_fundamentals_score=score,
                web_fundamentals_coverage=1.0,
                web_fundamentals_state="measured",
                technical_earned_weight=score / 100.0,
                technical_determinate_weight=1.0,
                technical_expected_weight=1.0,
                technical_critical_complete=True,
                is_current=analysis_id == high_analysis_id,
                created_at=same_created_at,
            )
            session.add(analysis)
            analyses.append(analysis)
        await session.flush()

        latest_evaluation_id = None
        for index, (analysis, artifact) in enumerate(
            zip(analyses, artifacts, strict=True)
        ):
            evaluation = SiteRuleEvaluation(
                workspace_id=seed.workspace_id,
                analysis_id=analysis.id,
                source_artifact_id=artifact.id,
                rule_id=("rule-0" if index == 0 else "technical.ttfb_band"),
                dimension="technical",
                category="stale" if index == 0 else "fresh",
                severity="high",
                weight=1.0,
                outcome=RULE_OUTCOME_MISSING,
                expected_profile_membership=True,
                score_roles=["web_fundamentals"],
            )
            session.add(evaluation)
            await session.flush()
            if analysis.id == high_analysis_id:
                latest_evaluation_id = evaluation.id
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
        assert await refresh_live_score_summary(session, crawl=crawl)
        assert crawl.score_summary is not None
        assert crawl.score_summary["analyzed_count"] == 1
        assert crawl.score_summary["web_fundamentals_score"] == 0.0
        assert crawl.score_summary["web_fundamentals_state"] == "measured"
        # The same call the worker's terminalization makes (its
        # ``_persist_snapshot`` is a thin ``persist_empty=True`` delegation).
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)
        latest_artifact_id = artifacts[1].id
        latest_task_id = second_task.id
        await session.commit()

    assert latest_evaluation_id is not None

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        # Site aggregation is rebuilt from immutable rule rows; the stale
        # per-page scalar is not a second scoring authority.
        assert snapshot.web_fundamentals_score == 0.0
        assert snapshot.source_analysis_ids == [high_analysis_id]
        assert snapshot.source_artifact_ids == [latest_artifact_id]
        assert snapshot.source_evaluation_ids == [latest_evaluation_id]
        assert snapshot.source_task_ids == [latest_task_id]
        assert snapshot.issue_count == 1
        assert snapshot.technical_defect_count == 1
        assert snapshot.technical_defect_affected_page_count == 1
        assert snapshot.aeo_readiness_gap_count == 0
        assert snapshot.aeo_readiness_gap_affected_page_count == 0
        assert snapshot.category_counts == {"fresh": 1}
        assert snapshot.coverage_evidence["measured_check_count"] == 1
        assert snapshot.coverage_evidence["expected_check_count"] == 1
        assert snapshot.trend == {
            "state": "unavailable",
            "reason": "no_comparable_snapshot",
            "metric": "aeo_readiness_score",
            "series": [
                {
                    "label": snapshot.created_at.date().isoformat(),
                    "value": snapshot.aeo_readiness_score,
                }
            ],
        }
        assert snapshot.change_summary["state"] == "unavailable"
        assert len(snapshot.change_summary["metrics"]) == 4
        assert snapshot.aeo_readiness_diagnostic["crawl_id"] == str(seed.crawl_id)
        assert snapshot.aeo_readiness_diagnostic["source_analysis_ids"] == [
            str(high_analysis_id)
        ]
        assert len(snapshot.aeo_readiness_diagnostic["dimensions"]) == 7
        assert snapshot.web_fundamentals["state"] == "limited_evidence"
        assert snapshot.web_fundamentals["source_analysis_ids"] == [
            str(high_analysis_id)
        ]
        assert snapshot.web_fundamentals["source_artifact_ids"] == [
            str(latest_artifact_id)
        ]
        assert snapshot.web_fundamentals["source_evaluation_ids"] == [
            str(latest_evaluation_id)
        ]

    # A changed non-empty replay computes a different aggregate but loses the
    # immutable insert conflict. It must not overwrite the matching crawl
    # summary with that new computation.
    async with session_factory() as session:
        evaluation = await session.get(SiteRuleEvaluation, latest_evaluation_id)
        assert evaluation is not None
        evaluation.outcome = RULE_OUTCOME_SATISFIED
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        original_summary = dict(crawl.score_summary or {})
        await session.flush()
        changed = await load_crawl_measurement_projection(session, crawl=crawl)
        assert changed.aggregate.web_fundamentals_score == 100.0
        replayed = await persist_crawl_snapshot(
            session, crawl=crawl, persist_empty=True
        )
        await session.commit()
    assert replayed is False

    async with session_factory() as session:
        snapshot = await session.scalar(
            select(SiteHealthSnapshot).where(
                SiteHealthSnapshot.crawl_id == seed.crawl_id
            )
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert snapshot is not None
        assert crawl is not None
        assert snapshot.web_fundamentals_score == 0.0
        assert crawl.score_summary == original_summary
        assert crawl.score_summary["web_fundamentals_score"] == 0.0


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
        assert hreflang.outcome == RULE_OUTCOME_MISSING
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
        assert (
            sum(
                1
                for rule_id in issues
                if SITE_HEALTH_RULES_BY_ID[rule_id].applicability_key
                == APPLICABILITY_CRAWL_FINALIZE
            )
            > 0
        ), "the finalize issues must be part of what issue_count counted"
