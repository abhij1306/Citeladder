# Pure deterministic evaluation of the config-owned Site Health rule catalog.
# Finalize-scoped rules are evaluated and persisted only by ``finalize.py``.
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from itertools import islice, pairwise
from typing import Any

from app.analysis.site_health.delivery_rules import DELIVERY_CHECKS
from app.analysis.site_health.identity_rules import (
    check_organization_identity,
    check_trust_path_present,
)
from app.analysis.site_health.indexing import (
    canonical_origin,
    evaluate_indexability,
    normalized_url_for_compare,
    resolve_canonical,
)
from app.analysis.site_health.page_kinds import is_question_heading
from app.analysis.site_health.page_traits import has_contact_form_fields
from app.analysis.site_health.product_rules import (
    check_assortment_freshness_signal,
    check_listing_answer_set,
    check_listing_item_facts,
    check_offer_freshness_signal,
    check_product_answer_facts,
    check_product_brand_identity,
    check_product_evidence_facts,
)
from app.analysis.site_health.rule_scope import (
    applicability,
    observed_traits,
    profile_for,
)
from app.analysis.site_health.schema_rules import (
    check_schema_expected_for_type,
    check_schema_matches_content,
    check_schema_recommended_present,
    check_schema_required_valid,
    primary_schema_present,
)
from app.analysis.site_health.web_fundamentals import WEB_FUNDAMENTALS_CHECKS
from app.core.config.site_health_contracts import (
    RULE_FAILING_OUTCOMES,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    CAPABILITY_FAMILIES_BY_ID,
    PROFILE_STATUS_MEASURED,
    STRUCTURAL_NA_REASONS,
    UNAVAILABLE_REASONS,
    UNKNOWN_REASONS,
    expected_checkpoint_expressions,
    profile_rows,
    site_checkpoint_expressions,
)
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_DIAGNOSTIC,
    RULE_SCOPE_PAGE,
    SCORE_ROLE_AEO,
    SiteHealthRule,
)
from app.core.config.site_health_rules import (
    ANSWER_FIRST_MIN_WORDS,
    META_DESCRIPTION_LENGTH_BAND,
    QUESTION_HEADINGS_MIN_RATIO,
    SITE_HEALTH_RULES,
    SITE_HEALTH_RULES_BY_ID,
    TITLE_LENGTH_BAND,
)
from app.core.config.site_health_taxonomy import (
    CONTENT_SUFFICIENCY_PRICE_KINDS,
    CONTENT_SUFFICIENCY_TRAITS,
    MIN_MEANINGFUL_WORDS,
    PAGE_KIND_OTHER,
    PAGE_KIND_PROFILES,
)


def _has_price_evidence(facts: dict) -> bool:
    """A visible price, or a Product/Offer that declares one."""
    entity_product = (facts.get("entity") or {}).get("product") or {}
    if entity_product.get("has_primary_price"):
        return True
    if str((facts.get("commerce") or {}).get("visible_price") or "").strip():
        return True
    product = (facts.get("structured_data") or {}).get("product") or {}
    return bool(product.get("price"))


def _structural_sufficiency(facts: dict) -> tuple[str, bool]:
    """Return a completeness signal that may satisfy a short page."""
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    if page_kind in CONTENT_SUFFICIENCY_PRICE_KINDS:
        return "price", _has_price_evidence(facts)
    wanted = CONTENT_SUFFICIENCY_TRAITS.get(page_kind)
    if wanted:
        return "|".join(wanted), bool(observed_traits(facts) & set(wanted))
    return "", False


@dataclass(frozen=True)
class RuleEvaluation:
    """Immutable, bounded result the worker persists for one rule."""

    rule_id: str
    rule_version: str
    dimension: str
    category: str
    severity: str
    finding_class: str
    weight: float
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    remediation: str = ""
    display_applicability: bool = True
    score_applicability: bool = False
    expected_profile_membership: bool = False
    reason_code: str = ""
    score_roles: tuple[str, ...] = ()
    checkpoint_family: str = ""
    readiness_dimension: str = ""
    readiness_weight: float = 0.0
    scope: str = RULE_SCOPE_PAGE


