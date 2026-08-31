# Site Health persisted-data exports (Slice 6, workspace-safe).
#
# Pure renderers over ALREADY-PROJECTED dicts (the exact shapes the service
# layer produces for the inventory / pages / issues views). They never re-score,
# never fetch, and never read a raw body — the router hands them the same
# workspace-scoped projections the JSON API returns, so an export can never leak
# more than the API. CSV quoting/escaping is delegated to the stdlib ``csv``
# writer; a cell beginning with a spreadsheet-formula trigger (``=``/``+``/``-``
# /``@``) is additionally prefixed with ``'`` to neutralize CSV/formula
# injection. Markdown cell content is escaped (and formula-neutralized) so a
# URL/title containing ``|`` or a newline can never break the table. Empty
# result sets still render a valid header row / empty table, and ``None``
# renders as an empty cell.
from __future__ import annotations

import csv
import io

from app.analysis.csv_cells import csv_cell, md_cell
from app.core.config.site_health_archetypes import ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN

_INVENTORY_COLUMNS = [
    "site_url_id",
    "normalized_url",
    "display_url",
    "title",
    "content_type",
    "source",
    "depth",
    "monitored",
    "page_kind",
    "issue_count",
    "web_fundamentals_score",
    "aeo_readiness_score",
    "aeo_measurement_coverage",
    "aeo_measurement_state",
    "aeo_measurement_reason",
    "last_audited",
]

_PAGES_COLUMNS = [
    "site_url_id",
    "normalized_url",
    "display_url",
    "title",
    "monitored",
    "analysis_status",
    "error_code",
    "page_kind",
    "issue_count",
    "web_fundamentals_score",
    "aeo_readiness_score",
    "aeo_measurement_coverage",
    "aeo_measurement_state",
    "aeo_measurement_reason",
    "last_audited",
]

_ISSUES_COLUMNS = [
    "id",
    "rule_id",
    "title",
    "dimension",
    "category",
    "severity",
    "finding_class",
    # Distinct page types of the group's affected analyses (comma-joined).
    "page_kind",
    "affected_url_count",
    "description",
    "remediation",
    "analyzer_version",
    "rule_version",
    "created_at",
]

_VIEW_COLUMNS: dict[str, list[str]] = {
    "inventory": _INVENTORY_COLUMNS,
    "pages": _PAGES_COLUMNS,
    "issues": _ISSUES_COLUMNS,
}

EXPORT_VIEWS = frozenset(_VIEW_COLUMNS)


def rows_to_csv(view: str, items: list[dict]) -> str:
    """Render projected ``items`` for ``view`` as CSV (RFC-4180 via stdlib).

    The stdlib writer quotes/escapes any cell containing a comma, quote, or
    newline, so a URL or remediation string can never break the columns.
    """
    columns = _VIEW_COLUMNS[view]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        writer.writerow({col: csv_cell(item.get(col)) for col in columns})
    return buffer.getvalue()


_VIEW_TITLES: dict[str, str] = {
    "inventory": "Site Health — URL Inventory",
    "pages": "Site Health — Analyzed Pages",
    "issues": "Site Health — Issues",
}


