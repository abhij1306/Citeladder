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


def _rule(
    rule_id: str,
    *,
    severity: str,
    description: str,
    remediation: str,
    display_label: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "rule_version": RULE_CATALOG_VERSION,
        "dimension": DIMENSION_TECHNICAL,
        "category": CATEGORY_ARCHITECTURE,
        "severity": severity,
        "weight": 0.0,
        "applicability_key": APPLICABILITY_CRAWL_FINALIZE,
        "description": description,
        "remediation": remediation,
        "display_label": display_label,
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
        "architecture.duplicate_metadata_in_family",
        severity=SEVERITY_MEDIUM,
        description=(
            "An observed URL family repeats title and description metadata "
            "across pages."
        ),
        remediation=(
            "Give each family page metadata that describes its distinct purpose."
        ),
        display_label="Duplicate metadata within page families",
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
        "architecture.unhubbed_family",
        severity=SEVERITY_MEDIUM,
        description="A large observed detail-page family has no crawlable hub.",
        remediation=(
            "Create or expose a hub that links to the related detail-page family."
        ),
        display_label="Page family without an observed hub",
    ),
)


__all__ = ["ARCHITECTURE_RULE_SPECS"]