def creates_issue(evaluation: RuleEvaluation) -> bool:
    """Only a failing observation that participates in a score is an issue."""
    return (
        evaluation.outcome in RULE_FAILING_OUTCOMES
        and evaluation.finding_class != FINDING_CLASS_DIAGNOSTIC
        and bool(evaluation.score_roles)
    )


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_SATISFIED if condition else RULE_OUTCOME_MISSING


def _check_present_field(
    facts: dict, *, field: str, length_key: str | None = None
) -> tuple[str, dict]:
    value = (facts.get(field) or "").strip()
    evidence: dict[str, Any] = {"present": bool(value)}
    if length_key:
        evidence[length_key] = len(value)
    else:
        evidence[field] = value
    return _pass_fail(bool(value)), evidence


def _check_indexable(facts: dict) -> tuple[str, dict]:
    return evaluate_indexability(facts)


def _check_single_h1(facts: dict) -> tuple[str, dict]:
    headings = facts.get("headings") or {}
    h1_count = int(headings.get("h1_count", 0) or 0)
    return _pass_fail(h1_count == 1), {"h1_count": h1_count}


def _check_structured_data_present(facts: dict) -> tuple[str, dict]:
    sd = facts.get("structured_data") or {}
    count = int(sd.get("count", 0) or 0)
    return _pass_fail(count > 0), {
        "block_count": count,
        "has_json_ld": bool(sd.get("has_json_ld")),
        "has_microdata": bool(sd.get("has_microdata")),
        "types": list(sd.get("types") or []),
    }


def _check_open_graph_present(facts: dict) -> tuple[str, dict]:
    og = facts.get("open_graph") or {}
    has_title = bool((og.get("og:title") or "").strip())
    has_desc = bool((og.get("og:description") or "").strip())
    present = has_title and has_desc
    return _pass_fail(present), {
        "has_og_title": has_title,
        "has_og_description": has_desc,
        "property_count": len(og),
    }


def _check_thin_content(facts: dict) -> tuple[str, dict]:
    """Fail only empty pages; a structural signal can satisfy a short page."""
    body = facts.get("body") or {}
    word_count = int(body.get("word_count", 0) or 0)
    profile = profile_for(facts) or PAGE_KIND_PROFILES[PAGE_KIND_OTHER]
    evidence: dict[str, Any] = {
        "word_count": word_count,
        "minimum": MIN_MEANINGFUL_WORDS,
        "page_kind": profile.page_kind,
    }
    if word_count >= MIN_MEANINGFUL_WORDS:
        return RULE_OUTCOME_SATISFIED, evidence
    signal, satisfied = _structural_sufficiency(facts)
    evidence["structural_signal"] = signal
    evidence["structurally_sufficient"] = satisfied
    return _pass_fail(satisfied), evidence


def _hreflang_alternate_urls(facts: dict) -> list[str]:
    alternates = facts.get("hreflang_alternates") or []
    return [
        str(entry.get("url") or "")
        for entry in alternates
        if isinstance(entry, dict) and entry.get("url")
    ]


