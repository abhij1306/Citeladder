"""Page-kind expressions added by the Site Health measurement cutover."""

from __future__ import annotations

from typing import Final

from app.core.config.site_health_contracts import (
    APPLICABILITY_SITE_ROOT,
    CATEGORY_CITABILITY,
    CATEGORY_CONTENT,
    CATEGORY_INDEXABILITY,
    DIMENSION_AEO,
    DIMENSION_TECHNICAL,
    RULE_CATALOG_VERSION,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)
from app.core.config.site_health_rule_types import (
    COMPOSITE_THRESHOLD_ALL_REQUIRED,
    COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE,
    FINDING_CLASS_ADVISORY,
    RULE_SCOPE_SITE,
    SCORE_ROLE_AEO,
    SCORE_ROLE_WEB_FUNDAMENTALS,
    CompositeAtom,
    CompositeContract,
    SiteHealthRule,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_ARTICLE,
    PAGE_KIND_CASE_STUDY_REVIEW,
    PAGE_KIND_CATEGORY,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_DOCS,
    PAGE_KIND_GUIDE,
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_LOCAL,
    PAGE_KIND_OTHER,
    PAGE_KIND_PRICING,
    PAGE_KIND_PRODUCT,
    PAGE_KIND_SERVICE,
    PAGE_KINDS,
    _page_kinds,
)
from app.core.config.site_health_traits import (
    PAGE_TRAIT_COMPANY_PROFILE_INTENT,
    _traits,
)

_EDITORIAL_KINDS: Final = (
    PAGE_KIND_ARTICLE,
    PAGE_KIND_GUIDE,
    PAGE_KIND_DOCS,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_CASE_STUDY_REVIEW,
)
_ENTITY_KINDS: Final = (
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_PRICING,
    PAGE_KIND_SERVICE,
    PAGE_KIND_LOCAL,
)
_CLASSIFIED_KINDS: Final = tuple(kind for kind in PAGE_KINDS if kind != PAGE_KIND_OTHER)

ENTITY_VALUE_PROPOSITION_CONTRACT: Final = CompositeContract(
    atoms=(
        CompositeAtom(name="entity_identity", required=True),
        CompositeAtom(
            name="contact_path",
            required=True,
            condition="page_trait:contact_intent",
        ),
        CompositeAtom(
            name="value_proposition",
            required=True,
            condition="not_page_trait:contact_intent",
        ),
    ),
    threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED,
)

PRODUCT_ANSWER_FACTS_CONTRACT: Final = CompositeContract(
    atoms=(
        CompositeAtom(name="identity", required=True),
        CompositeAtom(name="offer", required=True),
        CompositeAtom(name="availability", required=True),
        CompositeAtom(
            name="variants",
            required=False,
            condition="page_trait:has_variants",
        ),
    ),
    threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED_AND_APPLICABLE,
)

LISTING_ANSWER_SET_CONTRACT: Final = CompositeContract(
    atoms=(
        CompositeAtom(name="collection_purpose", required=True),
        CompositeAtom(name="item_set", required=True),
    ),
    threshold=COMPOSITE_THRESHOLD_ALL_REQUIRED,
)


