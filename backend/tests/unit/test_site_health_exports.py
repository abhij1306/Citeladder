"""Unit tests for the Site Health CSV/Markdown exporters (pure renderers).

The exporters render already-projected dict rows into RFC-4180 CSV and safe
Markdown tables. They never touch the DB, so these tests cover: header/column
ordering, RFC-4180 quoting of embedded delimiters/quotes/newlines, Markdown
cell escaping (``|``, ``\\``, newline collapse), boolean/None cell rendering,
and the always-valid empty table.
"""

from __future__ import annotations

import csv
import io

import pytest

from app.analysis.site_health.exports import (
    _VIEW_COLUMNS,
    EXPORT_VIEWS,
    architecture_to_markdown,
    rows_to_csv,
    rows_to_markdown,
)
from app.core.config.site_health_archetypes import ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_export_views_cover_the_three_surfaces() -> None:
    assert EXPORT_VIEWS == frozenset({"inventory", "pages", "issues"})


@pytest.mark.parametrize("view", sorted(EXPORT_VIEWS))
def test_csv_header_matches_view_columns(view: str) -> None:
    text = rows_to_csv(view, [])
    rows = _parse_csv(text)
    assert rows[0] == _VIEW_COLUMNS[view]


def test_csv_renders_bool_and_none_cells() -> None:
    items = [
        {
            "site_url_id": "abc",
            "normalized_url": "https://x/",
            "display_url": "https://x/",
            "title": None,
            "content_type": "text/html",
            "source": "sitemap",
            "depth": 0,
            "monitored": True,
            "issue_count": None,
            "technical_integrity_score": None,
            "aeo_readiness_score": None,
            "aeo_measurement_coverage": None,
            "last_audited": None,
        }
    ]
    rows = _parse_csv(rows_to_csv("inventory", items))
    data = dict(zip(rows[0], rows[1], strict=True))
    # None -> empty string; bool -> lowercase literal.
    assert data["title"] == ""
    assert data["issue_count"] == ""
    assert data["monitored"] == "true"