def _check_canonical_conflict(facts: dict) -> tuple[str, dict]:
    """Fail invalid or conflicting canonicals; permit same-origin consolidation."""
    declared = (facts.get("canonical_url") or "").strip()
    if not declared:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_canonical"}
    delivery = facts.get("delivery") or {}
    final_url = str(delivery.get("final_url") or "")
    canonical = resolve_canonical(declared, final_url)
    evidence: dict[str, Any] = {
        "declared_canonical": declared[:2048],
        "canonical_url": canonical[:2048],
        "final_url": final_url[:2048],
    }
    self_canonical = normalized_url_for_compare(
        canonical
    ) == normalized_url_for_compare(final_url)
    evidence["self_canonical"] = self_canonical
    if self_canonical:
        return RULE_OUTCOME_SATISFIED, evidence

    origin = canonical_origin(canonical)
    if not origin:
        evidence["problem"] = "invalid_canonical"
        return RULE_OUTCOME_MISSING, evidence

    final_origin = canonical_origin(final_url)
    if final_origin and origin != final_origin:
        evidence["problem"] = "cross_origin_canonical"
        return RULE_OUTCOME_MISSING, evidence

    alternates = {
        normalized_url_for_compare(url) for url in _hreflang_alternate_urls(facts)
    }
    if alternates and normalized_url_for_compare(canonical) in alternates:
        evidence["problem"] = "hreflang_canonical_conflict"
        return RULE_OUTCOME_MISSING, evidence

    evidence["reason"] = "intentional_consolidation"
    return RULE_OUTCOME_SATISFIED, evidence


def _length_band_check(
    value: object, *, band: tuple[int, int], empty_reason: str, length_key: str
) -> tuple[str, dict]:
    """N/A for an absent field; otherwise check its inclusive config band."""
    text = (str(value or "")).strip()
    if not text:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": empty_reason}
    low, high = band
    length = len(text)
    return _pass_fail(low <= length <= high), {
        length_key: length,
        "band": [low, high],
    }


def _check_title_length_band(facts: dict) -> tuple[str, dict]:
    return _length_band_check(
        facts.get("title"),
        band=TITLE_LENGTH_BAND,
        empty_reason="empty_title",
        length_key="title_length",
    )


def _check_meta_description_length_band(facts: dict) -> tuple[str, dict]:
    return _length_band_check(
        facts.get("meta_description"),
        band=META_DESCRIPTION_LENGTH_BAND,
        empty_reason="empty_meta_description",
        length_key="description_length",
    )


def _check_visible_attribution(facts: dict) -> tuple[str, dict]:
    authorship = facts.get("authorship") or {}
    visible = str(authorship.get("visible_byline") or "").strip()
    profile_url = str(authorship.get("visible_profile_url") or "").strip()
    declared = str(authorship.get("declared_author") or "").strip()
    declared_source = str(authorship.get("declared_author_source") or "").strip()
    evidence = {
        "visible_name": visible[:256],
        "visible_profile_url": profile_url[:512],
        "declared_name": declared[:256],
        "declared_source": declared_source,
    }
    if visible and profile_url:
        return RULE_OUTCOME_SATISFIED, evidence
    if visible:
        evidence["reason"] = "visible_attribution_unlinked"
        return RULE_OUTCOME_PARTIAL, evidence
    if declared:
        evidence["reason"] = "declared_attribution_only"
        return RULE_OUTCOME_PARTIAL, evidence
    evidence["reason"] = "visible_attribution_absent"
    return RULE_OUTCOME_MISSING, evidence


def _check_content_date_present(facts: dict) -> tuple[str, dict]:
    dates = facts.get("dates") or {}
    published = bool((dates.get("published") or "").strip())
    modified = bool((dates.get("modified") or "").strip())
    evidence: dict[str, object] = {
        "has_published": published,
        "has_modified": modified,
    }
    if not (published or modified):
        evidence["reason"] = "freshness_signal_missing"
    return _pass_fail(published or modified), evidence


