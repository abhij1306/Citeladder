"""Focused persistence mechanics for Site Health page analysis rows."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.workers.site_health.phases.analyze_rows import (
    _persist_evaluations_and_issues,
    _prepare_page_evaluation,
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
        weight=1.0,
        outcome=outcome,
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
        _evaluation("technical.first", "pass"),
        _evaluation("technical.second", "fail"),
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
    assert len(persisted_issues) == 1
    assert persisted_issues[0].evaluation_id == persisted_evaluations[1].id


def test_prepare_page_evaluation_injects_classifier_evidence() -> None:
    """The evaluation copy must carry the tier the confidence gate reads.

    ``_kind_expectation_allowed`` opens when ``page_kind_evidence`` is absent,
    so if this injection were ever dropped the gate would silently stop
    gating. Asserting the injection here is what makes that fail-open safe.
    """
    crawl = SimpleNamespace(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        root_url="https://x.example/",
        site_facts=None,
        analyzer_version="",
        scoring_version="",
    )
    task = SimpleNamespace(url_hash="whatever")
    facts = {
        "has_html": True,
        "title": "Acme",
        "body": {"word_count": 40, "text": "word " * 40},
        "delivery": {"final_url": "https://x.example/", "is_https": True},
        "headings": {"h1_count": 1, "counts": {"h1": 1}, "h1_texts": ["Acme"]},
        "structured_data": {"count": 0, "blocks": [], "types": []},
    }

    assessment, evaluations, _scores = _prepare_page_evaluation(
        crawl=cast(Any, crawl), task=cast(Any, task), facts=facts
    )

    assert assessment.tier
    assert "tier" in assessment.to_evidence()
    # The artifact's own facts are never mutated by the evaluation copy.
    assert "page_kind" not in facts
    assert "page_kind_evidence" not in facts
    assert evaluations