READINESS_EXPANSION_RULES: Final[tuple[SiteHealthRule, ...]] = (
    SiteHealthRule(
        rule_id="aeo.heading_hierarchy",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(*_CLASSIFIED_KINDS, reads_content=True),
        description="The primary-content heading hierarchy skips one or more levels.",
        remediation="Use sequential heading levels to express content hierarchy.",
        display_label="Primary-content heading hierarchy",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.organization_identity",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        scope=RULE_SCOPE_SITE,
        description="Organization markup identifies the site with a name and URL.",
        remediation="Add Organization name and URL on the site root.",
        display_label="Organization identity incomplete",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.trust_path_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=APPLICABILITY_SITE_ROOT,
        scope=RULE_SCOPE_SITE,
        description="The site root links to an about, contact, or policy surface.",
        remediation="Expose crawlable trust and contact paths from the site root.",
        display_label="No crawlable trust path",
        score_roles=(SCORE_ROLE_AEO,),
    ),
    SiteHealthRule(
        rule_id="aeo.content_date_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(*_EDITORIAL_KINDS, reads_content=True),
        description="Editorial content exposes a published or modified date.",
        remediation="Add a visible or machine-readable publication/update date.",
        display_label="Missing content date",
        finding_class=FINDING_CLASS_ADVISORY,
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.editorial_lead_present",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key=_page_kinds(*_EDITORIAL_KINDS, reads_content=True),
        description="Editorial content opens with a substantive lead paragraph.",
        remediation="Add a concise lead that establishes the page topic.",
        display_label="Editorial lead is absent or too short",
        finding_class=FINDING_CLASS_ADVISORY,
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.entity_value_proposition",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_LOW,
        weight=1.0,
        applicability_key=_page_kinds(*_ENTITY_KINDS, reads_content=True),
        description="Entity pages name the entity and state a substantive proposition.",
        remediation="Pair a clear H1 with a concise first explanatory paragraph.",
        display_label="Entity or value proposition unclear",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
        composite_contract=ENTITY_VALUE_PROPOSITION_CONTRACT,
    ),
    SiteHealthRule(
        rule_id="aeo.company_entity_completeness",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_traits(
            PAGE_TRAIT_COMPANY_PROFILE_INTENT,
            reads_content=True,
        ),
        description=(
            "Canonical About pages define the company, offering, audience, "
            "specific value, and durable first-party proof."
        ),
        remediation=(
            "Add the missing company entity signals, prioritizing the company "
            "and offering definition before audience, value, and durable proof."
        ),
        display_label="Company entity information incomplete",
        finding_class=FINDING_CLASS_ADVISORY,
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.product_answer_facts",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_PRODUCT, reads_content=True),
        description=(
            "Product pages expose identity, offer, availability, and variants "
            "when applicable."
        ),
        remediation=(
            "Expose the required product answer facts in visible content or "
            "structured data."
        ),
        display_label="Critical product answer facts missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
        composite_contract=PRODUCT_ANSWER_FACTS_CONTRACT,
    ),
    SiteHealthRule(
        rule_id="aeo.product_evidence_facts",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_PRODUCT, reads_content=True),
        description="Product pages expose a stable SKU, GTIN, or MPN signal.",
        remediation="Expose a stable product identifier visibly or in Product markup.",
        display_label="Product identifier missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.product_brand_identity",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_PRODUCT, reads_content=True),
        description="Product pages identify the brand or manufacturer.",
        remediation="Expose the product brand or manufacturer in Product markup.",
        display_label="Product brand identity missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.offer_freshness_signal",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_PRODUCT, reads_content=True),
        description="Product pages expose dated, currency-qualified Offer evidence.",
        remediation="Expose a currency and an updated timestamp with Offer data.",
        display_label="Offer freshness signal missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.listing_answer_set",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CONTENT,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_CATEGORY, reads_content=True),
        description=(
            "Category pages expose a collection purpose and crawlable item set."
        ),
        remediation="Add a clear H1 and crawlable links to collection items.",
        display_label="Collection answer set incomplete",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
        composite_contract=LISTING_ANSWER_SET_CONTRACT,
    ),
    SiteHealthRule(
        rule_id="aeo.listing_item_facts",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_CATEGORY, reads_content=True),
        description="Category items expose crawlable labels and targets.",
        remediation="Render item names and crawlable product links in the collection.",
        display_label="Category item facts missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="aeo.assortment_freshness_signal",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_AEO,
        category=CATEGORY_CITABILITY,
        severity=SEVERITY_MEDIUM,
        weight=1.0,
        applicability_key=_page_kinds(PAGE_KIND_CATEGORY, reads_content=True),
        description="Category pages expose an updated timestamp for the assortment.",
        remediation="Expose a publication or update timestamp for the assortment.",
        display_label="Assortment freshness signal missing",
        score_roles=(SCORE_ROLE_AEO,),
        content_addressable=True,
    ),
    SiteHealthRule(
        rule_id="technical.soft_error",
        rule_version=RULE_CATALOG_VERSION,
        dimension=DIMENSION_TECHNICAL,
        category=CATEGORY_INDEXABILITY,
        severity=SEVERITY_HIGH,
        weight=3.0,
        applicability_key="has_html",
        description="A successful HTTP response does not contain error-page content.",
        remediation="Return the correct error status for missing or failed resources.",
        display_label="Soft error page",
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
    ),
)


__all__ = ["READINESS_EXPANSION_RULES"]