def _check_source_support_present(facts: dict) -> tuple[str, dict]:
    support = facts.get("source_support") or {}
    available = bool(support.get("primary_content_available"))
    sources = list(support.get("attached_sources") or ())
    ambiguous = int(support.get("ambiguous_source_count") or 0)
    invalid = int(support.get("invalid_source_count") or 0)
    evidence = {
        "attached_sources": list(islice(sources, 24)),
        "attached_source_count": len(sources),
        "ambiguous_source_count": ambiguous,
        "invalid_source_count": invalid,
        "context_reasons": list(
            islice(support.get("context_reasons") or (), 8)
        ),
    }
    if not available:
        evidence["reason"] = "primary_content_unavailable"
        return RULE_OUTCOME_UNKNOWN, evidence
    if sources:
        return RULE_OUTCOME_SATISFIED, evidence
    if invalid:
        evidence["reason"] = "invalid_source_relationship"
        return RULE_OUTCOME_MISSING, evidence
    if ambiguous:
        evidence["reason"] = "ambiguous_source_attachment"
        return RULE_OUTCOME_UNKNOWN, evidence
    evidence["reason"] = "source_support_absent"
    return RULE_OUTCOME_MISSING, evidence


def _check_answer_first(facts: dict) -> tuple[str, dict]:
    outline = list(facts.get("primary_heading_outline") or ())
    if not outline:
        return RULE_OUTCOME_MISSING, {"reason": "no_headings"}
    answer = str(facts.get("direct_answer") or "")
    word_count = len(answer.split())
    evidence = {
        "answer_word_count": word_count,
        "minimum_words": ANSWER_FIRST_MIN_WORDS,
        "answer_preview": answer[:256],
    }
    if word_count < ANSWER_FIRST_MIN_WORDS:
        evidence["reason"] = "direct_answer_missing"
    return _pass_fail(word_count >= ANSWER_FIRST_MIN_WORDS), evidence


def _check_editorial_lead_present(facts: dict) -> tuple[str, dict]:
    lead = str(facts.get("editorial_lead") or "")
    word_count = len(lead.split())
    evidence = {
        "lead_word_count": word_count,
        "minimum_words": ANSWER_FIRST_MIN_WORDS,
        "lead_preview": lead[:256],
    }
    if word_count < ANSWER_FIRST_MIN_WORDS:
        evidence["reason"] = "editorial_lead_missing"
    return _pass_fail(word_count >= ANSWER_FIRST_MIN_WORDS), evidence


def _check_entity_value_proposition(facts: dict) -> tuple[str, dict]:
    proposition = facts.get("entity_proposition") or {}
    identity_text = str(proposition.get("identity") or "")
    proposition_text = str(proposition.get("proposition") or "")
    identity = bool(identity_text.strip())
    traits = facts.get("page_traits") or ()
    contact_path = bool(facts.get("contact_points") or has_contact_form_fields(facts))
    value_proposition = len(proposition_text.split()) >= ANSWER_FIRST_MIN_WORDS
    contract = _composite_contract("aeo.entity_value_proposition")
    atoms = [
        contract.atom_detail(
            "entity_identity",
            satisfied=identity,
            evidence=identity_text[:256],
            page_traits=traits,
        ),
        contract.atom_detail(
            "contact_path",
            satisfied=contact_path,
            evidence=contact_path,
            page_traits=traits,
        ),
        contract.atom_detail(
            "value_proposition",
            satisfied=value_proposition,
            evidence={"word_count": len(proposition_text.split())},
            page_traits=traits,
        ),
    ]
    return contract.outcome_for(atoms), {
        "atoms": atoms,
        "threshold": contract.threshold,
    }


def _composite_contract(rule_id: str):
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    if rule is None or rule.composite_contract is None:
        raise RuntimeError(f"Composite contract missing for {rule_id}")
    return rule.composite_contract


def _check_product_answer_facts(facts: dict) -> tuple[str, dict]:
    return check_product_answer_facts(
        facts, contract=_composite_contract("aeo.product_answer_facts")
    )


def _check_listing_answer_set(facts: dict) -> tuple[str, dict]:
    return check_listing_answer_set(
        facts, contract=_composite_contract("aeo.listing_answer_set")
    )


