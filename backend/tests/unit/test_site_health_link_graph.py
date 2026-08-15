from __future__ import annotations

import uuid

import pytest

from app.analysis.site_health.link_graph import (
    LinkGraphNodeInput,
    LinkGraphReferenceInput,
    analyze_link_graph,
)


def _id(value: int) -> uuid.UUID:
    return uuid.UUID(int=value)


def _node(value: int, path: str, *, indexable: bool = True, nofollow: bool = False):
    return LinkGraphNodeInput(
        site_url_id=_id(value),
        source_analysis_id=_id(1000 + value),
        normalized_url=f"https://example.test/{path}",
        title=path.replace("-", " "),
        indexable=indexable,
        page_nofollow=nofollow,
    )


def test_pagerank_depth_and_collapsed_followed_topology_are_deterministic() -> None:
    nodes = [_node(1, ""), _node(2, "guide"), _node(3, "guide-detail")]
    references = [
        LinkGraphReferenceInput(
            _id(1), _id(2), "https://example.test/guide", anchor_text="Guide"
        ),
        LinkGraphReferenceInput(
            _id(1), _id(2), "https://example.test/guide", anchor_text="Read guide"
        ),
        LinkGraphReferenceInput(_id(2), _id(3), "https://example.test/guide-detail"),
        LinkGraphReferenceInput(
            _id(3), _id(2), "https://example.test/guide", rel="nofollow"
        ),
    ]

    first = analyze_link_graph(
        nodes, references, root_site_url_id=_id(1), complete_coverage=True
    )
    second = analyze_link_graph(
        list(reversed(nodes)),
        list(reversed(references)),
        root_site_url_id=_id(1),
        complete_coverage=True,
    )

    assert first == second
    assert sum(node.pagerank for node in first.nodes) == pytest.approx(1.0)
    assert [node.click_depth for node in first.nodes] == [0, 1, 2]
    edge = next(item for item in first.edges if item.source_site_url_id == _id(1))
    assert (edge.occurrence_count, edge.followed_occurrence_count) == (2, 2)
    assert edge.anchor_texts == ("Guide", "Read guide")


def test_nofollow_and_unreachable_nodes_remain_observed_without_topology_mass() -> None:
    nodes = [_node(1, ""), _node(2, "target"), _node(3, "isolated")]
    result = analyze_link_graph(
        nodes,
        [
            LinkGraphReferenceInput(
                _id(1),
                _id(2),
                "https://example.test/target",
                rel="nofollow",
            )
        ],
        root_site_url_id=_id(1),
        complete_coverage=False,
        limitations=("Only 3 of 5 selected analyses completed.",),
    )

    assert result.state == "incomplete"
    assert result.edges[0].followed is False
    assert (
        next(node for node in result.nodes if node.site_url_id == _id(2)).click_depth
        is None
    )
    assert all(not node.suggested_source_ids for node in result.nodes)
    assert result.limitations == ("Only 3 of 5 selected analyses completed.",)


def test_weak_authority_requires_twenty_nodes_and_suggestions_are_bounded() -> None:
    nodes = [_node(index, f"guides/topic-{index}") for index in range(1, 21)]
    references = [
        LinkGraphReferenceInput(
            _id(1), _id(index), f"https://example.test/guides/topic-{index}"
        )
        for index in range(2, 21)
    ]
    result = analyze_link_graph(
        nodes, references, root_site_url_id=_id(1), complete_coverage=True
    )

    weak = [node for node in result.nodes if node.weak_authority]
    assert weak
    assert all(len(node.suggested_source_ids) <= 3 for node in weak)
