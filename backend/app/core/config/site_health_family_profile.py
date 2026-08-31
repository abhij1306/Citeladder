"""Executable AEO capability-family and classified-kind profile policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from app.core.config.site_health_contracts import AEO_READINESS_DIMENSIONS
from app.core.config.site_health_rule_types import RULE_SCOPE_PAGE, RULE_SCOPE_SITE
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER, PAGE_KINDS

PROFILE_STATUS_MEASURED: Final = "measured"
PROFILE_STATUS_MEASUREMENT_GAP: Final = "measurement_gap"
PROFILE_STATUS_NOT_APPLICABLE: Final = "not_applicable"
PROFILE_STATUSES: Final = frozenset(
    {
        PROFILE_STATUS_MEASURED,
        PROFILE_STATUS_MEASUREMENT_GAP,
        PROFILE_STATUS_NOT_APPLICABLE,
    }
)

TRAIT_CONDITION_ALWAYS: Final = "always"
TRAIT_CONDITION_RESEARCH_SENSITIVE: Final = "research_sensitive"
TRAIT_CONDITION_FRESHNESS_SENSITIVE: Final = "freshness_sensitive"
TRAIT_CONDITION_PROCEDURAL: Final = "procedural"
TRAIT_CONDITION_CASE_STUDY: Final = "case_study"
TRAIT_CONDITION_REVIEW: Final = "review"
TRAIT_CONDITIONS: Final = frozenset(
    {
        TRAIT_CONDITION_ALWAYS,
        TRAIT_CONDITION_RESEARCH_SENSITIVE,
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        TRAIT_CONDITION_PROCEDURAL,
        TRAIT_CONDITION_CASE_STUDY,
        TRAIT_CONDITION_REVIEW,
    }
)

FAMILY_ANSWER_CONTENT: Final = "answer_content"
FAMILY_SEMANTIC_STRUCTURE: Final = "semantic_structure"
FAMILY_SOURCE_SUPPORT: Final = "source_support"
FAMILY_COMMERCE_FACTS: Final = "commerce_facts"
FAMILY_STRUCTURED_REPRESENTATION: Final = "structured_representation"
FAMILY_VISIBLE_ATTRIBUTION: Final = "visible_attribution"
FAMILY_SITE_IDENTITY: Final = "site_identity"
FAMILY_CURRENCY: Final = "currency"
FAMILY_INDEXABILITY: Final = "indexability"
FAMILY_SNIPPET_ACCESS: Final = "snippet_access"
FAMILY_CRAWLER_ACCESS: Final = "crawler_access"
_HEADING_HIERARCHY_CHECKPOINT: Final = "aeo.heading_hierarchy"
_SCHEMA_EXPECTED_CHECKPOINT: Final = "aeo.schema_expected_for_type"


@dataclass(frozen=True, slots=True)
class CheckpointExpression:
    checkpoint_id: str
    internal_weight: float


@dataclass(frozen=True, slots=True)
class CapabilityFamily:
    family_id: str
    dimension_id: str
    budget: float
    scope: str
    checkpoint_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FamilyProfileRow:
    page_kind: str
    trait_condition: str
    family_id: str
    status: str
    checkpoints: tuple[CheckpointExpression, ...]
    reason: str


CAPABILITY_FAMILY_MANIFEST: Final[tuple[CapabilityFamily, ...]] = (
    CapabilityFamily(
        FAMILY_ANSWER_CONTENT,
        "answerability",
        1.0,
        RULE_SCOPE_PAGE,
        (
            "aeo.editorial_lead_present",
            "aeo.answer_first",
            "aeo.entity_value_proposition",
            "aeo.product_answer_facts",
            "aeo.listing_answer_set",
        ),
    ),
    CapabilityFamily(
        FAMILY_SEMANTIC_STRUCTURE,
        "structure",
        1.0,
        RULE_SCOPE_PAGE,
        (_HEADING_HIERARCHY_CHECKPOINT, "aeo.question_headings"),
    ),
    CapabilityFamily(
        FAMILY_SOURCE_SUPPORT,
        "evidence",
        0.5,
        RULE_SCOPE_PAGE,
        ("aeo.source_support_present",),
    ),
    CapabilityFamily(
        FAMILY_COMMERCE_FACTS,
        "evidence",
        0.5,
        RULE_SCOPE_PAGE,
        ("aeo.product_evidence_facts", "aeo.listing_item_facts"),
    ),
    CapabilityFamily(
        FAMILY_STRUCTURED_REPRESENTATION,
        "machine-readability",
        1.0,
        RULE_SCOPE_PAGE,
        (
            _SCHEMA_EXPECTED_CHECKPOINT,
            "aeo.schema_required_valid",
            "aeo.schema_recommended_present",
            "aeo.schema_matches_content",
        ),
    ),
    CapabilityFamily(
        FAMILY_VISIBLE_ATTRIBUTION,
        "authority",
        0.5,
        RULE_SCOPE_PAGE,
        ("aeo.visible_attribution", "aeo.product_brand_identity"),
    ),
    CapabilityFamily(
        FAMILY_SITE_IDENTITY,
        "authority",
        0.5,
        RULE_SCOPE_SITE,
        ("aeo.organization_identity", "aeo.trust_path_present"),
    ),
    CapabilityFamily(
        FAMILY_CURRENCY,
        "freshness",
        1.0,
        RULE_SCOPE_PAGE,
        (
            "aeo.content_date_present",
            "aeo.offer_freshness_signal",
            "aeo.assortment_freshness_signal",
        ),
    ),
    CapabilityFamily(
        FAMILY_INDEXABILITY,
        "crawlability",
        1.0 / 3.0,
        RULE_SCOPE_PAGE,
        ("technical.indexable",),
    ),
    CapabilityFamily(
        FAMILY_SNIPPET_ACCESS,
        "crawlability",
        1.0 / 3.0,
        RULE_SCOPE_PAGE,
        ("search.snippet_access",),
    ),
    CapabilityFamily(
        FAMILY_CRAWLER_ACCESS,
        "crawlability",
        1.0 / 3.0,
        RULE_SCOPE_SITE,
        ("search.crawler_access",),
    ),
)
CAPABILITY_FAMILIES_BY_ID: Final = {
    family.family_id: family for family in CAPABILITY_FAMILY_MANIFEST
}
CHECKPOINT_FAMILY_BY_ID: Final = {
    checkpoint_id: family.family_id
    for family in CAPABILITY_FAMILY_MANIFEST
    for checkpoint_id in family.checkpoint_ids
}
CHECKPOINT_DIMENSION_BY_ID: Final = {
    checkpoint_id: family.dimension_id
    for family in CAPABILITY_FAMILY_MANIFEST
    for checkpoint_id in family.checkpoint_ids
}


def _expressions(*values: tuple[str, float]) -> tuple[CheckpointExpression, ...]:
    return tuple(CheckpointExpression(*value) for value in values)


_EXPRESSIONS: Final[dict[str, tuple[CheckpointExpression, ...]]] = {
    "answer_entity": _expressions(("aeo.entity_value_proposition", 1.0)),
    "answer_editorial": _expressions(("aeo.editorial_lead_present", 1.0)),
    "answer_product": _expressions(("aeo.product_answer_facts", 1.0)),
    "answer_listing": _expressions(("aeo.listing_answer_set", 1.0)),
    "answer_faq": _expressions(("aeo.answer_first", 1.0)),
    "semantic": _expressions((_HEADING_HIERARCHY_CHECKPOINT, 1.0)),
    "semantic_faq": _expressions(
        (_HEADING_HIERARCHY_CHECKPOINT, 0.5), ("aeo.question_headings", 0.5)
    ),
    "source": _expressions(("aeo.source_support_present", 1.0)),
    "commerce_product": _expressions(("aeo.product_evidence_facts", 1.0)),
    "commerce_listing": _expressions(("aeo.listing_item_facts", 1.0)),
    "structured": _expressions(
        (_SCHEMA_EXPECTED_CHECKPOINT, 1.0),
        ("aeo.schema_required_valid", 0.5),
        ("aeo.schema_matches_content", 1.0 / 3.0),
        ("aeo.schema_recommended_present", 1.0 / 6.0),
    ),
    "attribution_visible": _expressions(("aeo.visible_attribution", 1.0)),
    "attribution_brand": _expressions(("aeo.product_brand_identity", 1.0)),
    "site_identity": _expressions(
        ("aeo.organization_identity", 0.5), ("aeo.trust_path_present", 0.5)
    ),
    "currency_date": _expressions(("aeo.content_date_present", 1.0)),
    "currency_offer": _expressions(("aeo.offer_freshness_signal", 1.0)),
    "currency_assortment": _expressions(("aeo.assortment_freshness_signal", 1.0)),
    "indexability": _expressions(("technical.indexable", 1.0)),
    "snippet_access": _expressions(("search.snippet_access", 1.0)),
    "crawler_access": _expressions(("search.crawler_access", 1.0)),
}

_GAP_REASONS: Final = frozenset(
    {
        "claim_support_attachment_unavailable",
        "pricing_commerce_evaluator_unavailable",
        "policy_schema_contract_unavailable",
        "purpose_answer_evaluator_unavailable",
        "responsible_publisher_evaluator_unavailable",
    }
)
_NOT_APPLICABLE_REASONS: Final = frozenset(
    {
        "commerce_facts_not_required_for_page_purpose",
        "freshness_context_irrelevant",
        "source_support_not_required_by_context",
        "structured_representation_not_required_for_page_purpose",
        "visible_attribution_not_required_for_page_purpose",
    }
)

_G = "gap:"
_N = "not_applicable:"


def _kind_spec(
    *,
    answer: str,
    semantic: str = "semantic",
    source: str = f"{_N}source_support_not_required_by_context",
    commerce: str = f"{_N}commerce_facts_not_required_for_page_purpose",
    structured: str = "structured",
    attribution: str = f"{_N}visible_attribution_not_required_for_page_purpose",
    site_identity: str = "site_identity",
    currency: str = f"{_N}freshness_context_irrelevant",
) -> dict[str, str]:
    return {
        FAMILY_ANSWER_CONTENT: answer,
        FAMILY_SEMANTIC_STRUCTURE: semantic,
        FAMILY_SOURCE_SUPPORT: source,
        FAMILY_COMMERCE_FACTS: commerce,
        FAMILY_STRUCTURED_REPRESENTATION: structured,
        FAMILY_VISIBLE_ATTRIBUTION: attribution,
        FAMILY_SITE_IDENTITY: site_identity,
        FAMILY_CURRENCY: currency,
        FAMILY_INDEXABILITY: "indexability",
        FAMILY_SNIPPET_ACCESS: "snippet_access",
        FAMILY_CRAWLER_ACCESS: "crawler_access",
    }


_KIND_PROFILE_SPECS: Final[dict[str, dict[str, str]]] = {
    "homepage": _kind_spec(
        answer="answer_entity",
        source=f"{_G}claim_support_attachment_unavailable",
    ),
    "article": _kind_spec(
        answer="answer_editorial",
        attribution="attribution_visible",
    ),
    "product": _kind_spec(
        answer="answer_product",
        commerce="commerce_product",
        attribution="attribution_brand",
        currency="currency_offer",
    ),
    "category": _kind_spec(
        answer="answer_listing",
        commerce="commerce_listing",
        currency="currency_assortment",
    ),
    "pricing": _kind_spec(
        answer=f"{_G}purpose_answer_evaluator_unavailable",
        source=f"{_G}claim_support_attachment_unavailable",
        commerce=f"{_G}pricing_commerce_evaluator_unavailable",
        currency="currency_date",
    ),
    "docs": _kind_spec(answer="answer_editorial"),
    "faq": _kind_spec(
        answer="answer_faq",
        semantic="semantic_faq",
        structured=(f"{_N}structured_representation_not_required_for_page_purpose"),
    ),
    "about_contact": _kind_spec(
        answer="answer_entity",
        source=f"{_G}claim_support_attachment_unavailable",
    ),
    "service": _kind_spec(
        answer="answer_entity",
        source=f"{_G}claim_support_attachment_unavailable",
    ),
    "local": _kind_spec(
        answer="answer_entity",
        source=f"{_G}claim_support_attachment_unavailable",
    ),
    "guide": _kind_spec(
        answer="answer_editorial",
        structured=f"{_G}purpose_answer_evaluator_unavailable",
        attribution="attribution_visible",
    ),
    "comparison": _kind_spec(
        answer=f"{_G}purpose_answer_evaluator_unavailable",
        source="source",
        attribution="attribution_visible",
    ),
    "case_study_review": _kind_spec(
        answer=f"{_G}purpose_answer_evaluator_unavailable",
        source="source",
        structured=f"{_G}purpose_answer_evaluator_unavailable",
        attribution="attribution_visible",
    ),
    "trust_policy": _kind_spec(
        answer=f"{_G}purpose_answer_evaluator_unavailable",
        structured=f"{_G}policy_schema_contract_unavailable",
        attribution=f"{_G}responsible_publisher_evaluator_unavailable",
    ),
}

_OVERRIDE_SPECS: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("article", TRAIT_CONDITION_RESEARCH_SENSITIVE, FAMILY_SOURCE_SUPPORT, "source"),
    ("docs", TRAIT_CONDITION_RESEARCH_SENSITIVE, FAMILY_SOURCE_SUPPORT, "source"),
    ("guide", TRAIT_CONDITION_RESEARCH_SENSITIVE, FAMILY_SOURCE_SUPPORT, "source"),
    (
        "article",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "docs",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "guide",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "comparison",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "case_study_review",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "trust_policy",
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        FAMILY_CURRENCY,
        "currency_date",
    ),
    (
        "guide",
        TRAIT_CONDITION_PROCEDURAL,
        FAMILY_ANSWER_CONTENT,
        f"{_G}purpose_answer_evaluator_unavailable",
    ),
    (
        "guide",
        TRAIT_CONDITION_PROCEDURAL,
        FAMILY_STRUCTURED_REPRESENTATION,
        "structured",
    ),
    (
        "case_study_review",
        TRAIT_CONDITION_REVIEW,
        FAMILY_STRUCTURED_REPRESENTATION,
        "structured",
    ),
    (
        "case_study_review",
        TRAIT_CONDITION_CASE_STUDY,
        FAMILY_VISIBLE_ATTRIBUTION,
        f"{_N}visible_attribution_not_required_for_page_purpose",
    ),
)


def _row(page_kind: str, condition: str, family_id: str, spec: str) -> FamilyProfileRow:
    if spec.startswith(_G):
        return FamilyProfileRow(
            page_kind,
            condition,
            family_id,
            PROFILE_STATUS_MEASUREMENT_GAP,
            (),
            spec.removeprefix(_G),
        )
    if spec.startswith(_N):
        return FamilyProfileRow(
            page_kind,
            condition,
            family_id,
            PROFILE_STATUS_NOT_APPLICABLE,
            (),
            spec.removeprefix(_N),
        )
    return FamilyProfileRow(
        page_kind,
        condition,
        family_id,
        PROFILE_STATUS_MEASURED,
        _EXPRESSIONS[spec],
        "",
    )


def _assemble_profile() -> tuple[FamilyProfileRow, ...]:
    rows = [
        _row(page_kind, TRAIT_CONDITION_ALWAYS, family_id, spec)
        for page_kind, family_specs in _KIND_PROFILE_SPECS.items()
        for family_id, spec in family_specs.items()
    ]
    rows.extend(_row(*spec) for spec in _OVERRIDE_SPECS)
    return tuple(
        sorted(
            rows, key=lambda row: (row.page_kind, row.trait_condition, row.family_id)
        )
    )


CLASSIFIED_KIND_FAMILY_PROFILE: Final[tuple[FamilyProfileRow, ...]] = (
    _assemble_profile()
)


def _condition_matches(
    condition: str, *, traits: frozenset[str], context: Mapping[str, object]
) -> bool:
    if condition == TRAIT_CONDITION_RESEARCH_SENSITIVE:
        return bool(context.get("research_sensitive"))
    if condition == TRAIT_CONDITION_FRESHNESS_SENSITIVE:
        return bool(context.get("freshness_sensitive"))
    if condition == TRAIT_CONDITION_PROCEDURAL:
        return "procedural" in traits
    if condition == TRAIT_CONDITION_CASE_STUDY:
        return "case_study_intent" in traits
    if condition == TRAIT_CONDITION_REVIEW:
        return "case_study_intent" not in traits
    return condition == TRAIT_CONDITION_ALWAYS


def _is_base_row_for_kind(row: FamilyProfileRow, page_kind: str) -> bool:
    return row.page_kind == page_kind and row.trait_condition == TRAIT_CONDITION_ALWAYS


def _is_matching_override(
    row: FamilyProfileRow,
    *,
    page_kind: str,
    traits: frozenset[str],
    context: Mapping[str, object],
) -> bool:
    return (
        row.page_kind == page_kind
        and row.trait_condition != TRAIT_CONDITION_ALWAYS
        and _condition_matches(row.trait_condition, traits=traits, context=context)
    )


def profile_rows(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[FamilyProfileRow, ...]:
    if page_kind == PAGE_KIND_OTHER or page_kind not in PAGE_KINDS:
        return ()
    traits = frozenset(str(value) for value in page_traits)
    effective_context = context or {}
    selected = {
        row.family_id: row
        for row in CLASSIFIED_KIND_FAMILY_PROFILE
        if _is_base_row_for_kind(row, page_kind)
    }
    selected.update(
        (row.family_id, row)
        for row in CLASSIFIED_KIND_FAMILY_PROFILE
        if _is_matching_override(
            row,
            page_kind=page_kind,
            traits=traits,
            context=effective_context,
        )
    )
    return tuple(selected[family.family_id] for family in CAPABILITY_FAMILY_MANIFEST)


def _active_expressions(
    row: FamilyProfileRow, context: Mapping[str, object]
) -> tuple[CheckpointExpression, ...]:
    if row.family_id != FAMILY_STRUCTURED_REPRESENTATION:
        return row.checkpoints
    if not bool(context.get("primary_schema_present")):
        return tuple(
            item
            for item in row.checkpoints
            if item.checkpoint_id == _SCHEMA_EXPECTED_CHECKPOINT
        )
    return tuple(
        item
        for item in row.checkpoints
        if item.checkpoint_id != _SCHEMA_EXPECTED_CHECKPOINT
    )


def _row_is_in_evaluation_scope(
    row: FamilyProfileRow, context: Mapping[str, object]
) -> bool:
    family = CAPABILITY_FAMILIES_BY_ID[row.family_id]
    return family.scope == RULE_SCOPE_PAGE or bool(context.get("is_site_root"))


def expected_checkpoint_expressions(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[tuple[str, str, float], ...]:
    effective_context = context or {}
    return tuple(
        (row.family_id, item.checkpoint_id, item.internal_weight)
        for row in profile_rows(page_kind, page_traits, effective_context)
        if row.status == PROFILE_STATUS_MEASURED
        if _row_is_in_evaluation_scope(row, effective_context)
        for item in _active_expressions(row, effective_context)
    )


def site_checkpoint_expressions() -> tuple[tuple[str, str, float], ...]:
    """Return page-kind-independent expectations for site-scoped evidence."""
    expressions_by_family: dict[str, tuple[CheckpointExpression, ...]] = {}
    for row in CLASSIFIED_KIND_FAMILY_PROFILE:
        family = CAPABILITY_FAMILIES_BY_ID[row.family_id]
        if (
            family.scope != RULE_SCOPE_SITE
            or row.trait_condition != TRAIT_CONDITION_ALWAYS
            or row.status != PROFILE_STATUS_MEASURED
        ):
            continue
        previous = expressions_by_family.setdefault(row.family_id, row.checkpoints)
        if previous != row.checkpoints:
            raise ValueError(f"Site family varies by page kind: {row.family_id}")
    return tuple(
        (family.family_id, checkpoint.checkpoint_id, checkpoint.internal_weight)
        for family in CAPABILITY_FAMILY_MANIFEST
        for checkpoint in expressions_by_family.get(family.family_id, ())
    )


def expected_checkpoints(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            checkpoint_id
            for _family_id, checkpoint_id, _weight in expected_checkpoint_expressions(
                page_kind, page_traits, context
            )
        )
    )


def expected_families(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    effective_context = context or {}
    return tuple(
        row.family_id
        for row in profile_rows(page_kind, page_traits, effective_context)
        if row.status != PROFILE_STATUS_NOT_APPLICABLE
        if _row_is_in_evaluation_scope(row, effective_context)
    )


def relevant_dimensions(
    page_kind: str,
    page_traits: Iterable[str] = (),
    context: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    expected = set(expected_families(page_kind, page_traits, context))
    relevant = {
        family.dimension_id
        for family in CAPABILITY_FAMILY_MANIFEST
        if family.family_id in expected
    }
    return tuple(key for key in AEO_READINESS_DIMENSIONS if key in relevant)


def validate_measurement_profile(
    *,
    families: tuple[CapabilityFamily, ...] = CAPABILITY_FAMILY_MANIFEST,
    rows: tuple[FamilyProfileRow, ...] = CLASSIFIED_KIND_FAMILY_PROFILE,
    implemented_checkpoint_ids: Iterable[str] | None = None,
) -> None:
    family_by_id = _validate_families(families)
    implemented = (
        None
        if implemented_checkpoint_ids is None
        else frozenset(implemented_checkpoint_ids)
    )
    _validate_rows(rows, family_by_id=family_by_id, implemented=implemented)


def _validate_family_membership(
    families: tuple[CapabilityFamily, ...],
    family_by_id: Mapping[str, CapabilityFamily],
) -> None:
    if len(family_by_id) != len(families) or set(family_by_id) != set(
        CAPABILITY_FAMILIES_BY_ID
    ):
        raise ValueError(
            "Capability family manifest must contain each fixed family once"
        )


def _validate_checkpoint_ownership(
    families: tuple[CapabilityFamily, ...],
) -> None:
    checkpoint_ids = [
        checkpoint_id for family in families for checkpoint_id in family.checkpoint_ids
    ]
    if len(checkpoint_ids) != len(set(checkpoint_ids)):
        raise ValueError("A checkpoint may belong to only one capability family")


def _validate_family_definition(family: CapabilityFamily) -> None:
    if (
        family.dimension_id not in AEO_READINESS_DIMENSIONS
        or family.scope not in {RULE_SCOPE_PAGE, RULE_SCOPE_SITE}
        or family.budget <= 0
        or not family.checkpoint_ids
    ):
        raise ValueError(f"Invalid capability family: {family.family_id}")


def _validate_dimension_budgets(
    families: tuple[CapabilityFamily, ...],
) -> None:
    for dimension in AEO_READINESS_DIMENSIONS:
        budget = sum(
            family.budget for family in families if family.dimension_id == dimension
        )
        if abs(budget - 1.0) > 1e-9:
            raise ValueError(f"Capability family budgets must sum to one: {dimension}")


def _validate_families(
    families: tuple[CapabilityFamily, ...],
) -> dict[str, CapabilityFamily]:
    family_by_id = {family.family_id: family for family in families}
    _validate_family_membership(families, family_by_id)
    _validate_checkpoint_ownership(families)
    for family in families:
        _validate_family_definition(family)
    _validate_dimension_budgets(families)
    return family_by_id


def _validate_rows(
    rows: tuple[FamilyProfileRow, ...],
    *,
    family_by_id: Mapping[str, CapabilityFamily],
    implemented: frozenset[str] | None,
) -> None:
    keys = [(row.page_kind, row.trait_condition, row.family_id) for row in rows]
    if len(keys) != len(set(keys)):
        raise ValueError("Family profile rows must be unique")
    base_pairs = {
        (row.page_kind, row.family_id)
        for row in rows
        if row.trait_condition == TRAIT_CONDITION_ALWAYS
    }
    expected_pairs = {
        (page_kind, family_id)
        for page_kind in PAGE_KINDS
        if page_kind != PAGE_KIND_OTHER
        for family_id in family_by_id
    }
    if base_pairs != expected_pairs or any(
        row.page_kind == PAGE_KIND_OTHER for row in rows
    ):
        raise ValueError(
            "Every classified kind must enumerate every family; other has none"
        )
    for row in rows:
        _validate_row(row, family_by_id=family_by_id, implemented=implemented)


def _validate_row_vocabulary(row: FamilyProfileRow) -> None:
    if (
        row.status not in PROFILE_STATUSES
        or row.trait_condition not in TRAIT_CONDITIONS
    ):
        raise ValueError("Unsupported family profile status or trait condition")


def _has_invalid_measured_expression(
    row: FamilyProfileRow, checkpoint_ids: list[str]
) -> bool:
    return (
        not checkpoint_ids
        or bool(row.reason)
        or len(checkpoint_ids) != len(set(checkpoint_ids))
        or any(item.internal_weight <= 0 for item in row.checkpoints)
    )


def _has_invalid_checkpoint_membership(
    checkpoint_ids: list[str],
    *,
    family: CapabilityFamily,
    implemented: frozenset[str] | None,
) -> bool:
    selected = set(checkpoint_ids)
    if not selected.issubset(family.checkpoint_ids):
        return True
    return implemented is not None and not selected.issubset(implemented)


def _validate_measured_row(
    row: FamilyProfileRow,
    *,
    family: CapabilityFamily,
    implemented: frozenset[str] | None,
) -> None:
    checkpoint_ids = [item.checkpoint_id for item in row.checkpoints]
    if _has_invalid_measured_expression(
        row, checkpoint_ids
    ) or _has_invalid_checkpoint_membership(
        checkpoint_ids,
        family=family,
        implemented=implemented,
    ):
        raise ValueError(f"Invalid measured family profile row: {row}")


def _validate_unresolved_row(row: FamilyProfileRow) -> None:
    allowed = (
        _GAP_REASONS
        if row.status == PROFILE_STATUS_MEASUREMENT_GAP
        else _NOT_APPLICABLE_REASONS
    )
    if row.checkpoints or row.reason not in allowed:
        raise ValueError(f"Invalid unresolved family profile row: {row}")


def _validate_row(
    row: FamilyProfileRow,
    *,
    family_by_id: Mapping[str, CapabilityFamily],
    implemented: frozenset[str] | None,
) -> None:
    _validate_row_vocabulary(row)
    family = family_by_id.get(row.family_id)
    if family is None:
        raise ValueError(f"Unknown capability family: {row.family_id}")
    if row.status == PROFILE_STATUS_MEASURED:
        _validate_measured_row(row, family=family, implemented=implemented)
        return
    _validate_unresolved_row(row)


validate_measurement_profile()