def _check_question_headings(facts: dict) -> tuple[str, dict]:
    outline = list(facts.get("primary_heading_outline") or ())
    subheadings = [
        str(item.get("text") or "")
        for item in outline
        if int(item.get("level") or 0) in {2, 3}
    ]
    if not subheadings:
        return RULE_OUTCOME_MISSING, {"reason": "no_subheadings"}
    question_count = sum(is_question_heading(value) for value in subheadings)
    ratio = question_count / len(subheadings)
    return _pass_fail(ratio > QUESTION_HEADINGS_MIN_RATIO), {
        "question_heading_ratio": round(ratio, 4),
        "question_heading_count": question_count,
        "subheading_count": len(subheadings),
        "minimum_ratio": QUESTION_HEADINGS_MIN_RATIO,
    }


def _check_primary_heading_hierarchy(facts: dict) -> tuple[str, dict]:
    outline = list(facts.get("primary_heading_outline") or ())
    levels = [int(item.get("level") or 0) for item in outline]
    skips = [
        {"from": previous, "to": current}
        for previous, current in pairwise(levels)
        if current > previous + 1
    ]
    if not levels:
        return RULE_OUTCOME_MISSING, {"reason": "no_primary_headings", "levels": []}
    return _pass_fail(not skips), {"levels": levels, "skips": skips}


# Unmapped rules become ERROR; finalize-scoped rules belong to ``finalize.py``.
_CHECKS: dict[str, Callable[[dict], tuple[str, dict]]] = {
    "technical.title_present": lambda facts: _check_present_field(
        facts, field="title", length_key="title_length"
    ),
    "technical.meta_description_present": lambda facts: _check_present_field(
        facts, field="meta_description", length_key="description_length"
    ),
    "technical.canonical_present": lambda facts: _check_present_field(
        facts, field="canonical_url"
    ),
    "technical.indexable": _check_indexable,
    **DELIVERY_CHECKS,
    "technical.single_h1": _check_single_h1,
    "technical.thin_content": _check_thin_content,
    "technical.canonical_conflict": _check_canonical_conflict,
    "technical.title_length_band": _check_title_length_band,
    "technical.meta_description_length_band": _check_meta_description_length_band,
    **WEB_FUNDAMENTALS_CHECKS,
    "aeo.structured_data_present": _check_structured_data_present,
    "aeo.open_graph_present": _check_open_graph_present,
    "aeo.schema_expected_for_type": check_schema_expected_for_type,
    "aeo.schema_required_valid": check_schema_required_valid,
    "aeo.schema_recommended_present": check_schema_recommended_present,
    "aeo.schema_matches_content": check_schema_matches_content,
    "aeo.visible_attribution": _check_visible_attribution,
    "aeo.content_date_present": _check_content_date_present,
    "aeo.source_support_present": _check_source_support_present,
    "aeo.organization_identity": check_organization_identity,
    "aeo.trust_path_present": check_trust_path_present,
    "aeo.answer_first": _check_answer_first,
    "aeo.editorial_lead_present": _check_editorial_lead_present,
    "aeo.entity_value_proposition": _check_entity_value_proposition,
    "aeo.question_headings": _check_question_headings,
    "aeo.heading_hierarchy": _check_primary_heading_hierarchy,
    "aeo.product_answer_facts": _check_product_answer_facts,
    "aeo.product_evidence_facts": check_product_evidence_facts,
    "aeo.product_brand_identity": check_product_brand_identity,
    "aeo.offer_freshness_signal": check_offer_freshness_signal,
    "aeo.listing_answer_set": _check_listing_answer_set,
    "aeo.listing_item_facts": check_listing_item_facts,
    "aeo.assortment_freshness_signal": check_assortment_freshness_signal,
}


def _weight_for(rule: SiteHealthRule, facts: dict) -> float:
    """Resolve config-owned per-page-kind weight overrides."""
    profile = profile_for(facts)
    if profile is not None:
        override = profile.rule_weight_overrides.get(rule.rule_id)
        if override is not None:
            return float(override)
    return float(rule.weight)