def test_csv_rfc4180_quoting_of_delimiters_quotes_newlines() -> None:
    items = [
        {
            "id": "1",
            "rule_id": "technical.title_present",
            "title": 'A "quoted", comma title',
            "dimension": "technical",
            "category": "meta",
            "severity": "critical",
            "affected_url_count": 3,
            "remediation": "line one\nline two",
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    text = rows_to_csv("issues", items)
    rows = _parse_csv(text)
    data = dict(zip(rows[0], rows[1], strict=True))
    # csv round-trips the raw values intact.
    assert data["title"] == 'A "quoted", comma title'
    assert data["remediation"] == "line one\nline two"


def test_markdown_always_emits_title_header_separator_even_when_empty() -> None:
    md = rows_to_markdown("pages", [])
    lines = md.splitlines()
    assert lines[0].startswith("# ")
    # Header row + separator row present with the right column count.
    header_idx = next(i for i, ln in enumerate(lines) if ln.startswith("|"))
    header = lines[header_idx]
    separator = lines[header_idx + 1]
    ncols = len(_VIEW_COLUMNS["pages"])
    assert header.count("|") == ncols + 1
    assert set(separator.replace("|", "").replace("-", "").strip()) == set()


def test_markdown_escapes_pipes_backslashes_and_collapses_newlines() -> None:
    items = [
        {
            "id": "1",
            "rule_id": "r",
            "title": "a | b \\ c",
            "dimension": "technical",
            "category": "meta",
            "severity": "info",
            "affected_url_count": 1,
            "remediation": "fix\nthis\r\nnow",
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    md = rows_to_markdown("issues", items)
    # The data row must escape the pipe/backslash and collapse the newlines.
    data_line = next(ln for ln in md.splitlines() if "fix" in ln and ln.startswith("|"))
    assert "\\|" in data_line
    assert "\\\\" in data_line
    assert "\n" not in data_line.replace("|", "")
    assert "\r" not in data_line
    # Newlines are collapsed to spaces; no raw line break leaks into the cell.
    assert "fix" in data_line and "now" in data_line


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_csv_neutralizes_leading_spreadsheet_formula_triggers(
    trigger: str,
) -> None:
    """A cell that begins with =/+/-/@ is prefixed with ``'`` (formula guard).

    This is the OWASP CSV-injection mitigation: a URL/title/remediation crafted
    to begin with a formula trigger must render as literal text in a spreadsheet
    rather than being evaluated.
    """
    payload = f'{trigger}HYPERLINK("http://evil")'
    items = [
        {
            "id": "1",
            "rule_id": "r",
            "title": payload,
            "dimension": "technical",
            "category": "meta",
            "severity": "info",
            "affected_url_count": 1,
            "remediation": payload,
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    rows = _parse_csv(rows_to_csv("issues", items))
    data = dict(zip(rows[0], rows[1], strict=True))
    # The neutralizing quote is prepended (and survives CSV round-trip).
    assert data["title"] == "'" + payload
    assert data["remediation"] == "'" + payload


@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_markdown_neutralizes_leading_spreadsheet_formula_triggers(
    trigger: str,
) -> None:
    """Markdown cells are also formula-neutralized (tables get pasted to Excel)."""
    payload = f"{trigger}1+1"
    items = [
        {
            "id": "1",
            "rule_id": "r",
            "title": payload,
            "dimension": "technical",
            "category": "meta",
            "severity": "info",
            "affected_url_count": 1,
            "remediation": "ok",
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    md = rows_to_markdown("issues", items)
    data_line = next(
        ln for ln in md.splitlines() if payload in ln and ln.startswith("|")
    )
    # The cell text is prefixed with a single quote before the trigger char.
    assert f"'{payload}" in data_line


@pytest.mark.parametrize("prefix", ["\t", "\r", "\n", "  \t"])
def test_csv_neutralizes_whitespace_hidden_formula_triggers(
    prefix: str,
) -> None:
    """A leading tab/CR/LF (or run of whitespace) hiding a trigger is also

    neutralized: some spreadsheets still treat the cell as a formula once
    leading whitespace/control characters are stripped during paste.
    """
    payload = f'{prefix}=HYPERLINK("http://evil")'
    items = [
        {
            "id": "1",
            "rule_id": "r",
            "title": payload,
            "dimension": "technical",
            "category": "meta",
            "severity": "info",
            "affected_url_count": 1,
            "remediation": payload,
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    rows = _parse_csv(rows_to_csv("issues", items))
    data = dict(zip(rows[0], rows[1], strict=True))
    assert data["title"].startswith("'")
    assert data["remediation"].startswith("'")


def test_csv_does_not_prefix_safe_leading_characters() -> None:
    """A normal https URL / plain text is emitted verbatim (no false positive)."""
    items = [
        {
            "id": "1",
            "rule_id": "technical.title_present",
            "title": "Missing page title",
            "dimension": "technical",
            "category": "meta",
            "severity": "critical",
            "affected_url_count": 1,
            "remediation": "https://example.test/fix",
            "analyzer_version": "v1",
            "rule_version": "v1",
            "created_at": "2026-01-01T00:00:00Z",
        }
    ]
    rows = _parse_csv(rows_to_csv("issues", items))
    data = dict(zip(rows[0], rows[1], strict=True))
    assert data["title"] == "Missing page title"
    assert data["remediation"] == "https://example.test/fix"


def _architecture_model(nodes: list[dict], **overrides) -> dict:
    return {
        "coverage_state": "complete",
        "nodes": nodes,
        **overrides,
    }


def _node(
    node_id: str,
    url: str,
    *,
    parent: str | None,
    kind: str = "product",
    family: str = "",
) -> dict:
    return {
        "site_url_id": node_id,
        "url": url,
        "page_kind": kind,
        "family": family,
        "parent_site_url_id": parent,
    }


def test_architecture_markdown_nests_resolved_parents() -> None:
    model = _architecture_model(
        [
            _node("1", "https://x.test/", parent=None, kind="homepage"),
            _node("2", "https://x.test/shoes", parent="1", kind="category"),
            _node("3", "https://x.test/shoes/boot", parent="2"),
        ]
    )
    body = architecture_to_markdown(model)
    lines = body.splitlines()
    tree = lines[lines.index("```") + 1 :]
    assert tree[0] == "/"
    assert tree[1] == "`-- https://x.test/  [homepage]"
    assert tree[2] == "    `-- https://x.test/shoes  [category]"
    assert tree[3] == "        `-- https://x.test/shoes/boot  [product]"
    assert "Coverage: complete" in body


def test_architecture_markdown_collapses_a_large_page_kind_group_to_a_count() -> None:
    """A large product sibling group is a count, not a flat URL dump."""
    nodes = [_node("root", "https://x.test/", parent=None, kind="homepage")]
    nodes += [
        _node(
            str(index),
            f"https://x.test/p/{index}",
            parent="root",
        )
        for index in range(ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN)
    ]
    tree = architecture_to_markdown(_architecture_model(nodes)).splitlines()
    assert f"    `-- [{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN} product]" in tree
    assert not any("https://x.test/p/" in line for line in tree)


def test_architecture_markdown_does_not_collapse_nodes_with_descendants() -> None:
    nodes = [_node("root", "https://x.test/", parent=None, kind="homepage")]
    nodes += [
        _node(str(index), f"https://x.test/p/{index}", parent="root")
        for index in range(ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN)
    ]
    nodes.append(_node("child", "https://x.test/p/0/details", parent="0", kind="docs"))

    body = architecture_to_markdown(_architecture_model(nodes))

    assert f"[{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN} product]" not in body
    assert "https://x.test/p/0/details" in body


def test_architecture_markdown_does_not_collapse_mixed_page_kinds() -> None:
    nodes = [
        _node("root", "https://x.test/", parent=None, kind="homepage"),
        _node("section", "https://x.test/section", parent="root", kind="category"),
    ]
    nodes += [
        _node(
            str(index),
            f"https://x.test/section/item-{index}",
            parent="section",
            kind="article" if index % 2 else "service",
        )
        for index in range(ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN)
    ]
    body = architecture_to_markdown(_architecture_model(nodes))
    assert "https://x.test/section/item-0" in body
    last_item = f"https://x.test/section/item-{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN - 1}"
    assert last_item in body
    assert f"[{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN} article]" not in body
    assert f"[{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN} service]" not in body


def test_architecture_markdown_never_collapses_root_group() -> None:
    nodes = [
        _node(
            str(index),
            f"https://x.test/root-{index}",
            parent=None,
            family="/root/*",
        )
        for index in range(ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN)
    ]
    body = architecture_to_markdown(_architecture_model(nodes))
    assert "https://x.test/root-0" in body
    assert f"[{ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN} product]" not in body


def test_architecture_markdown_reparents_nodes_whose_parent_is_absent() -> None:
    """A parent outside the projection cannot silently swallow its child."""
    tree = architecture_to_markdown(
        _architecture_model(
            [_node("2", "https://x.test/orphan", parent="missing-parent")]
        )
    ).splitlines()
    assert "`-- https://x.test/orphan  [product]" in tree


def test_architecture_markdown_states_unknown_coverage_and_omits_absence() -> None:
    body = architecture_to_markdown(
        _architecture_model(
            [_node("1", "https://x.test/", parent=None)],
            coverage_state="unknown",
        )
    )
    assert "Coverage: unknown" in body
    assert "Common structures not observed" not in body
    assert "## Observed" not in body


def test_architecture_markdown_keeps_a_self_parenting_node() -> None:
    """A page naming itself as its parent must not delete itself from the tree."""
    tree = architecture_to_markdown(
        _architecture_model([_node("1", "https://x.test/loop", parent="1")])
    ).splitlines()
    assert "`-- https://x.test/loop  [product]" in tree


def test_architecture_markdown_keeps_nodes_trapped_in_a_parent_cycle() -> None:
    """Two nodes naming each other are unreachable from any root — still shown."""
    body = architecture_to_markdown(
        _architecture_model(
            [
                _node("1", "https://x.test/a", parent="2"),
                _node("2", "https://x.test/b", parent="1"),
            ]
        )
    )
    assert body.count("https://x.test/a") == 1
    assert body.count("https://x.test/b") == 1
