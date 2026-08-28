from __future__ import annotations

import uuid

from app.analysis.opportunities.detectors import (
    AnalysisEvidence,
    PromptSnapshotEvidence,
)
from app.analysis.opportunities.earned_detector import (
    detect_earned_source_opportunities,
)
from app.analysis.opportunities.source_mix import build_source_projection
from app.analysis.opportunities.source_patterns import CitationEvidence


def _analysis(index: int, *citations: CitationEvidence) -> AnalysisEvidence:
    return AnalysisEvidence(
        analysis_id=uuid.uuid4(),
        prompt_index=index,
        logical_engine="chatgpt",
        owned_citation_count=0,
        competitor_names=("Rival",),
        citations=tuple(citations),
        artifact_id=uuid.uuid4(),
    )


def _citation(domain: str, *, competitor: str | None = None) -> CitationEvidence:
    return CitationEvidence(
        domain=domain,
        url=f"https://{domain}/guide",
        title="Guide",
        is_owned=False,
        matched_competitor=competitor,
    )


def test_source_mix_deduplicates_within_answer_and_counts_across_answers() -> None:
    analyses = (
        _analysis(0, _citation("forbes.com"), _citation("forbes.com")),
        _analysis(
            1,
            _citation("forbes.com"),
            _citation("rival.test", competitor="Rival"),
        ),
    )
    snapshots = (
        PromptSnapshotEvidence(0, None, "Best tool?", "tools", "purchase"),
        PromptSnapshotEvidence(1, None, "Compare tools", "tools", "comparison"),
    )
    source_mix, action_mix, rollups = build_source_projection(
        analyses=analyses, snapshots=snapshots, gap_prompt_indices={0, 1}
    )
    assert source_mix["counts"] == {"competitive_evidence": 1, "earned": 2}
    assert source_mix["observation_count"] == 3
    assert action_mix["counts"] == {"earned": 2, "owned": 1}
    forbes = next(row for row in rollups if row["canonical_domain"] == "forbes.com")
    assert forbes["answer_count"] == 2
    assert forbes["usage_denominator"] == 2
    assert forbes["actionable"] is True
    assert len(detect_earned_source_opportunities(rollups)) == 1


def test_source_mix_preserves_not_applicable_and_unavailable() -> None:
    not_applicable, _, _ = build_source_projection(
        analyses=(), snapshots=(), gap_prompt_indices=set()
    )
    unavailable, _, _ = build_source_projection(
        analyses=(_analysis(0),),
        snapshots=(PromptSnapshotEvidence(0, None, "Question", "", ""),),
        gap_prompt_indices={0},
    )
    assert not_applicable["state"] == "not_applicable"
    assert unavailable["state"] == "unavailable"


def test_competitor_owned_never_becomes_an_earned_task() -> None:
    analyses = (
        _analysis(0, _citation("rival.test", competitor="Rival")),
        _analysis(0, _citation("rival.test", competitor="Rival")),
    )
    _, action_mix, rollups = build_source_projection(
        analyses=analyses,
        snapshots=(PromptSnapshotEvidence(0, None, "Question", "", ""),),
        gap_prompt_indices={0},
    )
    assert action_mix["counts"] == {"owned": 2}
    assert detect_earned_source_opportunities(rollups) == []