def _normalized_outcome(
    rule: SiteHealthRule, outcome: str, evidence: dict
) -> tuple[str, str]:
    if (
        rule.rule_id == "technical.indexable"
        and outcome == RULE_OUTCOME_MISSING
        and evidence.get("indexing_intent") == "unknown"
    ):
        evidence["reason"] = "insufficient_evidence"
        return RULE_OUTCOME_UNKNOWN, "insufficient_evidence"
    reason = str(evidence.get("reason") or "")
    if outcome != RULE_OUTCOME_NOT_APPLICABLE:
        return outcome, reason
    if reason in UNAVAILABLE_REASONS:
        return RULE_OUTCOME_UNKNOWN, reason
    if reason in UNKNOWN_REASONS:
        return RULE_OUTCOME_UNKNOWN, reason
    if reason in STRUCTURAL_NA_REASONS:
        return outcome, reason
    bounded_reason = reason or "insufficient_evidence"
    evidence["reason"] = bounded_reason
    return RULE_OUTCOME_UNKNOWN, bounded_reason


@dataclass(frozen=True)
class _FrozenMeasurementProfile:
    context: dict[str, object]
    expressions: dict[str, tuple[str, float]]
    rows_by_family: dict[str, Any]


_CHECKPOINT_FAMILY_BY_ID = {
    checkpoint_id: family.family_id
    for family in CAPABILITY_FAMILIES_BY_ID.values()
    for checkpoint_id in family.checkpoint_ids
}


def measurement_context(facts: dict) -> dict[str, object]:
    source_support = facts.get("source_support") or {}
    freshness = facts.get("freshness_context") or {}
    page_kind = str(facts.get("page_kind") or "other")
    return {
        "is_site_root": facts.get("site") is not None,
        "research_sensitive": bool(source_support.get("research_sensitive")),
        "freshness_sensitive": bool(freshness.get("required"))
        or page_kind in {"product", "category", "pricing"},
        "primary_schema_present": primary_schema_present(facts),
    }


def _freeze_measurement_profile(facts: dict) -> _FrozenMeasurementProfile:
    page_kind = str(facts.get("page_kind") or "other")
    traits = observed_traits(facts)
    context = measurement_context(facts)
    expressions = {
        checkpoint_id: (family_id, internal_weight)
        for family_id, checkpoint_id, internal_weight in (
            expected_checkpoint_expressions(page_kind, traits, context)
        )
    }
    if context["is_site_root"]:
        expressions.update(
            {
                checkpoint_id: (family_id, internal_weight)
                for family_id, checkpoint_id, internal_weight in (
                    site_checkpoint_expressions()
                )
            }
        )
    rows = {row.family_id: row for row in profile_rows(page_kind, traits, context)}
    return _FrozenMeasurementProfile(context, expressions, rows)


def _measurement_metadata(
    rule: SiteHealthRule, frozen: _FrozenMeasurementProfile
) -> dict[str, Any]:
    expression = frozen.expressions.get(rule.rule_id)
    guard_member = rule.rule_id == "aeo.schema_expected_for_type" and bool(
        frozen.context.get("primary_schema_present")
    )
    profile_member = (
        expression is not None or guard_member or SCORE_ROLE_AEO not in rule.score_roles
    )
    score_roles = tuple(
        role
        for role in rule.score_roles
        if role != SCORE_ROLE_AEO or expression is not None
    )
    family_id = expression[0] if expression else ""
    family = CAPABILITY_FAMILIES_BY_ID.get(family_id)
    return {
        "score_applicability": bool(score_roles),
        "expected_profile_membership": profile_member,
        "score_roles": score_roles,
        "checkpoint_family": family_id,
        "readiness_dimension": family.dimension_id if family else "",
        "readiness_weight": expression[1] if expression else 0.0,
    }


