"""Persist deterministic third-party domain candidates for human review."""

from __future__ import annotations

from dataclasses import dataclass, field
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
from app.core.config.prompts import ORGANIC_PROMPT_COHORTS
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import Audit
from app.models.brand import ObservedEntityCandidate


def _domain_matches_any(domain: str, excluded: set[str]) -> bool:
    return any(domain == item or domain.endswith(f".{item}") for item in excluded)


@dataclass
class _DomainEvidence:
    """Distinct prompts/engines that cited one domain, plus its provenance.

    A ``dict[str, set | list]`` bucket used to carry these four fields, which
    made every ``.add``/``.append`` an unchecked call on the union.
    """

    prompts: set[int] = field(default_factory=set)
    engines: set[str] = field(default_factory=set)
    analyses: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)


def _group_citations(
    citations: list[Citation],
    analysis_by_id: dict[Any, ResponseAnalysis],
    excluded: set[str],
) -> dict[str, _DomainEvidence]:
    grouped: dict[str, _DomainEvidence] = {}
    for citation in citations:
        domain = citation.domain.lower().removeprefix("www.")
        analysis = analysis_by_id.get(citation.analysis_id)
        if (
            not domain
            or _domain_matches_any(domain, excluded)
            or analysis is None
            or analysis.cohort not in ORGANIC_PROMPT_COHORTS
        ):
            continue
        bucket = grouped.setdefault(domain, _DomainEvidence())
        bucket.prompts.add(analysis.prompt_index)
        bucket.engines.add(analysis.logical_engine)
        bucket.analyses.append(str(analysis.id))
        if analysis.artifact_id is not None:
            bucket.artifacts.append(str(analysis.artifact_id))
    return grouped


def _qualified_domains(
    grouped: dict[str, _DomainEvidence],
) -> list[tuple[str, _DomainEvidence]]:
    qualified = [
        (domain, evidence)
        for domain, evidence in grouped.items()
        if len(evidence.prompts) >= MIN_DISTINCT_PROMPTS
        and len(evidence.engines) >= MIN_DISTINCT_ENGINES
    ]
    qualified.sort(
        key=lambda item: (
            -len(item[1].prompts),
            -len(item[1].engines),
            item[0],
        )
    )
    return qualified


def _candidate(
    audit: Audit, domain: str, evidence: _DomainEvidence
) -> ObservedEntityCandidate:
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
        prompt_count=len(evidence.prompts),
        engine_count=len(evidence.engines),
        market_relevant=False,
        analyzer_version=ANALYZER_VERSION,
        source_analysis_ids=sorted(set(evidence.analyses)),
        source_artifact_ids=sorted(set(evidence.artifacts)),
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