def rows_to_markdown(view: str, items: list[dict]) -> str:
    """Render projected ``items`` for ``view`` as a Markdown table.

    Always emits the title + header + separator, so an empty result set is a
    valid (empty) table rather than a broken document.
    """
    columns = _VIEW_COLUMNS[view]
    lines = [f"# {_VIEW_TITLES.get(view, 'Site Health Export')}", ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("|" + "|".join(["---"] * len(columns)) + "|")
    for item in items:
        lines.append(
            "| " + " | ".join(md_cell(item.get(col)) for col in columns) + " |"
        )
    lines.append("")
    return "\n".join(lines)


# =========================================================================
# Observed architecture (Markdown only — a tree is not a table)
# =========================================================================
ARCHITECTURE_EXPORT_VIEW = "architecture"

_COVERAGE_NOTE = {
    "complete": "Coverage: complete — the discovery frontier was exhausted.",
    "partial": (
        "Coverage: partial — the crawl hit its page budget, so this is what "
        "CiteLadder observed, not the whole site."
    ),
    "unknown": ("Coverage: unknown — the crawl could not prove it saw the whole site."),
}


def _node_order(node: dict) -> tuple[str, str]:
    return (str(node.get("url") or ""), str(node.get("site_url_id") or ""))


def _children_by_parent(nodes: list[dict]) -> dict[str | None, list[dict]]:
    children: dict[str | None, list[dict]] = {}
    for node in nodes:
        parent = node.get("parent_site_url_id") or None
        children.setdefault(parent, []).append(node)
    for group in children.values():
        group.sort(key=_node_order)
    return children


def _node_label(node: dict) -> str:
    kind = str(node.get("page_kind") or "")
    url = str(node.get("url") or "")
    return f"{url}  [{kind}]" if kind else url


def _collapsed_lines(group: list[dict], prefix: str) -> list[str]:
    """Render a large sibling set as one count line per page kind.

    A 142-product sibling set listed URL by URL is not readable architecture; the
    count IS the observation.
    """
    counts: dict[str, int] = {}
    for node in group:
        counts[str(node.get("page_kind") or "unclassified")] = (
            counts.get(str(node.get("page_kind") or "unclassified"), 0) + 1
        )
    lines: list[str] = []
    ordered = sorted(counts.items())
    for index, (kind, count) in enumerate(ordered):
        connector = "`-- " if index == len(ordered) - 1 else "|-- "
        lines.append(f"{prefix}{connector}[{count} {kind}]")
    return lines


def _tree_lines(
    node_id: str | None,
    children: dict[str | None, list[dict]],
    *,
    prefix: str,
    seen: set[str],
) -> list[str]:
    group = children.get(node_id, [])
    if node_id is not None and _is_large_page_kind_group(group, children):
        return _collapsed_lines(group, prefix)
    lines: list[str] = []
    for index, node in enumerate(group):
        last = index == len(group) - 1
        child_id = str(node.get("site_url_id") or "")
        if not child_id or child_id in seen:
            continue
        seen.add(child_id)
        lines.append(f"{prefix}{'`-- ' if last else '|-- '}{_node_label(node)}")
        lines.extend(
            _tree_lines(
                child_id,
                children,
                prefix=prefix + ("    " if last else "|   "),
                seen=seen,
            )
        )
    return lines


def _is_large_page_kind_group(
    group: list[dict], children: dict[str | None, list[dict]]
) -> bool:
    """Collapse only a large, homogeneous sibling group of leaf pages."""
    page_kinds = {str(node.get("page_kind") or "") for node in group}
    return (
        len(group) >= ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN
        and len(page_kinds) == 1
        and "" not in page_kinds
        and not any(children.get(str(node.get("site_url_id") or "")) for node in group)
    )


def _initial_roots(
    nodes: list[dict], children: dict[str | None, list[dict]]
) -> list[dict]:
    """Nodes with no usable parent: absent from the projection, or self-named."""
    known = {str(node.get("site_url_id") or "") for node in nodes}
    roots = list(children.get(None, []))
    for parent, group in children.items():
        if parent is None:
            continue
        if parent not in known:
            roots.extend(group)
            continue
        # A self-parent has no ancestor to hang from, so it is its own root.
        roots.extend(node for node in group if str(node.get("site_url_id")) == parent)
    return roots


def _reachable(roots: list[dict], children: dict[str | None, list[dict]]) -> set[str]:
    reached = {str(node.get("site_url_id") or "") for node in roots}
    queue = list(reached)
    while queue:
        for child in children.get(queue.pop(), []):
            child_id = str(child.get("site_url_id") or "")
            if child_id and child_id not in reached:
                reached.add(child_id)
                queue.append(child_id)
    return reached


def _rooted_tree(nodes: list[dict]) -> dict[str | None, list[dict]]:
    """Children keyed by parent, with every unreachable node hoisted to root.

    Three ways a node can fail to hang off a root, all of which used to delete
    it from the rendered tree entirely: its parent is outside this projection,
    it names itself as its own parent, or it sits in a parent cycle (A names B,
    B names A).

    So the roots are settled by traversal, not by the ``parent is None`` test:
    anything the walk never reaches becomes a root itself. A tree that silently
    drops pages is worse than a flat one.
    """
    children = _children_by_parent(nodes)
    roots = _initial_roots(nodes, children)
    reached = _reachable(roots, children)
    roots.extend(
        node for node in nodes if str(node.get("site_url_id") or "") not in reached
    )
    roots.sort(key=_node_order)
    return {**children, None: roots}


def architecture_to_markdown(model: dict) -> str:
    """Render the observed-architecture projection as Markdown + an ASCII tree.

    Renders exactly what the API projected, always including coverage state.
    """
    coverage = str(model.get("coverage_state") or "unknown")
    nodes = [node for node in model.get("nodes") or [] if isinstance(node, dict)]
    lines = [
        "# Site Health — Observed architecture",
        "",
        f"{len(nodes)} pages sampled · "
        f"{_COVERAGE_NOTE.get(coverage, _COVERAGE_NOTE['unknown'])}",
        "",
        "## Tree",
        "",
        "```",
        "/",
        *_tree_lines(None, _rooted_tree(nodes), prefix="", seen=set()),
        "```",
        "",
    ]
    return "\n".join(lines)