def _semantic_profile_skip_reason(
    rule: SiteHealthRule, frozen: _FrozenMeasurementProfile
) -> str:
    if SCORE_ROLE_AEO not in rule.score_roles or rule.rule_id in frozen.expressions:
        return ""
    family_id = _CHECKPOINT_FAMILY_BY_ID.get(rule.rule_id)
    if not family_id:
        return ""
    row = frozen.rows_by_family.get(family_id)
    if row is None:
        return ""
    if row.status != PROFILE_STATUS_MEASURED:
        return str(row.reason)
    if family_id == "structured_representation":
        return ""
    return "family_expression_not_selected"


def evaluate_rule(
    rule: SiteHealthRule,
    facts: dict,
    *,
    frozen_profile: _FrozenMeasurementProfile | None = None,
) -> RuleEvaluation:
    """Evaluate one rule against a profile frozen before checkpoint outcomes."""
    frozen = frozen_profile or _freeze_measurement_profile(facts)
    base: dict[str, Any] = dict(
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        dimension=rule.dimension,
        category=rule.category,
        severity=rule.severity,
        finding_class=rule.finding_class,
        scope=rule.scope,
        weight=_weight_for(rule, facts),
        description=rule.description,
        remediation=rule.remediation,
    )
    applicable, skip_reason = applicability(rule, facts)
    if not applicable:
        evidence = {"reason": skip_reason or "unknown_applicability"}
        outcome, reason = _normalized_outcome(
            rule, RULE_OUTCOME_NOT_APPLICABLE, evidence
        )
        metadata = (
            _measurement_metadata(rule, frozen)
            if outcome != RULE_OUTCOME_NOT_APPLICABLE
            else {}
        )
        return RuleEvaluation(
            outcome=outcome,
            evidence=evidence,
            display_applicability=outcome != RULE_OUTCOME_NOT_APPLICABLE,
            reason_code=reason,
            **metadata,
            **base,
        )
    semantic_skip = _semantic_profile_skip_reason(rule, frozen)
    if semantic_skip:
        return RuleEvaluation(
            outcome=RULE_OUTCOME_NOT_APPLICABLE,
            evidence={"reason": semantic_skip},
            display_applicability=False,
            reason_code=semantic_skip,
            **_measurement_metadata(rule, frozen),
            **base,
        )
    check = _CHECKS.get(rule.rule_id)
    if check is None:
        reason = "no_check_mapped"
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": reason},
            reason_code=reason,
            **_measurement_metadata(rule, frozen),
            **base,
        )
    try:
        outcome, evidence = check(facts)
    # Preserve unexpected check failures as evidence instead of aborting the page.
    except Exception as exc:  # noqa: BLE001
        reason = "check_error"
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": f"{type(exc).__name__}: {exc}"[:512]},
            reason_code=reason,
            **_measurement_metadata(rule, frozen),
            **base,
        )
    outcome, reason = _normalized_outcome(rule, outcome, evidence)
    return RuleEvaluation(
        outcome=outcome,
        evidence=evidence,
        display_applicability=True,
        reason_code=reason,
        **_measurement_metadata(rule, frozen),
        **base,
    )


def evaluate_all(facts: dict) -> list[RuleEvaluation]:
    """Evaluate every catalog rule against one frozen measurement profile."""
    return evaluate_rules(facts, SITE_HEALTH_RULES)


def evaluate_rules(
    facts: dict, rules: Iterable[SiteHealthRule]
) -> list[RuleEvaluation]:
    """Evaluate the supplied rules against one immutable measurement profile."""
    frozen = _freeze_measurement_profile(facts)
    return [
        evaluate_rule(rule, facts, frozen_profile=frozen) for rule in rules
    ]


def rule_for(rule_id: str) -> SiteHealthRule | None:
    """Convenience lookup of a catalog rule by id (or None)."""
    return SITE_HEALTH_RULES_BY_ID.get(rule_id)
