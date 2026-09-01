"""Crawl snapshot selection and finalize-pass scenarios.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    CRAWL_STATUS_COMPLETED,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    CORPUS_DISPOSITION_EXCLUDE,
    SELECTION_SOURCE_BOOTSTRAP,
    SELECTION_SOURCE_USER,
    URL_EXCLUSION_DUPLICATE,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.canonical_aliases import (
    _AliasGraph,
    _load_alias_graph,
    _resolved_duplicate_targets,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.score_summary import (
    _classified_evidence,
    load_crawl_measurement_projection,
    refresh_live_score_summary,
)
from app.domain.site_health.service.issues import get_issues
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
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation
from app.workers.site_health.phases import analyze as analyze_phase
from app.workers.site_health.resolution_evidence import (
    canonical_resolution_evaluations,
)
from tests.component.site_health_worker_helpers import (
    _analyses_by_page_url,
    _rich_html,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
    _worker,
)


def test_classification_projection_rejects_analysis_from_older_task_artifact() -> None:
    site_url_id = uuid.uuid4()
    current_artifact_id = uuid.uuid4()
    stale_row = SimpleNamespace(
        id=uuid.uuid4(),
        site_url_id=site_url_id,
        artifact_id=uuid.uuid4(),
        page_kind="article",
        page_kind_evidence={},
    )
    current_task = SimpleNamespace(result_artifact_id=current_artifact_id)

    evidence = _classified_evidence(
        [stale_row],
        {site_url_id: current_task},
    )

    assert evidence.classified_count == 0
    assert evidence.completed_site_url_ids == set()


def test_canonical_resolution_is_persisted_for_each_shared_artifact_analysis() -> None:
    artifact_id = uuid.uuid4()
    analysis_ids = [uuid.uuid4(), uuid.uuid4()]
    target = "https://example.com/shared"
    source_ids = (uuid.uuid4(), uuid.uuid4(), None)

    evaluations = canonical_resolution_evaluations(
        [(artifact_id, target, {"canonical_url": target})],
        analysis_ids_by_artifact={artifact_id: analysis_ids},
        resolutions={target: (200, target, False, *source_ids)},
    )

    assert [analysis_id for analysis_id, _evaluation in evaluations] == analysis_ids


def _alias_graph(
    edges: dict[str, str],
    *,
    active: set[str] | None = None,
    protected: set[str] | None = None,
    known: set[str] | None = None,
) -> _AliasGraph:
    hashes = set(edges) | set(edges.values())
    active_hashes = hashes if active is None else active
    protected_hashes = protected or set()
    return _AliasGraph(
        site_url_ids={value: uuid.uuid4() for value in hashes},
        active_hashes=active_hashes,
        protected_hashes=protected_hashes,
        candidate_hashes=active_hashes - protected_hashes,
        known_hashes=hashes if known is None else known,
        edges=edges,
    )


def test_alias_chain_resolves_every_duplicate_to_retained_sink() -> None:
    graph = _alias_graph({"alias-a": "alias-b", "alias-b": "canonical"})

    assert _resolved_duplicate_targets(graph) == {
        "alias-a": "canonical",
        "alias-b": "canonical",
    }


def test_alias_cycle_retains_one_deterministic_representative() -> None:
    graph = _alias_graph(
        {"alias-b": "alias-a", "alias-a": "alias-b", "incoming": "alias-b"}
    )

    assert _resolved_duplicate_targets(graph) == {
        "alias-b": "alias-a",
        "incoming": "alias-a",
    }


def test_alias_resolution_preserves_user_selection_and_unknown_target() -> None:
    protected = _alias_graph({"system": "user", "user": "system"}, protected={"user"})
    unresolved = _alias_graph({"system": "unfetched"}, known={"system"})

    assert _resolved_duplicate_targets(protected) == {"system": "user"}
    assert _resolved_duplicate_targets(unresolved) == {}


def test_alias_chain_can_traverse_an_already_excluded_intermediate() -> None:
    graph = _alias_graph(
        {"alias": "old-alias", "old-alias": "canonical"},
        active={"alias", "canonical"},
    )

    assert _resolved_duplicate_targets(graph) == {"alias": "canonical"}


@pytest.mark.asyncio
async def test_alias_graph_uses_latest_artifact_even_when_facts_are_missing() -> None:
    source = "https://example.com/alias"
    target = "https://example.com/canonical"
    _, source_hash = canonical_identity(source)
    _, target_hash = canonical_identity(target)
    session = AsyncMock()
    session.execute.side_effect = [
        [
            (uuid.uuid4(), source_hash, True, SELECTION_SOURCE_BOOTSTRAP),
            (uuid.uuid4(), target_hash, True, SELECTION_SOURCE_BOOTSTRAP),
        ],
        [
            (source_hash, source, {"canonical_url": target}),
            (source_hash, source, None),
        ],
    ]
    crawl = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        root_url=source,
        configuration={"root_registrable_domain": "example.com"},
    )

    graph = await _load_alias_graph(session, crawl=crawl)

    admitted_query = str(session.execute.await_args_list[0].args[0])
    artifact_query = str(session.execute.await_args_list[1].args[0])
    assert "SELECT DISTINCT" in admitted_query
    assert "normalized_facts IS NOT NULL" not in artifact_query
    assert source_hash in graph.known_hashes
    assert source_hash not in graph.edges


@pytest.mark.asyncio
async def test_terminal_reconciliation_excludes_late_system_alias_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    canonical = "https://example.com/products/widget"
    system_alias = "https://example.com/collections/sale/products/widget"
    user_alias = "https://example.com/collections/selected/products/widget"
    urls = (canonical, system_alias, user_alias)
    async with session_factory() as session:
        seed, ids = await _seed_analyze_phase_crawl(session, root=canonical, urls=urls)
        site_url_ids = [site_url_id for site_url_id, _task_id in ids]
        memberships = list(
            await session.scalars(
                select(MonitoredSiteUrl).where(
                    MonitoredSiteUrl.workspace_id == seed.workspace_id,
                    MonitoredSiteUrl.project_id == seed.project_id,
                    MonitoredSiteUrl.site_url_id.in_(site_url_ids),
                )
            )
        )
        membership_by_url_id = {row.site_url_id: row for row in memberships}
        membership_by_url_id[
            site_url_ids[0]
        ].selection_source = SELECTION_SOURCE_BOOTSTRAP
        membership_by_url_id[
            site_url_ids[1]
        ].selection_source = SELECTION_SOURCE_BOOTSTRAP
        assert membership_by_url_id[site_url_ids[2]].selection_source == (
            SELECTION_SOURCE_USER
        )
        for site_url_id, url in zip(site_url_ids, urls, strict=True):
            session.add(
                SiteUrlObservation(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    crawl_id=seed.crawl_id,
                    site_url_id=site_url_id,
                    source_kind="link",
                    observed_url=url,
                    final_url=url,
                    status_code=200,
                    content_type="text/html",
                )
            )
        await session.commit()

    def _page(*, declared_canonical: str, hreflang: bool = False) -> bytes:
        alternate = (
            f'<link rel="alternate" hreflang="en" href="{canonical}">'
            if hreflang
            else ""
        )
        return (
            "<html lang='en'><head><title>Widget</title>"
            f'<link rel="canonical" href="{declared_canonical}">{alternate}'
            "</head><body><main><h1>Widget</h1><p>Widget details.</p>"
            "</main></body></html>"
        ).encode()

    worker = _worker(
        session_factory,
        {
            "/products/widget": _page(declared_canonical=canonical),
            "/collections/sale/products/widget": _page(
                declared_canonical=canonical, hreflang=True
            ),
            "/collections/selected/products/widget": _page(
                declared_canonical=canonical
            ),
        },
        owner="late-canonical-alias",
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        analyses = await _analyses_by_page_url(session, seed)
        assert analyses[canonical].is_current is True
        assert analyses[system_alias].is_current is False
        assert analyses[user_alias].is_current is True

        url_rows = list(
            await session.scalars(
                select(SiteUrl).where(
                    SiteUrl.workspace_id == seed.workspace_id,
                    SiteUrl.project_id == seed.project_id,
                    SiteUrl.normalized_url.in_(urls),
                )
            )
        )
        by_url = {row.normalized_url: row for row in url_rows}
        assert by_url[system_alias].corpus_disposition == CORPUS_DISPOSITION_EXCLUDE
        assert by_url[system_alias].disposition_reason == URL_EXCLUSION_DUPLICATE
        assert by_url[user_alias].corpus_disposition != CORPUS_DISPOSITION_EXCLUDE

        refreshed_memberships = list(
            await session.scalars(
                select(MonitoredSiteUrl).where(
                    MonitoredSiteUrl.workspace_id == seed.workspace_id,
                    MonitoredSiteUrl.project_id == seed.project_id,
                    MonitoredSiteUrl.site_url_id.in_(site_url_ids),
                )
            )
        )
        active_by_id = {row.site_url_id: row.active for row in refreshed_memberships}
        assert active_by_id[site_url_ids[1]] is False
        assert active_by_id[site_url_ids[2]] is True
        assert crawl.score_summary is not None
        assert crawl.score_summary["analyzed_count"] == 2

        alias_finalize_rules = list(
            await session.scalars(
                select(SiteRuleEvaluation.rule_id).where(
                    SiteRuleEvaluation.analysis_id == analyses[system_alias].id,
                    SiteRuleEvaluation.rule_id == "technical.hreflang_conflict",
                )
            )
        )
        assert alias_finalize_rules == []

        persisted_alias_issues = list(
            await session.scalars(
                select(SiteIssue.id).where(
                    SiteIssue.crawl_id == seed.crawl_id,
                    SiteIssue.site_url_id == site_url_ids[1],
                )
            )
        )
        assert persisted_alias_issues
        alias_issue_projection = await get_issues(
            session,
            workspace_id=seed.workspace_id,
            crawl_id=seed.crawl_id,
            limit=50,
            cursor=None,
            site_url_id=site_url_ids[1],
        )
        assert alias_issue_projection["items"] == []
        assert alias_issue_projection["summary"]["occurrence_count"] == 0


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
            "cohort_composition": {
                "added_page_kinds": [],
                "removed_page_kinds": [],
                "previous_page_count_by_kind": {},
                "current_page_count_by_kind": {},
            },
        }
        assert snapshot.change_summary["state"] == "unavailable"
        assert len(snapshot.change_summary["metrics"]) == 4
        assert snapshot.change_summary["cohort_composition"] == {
            "added_page_kinds": [],
            "removed_page_kinds": [],
            "previous_page_count_by_kind": {},
            "current_page_count_by_kind": {},
        }
        assert snapshot.aeo_readiness_diagnostic["crawl_id"] == str(seed.crawl_id)
        assert snapshot.aeo_readiness_diagnostic["source_analysis_ids"] == [
            str(high_analysis_id)
        ]
        assert len(snapshot.aeo_readiness_diagnostic["dimensions"]) == 7
        assert snapshot.web_fundamentals["state"] == "measured"
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
async def test_classification_only_terminal_snapshot_survives_without_analysis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert task is not None
        assert crawl is not None
        task.status = TASK_STATUS_CANCELLED
        task.error_code = ""
        task.classification_expected = True

        assert await persist_crawl_snapshot(session, crawl=crawl)
        await session.commit()

    async with session_factory() as session:
        snapshot = await session.scalar(
            select(SiteHealthSnapshot).where(
                SiteHealthSnapshot.crawl_id == seed.crawl_id
            )
        )
        assert snapshot is not None
        assert snapshot.source_analysis_ids == []
        assert snapshot.classification_expected_page_count == 1
        assert snapshot.classification_error_page_count == 1
        assert snapshot.classification_coverage == 0.0
        assert snapshot.classification_state == "partial"
        assert snapshot.classification_reason_groups == {"classification_failed": 1}
        assert snapshot.classification_source_task_ids == [task_id]


@pytest.mark.asyncio
async def test_terminal_snapshot_freezes_classification_cohort_and_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_url = "https://example.com/blog/classified"
    other_url = "https://example.com/unclassified"
    failed_url = "https://example.com/parser-failure"
    async with session_factory() as session:
        seed, ids = await _seed_analyze_phase_crawl(
            session,
            root=article_url,
            urls=(article_url, other_url, failed_url),
        )
    task_ids = [task_id for _site_url_id, task_id in ids]
    original_extract = analyze_phase.extract_page_facts

    def fail_one_page(body, **kwargs):
        if kwargs["final_url"] == failed_url:
            raise RuntimeError("classification parser failure")
        return original_extract(body, **kwargs)

    monkeypatch.setattr(analyze_phase, "extract_page_facts", fail_one_page)
    worker = _worker(
        session_factory,
        {
            "/blog/classified": _rich_html(),
            "/unclassified": _rich_html(),
            "/parser-failure": _rich_html(),
        },
        owner="classification-terminal-snapshot",
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = [
            task
            for task_id in task_ids
            if (task := await session.get(SiteCrawlTask, task_id)) is not None
        ]
        analyses = await _analyses_by_page_url(session, seed)
        snapshot = await session.scalar(
            select(SiteHealthSnapshot).where(
                SiteHealthSnapshot.crawl_id == seed.crawl_id
            )
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)

        assert len(tasks) == 3
        assert all(task.classification_expected for task in tasks)
        failed_task = next(task for task in tasks if task.requested_url == failed_url)
        assert failed_task.status == TASK_STATUS_FAILED
        assert failed_task.error_code == "crawl_task_crashed"
        assert set(analyses) == {article_url, other_url}
        assert analyses[article_url].page_kind == "article"
        assert analyses[other_url].page_kind == "other"
        other_evidence = analyses[other_url].page_kind_evidence
        assert other_evidence is not None
        assert other_evidence["other_reason"] == "no_classification_signals"
        assert snapshot is not None
        assert crawl is not None

        expected_analysis_ids = sorted(
            [analyses[article_url].id, analyses[other_url].id], key=str
        )
        expected_artifact_ids = sorted(
            [
                analyses[article_url].artifact_id,
                analyses[other_url].artifact_id,
            ],
            key=str,
        )
        expected_task_ids = sorted(task_ids, key=str)
        assert snapshot.classified_page_count == 1
        assert snapshot.other_page_count == 1
        assert snapshot.classification_error_page_count == 1
        assert snapshot.classification_expected_page_count == 3
        assert snapshot.classification_coverage == pytest.approx(1 / 3, abs=0.0001)
        assert snapshot.classification_state == "partial"
        assert snapshot.classification_reason_groups == {
            "crawl_task_crashed": 1,
            "no_classification_signals": 1,
        }
        assert snapshot.classification_formula_version == "sh-classification-1"
        assert snapshot.classification_source_analysis_ids == expected_analysis_ids
        assert snapshot.classification_source_artifact_ids == expected_artifact_ids
        assert snapshot.classification_source_task_ids == expected_task_ids
        assert snapshot.scored_page_kind_set == ["article"]
        assert snapshot.scored_page_count_by_kind == {"article": 1}

        summary = crawl.score_summary
        assert summary is not None
        assert summary["classified_page_count"] == 1
        assert summary["other_page_count"] == 1
        assert summary["classification_error_page_count"] == 1
        assert summary["classification_expected_page_count"] == 3
        assert summary["classification_coverage"] == pytest.approx(1 / 3, abs=0.0001)
        assert summary["classification_state"] == "partial"
        assert summary["classification_reason_groups"] == {
            "crawl_task_crashed": 1,
            "no_classification_signals": 1,
        }
        assert summary["classification_formula_version"] == "sh-classification-1"
        assert summary["classification_source_analysis_ids"] == [
            str(value) for value in expected_analysis_ids
        ]
        assert summary["classification_source_artifact_ids"] == [
            str(value) for value in expected_artifact_ids
        ]
        assert summary["classification_source_task_ids"] == [
            str(value) for value in expected_task_ids
        ]
        assert summary["scored_page_kind_set"] == ["article"]
        assert summary["scored_page_count_by_kind"] == {"article": 1}
        assert set(summary["by_page_kind"]) == {"article", "other"}
        assert summary["by_page_kind"]["article"]["aeo_readiness_score"] is not None
        assert summary["by_page_kind"]["other"]["aeo_readiness_score"] is None
        assert snapshot.aeo_readiness_score == summary["aeo_readiness_score"]
        assert (
            snapshot.aeo_readiness_score
            != summary["by_page_kind"]["article"]["aeo_readiness_score"]
        )


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
