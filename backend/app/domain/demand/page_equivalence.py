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
    PAGE_EQUIVALENCE_MAX_ARTIFACTS,
    PAGE_EQUIVALENCE_MAX_CANDIDATES,
    PAGE_EQUIVALENCE_QUERY_CHUNK_SIZE,
    PAGE_EQUIVALENCE_RESOLVER_VERSION,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl

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
        artifact.normalized_facts if isinstance(artifact.normalized_facts, dict) else {}
    )
    declared = _safe_canonicalize(str(facts.get("canonical_url") or ""))
    source_matches = requested == requested_url or any(
        item.site_url_id == source_site_url_id and item.normalized_url == requested_url
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
    try:
        requested = canonicalize(url)
    except UrlPolicyError:
        return PageResolution("unresolved", None, ())
    preferred = _safe_canonicalize(preferred_origin) if preferred_origin else None
    preferred_prefix = f"{preferred.rstrip('/')}/" if preferred else ""
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
            preferred_origin=bool(preferred)
            and (
                row.normalized_url == preferred
                or row.normalized_url.startswith(preferred_prefix)
            ),
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


async def resolve_owned_pages(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    urls: Sequence[str],
    preferred_origin: str = "",
) -> dict[str, PageResolution]:
    """Resolve a bounded URL set with two workspace-scoped database reads."""
    requested_urls = _canonical_batch(urls)
    variants_by_url = {
        url: _variant_urls(canonical) for url, canonical in requested_urls.items()
    }
    all_variants = sorted(
        {variant for variants in variants_by_url.values() for variant in variants}
    )
    site_rows = await _load_batch_site_urls(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        variants=all_variants,
    )
    row_by_url = {row.normalized_url: row for row in site_rows}
    preferred = _safe_canonicalize(preferred_origin) if preferred_origin else None
    results, candidates_by_url, unresolved_ids = _partition_batch(
        urls=urls,
        requested_urls=requested_urls,
        variants_by_url=variants_by_url,
        row_by_url=row_by_url,
        preferred=preferred,
    )
    artifacts = (
        await _load_candidate_artifacts(
            session, workspace_id=workspace_id, candidate_ids=sorted(unresolved_ids)
        )
        if unresolved_ids
        else []
    )
    for url, candidates in candidates_by_url.items():
        results[url] = _resolve_from_artifacts(
            requested_urls[url], candidates, artifacts
        )
    return results


def _canonical_batch(urls: Sequence[str]) -> dict[str, str]:
    requested: dict[str, str] = {}
    for url in sorted(set(urls)):
        canonical = _safe_canonicalize(url)
        if canonical is not None:
            requested[url] = canonical
    return requested


async def _load_batch_site_urls(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    variants: list[str],
) -> list[SiteUrl]:
    rows: list[SiteUrl] = []
    for chunk in _query_chunks(variants):
        rows.extend(
            (
                await session.scalars(
                    select(SiteUrl)
                    .where(SiteUrl.workspace_id == workspace_id)
                    .where(SiteUrl.project_id == project_id)
                    .where(SiteUrl.normalized_url.in_(chunk))
                    .order_by(SiteUrl.normalized_url, SiteUrl.id)
                )
            ).all()
        )
    return rows


def _query_chunks(values: list[str]) -> tuple[list[str], ...]:
    return tuple(
        values[offset : offset + PAGE_EQUIVALENCE_QUERY_CHUNK_SIZE]
        for offset in range(0, len(values), PAGE_EQUIVALENCE_QUERY_CHUNK_SIZE)
    )


def _url_candidates(
    variants: tuple[str, ...],
    row_by_url: dict[str, SiteUrl],
    preferred: str | None,
) -> tuple[PageCandidate, ...]:
    prefix = f"{preferred.rstrip('/')}/" if preferred else ""
    rows = [row_by_url[value] for value in variants if value in row_by_url]
    return tuple(
        PageCandidate(
            site_url_id=row.id,
            normalized_url=row.normalized_url,
            sitemap_member=row.latest_source_kind == "sitemap",
            preferred_origin=bool(preferred)
            and (
                row.normalized_url == preferred or row.normalized_url.startswith(prefix)
            ),
        )
        for row in rows[:PAGE_EQUIVALENCE_MAX_CANDIDATES]
    )


def _partition_batch(
    *,
    urls: Sequence[str],
    requested_urls: dict[str, str],
    variants_by_url: dict[str, tuple[str, ...]],
    row_by_url: dict[str, SiteUrl],
    preferred: str | None,
) -> tuple[
    dict[str, PageResolution],
    dict[str, tuple[PageCandidate, ...]],
    set[uuid.UUID],
]:
    results: dict[str, PageResolution] = {}
    pending: dict[str, tuple[PageCandidate, ...]] = {}
    candidate_ids: set[uuid.UUID] = set()
    for url in urls:
        canonical = requested_urls.get(url)
        candidates = _url_candidates(
            variants_by_url.get(url, ()), row_by_url, preferred
        )
        exact = next(
            (item for item in candidates if item.normalized_url == canonical), None
        )
        if exact is not None:
            results[url] = PageResolution("exact", exact.site_url_id, candidates)
        elif canonical is None or not candidates:
            results[url] = PageResolution("unresolved", None, ())
        else:
            pending[url] = candidates
            candidate_ids.update(item.site_url_id for item in candidates)
    return results, pending, candidate_ids


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
            .order_by(SiteFetchArtifact.created_at.desc(), SiteFetchArtifact.id.desc())
            .limit(PAGE_EQUIVALENCE_MAX_ARTIFACTS)
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
