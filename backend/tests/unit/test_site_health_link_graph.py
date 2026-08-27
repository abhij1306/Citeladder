"""Deterministic transient-graph coverage for Site Health link metrics."""

from __future__ import annotations

import random
import uuid

from app.analysis.site_health.link_graph import LinkPageInput, build_link_metrics


def _id(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


def _page(
    value: int,
    path: str,
    anchors: list[dict[str, object]],
    *,
    final_url: str | None = None,
    page_nofollow: bool = False,
    aliases: tuple[str, ...] = (),
) -> LinkPageInput:
    url = f"https://example.test{path}"
    return LinkPageInput(
        site_url_id=_id(value),
        normalized_url=url,
        final_url=final_url or url,
        artifact_id=_id(100 + value),
        facts={
            "robots": {"nofollow": page_nofollow},
            "links": {"anchors": anchors},
        },
        aliases=aliases,
    )


def _anchor(
    url: str,
    *,
    region: str = "main",
    rel: str = "",
    internal: bool = True,
) -> dict[str, object]:
    return {
        "url": url,
        "is_internal": internal,
        "region": region,
        "rel": rel,
    }


def _metrics(pages: list[LinkPageInput]):
    return {
        row.site_url_id: row
        for row in build_link_metrics(
            pages, home_url="https://example.test/", neighbour_limit=2
        )
    }


def test_graph_collapses_duplicates_counts_off_crawl_and_separates_regions() -> None:
    pages = [
        _page(
            1,
            "/",
            [
                _anchor("/category", region="nav"),
                _anchor("/category", region="main"),
                _anchor("/outside-crawl"),
                _anchor("https://external.test/page", internal=False),
            ],
        ),
        _page(2, "/category", [_anchor("/product", region="main")]),
        _page(3, "/product", []),
    ]

    rows = _metrics(pages)

    assert rows[_id(1)].outbound_count == 2
    assert rows[_id(1)].main_content_outbound_count == 2
    assert rows[_id(2)].inbound_count == 1
    assert rows[_id(2)].main_content_inbound_count == 1
    assert rows[_id(2)].top_inbound[0]["anchor_count"] == 2
    assert rows[_id(3)].depth_from_home == 2
    assert rows[_id(1)].source_page_count == 3
    assert rows[_id(1)].source_artifact_ids == [_id(101), _id(102), _id(103)]


def test_nofollow_and_page_nofollow_do_not_create_depth_paths() -> None:
    pages = [
        _page(1, "/", [_anchor("/blocked", rel="nofollow sponsored")]),
        _page(2, "/blocked", [_anchor("/child")], page_nofollow=True),
        _page(3, "/child", []),
    ]

    rows = _metrics(pages)

    assert rows[_id(2)].inbound_count == 1
    assert rows[_id(2)].nofollow_inbound_count == 1
    assert rows[_id(2)].depth_from_home is None
    assert rows[_id(3)].nofollow_inbound_count == 1
    assert rows[_id(3)].depth_from_home is None
    assert rows[_id(1)].top_outbound[0]["rel"] == ["nofollow", "sponsored"]


def test_redirect_alias_resolves_to_the_crawled_node() -> None:
    pages = [
        _page(1, "/", [_anchor("/old-product")]),
        _page(
            2,
            "/products/widget",
            [],
            aliases=("https://example.test/old-product",),
        ),
    ]

    rows = _metrics(pages)

    assert rows[_id(2)].inbound_count == 1
    assert rows[_id(2)].depth_from_home == 1


def test_exact_final_url_node_wins_over_a_redirect_source_alias() -> None:
    pages = [
        _page(1, "/", [_anchor("/new-product")]),
        _page(2, "/old-product", [], final_url="https://example.test/new-product"),
        _page(3, "/new-product", []),
    ]

    rows = _metrics(pages)

    assert rows[_id(2)].inbound_count == 0
    assert rows[_id(3)].inbound_count == 1
    assert rows[_id(3)].depth_from_home == 1


def test_resolved_aliases_emit_the_target_nodes_stable_url() -> None:
    aliases = [
        "https://example.test/products/widget?campaign=one",
        "https://example.test/old-widget",
    ]
    anchors = [_anchor(alias) for alias in aliases]
    pages = [
        _page(1, "/", anchors),
        _page(2, "/products/widget", [], aliases=tuple(aliases)),
    ]
    expected = _metrics(pages)[_id(1)].top_outbound

    random.Random(13).shuffle(aliases)
    random.Random(17).shuffle(anchors)
    shuffled_pages = [
        _page(1, "/", anchors),
        _page(2, "/products/widget", [], aliases=tuple(aliases)),
    ]
    actual = _metrics(shuffled_pages)[_id(1)].top_outbound

    assert actual == expected
    assert actual[0]["url"] == "https://example.test/products/widget"
    assert actual[0]["anchor_count"] == 2


def test_graph_is_deterministic_under_shuffled_pages_and_anchors() -> None:
    anchors = [_anchor("/b"), _anchor("/a"), _anchor("/b", region="nav")]
    pages = [_page(1, "/", anchors), _page(2, "/a", []), _page(3, "/b", [])]
    expected = build_link_metrics(
        pages, home_url="https://example.test/", neighbour_limit=10
    )

    random.Random(7).shuffle(pages)
    random.Random(11).shuffle(anchors)
    actual = build_link_metrics(
        pages, home_url="https://example.test/", neighbour_limit=10
    )

    assert actual == expected
