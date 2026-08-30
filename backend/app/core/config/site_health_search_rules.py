"""Search/citation access and optional crawler-discovery rule definitions."""

from __future__ import annotations

from typing import Final

from app.core.config.site_health_contracts import (
    APPLICABILITY_SITE_ROOT,
    CATEGORY_CITABILITY,
    CATEGORY_INDEXABILITY,
    DIMENSION_AEO,
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    SEVERITY_HIGH,
    SEVERITY_LOW,
)
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_DIAGNOSTIC,
    SiteHealthRule,
)

SEARCH_ACCESS_RULES: Final[tuple[SiteHealthRule, ...]] = (
    SiteHealthRule(
        rule_id="technical.ai_crawler_access",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=0.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        description="robots.txt records the configured AI-agent role stances.",
        remediation=(
            "Review search/citation, training, and user-triggered agent policy "
            "separately; do not infer citation access from a training bot."
        ),
        display_label="AI-agent robots policy requires review",
        finding_class=FINDING_CLASS_DIAGNOSTIC,
    ),
    SiteHealthRule(
        rule_id="search.crawler_access",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=1.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        description="robots.txt permits configured search and citation crawlers.",
        remediation=(
            "Allow the search and citation crawler roles you expect to surface "
            "the site; manage training and user-triggered agents separately."
        ),
        display_label="Search or citation crawlers blocked",
    ),
    SiteHealthRule(
        rule_id="search.snippet_access",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=1.0,
        applicability_key="has_html",
        description="Page directives permit useful search and answer snippets.",
        remediation=(
            "Remove nosnippet or max-snippet:0 when this intended-public page "
            "should be eligible for search and answer citations."
        ),
        display_label="Search snippets blocked",
    ),
    SiteHealthRule(
        rule_id="aeo.llms_txt_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_LOW,
        weight=0.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        description="Site serves an optional llms.txt discovery file at the root.",
        remediation="Publish /llms.txt only when it supports your chosen workflow.",
        display_label="Optional llms.txt not present",
        finding_class=FINDING_CLASS_DIAGNOSTIC,
    ),
)
