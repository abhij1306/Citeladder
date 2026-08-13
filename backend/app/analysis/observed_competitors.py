"""Persist deterministic third-party domain candidates for human review."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.observed_competitors import (
    ANALYZER_VERSION,
    EXCLUDED_RESEARCH_DOMAINS,
    MAX_CANDIDATES_PER_AUDIT,
    MIN_DISTINCT_ENGINES,
    MIN_DISTINCT_PROMPTS,
)
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit
from app.models.brand import ObservedEntityCandidate


def _domain_matches_any(domain: str, excluded: set[str]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in excluded)


def _group_citations(citations, analysis_by_id, excluded):
    grouped: dict[str, dict[str, set | list]] = {}
    for citation in citations:
        domain = citation.domain.lower().removeprefix("www.")
        analysis = analysis_by_id.get(citation.analysis_id)
        if (
            not domain
            or _domain_matches_any(domain, excluded)
            or analysis is None
            or analysis.cohort not in {"core", "market_visibility", "brand_relevant"}
        ):
            continue
        bucket = grouped.setdefault(
            domain,
            {"prompts": set(), "engines": set(), "analyses": [], "artifacts": []},
        )
        bucket["prompts"].add(analysis.prompt_index)
        bucket["engines"].add(analysis.logical_engine)
        bucket["analyses"].append(str(analysis.id))
        if analysis.artifact_id is not None:
            bucket["artifacts"].append(str(analysis.artifact_id))
    return grouped


def _qualified_domains(grouped):
    qualified = [
        (domain, evidence)
        for domain, evidence in grouped.items()
        if len(evidence["prompts"]) >= MIN_DISTINCT_PROMPTS
        and len(evidence["engines"]) >= MIN_DISTINCT_ENGINES
    ]
    qualified.sort(
        key=lambda item: (
            -len(item[1]["prompts"]),
            -len(item[1]["engines"]),
            item[0],
        )
    )
    return qualified


def _candidate(audit: Audit, domain: str, evidence) -> ObservedEntityCandidate:
    return ObservedEntityCandidate(
        workspace_id=audit.workspace_id,
        project_id=audit.project_id,
        audit_id=audit.id,
        name=domain.split(".")[0].replace("-", " ").title(),
        domain=domain,
        qualification_reason=(
            "Repeatedly cited across market-specific prompts and answer engines. "
            "Product overlap and geographic relevance require human verification."
        ),
        prompt_count=len(evidence["prompts"]),
        engine_count=len(evidence["engines"]),
        market_relevant=False,
        analyzer_version=ANALYZER_VERSION,
        source_analysis_ids=sorted(set(evidence["analyses"])),
        source_artifact_ids=sorted(set(evidence["artifacts"])),
    )


async def persist_observed_competitors(
    session: AsyncSession,
    *,
    audit: Audit,
    analyses: list[ResponseAnalysis],
    config: Any,
) -> None:
    analysis_by_id = {item.id: item for item in analyses}
    tracked_domains = {
        domain.lower().removeprefix("www.")
        for competitor in config.competitors
        for domain in competitor.domains
    }
    excluded = {
        *EXCLUDED_RESEARCH_DOMAINS,
        *(domain.lower().removeprefix("www.") for domain in config.owned_domains),
        *(domain.lower().removeprefix("www.") for domain in config.unintended_domains),
        *tracked_domains,
    }
    citations = list(
        (
            await session.scalars(
                select(Citation)
                .where(
                    Citation.audit_id == audit.id,
                    Citation.classification == "third_party",
                )
                .order_by(Citation.domain.asc(), Citation.ordinal.asc())
            )
        ).all()
    )
    grouped = _group_citations(citations, analysis_by_id, excluded)
    for domain, evidence in _qualified_domains(grouped)[:MAX_CANDIDATES_PER_AUDIT]:
        session.add(_candidate(audit, domain, evidence))
