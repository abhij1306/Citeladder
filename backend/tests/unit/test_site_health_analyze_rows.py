"""Focused persistence mechanics for Site Health page analysis rows."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_SATISFIED,
)
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.workers.site_health.phases.analyze_rows import (
    _persist_evaluations_and_issues,
)


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flush_count = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flush_count += 1


def _evaluation(rule_id: str, outcome: str) -> SimpleNamespace:
    return SimpleNamespace(
        rule_id=rule_id,
        rule_version="rule-v1",
        dimension="technical",
        category="delivery",
        severity="high",
        finding_class="defect",
        scope="page",
        weight=1.0,
        outcome=outcome,
        display_applicability=True,
        score_applicability=True,
        expected_profile_membership=True,
        reason_code="",
        score_roles=("web_fundamentals",),
        checkpoint_family="",
        readiness_dimension="",
        readiness_weight=0.0,
        evidence={"rule": rule_id},
        description=f"{rule_id} failed",
        remediation=f"Fix {rule_id}",
    )


@pytest.mark.asyncio
async def test_evaluations_and_issues_flush_as_two_ordered_batches() -> None:
    session = _RecordingSession()
    crawl = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        extractor_version="extractor-v1",
        analyzer_version="analyzer-v1",
    )
    analysis = SitePageAnalysis(id=uuid.uuid4())
    artifact_id = uuid.uuid4()
    evaluations = [
        _evaluation("technical.first", RULE_OUTCOME_SATISFIED),
        _evaluation("technical.second", RULE_OUTCOME_MISSING),
    ]

    await _persist_evaluations_and_issues(
        cast(Any, session),
        crawl=cast(Any, crawl),
        analysis=analysis,
        artifact_id=artifact_id,
        site_url_id=uuid.uuid4(),
        evaluations=cast(Any, evaluations),
    )

    persisted_evaluations = [
        row for row in session.added if isinstance(row, SiteRuleEvaluation)
    ]
    persisted_issues = [row for row in session.added if isinstance(row, SiteIssue)]
    assert session.flush_count == 2
    assert [row.rule_id for row in persisted_evaluations] == [
        "technical.first",
        "technical.second",
    ]
    assert analysis.source_evaluation_ids == [row.id for row in persisted_evaluations]
    assert [row.scope for row in persisted_evaluations] == ["page", "page"]
    assert len(persisted_issues) == 1
    assert persisted_issues[0].evaluation_id == persisted_evaluations[1].id


@pytest.mark.asyncio
async def test_failed_diagnostic_persists_without_creating_an_issue() -> None:
    session = _RecordingSession()
    crawl = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        extractor_version="extractor-v1",
        analyzer_version="analyzer-v1",
    )
    analysis = SitePageAnalysis(id=uuid.uuid4())
    diagnostic = _evaluation("aeo.server_rendered_content", RULE_OUTCOME_MISSING)
    diagnostic.finding_class = "diagnostic"

    await _persist_evaluations_and_issues(
        cast(Any, session),
        crawl=cast(Any, crawl),
        analysis=analysis,
        artifact_id=uuid.uuid4(),
        site_url_id=uuid.uuid4(),
        evaluations=cast(Any, [diagnostic]),
    )

    assert (
        len([row for row in session.added if isinstance(row, SiteRuleEvaluation)]) == 1
    )
    assert not [row for row in session.added if isinstance(row, SiteIssue)]


@pytest.mark.asyncio
async def test_non_scoring_guidance_does_not_create_an_issue() -> None:
    session = _RecordingSession()
    crawl = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        extractor_version="extractor-v1",
        analyzer_version="analyzer-v1",
    )
    guidance = _evaluation("technical.title_length_band", RULE_OUTCOME_MISSING)
    guidance.finding_class = "advisory"
    guidance.score_roles = ()

    await _persist_evaluations_and_issues(
        cast(Any, session),
        crawl=cast(Any, crawl),
        analysis=SitePageAnalysis(id=uuid.uuid4()),
        artifact_id=uuid.uuid4(),
        site_url_id=uuid.uuid4(),
        evaluations=cast(Any, [guidance]),
    )

    assert not [row for row in session.added if isinstance(row, SiteIssue)]
