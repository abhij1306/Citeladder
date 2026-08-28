"""Shelf membership and catalog URL identity for the Commerce projection.

Split out of ``projector.py``, which had grown past the module LOC ceiling
carrying two separable concerns. The projector owns turning ONE analyzed page
into catalog rows; this module owns the question that sits underneath it:
which URL is a product, and which shelf lists it.

That question is its own subject because a storefront answers it in several
inconsistent ways at once. One product is reachable at six addresses (once per
collection that lists it, plus a ``?variant=`` form of each), the shelf links
whichever alias its own path produced, and only the page's ``rel=canonical``
ties them together -- while a sitemap may mean the crawler never fetched the
alias at all. Every function here exists to reconcile one of those.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    is_in_scope,
    registrable_domain,
)
from app.core.config.site_health_acquisition import FETCH_PURPOSE_DISCOVER
from app.domain.commerce.facts import _dict_value, _list_value
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommerceProductCategory,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl


def _catalog_identity(facts: dict[str, Any], base_url: str) -> str:
    """The URL this page IS, not the URL we happened to fetch it from.

    A Shopify storefront serves one product at six addresses -- once per
    collection that lists it, plus a `?variant=` form of each -- and every one
    of them declares the same `rel=canonical`. Keyed on the fetched URL the
    catalog held 108 rows for 30 products, all six "Bamboo Toothbrush" rows
    carrying the same `TBB21` SKU, and the shelf UI was unreadable.

    The declared canonical is only trusted when it stays on the same
    registrable domain as the page that declared it: `rel=canonical` is
    attacker-controllable markup, and a cross-domain value would let one site
    write rows keyed to another's URLs. Anything unparseable or off-domain
    falls back to the final delivered URL (or admitted URL when unavailable).
    """
    declared = str(facts.get("canonical_url") or "").strip()
    if not declared:
        return base_url
    try:
        canonical = canonicalize(declared, base_url=base_url)
    except UrlPolicyError:
        return base_url
    domain = registrable_domain(base_url)
    if not domain or not is_in_scope(canonical, domain):
        return base_url
    return canonical


def _identity_base_url(final_url: str, admitted_url: str) -> str:
    """Use the delivered URL as the base for stored URL declarations."""
    return str(final_url or "").strip() or admitted_url


#: The page region a shelf lists its own products in. Header/footer/nav
#: anchors are the site's menus, which every page carries and which say
#: nothing about what is on THIS shelf.
_SHELF_LINK_REGION = "main"


def _shelf_product_urls(facts: dict[str, Any]) -> list[str]:
    """The URLs a shelf page lists, preferring the extractor's card region.

    ``commerce.product_cards`` is the precise answer when the extractor's card
    heuristic matches the theme's markup. On real storefronts it frequently
    does not: every one of a Shopify store's 19 collection pages came back with
    ``product_cards: []`` while carrying 24 main-region anchors each, one per
    product on the shelf, so membership was derived from nothing and every
    product fell into a single synthetic bucket.

    Main-region anchors are the same evidence read one level lower down. They
    are still the crawl's own record of what this page links to, and callers
    intersect them with products the catalog ALREADY holds -- so a menu link or
    a link to another collection contributes nothing rather than inventing a
    product. The cards are preferred when present because they are scoped to
    the grid; the anchors are the fallback, not a replacement.
    """
    commerce = _dict_value(facts.get("commerce"))
    cards = _list_value(commerce.get("product_cards"))
    urls = [
        url
        for card in cards
        if (url := str(_dict_value(card).get("url") or "").strip())
    ]
    if not urls:
        anchors = _list_value(_dict_value(facts.get("links")).get("anchors"))
        urls = [
            url
            for anchor in anchors
            if _dict_value(anchor).get("region") == _SHELF_LINK_REGION
            and (url := str(_dict_value(anchor).get("url") or "").strip())
        ]
    return list(dict.fromkeys(urls))


async def _link_shelf_products(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    category: CommerceCategory,
) -> None:
    """Attach the products a category page actually lists to that category.

    Membership used to come ONLY from each product page's own metadata -- its
    JSON-LD ``category`` and its breadcrumb trail. A storefront that publishes
    neither (most Shopify themes) produced no membership at all, so every
    product fell into the "Uncategorized" bucket and every real collection
    reported zero products. The shelf page is the authority on what is on the
    shelf, and it is already crawled, parsed and stored -- it was simply never
    read for this.

    Only products the catalog already knows are linked: this reads the crawl's
    own evidence, it does not invent products from hrefs.
    """
    urls = _shelf_product_urls(_dict_value(artifact.normalized_facts))
    if not urls:
        return
    shelf_url = str(artifact.final_url or artifact.requested_url or "")
    candidates = {_canonical_or_blank(url, shelf_url) for url in urls}
    candidates.discard("")
    if not candidates:
        return
    # A shelf links its products through the shelf's own path
    # (`/collections/oral-care/products/x`), while the catalog keys them on the
    # identity those pages declare (`/products/x`). Matching the hrefs verbatim
    # therefore found nothing on exactly the storefronts this exists to serve,
    # so the crawled alias is resolved to the same identity first.
    candidates |= await _declared_identities(
        session, analysis=analysis, urls=candidates
    )
    candidates |= {
        identity
        for url in tuple(candidates)
        if (identity := _shelf_scoped_alias_identity(url))
    }
    product_ids = list(
        (
            await session.scalars(
                select(CommerceProduct.id).where(
                    CommerceProduct.project_id == analysis.project_id,
                    CommerceProduct.workspace_id == analysis.workspace_id,
                    CommerceProduct.canonical_url.in_(sorted(candidates)),
                )
            )
        ).all()
    )
    await _add_shelf_memberships(
        session,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        category_id=category.id,
        product_ids=product_ids,
    )


#: A storefront alias that addresses a product THROUGH the shelf listing it:
#: `/collections/<shelf>/products/<slug>` is the same page as `/products/<slug>`
#: and says so in its own `rel=canonical`.
_SHELF_SCOPED_PRODUCT_PATH = re.compile(
    r"^/collections/[^/]+(?P<product>/products/[^/]+)/?$"
)


def _shelf_scoped_alias_identity(url: str) -> str:
    """The un-shelfed form of a shelf-scoped product URL ("" when not one).

    ``_declared_identities`` can only resolve an alias the crawl actually
    fetched, and frequently it did not: a sitemap offers the canonical
    `/products/<slug>` form, so the frontier fills with those and the
    shelf-scoped alias is never admitted at all. The shelf page still links
    the alias, so matching stopped there and every collection reported zero
    products despite the shelf naming all 25 of them.

    Deriving the un-shelfed form adds a CANDIDATE, never a product: it is
    matched against the catalog like any other, so a URL no product claims
    contributes nothing. Host, scheme and slug are carried through untouched,
    so this can only ever point at the same site's own product page.
    """
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:
        return ""
    if not parts.scheme or not parts.netloc:
        return ""
    match = _SHELF_SCOPED_PRODUCT_PATH.match(parts.path)
    if match is None:
        return ""
    return urlunsplit((parts.scheme, parts.netloc, match.group("product"), "", ""))


async def _declared_identities(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    urls: set[str],
) -> set[str]:
    """The identities the crawl's own evidence gives these crawled URLs.

    Only URLs this project actually crawled resolve; an external href simply
    contributes nothing, keeping this a stored-evidence lookup.
    """
    if not urls:
        return set()
    rows = (
        await session.execute(
            select(
                SiteUrl.normalized_url,
                SiteFetchArtifact.final_url,
                SiteFetchArtifact.normalized_facts,
            )
            .join(SiteCrawlTask, SiteCrawlTask.site_url_id == SiteUrl.id)
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.task_id == SiteCrawlTask.id,
            )
            .where(
                SiteUrl.workspace_id == analysis.workspace_id,
                SiteUrl.project_id == analysis.project_id,
                SiteCrawlTask.crawl_id == analysis.crawl_id,
                SiteFetchArtifact.fetch_purpose == FETCH_PURPOSE_DISCOVER,
                SiteUrl.normalized_url.in_(sorted(urls)),
            )
        )
    ).all()
    return {
        identity
        for normalized_url, final_url, facts in rows
        if (
            identity := _catalog_identity(
                _dict_value(facts), _identity_base_url(final_url, normalized_url)
            )
        )
    }


async def _add_shelf_memberships(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    category_id: uuid.UUID,
    product_ids: list[uuid.UUID],
) -> None:
    if not product_ids:
        return
    await session.execute(
        pg_insert(CommerceProductCategory)
        .values(
            [
                {
                    "id": uuid.uuid4(),
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "product_id": product_id,
                    "category_id": category_id,
                }
                for product_id in product_ids
            ]
        )
        .on_conflict_do_nothing(
            index_elements=[
                CommerceProductCategory.product_id,
                CommerceProductCategory.category_id,
            ]
        )
    )
    # A product a real shelf claims is no longer uncategorized. The product
    # projection cannot know a shelf will claim it later -- the two are
    # separate tasks in either order -- so the fallback is retracted here,
    # where the real membership is what has just become true.
    await session.execute(
        delete(CommerceProductCategory).where(
            CommerceProductCategory.project_id == project_id,
            CommerceProductCategory.product_id.in_(product_ids),
            CommerceProductCategory.category_id.in_(
                select(CommerceCategory.id).where(
                    CommerceCategory.project_id == project_id,
                    CommerceCategory.normalized_name == "uncategorized",
                )
            ),
        )
    )


def _canonical_or_blank(url: str, base_url: str = "") -> str:
    """Canonical identity for one href, or "" when it is not a usable URL.

    ``base_url`` resolves relative hrefs. Shelf anchors are stored exactly as
    the page wrote them ("/collections/dresses/products/x"), so canonicalizing
    them without the page they came from rejected every single one and the
    shelf linked nothing.
    """
    try:
        return canonicalize(url, base_url=base_url or None)
    except UrlPolicyError:
        return ""


async def _link_product_to_projected_shelves(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    product: CommerceProduct,
) -> None:
    """Complete shelf membership when the product projection lands second."""
    shelves = (
        await session.execute(
            select(CommerceCategory, SiteFetchArtifact)
            .join(
                SitePageAnalysis,
                SitePageAnalysis.id == CommerceCategory.source_analysis_id,
            )
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .where(
                CommerceCategory.workspace_id == analysis.workspace_id,
                CommerceCategory.project_id == analysis.project_id,
            )
        )
    ).all()
    product_url = _canonical_or_blank(product.canonical_url)
    if not product_url:
        return
    for category, artifact in shelves:
        shelf_url = str(artifact.final_url or artifact.requested_url or "")
        linked_urls = {
            _canonical_or_blank(url, shelf_url)
            for url in _shelf_product_urls(_dict_value(artifact.normalized_facts))
        }
        linked_urls.discard("")
        # Same alias-vs-identity gap as `_link_shelf_products`: the shelf links
        # the collection-scoped address, the product is keyed on the identity.
        linked_urls |= await _declared_identities(
            session, analysis=analysis, urls=linked_urls
        )
        linked_urls |= {
            identity
            for url in tuple(linked_urls)
            if (identity := _shelf_scoped_alias_identity(url))
        }
        if product_url not in linked_urls:
            continue
        await _add_shelf_memberships(
            session,
            workspace_id=analysis.workspace_id,
            project_id=analysis.project_id,
            category_id=category.id,
            product_ids=[product.id],
        )
