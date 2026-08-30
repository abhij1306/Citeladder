"""Catalog specifications for crawl-finalize architecture findings."""

from __future__ import annotations

from typing import Any, Final

from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    CATEGORY_ARCHITECTURE,
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_CLUSTER,
    RULE_SCOPE_GRAPH,
    SCORE_ROLE_WEB_FUNDAMENTALS,
)

_WEIGHTS = {SEVERITY_HIGH: 3.0, SEVERITY_MEDIUM: 2.0}


def _rule(
    rule_id: str,
    *,
    severity: str,
    description: str,
    remediation: str,
    display_label: str,
    scope: str = RULE_SCOPE_GRAPH,
    scored: bool = True,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_version": RULE_CATALOG_VERSION,
        "dimension": DIMENSION_TECHNICAL,
        "category": CATEGORY_ARCHITECTURE,
        "severity": severity,
        "weight": _WEIGHTS[severity] if scored else 0.0,
        "applicability_key": APPLICABILITY_CRAWL_FINALIZE,
        "scope": scope,
        "description": description,
        "remediation": remediation,
        "display_label": display_label,
        "score_roles": (SCORE_ROLE_WEB_FUNDAMENTALS,) if scored else (),
    }


ARCHITECTURE_RULE_SPECS: Final[tuple[dict[str, Any], ...]] = (
    _rule(
        "architecture.excessive_depth",
        severity=SEVERITY_HIGH,
        description=(
            "Some observed pages require five or more clicks from the homepage."
        ),
        remediation=(
            "Add or strengthen hub links so important pages are easier to reach."
        ),
        display_label="Pages buried too deeply",
    ),
    _rule(
        "architecture.breadcrumb_hierarchy_conflict",
        severity=SEVERITY_MEDIUM,
        description="Visible breadcrumbs contradict explicit structural relationships.",
        remediation=(
            "Align visible breadcrumbs with BreadcrumbList or isPartOf relationships."
        ),
        display_label="Breadcrumb hierarchy conflict",
    ),
    _rule(
        "architecture.duplicate_metadata_in_page_kind",
        severity=SEVERITY_MEDIUM,
        description=(
            "An observed page kind repeats title and description metadata across pages."
        ),
        remediation=("Give each page metadata that describes its distinct purpose."),
        display_label="Duplicate metadata within a page kind",
        scope=RULE_SCOPE_CLUSTER,
        scored=False,
    ),
    _rule(
        "architecture.orphan_pages",
        severity=SEVERITY_HIGH,
        description="Some observed non-home pages have no internal inbound links.",
        remediation=(
            "Link orphaned pages from a relevant crawlable hub or contextual page."
        ),
        display_label="Orphan pages",
    ),
    _rule(
        "architecture.parentless_detail_pages",
        severity=SEVERITY_MEDIUM,
        description=(
            "Some observed detail pages have no conservative structural parent."
        ),
        remediation="Connect detail pages to a clear category, section, or hub parent.",
        display_label="Detail pages without a clear parent",
    ),
    _rule(
        "architecture.unhubbed_page_kind",
        severity=SEVERITY_MEDIUM,
        description="A large observed detail page kind has no crawlable hub.",
        remediation=("Create or expose a hub that links to the related detail pages."),
        display_label="Page kind without an observed hub",
    ),
)


__all__ = ["ARCHITECTURE_RULE_SPECS"]
