"""Per-page internal-link projections: the crawl's metric rows and its sorts.

Split out of ``queries`` so one module owns everything that reads
``SitePageLinkMetric``: which rows belong to a crawl's exact processing
versions, how a link column becomes a keyset sort, and how a metric row becomes
a bounded API projection.

The one rule that runs through all of it: a URL with no metric row is
UNMEASURED, not unlinked. Projections report ``None`` rather than ``0``, and the
sorts fall back only for ORDERING (an unmeasured page sorts as if it had no
inbound links, and an unmeasured depth sorts last) — never for display.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_link_metrics import LINK_METRIC_FORMULA_VERSION
from app.domain.site_health.service.common import _decode_int_keyset
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.urls import SiteUrl

# Pages sort catalog. `url` is the historical `(normalized_url, id)` keyset;
# the three link sorts are keyset over `(metric_value, site_url_id)` joined to
# the crawl's SitePageLinkMetric rows. A page with no metric row sorts as if it
# had none of that signal (0 inbound links) or as unreachable (depth sentinel)
# rather than dropping out of the list.
#
# The depth sentinel is the maximum value the `Integer` depth column can hold,
# so no measured depth can ever equal or exceed it — a smaller sentinel would
# let a (pathological) deep page tie with "unmeasured" and make the keyset
# ordering ambiguous. Keeping it inside one int also keeps the cursor two
# values wide, so pagination stays stable.
_DEPTH_SORT_SENTINEL = 2_147_483_647

_PAGE_SORTS: dict[str, tuple[str, bool]] = {
    "inbound": ("inbound_count", True),
    "main_content_inbound": ("main_content_inbound_count", True),
    "depth": ("depth_from_home", False),
}
PAGE_SORTS = frozenset({"url", *_PAGE_SORTS})


def _link_metric_join_condition(crawl: SiteCrawl):
    """Rows of the ONE link-metric projection this crawl's versions produced."""
    return and_(
        SitePageLinkMetric.site_url_id == SiteUrl.id,
        SitePageLinkMetric.crawl_id == crawl.id,
        SitePageLinkMetric.workspace_id == crawl.workspace_id,
        SitePageLinkMetric.project_id == crawl.project_id,
        SitePageLinkMetric.extractor_version == crawl.extractor_version,
        SitePageLinkMetric.formula_version == LINK_METRIC_FORMULA_VERSION,
    )


def _page_sort_expression(sort: str):
    column, descending = _PAGE_SORTS[sort]
    default = _DEPTH_SORT_SENTINEL if column == "depth_from_home" else 0
    expression = func.coalesce(getattr(SitePageLinkMetric, column), default)
    return expression, descending


async def _link_metrics_by_site_url(
    session: AsyncSession, *, crawl: SiteCrawl, site_url_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, SitePageLinkMetric]:
    """The crawl's persisted link metrics for a page window, keyed by URL id."""
    if not site_url_ids:
        return {}
    rows = await session.scalars(
        select(SitePageLinkMetric).where(
            SitePageLinkMetric.workspace_id == crawl.workspace_id,
            SitePageLinkMetric.project_id == crawl.project_id,
            SitePageLinkMetric.crawl_id == crawl.id,
            SitePageLinkMetric.extractor_version == crawl.extractor_version,
            SitePageLinkMetric.formula_version == LINK_METRIC_FORMULA_VERSION,
            SitePageLinkMetric.site_url_id.in_(site_url_ids),
        )
    )
    return {row.site_url_id: row for row in rows.all()}


def _internal_links_row(metric: SitePageLinkMetric | None) -> dict | None:
    """Bounded internal-link projection for one page (None when unmeasured)."""
    if metric is None:
        return None
    return {
        "inbound_count": metric.inbound_count,
        "outbound_count": metric.outbound_count,
        "main_content_inbound_count": metric.main_content_inbound_count,
        "main_content_outbound_count": metric.main_content_outbound_count,
        "nofollow_inbound_count": metric.nofollow_inbound_count,
        "depth_from_home": metric.depth_from_home,
        "source_page_count": metric.source_page_count,
        "top_inbound": list(metric.top_inbound or []),
        "top_outbound": list(metric.top_outbound or []),
        "formula_version": metric.formula_version,
    }


def _sorted_page_stmt(stmt, *, crawl: SiteCrawl, sort: str, cursor, scope, filters):
    """Apply one link-metric sort's join, cursor predicate and ordering.

    Descending sorts compare the whole ``(value, id)`` tuple downward so the
    tie-breaker travels in the same direction as the sort — a mixed-direction
    tuple comparison silently skips or repeats rows at every tie.
    """
    expression, descending = _page_sort_expression(sort)
    stmt = stmt.add_columns(expression.label("sort_value")).outerjoin(
        SitePageLinkMetric, _link_metric_join_condition(crawl)
    )
    if cursor:
        cur_value, cur_id = _decode_int_keyset(cursor, scope=scope, filters=filters)
        key = tuple_(expression, SiteUrl.id)
        stmt = stmt.where(
            key < (cur_value, cur_id) if descending else key > (cur_value, cur_id)
        )
    order = (
        (expression.desc(), SiteUrl.id.desc())
        if descending
        else (expression.asc(), SiteUrl.id.asc())
    )
    return stmt.order_by(*order)


def _page_link_fields(metric: SitePageLinkMetric | None) -> dict:
    """The three link columns a page-list row carries."""
    return {
        "inbound_count": metric.inbound_count if metric is not None else None,
        "main_content_inbound_count": (
            metric.main_content_inbound_count if metric is not None else None
        ),
        "depth_from_home": metric.depth_from_home if metric is not None else None,
    }


__all__ = [
    "PAGE_SORTS",
    "_internal_links_row",
    "_link_metrics_by_site_url",
    "_page_link_fields",
    "_sorted_page_stmt",
]
