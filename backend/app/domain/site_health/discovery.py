"""Progressive Site Health URL parsing and admission entry points."""

from __future__ import annotations

import codecs
import re
from typing import Any

from lxml import etree
from lxml import html as lxml_html
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    classify_url_admission,
)
from app.core.config.site_health_contracts import (
    LINK_REWRITE_ENCODED_TRACKING_QUERY,
    LINK_REWRITE_VERSION,
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_BOOTSTRAP,
)
from app.core.config.site_health_rules import (
    TRACKING_QUERY_PARAMS,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.domain.site_health.frontier import admit_candidates as admit_candidates
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
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime

_ENCODED_QUERY_DELIMITER = re.compile(r"%3f", re.IGNORECASE)
_ENCODED_QUERY_EQUALS = re.compile(r"%3d", re.IGNORECASE)
_ENCODED_QUERY_PAIR = re.compile(r"%26", re.IGNORECASE)


def _rewrite_extracted_href(href: str) -> tuple[str, str, str]:
    """Repair a positively identified encoded tracking-query delimiter."""
    if "?" in href:
        return href, "", ""
    match = _ENCODED_QUERY_DELIMITER.search(href)
    if match is None:
        return href, "", ""
    path, encoded_query = href[: match.start()], href[match.end() :]
    query = _ENCODED_QUERY_PAIR.sub("&", _ENCODED_QUERY_EQUALS.sub("=", encoded_query))
    first_key, separator, _value = query.partition("=")
    if not separator or first_key.casefold() not in TRACKING_QUERY_PARAMS:
        return href, "", ""
    return (
        f"{path}?{query}",
        LINK_REWRITE_ENCODED_TRACKING_QUERY,
        LINK_REWRITE_VERSION,
    )


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


def _parse_discovery_document(body: bytes, charset: str) -> tuple[str, Any | None]:
    if not body:
        return "", None
    parser = lxml_html.HTMLParser(
        recover=True,
        encoding=_safe_parser_encoding(charset),
        no_network=True,
    )
    try:
        root = lxml_html.document_fromstring(body, parser=parser)
    except (etree.ParserError, ValueError):
        return "", None
    if root is None:
        return "", None
    title_node = next(root.iter("title"), None)
    if title_node is None:
        return "", root
    title_text = "".join(
        text if isinstance(text, str) else text.decode("utf-8", "replace")
        for text in title_node.itertext()
    )
    return title_text.strip()[:1024], root


def _admit_discovery_href(
    href: str,
    *,
    base_url: str,
    root_registrable_domain: str,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
    ordinal: int,
) -> DiscoveredLink | None:
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
        return None
    rewritten_href, rewrite_reason, rewrite_version = _rewrite_extracted_href(href)
    try:
        candidate_href = (
            canonicalize(rewritten_href, base_url=base_url)
            if rewrite_reason
            else rewritten_href
        )
    except UrlPolicyError:
        return None
    admission = classify_url_admission(
        candidate_href,
        base_url=base_url,
        root_registrable_domain=root_registrable_domain,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )
    if not admission.accepted or not admission.canonical_url:
        return None
    canonical, url_hash = canonical_identity(admission.canonical_url)
    return DiscoveredLink(
        url=canonical,
        url_hash=url_hash,
        ordinal=ordinal,
        rewrite_reason=rewrite_reason,
        rewrite_version=rewrite_version,
    )


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
    title, root = _parse_discovery_document(body, charset)
    links: list[DiscoveredLink] = []
    if root is None:
        return title, links

    seen: set[str] = set()
    ordinal = 0
    for anchor in root.iter("a"):
        href = anchor.get("href")
        if not href:
            continue
        href = href.strip()
        href = href.strip()
        link = _admit_discovery_href(
            href,
            base_url=base_url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            ordinal=ordinal,
        )
        if link is None:
            continue
        url_hash = link.url_hash
        if url_hash in seen:
            continue
        seen.add(url_hash)
        links.append(link)
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
            rewrite_reason=link.rewrite_reason,
            rewrite_version=link.rewrite_version,
        )
        for link in output.links
    ]


async def add_automatic_root(
    session: AsyncSession,
    crawl: SiteCrawl,
    *,
    runtime: WorkspaceSiteHealthRuntime | None = None,
) -> None:
    """Persist and queue analysis for a user-triggered standard crawl root."""
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
        # The root keeps its own analyze task rather than waiting on the root
        # discover to hand one over. It is a single page, so it cannot starve
        # anything, and an independent task means a root whose DISCOVER fails
        # can still be analyzed -- the homepage is the one page a crawl must
        # not silently drop.
    )
