"""Progressive Site Health URL parsing and admission entry points."""

from __future__ import annotations

import codecs

from lxml import etree
from lxml import html as lxml_html
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health import (
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
    SELECTION_SOURCE_BOOTSTRAP,
    site_health_settings,
)
from app.domain.site_health.frontier import admit_candidates as admit_candidates
from app.domain.site_health.frontier import (
    drain_discovery_frontier as drain_discovery_frontier,
)
from app.domain.site_health.frontier_support import (
    _add_free_sample,
    _automatic_remaining,
    _upsert_site_url,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import (
    DiscoveredLink,
    DiscoveryOutput,
    FrontierCandidate,
)
from app.models.site_health import SiteCrawl, WorkspaceSiteHealthRuntime


def _safe_parser_encoding(charset: str) -> str | None:
    """Return a codec-valid encoding name, or ``None`` to auto-detect."""
    normalized = str(charset or "").strip()
    if not normalized:
        return None
    try:
        codecs.lookup(normalized)
    except LookupError:
        return None
    return normalized.lower()


def extract_discovery_links(
    body: bytes,
    *,
    base_url: str,
    root_registrable_domain: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    max_links: int | None = None,
    charset: str = "",
) -> tuple[str, list[DiscoveredLink]]:
    """Parse HTML into a title and bounded, canonical, in-scope links."""
    limit = max_links or site_health_settings.max_links_per_page
    title = ""
    links: list[DiscoveredLink] = []
    if not body:
        return title, links

    parser = lxml_html.HTMLParser(
        recover=True,
        encoding=_safe_parser_encoding(charset),
        no_network=True,
    )
    try:
        root = lxml_html.document_fromstring(body, parser=parser)
    except (etree.ParserError, ValueError):
        return title, links
    if root is None:
        return title, links

    title_node = next(root.iter("title"), None)
    if title_node is not None:
        title_text = "".join(
            text if isinstance(text, str) else text.decode("utf-8", "replace")
            for text in title_node.itertext()
        )
        title = title_text.strip()[:1024]

    seen: set[str] = set()
    ordinal = 0
    for anchor in root.iter("a"):
        href = anchor.get("href")
        if not href:
            continue
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        admission = classify_url_admission(
            href,
            base_url=base_url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        )
        if not admission.accepted or not admission.canonical_url:
            continue
        canonical, url_hash = canonical_identity(admission.canonical_url)
        if url_hash in seen:
            continue
        seen.add(url_hash)
        links.append(DiscoveredLink(url=canonical, url_hash=url_hash, ordinal=ordinal))
        ordinal += 1
        if len(links) >= limit:
            break
    return title, links


def build_frontier_candidates(
    output: DiscoveryOutput,
    *,
    parent_position: int,
    depth: int,
) -> list[FrontierCandidate]:
    """Turn a discover task's links into deterministically ordered candidates."""
    return [
        FrontierCandidate.from_admission(
            classify_url_admission(link.url),
            url=link.url,
            url_hash=link.url_hash,
            depth=depth + 1,
            source_kind=OBSERVATION_SOURCE_LINK,
            parent_position=parent_position,
            link_ordinal=link.ordinal,
        )
        for link in output.links
    ]


async def add_automatic_root(
    session: AsyncSession,
    crawl: SiteCrawl,
    *,
    runtime: WorkspaceSiteHealthRuntime | None = None,
) -> None:
    """Persist and queue analysis for a user-initiated automatic crawl root."""
    remaining = await _automatic_remaining(session, crawl, runtime=runtime)
    if remaining is None or remaining <= 0:
        return
    canonical_url, url_hash_value = canonical_identity(crawl.root_url)
    candidate = FrontierCandidate(
        url=canonical_url,
        url_hash=url_hash_value,
        depth=0,
        source_kind=OBSERVATION_SOURCE_ROOT,
        value_priority=0,
        parent_position=0,
        link_ordinal=0,
    )
    site_url_id, _created = await _upsert_site_url(
        session, crawl=crawl, candidate=candidate
    )
    await _add_free_sample(
        session,
        crawl=crawl,
        site_url_id=site_url_id,
        url=canonical_url,
        url_hash_value=url_hash_value,
        depth=0,
        source_kind=OBSERVATION_SOURCE_ROOT,
        selection_source=SELECTION_SOURCE_BOOTSTRAP,
    )
