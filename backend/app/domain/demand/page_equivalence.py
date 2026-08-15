"""Evidence-aware mapping from external URLs to owned ``SiteUrl`` identities.

This owner never changes crawler identity. Scheme, ``www``, and trailing-slash
variants are candidate discovery only; only an observed redirect or canonical
declaration can resolve a non-exact URL.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import UrlPolicyError, canonicalize
from app.core.config.demand import (
    PAGE_EQUIVALENCE_MAX_CANDIDATES,
    PAGE_EQUIVALENCE_RESOLVER_VERSION,
)
from app.models.site_health import SiteCrawlTask, SiteFetchArtifact, SiteUrl

ResolutionOutcome = Literal["exact", "resolved", "ambiguous", "unresolved"]


@dataclass(frozen=True)
class PageCandidate:
    site_url_id: uuid.UUID
    normalized_url: str
    evidence: tuple[str, ...] = ()
    sitemap_member: bool = False
    preferred_origin: bool = False


@dataclass(frozen=True)
class PageResolution:
    outcome: ResolutionOutcome
    site_url_id: uuid.UUID | None
    candidates: tuple[PageCandidate, ...]
    resolver_version: str = PAGE_EQUIVALENCE_RESOLVER_VERSION


class _ArtifactEvidence(Protocol):
    requested_url: str
    final_url: str
    normalized_facts: dict | None


def _safe_canonicalize(value: str) -> str | None:
    try:
        return canonicalize(value)
    except UrlPolicyError:
        return None


def _variant_urls(url: str) -> tuple[str, ...]:
    canonical = canonicalize(url)
    parts = urlsplit(canonical)
    host = parts.hostname or ""
    hosts = {host, host[4:] if host.startswith("www.") else f"www.{host}"}
    path = parts.path or "/"
    paths = {path}
    if path != "/":
        paths.add(path.rstrip("/") if path.endswith("/") else f"{path}/")
    variants: set[str] = set()
    for scheme in ("http", "https"):
        for candidate_host in hosts:
            for candidate_path in paths:
                value = _safe_canonicalize(
                    urlunsplit(
                        (scheme, candidate_host, candidate_path, parts.query, "")
                    )
                )
                if value:
                    variants.add(value)
    return tuple(sorted(variants))


def _artifact_proofs(
    *,
    requested_url: str,
    candidate_by_url: dict[str, PageCandidate],
    artifacts: Sequence[tuple[_ArtifactEvidence, uuid.UUID | None]],
) -> dict[uuid.UUID, set[str]]:
    proofs: dict[uuid.UUID, set[str]] = {}
    for artifact, source_site_url_id in artifacts:
        requested = _safe_canonicalize(artifact.requested_url)
        final = _safe_canonicalize(artifact.final_url)
        _add_redirect_proof(
            proofs,
            requested_url=requested_url,
            requested=requested,
            final=final,
            candidate_by_url=candidate_by_url,
        )
        _add_canonical_proof(
            proofs,
            requested_url=requested_url,
            requested=requested,
            source_site_url_id=source_site_url_id,
            artifact=artifact,
            candidate_by_url=candidate_by_url,
        )
    return proofs


def _add_redirect_proof(
    proofs: dict[uuid.UUID, set[str]],
    *,
    requested_url: str,
    requested: str | None,
    final: str | None,
    candidate_by_url: dict[str, PageCandidate],
) -> None:
    if (
        requested != requested_url
        or final not in candidate_by_url
        or final == requested
    ):
        return
    proofs.setdefault(candidate_by_url[final].site_url_id, set()).add("redirect")


def _add_canonical_proof(
    proofs: dict[uuid.UUID, set[str]],
    *,
    requested_url: str,
    requested: str | None,
    source_site_url_id: uuid.UUID | None,
    artifact: _ArtifactEvidence,
    candidate_by_url: dict[str, PageCandidate],
) -> None:
    facts = (
        artifact.normalized_facts
        if isinstance(artifact.normalized_facts, dict)
        else {}
    )
    declared = _safe_canonicalize(str(facts.get("canonical_url") or ""))
    source_matches = requested == requested_url or any(
        item.site_url_id == source_site_url_id
        and item.normalized_url == requested_url
        for item in candidate_by_url.values()
    )
    if not source_matches or declared not in candidate_by_url:
        return
    if declared == requested_url:
        return
    proofs.setdefault(candidate_by_url[declared].site_url_id, set()).add("canonical")


def _rank(candidate: PageCandidate) -> tuple[int, int, str, str]:
    return (
        -int(candidate.sitemap_member),
        -int(candidate.preferred_origin),
        candidate.normalized_url,
        str(candidate.site_url_id),
    )


async def resolve_owned_page(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    url: str,
    preferred_origin: str = "",
) -> PageResolution:
    """Resolve one external URL using persisted workspace-owned evidence."""
    requested = canonicalize(url)
    variants = _variant_urls(requested)
    rows = list(
        (
            await session.scalars(
                select(SiteUrl)
                .where(SiteUrl.workspace_id == workspace_id)
                .where(SiteUrl.project_id == project_id)
                .where(SiteUrl.normalized_url.in_(variants))
                .order_by(SiteUrl.normalized_url, SiteUrl.id)
                .limit(PAGE_EQUIVALENCE_MAX_CANDIDATES)
            )
        ).all()
    )
    exact = next((row for row in rows if row.normalized_url == requested), None)
    candidates = tuple(
        PageCandidate(
            site_url_id=row.id,
            normalized_url=row.normalized_url,
            sitemap_member=row.latest_source_kind == "sitemap",
            preferred_origin=bool(preferred_origin)
            and row.normalized_url.startswith(preferred_origin.rstrip("/") + "/"),
        )
        for row in rows
    )
    if exact is not None:
        return PageResolution("exact", exact.id, candidates)
    if not candidates:
        return PageResolution("unresolved", None, ())

    artifacts = await _load_candidate_artifacts(
        session,
        workspace_id=workspace_id,
        candidate_ids=[candidate.site_url_id for candidate in candidates],
    )
    return _resolve_from_artifacts(requested, candidates, artifacts)


async def _load_candidate_artifacts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    candidate_ids: list[uuid.UUID],
) -> list[tuple[SiteFetchArtifact, uuid.UUID | None]]:
    rows = (
        await session.execute(
            select(SiteFetchArtifact, SiteCrawlTask.site_url_id)
            .join(SiteCrawlTask, SiteCrawlTask.id == SiteFetchArtifact.task_id)
            .where(SiteFetchArtifact.workspace_id == workspace_id)
            .where(SiteCrawlTask.workspace_id == workspace_id)
            .where(SiteCrawlTask.site_url_id.in_(candidate_ids))
        )
    ).all()
    return [(artifact, site_url_id) for artifact, site_url_id in rows]


def _resolve_from_artifacts(
    requested: str,
    candidates: tuple[PageCandidate, ...],
    artifacts: list[tuple[SiteFetchArtifact, uuid.UUID | None]],
) -> PageResolution:
    by_url = {candidate.normalized_url: candidate for candidate in candidates}
    proofs = _artifact_proofs(
        requested_url=requested,
        candidate_by_url=by_url,
        artifacts=artifacts,
    )
    enriched = tuple(
        PageCandidate(
            site_url_id=item.site_url_id,
            normalized_url=item.normalized_url,
            evidence=tuple(sorted(proofs.get(item.site_url_id, set()))),
            sitemap_member=item.sitemap_member,
            preferred_origin=item.preferred_origin,
        )
        for item in candidates
    )
    proven = [item for item in enriched if item.evidence]
    ordered = tuple(sorted(enriched, key=_rank))
    if len(proven) == 1:
        return PageResolution("resolved", proven[0].site_url_id, ordered)
    return PageResolution("ambiguous", None, ordered)
