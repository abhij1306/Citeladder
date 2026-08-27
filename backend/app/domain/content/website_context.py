"""Deterministic crawl-fragment selection from persisted Site Health evidence.

Pure DB projection (invariant 7): no fetch, no extraction, no provider call.
Selects the newest terminal crawl with usable artifacts, then ranks its pages
by lexical relevance to the generation prompt (and to an explicit target URL
when rewriting), emits an allowlist-only subset of each page's
``normalized_facts``, sanitises and caps every field plus the total character
budget, and records full provenance so the result UI can show exactly which
crawl (and how fresh) grounded the content.

Relevance is deliberately a deterministic lexical score — no embeddings, no
vector store. The same inputs always produce the same snapshot. With no prompt
text the module falls back to the original positional ordering (homepage ->
active monitored -> stable URL) so behaviour is never undefined.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, and_, cast, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.content import (
    CONTENT_CONTEXT_FIELD_MAX_CHARS,
    CONTENT_CONTEXT_MAX_CHARS,
    CONTENT_CONTEXT_MAX_PAGES,
    CONTENT_CONTEXT_PER_PAGE_BODY_CHARS,
    CONTENT_CRAWL_FRAGMENT_SELECTION_VERSION,
    CONTENT_SCORE_BODY,
    CONTENT_SCORE_H1,
    CONTENT_SCORE_H2,
    CONTENT_SCORE_MONITORED,
    CONTENT_SCORE_TARGET_URL,
    CONTENT_SCORE_TITLE,
    CONTENT_SCORE_URL,
    CONTEXT_MAX_H1,
    CONTEXT_MAX_H2,
)
from app.core.config.site_health_contracts import (
    CRAWL_TERMINAL_STATUSES,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl

# Control/non-printable chars stripped from every emitted string; the
# whitespace collapse in ``_clean`` then folds ALL whitespace (newlines
# included) to single spaces.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_WHITESPACE = re.compile(r"\s+")

# Relevance tokenisation: split on anything non-alphanumeric so URL path
# segments ("/school-polos") tokenise the same way prose does.
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
# Small inline stop list — enough to stop instruction verbs and articles from
# matching every page. Deliberately not a linguistics dependency.
_STOP_WORDS: frozenset[str] = frozenset(
    {
        "about",
        "and",
        "any",
        "are",
        "best",
        "but",
        "can",
        "content",
        "create",
        "for",
        "from",
        "get",
        "give",
        "guide",
        "has",
        "have",
        "how",
        "into",
        "its",
        "make",
        "more",
        "new",
        "not",
        "our",
        "out",
        "page",
        "post",
        "some",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "top",
        "use",
        "using",
        "want",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "write",
        "writing",
        "you",
        "your",
    }
)


def _facts_usable() -> ColumnElement[bool]:
    """SQL predicate: artifact facts are a non-empty JSON object.

    An explicit Python ``None`` persists as JSON ``null`` (not SQL NULL) in a
    JSONB column, so an ``IS NOT NULL`` check alone would treat factless
    artifacts as usable. ``jsonb_typeof`` is NULL for SQL NULL and ``'null'``
    for JSON null, so one comparison covers both. ``{}`` must also be
    excluded here — the in-memory page filter drops empty facts, so a crawl
    admitted on ``{}`` alone would be selected and then yield zero pages
    instead of falling back to an older usable crawl.
    """
    facts = SiteFetchArtifact.normalized_facts
    return and_(
        func.jsonb_typeof(facts) == "object",
        facts != cast({}, JSONB),
    )


@dataclass(frozen=True)
class CrawlFragmentSelection:
    """Bounded crawl-observed fragments consumed only by grounding."""

    pages: list[dict] = field(default_factory=list)
    summary: dict | None = None


def _clean(value: object, *, max_chars: int) -> str:
    """Strip control chars, collapse whitespace, enforce the char cap."""
    text = _CONTROL_CHARS.sub("", str(value or ""))
    text = _WHITESPACE.sub(" ", text).strip()
    return text[:max_chars]


type _ContextRow = tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]


@dataclass(frozen=True)
class _ContextProjection:
    pages: list[dict]
    site_url_ids: list[str]
    artifact_ids: list[str]
    content_hashes: list[str]
    fetched_ats: list[str | None]
    extractor_version: str
    analyzer_version: str
    total_chars: int
    omissions: list[dict]


def _is_homepage(site_url: SiteUrl, *, root_url: str, root_host: str) -> bool:
    normalized = site_url.normalized_url
    if root_url and normalized.rstrip("/") == root_url.rstrip("/"):
        return True
    if not root_host:
        return False
    stripped = re.sub(r"^https?://", "", normalized).rstrip("/")
    return stripped == root_host


def _tokens(value: object) -> set[str]:
    """Lowercase alphanumeric terms, minus stop words and 1-2 char noise."""
    text = str(value or "").lower()
    return {
        token
        for token in _TOKEN_SPLIT.split(text)
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _overlap(terms: set[str], value: object) -> int:
    """Count of DISTINCT prompt terms present — never term frequency, so a
    long page cannot outrank a precise one by repeating a word."""
    if not terms:
        return 0
    return len(terms & _tokens(value))


def _normalized_target(url: str) -> str:
    """Compare URLs without scheme, trailing slash, or case differences."""
    return re.sub(r"^https?://", "", str(url or "").strip().lower()).rstrip("/")


def _relevance_score(
    entry: _ContextRow,
    *,
    terms: set[str],
    target: str,
    monitored_ids: set[uuid.UUID],
) -> int:
    """Deterministic lexical relevance of one page to the generation prompt."""
    _analysis, artifact, site_url = entry
    if target and target in {
        _normalized_target(artifact.final_url),
        _normalized_target(site_url.normalized_url),
    }:
        return CONTENT_SCORE_TARGET_URL

    facts = artifact.normalized_facts or {}
    headings = facts.get("headings") or {}
    body = facts.get("body") or {}
    score = 0
    score += CONTENT_SCORE_TITLE * _overlap(terms, facts.get("title"))
    score += CONTENT_SCORE_H1 * _overlap(
        terms, " ".join(headings.get("h1_texts") or [])
    )
    score += CONTENT_SCORE_H2 * _overlap(
        terms, " ".join(headings.get("h2_texts") or [])
    )
    score += CONTENT_SCORE_URL * _overlap(terms, site_url.normalized_url)
    score += CONTENT_SCORE_BODY * _overlap(
        terms, str(body.get("text") or "")[:CONTENT_CONTEXT_PER_PAGE_BODY_CHARS]
    )
    if site_url.id in monitored_ids:
        score += CONTENT_SCORE_MONITORED
    return score


def _positional_sort_key(
    entry: _ContextRow,
    *,
    root_url: str,
    root_host: str,
    monitored_ids: set[uuid.UUID],
) -> tuple[int, str, str]:
    """Prompt-free fallback ordering: homepage -> monitored -> stable URL."""
    _analysis, _artifact, site_url = entry
    if _is_homepage(site_url, root_url=root_url, root_host=root_host):
        tier = 0
    elif site_url.id in monitored_ids:
        tier = 1
    else:
        tier = 2
    return tier, site_url.normalized_url, str(site_url.id)


def _ordered_usable_rows(
    rows: list[_ContextRow],
    *,
    root_url: str,
    root_host: str,
    monitored_ids: set[uuid.UUID],
    query_text: str = "",
    target_url: str = "",
) -> list[_ContextRow]:
    """Filter and rank persisted page evidence for this generation.

    Ranked by lexical relevance to the prompt, with an explicit target URL
    always first. The homepage is demoted from its old top tier to a fallback
    appended last, so it supplies brand background without displacing a page
    that actually matches the topic.
    """
    usable = [entry for entry in rows if entry[1].normalized_facts]
    terms = _tokens(query_text)
    target = _normalized_target(target_url)
    if not terms and not target:
        usable.sort(
            key=lambda entry: _positional_sort_key(
                entry,
                root_url=root_url,
                root_host=root_host,
                monitored_ids=monitored_ids,
            )
        )
        return usable

    # The homepage is demoted UNLESS it is itself the rewrite target — a
    # request to rewrite the homepage must still put it first, so it stays in
    # the ranked set and picks up the target score like any other page.
    def _is_target(entry: _ContextRow) -> bool:
        return bool(target) and target in {
            _normalized_target(entry[1].final_url),
            _normalized_target(entry[2].normalized_url),
        }

    homepage = [
        entry
        for entry in usable
        if _is_homepage(entry[2], root_url=root_url, root_host=root_host)
        and not _is_target(entry)
    ]
    homepage_ids = {entry[2].id for entry in homepage}
    ranked = [entry for entry in usable if entry[2].id not in homepage_ids]
    ranked.sort(
        key=lambda entry: (
            -_relevance_score(
                entry, terms=terms, target=target, monitored_ids=monitored_ids
            ),
            entry[2].normalized_url,
            str(entry[2].id),
        )
    )
    # Homepage last: useful brand context, never a displacement of a match.
    return [*ranked, *homepage]


def _page_block(artifact: SiteFetchArtifact, site_url: SiteUrl) -> dict:
    """Project one artifact into the allowlisted, field-bounded page shape."""
    facts = artifact.normalized_facts or {}
    headings = facts.get("headings") or {}
    body = facts.get("body") or {}
    return {
        "final_url": _clean(
            artifact.final_url or site_url.normalized_url,
            max_chars=CONTENT_CONTEXT_FIELD_MAX_CHARS,
        ),
        "title": _clean(facts.get("title"), max_chars=CONTENT_CONTEXT_FIELD_MAX_CHARS),
        "meta_description": _clean(
            facts.get("meta_description"),
            max_chars=CONTENT_CONTEXT_FIELD_MAX_CHARS,
        ),
        "h1": [
            _clean(heading, max_chars=CONTENT_CONTEXT_FIELD_MAX_CHARS)
            for heading in (headings.get("h1_texts") or [])[:CONTEXT_MAX_H1]
        ],
        "h2": [
            _clean(heading, max_chars=CONTENT_CONTEXT_FIELD_MAX_CHARS)
            for heading in (headings.get("h2_texts") or [])[:CONTEXT_MAX_H2]
        ],
        "body_text": _clean(
            body.get("text"), max_chars=CONTENT_CONTEXT_PER_PAGE_BODY_CHARS
        ),
    }


def _page_char_count(page: dict) -> int:
    return sum(
        len(value) if isinstance(value, str) else sum(len(item) for item in value)
        for value in page.values()
    )


def _bounded_projection(rows: list[_ContextRow]) -> _ContextProjection:
    """Apply the exact total budget and collect matching page provenance."""
    pages: list[dict] = []
    site_url_ids: list[str] = []
    artifact_ids: list[str] = []
    content_hashes: list[str] = []
    fetched_ats: list[str | None] = []
    extractor_version = ""
    analyzer_version = ""
    total_chars = 0
    omissions: list[dict] = []
    budget_skipped = 0
    for index, (analysis, artifact, site_url) in enumerate(rows):
        if len(pages) >= CONTENT_CONTEXT_MAX_PAGES:
            omissions.append({"reason": "page_limit", "count": len(rows) - index})
            break
        page = _page_block(artifact, site_url)
        page_chars = _page_char_count(page)
        if total_chars + page_chars > CONTENT_CONTEXT_MAX_CHARS:
            # Skip, don't stop: one oversized page must not truncate every
            # smaller relevant page ranked behind it.
            budget_skipped += 1
            continue
        total_chars += page_chars
        pages.append(page)
        site_url_ids.append(str(site_url.id))
        artifact_ids.append(str(artifact.id))
        content_hashes.append(artifact.content_hash or "")
        fetched_at = artifact.fetched_at
        fetched_ats.append(fetched_at.isoformat() if fetched_at else None)
        extractor_version = extractor_version or artifact.extractor_version
        analyzer_version = analyzer_version or analysis.analyzer_version
    if budget_skipped:
        omissions.append({"reason": "character_budget", "count": budget_skipped})
    return _ContextProjection(
        pages=pages,
        site_url_ids=site_url_ids,
        artifact_ids=artifact_ids,
        content_hashes=content_hashes,
        fetched_ats=fetched_ats,
        extractor_version=extractor_version,
        analyzer_version=analyzer_version,
        total_chars=total_chars,
        omissions=omissions,
    )


def _included_selection(
    crawl: SiteCrawl, projection: _ContextProjection
) -> CrawlFragmentSelection:
    summary = {
        "crawl_id": str(crawl.id),
        "crawl_completed_at": (
            crawl.completed_at.isoformat() if crawl.completed_at else None
        ),
        "extractor_version": projection.extractor_version,
        "analyzer_version": projection.analyzer_version,
        "page_count": len(projection.pages),
        "char_count": projection.total_chars,
        "site_url_ids": projection.site_url_ids,
        "artifact_ids": projection.artifact_ids,
        "content_hashes": projection.content_hashes,
        "fetched_at": projection.fetched_ats,
        "selection_policy_version": CONTENT_CRAWL_FRAGMENT_SELECTION_VERSION,
        "omissions": projection.omissions,
    }
    return CrawlFragmentSelection(pages=projection.pages, summary=summary)


async def _newest_usable_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SiteCrawl | None:
    """Newest terminal crawl with >=1 analysis over non-empty facts.

    ``completed``/``partially_completed`` naturally qualify; ``failed``/
    ``cancelled`` qualify only when they still produced usable artifacts —
    the EXISTS predicate enforces that uniformly, in one bounded query
    (no per-crawl scan).
    """
    usable_exists = (
        select(SitePageAnalysis.id)
        .join(
            SiteFetchArtifact,
            SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
        )
        .where(SitePageAnalysis.crawl_id == SiteCrawl.id)
        .where(_facts_usable())
        .exists()
    )
    return await session.scalar(
        select(SiteCrawl)
        .where(SiteCrawl.workspace_id == workspace_id)
        .where(SiteCrawl.project_id == project_id)
        .where(SiteCrawl.status.in_(list(CRAWL_TERMINAL_STATUSES)))
        .where(usable_exists)
        .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
        .limit(1)
    )


async def select_crawl_fragments(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    query_text: str = "",
    target_url: str = "",
) -> CrawlFragmentSelection:
    """Select bounded crawl fragments most relevant to this generation.

    ``query_text`` is the user's prompt (plus any opportunity theme); pages are
    ranked by lexical overlap with it. ``target_url`` is an explicit rewrite
    target and always ranks first. With neither, ordering falls back to the
    deterministic positional tiering.
    """
    crawl = await _newest_usable_crawl(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if crawl is None:
        return CrawlFragmentSelection()

    profile = await session.scalar(
        select(SiteHealthProfile).where(SiteHealthProfile.project_id == project_id)
    )
    root_url = (profile.root_url if profile else "") or ""
    root_host = (profile.root_host if profile else "") or ""

    # All analysed pages of the crawl with their artifacts + URL identities.
    analysis_rows = await session.execute(
        select(SitePageAnalysis, SiteFetchArtifact, SiteUrl)
        .join(
            SiteFetchArtifact,
            SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
        )
        .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
        .where(SitePageAnalysis.crawl_id == crawl.id)
        .where(_facts_usable())
    )
    rows = analysis_rows.tuples().all()
    # Active monitored membership for this project (inactive rows ignored).
    monitored_ids = set(
        (
            await session.scalars(
                select(MonitoredSiteUrl.site_url_id)
                .where(MonitoredSiteUrl.project_id == project_id)
                .where(MonitoredSiteUrl.active.is_(True))
            )
        ).all()
    )
    ordered_rows = _ordered_usable_rows(
        list(rows),
        root_url=root_url,
        root_host=root_host,
        monitored_ids=monitored_ids,
        query_text=query_text,
        target_url=target_url,
    )
    projection = _bounded_projection(ordered_rows)
    if not projection.pages:
        return CrawlFragmentSelection()
    return _included_selection(crawl, projection)
