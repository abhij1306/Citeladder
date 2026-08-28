"""Site Health to Commerce catalog projection owner."""

from __future__ import annotations

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import (
    COMMERCE_PROJECTOR_VERSION,
    COMMERCE_VISIBLE_PRICE_AMBIGUOUS_TOKENS,
    COMMERCE_VISIBLE_PRICE_CURRENCY_MARKERS,
)
from app.domain.commerce.catalog_membership import (
    _catalog_identity,
    _identity_base_url,
    _link_product_to_projected_shelves,
    _link_shelf_products,
)
from app.domain.commerce.facts import _dict_value, _list_value
from app.domain.commerce.price import normalized_price_value
from app.domain.commerce.service import (
    CommerceNotFoundError,
    _merge_categories,
)
from app.models.analytics import AnalyticsTask
from app.models.commerce import (
    CommerceCategory,
    CommerceProduct,
    CommerceProductCategory,
    CommerceProductObservation,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.urls import SiteUrl


def _first(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    return str(next((value for value in values if value), ""))


_VISIBLE_PRICE_MARKERS = "|".join(
    re.escape(marker) for marker, _ in COMMERCE_VISIBLE_PRICE_CURRENCY_MARKERS
)
_VISIBLE_PRICE = re.compile(
    rf"(?P<prefix>{_VISIBLE_PRICE_MARKERS})\s*(?P<amount>\d[\d,.]*)"
    rf"|(?P<suffix_amount>\d[\d,.]*)\s*(?P<suffix>{_VISIBLE_PRICE_MARKERS})",
    re.IGNORECASE,
)


def _visible_price(value: Any, context: Any = "") -> tuple[Decimal | None, str]:
    text = value.strip() if isinstance(value, str) else ""
    match = _single_visible_price(text, context)
    if match is None:
        return None, ""
    observed_marker = str(match.group("prefix") or match.group("suffix") or "").upper()
    number = normalized_price_value(
        str(match.group("amount") or match.group("suffix_amount") or "")
    )
    try:
        price = Decimal(number) if number is not None else None
    except InvalidOperation:
        price = None
    currency = next(
        (
            currency
            for marker, currency in COMMERCE_VISIBLE_PRICE_CURRENCY_MARKERS
            if marker.upper() == observed_marker
        ),
        "",
    )
    return price, currency


def _single_visible_price(text: str, context: Any = "") -> re.Match[str] | None:
    # The guard reads the surrounding words when they are available: "over",
    # "from" and "up to" live next to the amount, never inside it, so checking
    # the bare match alone could never reject a shipping-threshold banner.
    surrounding = context.casefold() if isinstance(context, str) else ""
    if any(
        token in text.casefold() or token in surrounding
        for token in COMMERCE_VISIBLE_PRICE_AMBIGUOUS_TOKENS
    ):
        return None
    matches = list(_VISIBLE_PRICE.finditer(text))
    return matches[0] if len(matches) == 1 else None


def _decimal(value: Any) -> Decimal | None:
    text = _first(value)
    try:
        return Decimal(text) if text else None
    except InvalidOperation:
        return None


def _projected_price(
    product: dict[str, Any], commerce: dict[str, Any]
) -> tuple[Decimal | None, str, dict[str, str]]:
    price = _decimal(product.get("price"))
    visible_price, visible_currency = _visible_price(
        commerce.get("visible_price"), commerce.get("visible_price_context")
    )
    price_path = "structured_data.product.price"
    if price is None and visible_price is not None:
        price = visible_price
        price_path = "commerce.visible_price"
    structured_currency = _first(product.get("price_currency"))
    currency = structured_currency or visible_currency
    paths = {}
    if price is not None:
        paths["price"] = price_path
    if currency:
        paths["currency"] = (
            "structured_data.product.price_currency"
            if structured_currency
            else "commerce.visible_price"
        )
    return price, currency, paths


def _crawl_projection(
    facts: dict[str, Any], canonical_url: str
) -> tuple[dict[str, Any], dict[str, str]]:
    structured = _dict_value(facts.get("structured_data"))
    product = _dict_value(structured.get("product"))
    commerce = _dict_value(facts.get("commerce"))
    headings = _dict_value(facts.get("headings"))
    names = _list_value(product.get("name"))
    if not names:
        names = _list_value(headings.get("h1_texts"))
    price, currency, evidence_paths = _projected_price(product, commerce)
    availability = _list_value(product.get("availability"))
    values = {
        "canonical_url": canonical_url,
        "name": _first(names) or str(facts.get("title") or ""),
        "description": _first(product.get("description"))
        or str(facts.get("meta_description") or ""),
        "brand": _first(product.get("brand")),
        "price": price,
        "currency": currency,
        "sku": _first(product.get("sku")),
        "gtin": _first(product.get("gtin")),
        "mpn": _first(product.get("mpn")),
        "variants": _list_value(product.get("variants")),
        "attributes": {"availability": availability} if availability else {},
    }
    return values, evidence_paths


def _has_product_identity(values: dict[str, Any]) -> bool:
    """Whether the page identified a specific product, rather than listing some.

    A merchant identifier is proof on its own. Failing that, a product needs a
    name AND a price the page stated for it -- a collection page has a name
    (its title) but no price of its own once the shipping-banner amount is
    rejected.
    """
    if any(values.get(key) for key in ("sku", "gtin", "mpn")):
        return True
    return bool(values.get("name")) and values.get("price") is not None


def _crawl_values(facts: dict[str, Any], canonical_url: str) -> dict[str, Any]:
    return _crawl_projection(facts, canonical_url)[0]


def _json_observed_fields(values: dict[str, Any]) -> dict[str, Any]:
    observed = dict(values)
    if isinstance(observed.get("price"), Decimal):
        observed["price"] = float(observed["price"])
    return observed


async def project_catalog_analysis(session_factory, task: AnalyticsTask) -> None:
    """Idempotently project persisted Site Health analysis evidence."""
    raw_id = str((task.payload or {}).get("source_analysis_id") or "")
    source_analysis_id = uuid.UUID(raw_id)
    async with session_factory() as session:
        analysis, artifact, site_url = await _projection_source(
            session, task=task, source_analysis_id=source_analysis_id
        )
        if analysis.page_kind == "category":
            await _project_category_source(
                session, analysis=analysis, artifact=artifact, site_url=site_url
            )
        elif analysis.page_kind == "product":
            await _project_product_source(
                session, analysis=analysis, artifact=artifact, site_url=site_url
            )
        await session.commit()


async def _projection_source(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    source_analysis_id: uuid.UUID,
) -> tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]:
    row = (
        await session.execute(
            select(SitePageAnalysis, SiteFetchArtifact, SiteUrl)
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .where(
                SitePageAnalysis.id == source_analysis_id,
                SitePageAnalysis.workspace_id == task.workspace_id,
                SitePageAnalysis.project_id == task.project_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise CommerceNotFoundError("Source Site Health analysis not found")
    return row[0], row[1], row[2]


_TITLE_SEPARATORS = ("|", "–", "—", "·", "»", " - ")


def _is_named(value: str) -> bool:
    """Whether a candidate name says anything, rather than being punctuation.

    Breadcrumb trails are commonly marked up as one node per crumb AND one per
    separator, so the extractor reads "Home", "/", "Dresses". A crumb made only
    of separator characters is the markup's punctuation, not a category: taken
    as a leaf it produced a catalog category literally named "/" that every
    product on the site then hung off. One alphanumeric character is the whole
    requirement, so non-Latin names ("ドレス") still qualify.
    """
    return any(char.isalnum() for char in value)


def _category_title(facts: dict[str, Any], fallback: str) -> str:
    """A category's own name, not the page's title tag.

    The raw title was stored verbatim, which produced names like "ASTR The
    Label Elevated Women's Clothing | Red Dress" -- unreadable in the catalog,
    and interpolated straight into the competitor search query, where it
    returned marketplace listings instead of competing brands. It also meant a
    breadcrumb-derived category ("Dresses") could never match the crawled page,
    so crawled categories kept a product count of zero.

    The breadcrumb leaf and `h1` are the page's own claim about what it is, so
    they win over the title. A title is used only after its site-name segment
    is dropped.
    """
    commerce = _dict_value(facts.get("commerce"))
    breadcrumbs = [
        str(value).strip() for value in _list_value(commerce.get("breadcrumbs"))
    ]
    leaf = next(
        (value for value in reversed(breadcrumbs) if _is_named(value)),
        "",
    )
    if leaf:
        return leaf
    headings = _dict_value(facts.get("headings"))
    h1 = next(
        (
            str(value).strip()
            for value in _list_value(headings.get("h1_texts"))
            if _is_named(str(value))
        ),
        "",
    )
    if h1:
        return h1
    segment = _title_segment(str(facts.get("title") or fallback))
    return segment if _is_named(segment) else ""


def _title_segment(title: str) -> str:
    """The most specific segment of a separator-joined page title."""
    parts = [title]
    for separator in _TITLE_SEPARATORS:
        parts = [piece for part in parts for piece in part.split(separator)]
    cleaned = [" ".join(part.split()) for part in parts]
    named = [part for part in cleaned if part]
    # Titles are conventionally "<page> <sep> <site>", so the leading segment
    # is the page. Falling back to the whole title keeps a separator-free name.
    return named[0] if named else " ".join(title.split())


async def _project_category_source(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    site_url: SiteUrl,
) -> None:
    facts = _dict_value(artifact.normalized_facts)
    commerce = _dict_value(facts.get("commerce"))
    category = await _category_from_analysis(
        session,
        analysis=analysis,
        canonical_url=_catalog_identity(
            facts, _identity_base_url(artifact.final_url, site_url.normalized_url)
        ),
        title=_category_title(facts, str(site_url.latest_title or "Uncategorized")),
        role=str(commerce.get("category_role") or "unknown"),
    )
    await _link_shelf_products(
        session, analysis=analysis, artifact=artifact, category=category
    )


async def _project_product_source(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    site_url: SiteUrl,
) -> None:
    prior = await session.scalar(
        select(CommerceProductObservation.id).where(
            CommerceProductObservation.source_analysis_id == analysis.id,
            CommerceProductObservation.projector_version == COMMERCE_PROJECTOR_VERSION,
        )
    )
    if prior is not None:
        return
    facts = _dict_value(artifact.normalized_facts)
    # One identity per product, not one per address it is reachable at.
    identity = _catalog_identity(
        facts, _identity_base_url(artifact.final_url, site_url.normalized_url)
    )
    values, evidence_paths = _crawl_projection(facts, identity)
    if not _has_product_identity(values):
        # The classifier promotes a collection page to a product on nothing
        # more than a price regex plus a cart marker, which every Shopify
        # collection satisfies -- so "Back in Stock" and "Brands We Love"
        # entered the catalog as products. A product the page cannot identify
        # is not a product; entering it as one makes the catalog unanswerable.
        #
        # Dropping it silently was just as wrong: a retailer whose product
        # pages are client-rendered projects nothing at all, and the Commerce
        # workspace says "Nothing projected yet" while Site Health reports the
        # same pages analyzed. A listing page IS a category, so project it as
        # one -- the crawl's evidence reaches the catalog under the kind it
        # actually supports.
        category = await _category_from_analysis(
            session,
            analysis=analysis,
            canonical_url=identity,
            title=_category_title(facts, str(site_url.latest_title or "Uncategorized")),
            role=str(
                _dict_value(facts.get("commerce")).get("category_role") or "unknown"
            ),
        )
        # A listing page reaching here IS a shelf, whatever the classifier
        # called it, so the products it lists get their memberships the same
        # way a page classified as a category would. Skipping this left the
        # most common Shopify misclassification projecting a category with
        # nothing in it.
        await _link_shelf_products(
            session, analysis=analysis, artifact=artifact, category=category
        )
        return
    product = await _product_for_identity(
        session,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        canonical_url=identity,
    )
    _apply_projected_values(
        product,
        values=values,
        evidence_paths=evidence_paths,
        analysis=analysis,
        artifact=artifact,
    )
    observed_fields = _json_observed_fields(values)
    observed_fields["_evidence_paths"] = evidence_paths
    observation = CommerceProductObservation(
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        product_id=product.id,
        source_kind="site_health",
        source_analysis_id=analysis.id,
        source_artifact_id=artifact.id,
        observed_fields=observed_fields,
        extractor_version=artifact.extractor_version,
        classifier_version=analysis.classifier_version,
        projector_version=COMMERCE_PROJECTOR_VERSION,
    )
    session.add(observation)
    await session.flush()
    await _merge_projected_categories(
        session,
        analysis=analysis,
        artifact=artifact,
        product=product,
        observation=observation,
    )
    await _link_product_to_projected_shelves(
        session,
        analysis=analysis,
        product=product,
    )


async def _product_for_identity(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    canonical_url: str,
) -> CommerceProduct:
    """Return the one product row for a canonical catalog identity.

    Multiple crawl aliases can project concurrently. A select-then-ORM-add
    races on the unique ``(project_id, canonical_url)`` key, so creation uses
    the database conflict boundary and then reads the winner.
    """
    await session.execute(
        pg_insert(CommerceProduct)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            canonical_url=canonical_url,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "canonical_url"])
    )
    product = await session.scalar(
        select(CommerceProduct).where(
            CommerceProduct.workspace_id == workspace_id,
            CommerceProduct.project_id == project_id,
            CommerceProduct.canonical_url == canonical_url,
        )
    )
    if product is None:
        raise RuntimeError("Commerce product upsert did not return a row")
    return product


def _apply_projected_values(
    product: CommerceProduct,
    *,
    values: dict[str, Any],
    evidence_paths: dict[str, str] | None = None,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
) -> None:
    evidence_paths = evidence_paths or {}
    sources = dict(product.field_sources or {})
    for field, value in values.items():
        source = _dict_value(sources.get(field))
        if source.get("kind") in {"csv", "edit"}:
            continue
        if value not in (None, "", [], {}):
            setattr(product, field, value)
            sources[field] = {
                "kind": "site_health",
                "source_id": str(analysis.id),
                "artifact_id": str(artifact.id),
                "version": COMMERCE_PROJECTOR_VERSION,
            }
            if field in evidence_paths:
                sources[field]["evidence_path"] = evidence_paths[field]
    product.field_sources = sources


async def _merge_projected_categories(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    artifact: SiteFetchArtifact,
    product: CommerceProduct,
    observation: CommerceProductObservation,
) -> None:
    facts = _dict_value(artifact.normalized_facts)
    structured = _dict_value(_dict_value(facts.get("structured_data")).get("product"))
    names = [str(value) for value in _list_value(structured.get("category"))]
    commerce = _dict_value(facts.get("commerce"))
    # Separators are dropped BEFORE the slice, not after. Themes mark a
    # breadcrumb trail up as one node per crumb AND one per separator, so
    # "Home / Women / Dresses / Linen Dress" arrives as seven nodes. Slicing
    # that raw both took the bare "/" as a category name -- creating a catalog
    # category literally named "/" that all 413 of a site's products hung off
    # while its 19 real collections reported zero -- and shifted the [1:-1]
    # window off the crumbs it is meant to select.
    breadcrumbs = [
        crumb
        for value in _list_value(commerce.get("breadcrumbs"))
        if _is_named(crumb := str(value))
    ]
    if len(breadcrumbs) > 2:
        names.extend(breadcrumbs[1:-1])
    named = [name for name in dict.fromkeys(names) if _is_named(name)]
    if not named and await _has_membership(session, product_id=product.id):
        # "Uncategorized" is a FALLBACK, not a label. The shelf pages assign
        # membership independently and may be projected before or after this
        # product, so adding the bucket unconditionally filed all 413 products
        # under it in addition to the real collections they belong to -- the
        # catalog then showed one enormous "Uncategorized" group next to the
        # shelves, which is the view this projection exists to replace.
        return
    await _merge_categories(
        session,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        product_id=product.id,
        names=named or ["Uncategorized"],
        source_observation_id=observation.id,
    )


async def _has_membership(session: AsyncSession, *, product_id: uuid.UUID) -> bool:
    """Whether any category already claims this product."""
    return (
        await session.scalar(
            select(CommerceProductCategory.id)
            .where(CommerceProductCategory.product_id == product_id)
            .limit(1)
        )
    ) is not None


async def _category_from_analysis(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    canonical_url: str,
    title: str,
    role: str,
) -> CommerceCategory:
    stripped = title.strip()
    safe_title = stripped if _is_named(stripped) else "Uncategorized"
    normalized = " ".join(safe_title.casefold().split())
    category = await session.scalar(
        select(CommerceCategory).where(
            CommerceCategory.project_id == analysis.project_id,
            or_(
                CommerceCategory.canonical_url == canonical_url,
                CommerceCategory.normalized_name == normalized[:255],
            ),
        )
    )
    if category is None:
        category = CommerceCategory(
            # Assigned here rather than at flush so the shelf's product
            # memberships can reference it in this same transaction.
            id=uuid.uuid4(),
            workspace_id=analysis.workspace_id,
            project_id=analysis.project_id,
            name=safe_title[:255],
            normalized_name=normalized[:255],
            canonical_url=canonical_url,
        )
        session.add(category)
        # FLUSH, not just add: sessions run ``autoflush=False``
        # (``core/database.py``), and the shelf memberships below are written
        # by a Core ``pg_insert`` that the unit of work does not order against
        # a pending ORM add. Without this the child INSERT reached Postgres
        # first and the whole projection died on
        # ``commerce_product_categories_category_id_fkey`` -- 55 of 267
        # projection tasks, which is why every product stayed in
        # "Uncategorized" while the real collections reported zero.
        await session.flush()
    sources = dict(category.field_sources or {})
    source = {
        "kind": "site_health",
        "source_id": str(analysis.id),
        "version": COMMERCE_PROJECTOR_VERSION,
    }
    if _dict_value(sources.get("name")).get("kind") != "edit":
        category.name = safe_title[:255]
        category.normalized_name = normalized[:255]
        sources["name"] = source
    if _dict_value(sources.get("role")).get("kind") != "edit":
        category.role = role if role in {"hub", "leaf"} else "unknown"
        sources["role"] = source
    category.field_sources = sources
    category.source_analysis_id = analysis.id
    category.projector_version = COMMERCE_PROJECTOR_VERSION
    return category
