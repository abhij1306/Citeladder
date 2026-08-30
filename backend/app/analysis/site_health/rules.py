# Pure deterministic evaluation of the config-owned Site Health rule catalog.
# Finalize-scoped rules are evaluated and persisted only by ``finalize.py``.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    server_render_signals,
)
from app.analysis.site_health.schema_rules import (
    check_schema_expected_for_type,
    check_schema_matches_content,
    check_schema_recommended_present,
    check_schema_required_valid,
    schema_expectation_for,
)
from app.analysis.site_health.web_fundamentals import (
    WEB_FUNDAMENTALS_CHECKS,
    check_heading_order,
)
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
    SEARCH_CITATION_CRAWLER_BOTS,
)
from app.core.config.site_health_contracts import (
    RULE_FAILING_OUTCOMES,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNAVAILABLE,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    STRUCTURAL_NA_REASONS,
    UNAVAILABLE_REASONS,
    UNKNOWN_REASONS,
    expected_checkpoints,
)
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_DIAGNOSTIC,
    KIND_EVIDENCE_TRIGGERED,
    RULE_SCOPE_PAGE,
    SiteHealthRule,
)
from app.core.config.site_health_rules import (
    ANSWER_FIRST_MIN_WORDS,
    EXPAND_GATED_MAX_RATIO,
    META_DESCRIPTION_LENGTH_BAND,
    QUESTION_HEADINGS_MIN_RATIO,
    SITE_HEALTH_RULES,
    SITE_HEALTH_RULES_BY_ID,
    SOCIAL_DOMAINS,
    TITLE_LENGTH_BAND,
    TTFB_WARN_MS,
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


def _check_https(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    is_https = bool(delivery.get("is_https"))
    return _pass_fail(is_https), {
        "scheme": delivery.get("scheme", ""),
        "final_url": delivery.get("final_url", ""),
        "is_https": is_https,
    }


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


def _check_hsts_present(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    security = delivery.get("security_headers") or {}
    present = bool(security.get("strict-transport-security"))
    return _pass_fail(present), {
        "present": present,
        "scheme": delivery.get("scheme", ""),
    }


def _check_ttfb_band(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    ttfb = delivery.get("ttfb_ms")
    if ttfb is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_ttfb_measurement"}
    ttfb_ms = int(ttfb)
    return _pass_fail(ttfb_ms <= TTFB_WARN_MS), {
        "ttfb_ms": ttfb_ms,
        "threshold_ms": TTFB_WARN_MS,
    }


def _check_uncompressed_html(facts: dict) -> tuple[str, dict]:
    delivery = facts.get("delivery") or {}
    compressed = bool(delivery.get("is_compressed"))
    return _pass_fail(compressed), {
        "content_encoding": delivery.get("content_encoding", ""),
        "is_compressed": compressed,
    }


def _check_ai_crawler_access(facts: dict) -> tuple[str, dict]:
    site = facts.get("site") or {}
    robots = site.get("robots") or {}
    stance = robots.get("ai_crawlers") or {}
    bounded_stance = {bot: stance.get(bot, "") for bot in AI_CRAWLER_BOTS}
    if not robots.get("fetched"):
        # The stance is the fail-open default (robots.txt unfetchable): a
        # PASS would be vacuous for a HIGH-severity signal. N/A instead.
        return RULE_OUTCOME_NOT_APPLICABLE, {
            "reason": "robots_not_fetched",
            "robots_fetched": False,
            "ai_crawlers": bounded_stance,
        }
    blocked = [
        bot for bot in AI_CRAWLER_BOTS if stance.get(bot) == AI_CRAWLER_STANCE_BLOCK
    ]
    return _pass_fail(not blocked), {
        "robots_fetched": True,
        "ai_crawlers": bounded_stance,
        "blocked": blocked,
    }


def _check_llms_txt_present(facts: dict) -> tuple[str, dict]:
    site = facts.get("site") or {}
    llms = site.get("llms_txt") or {}
    present = bool(llms.get("present"))
    return _pass_fail(present), {
        "fetched": bool(llms.get("fetched")),
        "present": present,
        "url": str(llms.get("url") or "")[:2048],
    }


def _check_search_crawler_access(facts: dict) -> tuple[str, dict]:
    robots = (facts.get("site") or {}).get("robots") or {}
    stance = robots.get("ai_crawlers") or {}
    if not robots.get("fetched"):
        return RULE_OUTCOME_NOT_APPLICABLE, {
            "reason": "robots_not_fetched",
            "crawler_role": "search_citation",
        }
    blocked = [
        bot
        for bot in SEARCH_CITATION_CRAWLER_BOTS
        if stance.get(bot) == AI_CRAWLER_STANCE_BLOCK
    ]
    return _pass_fail(not blocked), {
        "crawler_role": "search_citation",
        "checked": list(SEARCH_CITATION_CRAWLER_BOTS),
        "blocked": blocked,
    }


def _check_snippet_access(facts: dict) -> tuple[str, dict]:
    robots = facts.get("robots") or {}
    nosnippet = bool(robots.get("nosnippet"))
    max_snippet = robots.get("max_snippet")
    blocked = nosnippet or max_snippet == 0
    return _pass_fail(not blocked), {
        "nosnippet": nosnippet,
        "max_snippet": max_snippet,
        "directives": list(robots.get("directives") or ())[:32],
    }


def _check_author_present(facts: dict) -> tuple[str, dict]:
    author = (facts.get("author") or "").strip()
    return _pass_fail(bool(author)), {
        "present": bool(author),
        "author": author[:256],
    }


def _check_content_date_present(facts: dict) -> tuple[str, dict]:
    dates = facts.get("dates") or {}
    published = bool((dates.get("published") or "").strip())
    modified = bool((dates.get("modified") or "").strip())
    return _pass_fail(published or modified), {
        "has_published": published,
        "has_modified": modified,
    }


def _is_social_domain(host: str) -> bool:
    host = host.lower()
    return any(
        host == social or host.endswith(f".{social}") for social in SOCIAL_DOMAINS
    )


def _check_outbound_citations(facts: dict) -> tuple[str, dict]:
    domains = [str(d) for d in (facts.get("outbound_domains") or [])]
    non_social = [d for d in domains if not _is_social_domain(d)]
    return _pass_fail(bool(non_social)), {
        "outbound_domain_count": len(domains),
        "non_social_domain_count": len(non_social),
        "non_social_domains": non_social[:10],
    }


_SOFT_ERROR_PHRASES = ("page not found", "404 not found", "does not exist")


def _check_soft_error(facts: dict) -> tuple[str, dict]:
    status_code = (facts.get("delivery") or {}).get("status_code")
    headings = facts.get("headings") or {}
    title_and_h1 = [str(facts.get("title") or ""), *(headings.get("h1_texts") or ())]
    normalized = {value.strip().casefold() for value in title_and_h1 if value}
    matched = next(
        (phrase for phrase in _SOFT_ERROR_PHRASES if phrase in normalized), ""
    )
    soft_error = status_code == 200 and bool(matched)
    return _pass_fail(not soft_error), {
        "status_code": status_code,
        "matched_error_phrase": matched,
    }


def _check_answer_first(facts: dict) -> tuple[str, dict]:
    headings = facts.get("headings") or {}
    counts = headings.get("counts") or {}
    has_heading = (
        int(headings.get("h1_count", 0) or 0) > 0 or int(counts.get("h2", 0) or 0) > 0
    )
    if not has_heading:
        return RULE_OUTCOME_MISSING, {"reason": "no_headings"}
    answer = str(facts.get("first_answer_text") or "")
    word_count = len(answer.split())
    return _pass_fail(word_count >= ANSWER_FIRST_MIN_WORDS), {
        "answer_word_count": word_count,
        "minimum_words": ANSWER_FIRST_MIN_WORDS,
        "answer_preview": answer[:256],
    }


def _check_editorial_lead_present(facts: dict) -> tuple[str, dict]:
    lead = str(facts.get("first_answer_text") or "")
    word_count = len(lead.split())
    return _pass_fail(word_count >= ANSWER_FIRST_MIN_WORDS), {
        "lead_word_count": word_count,
        "minimum_words": ANSWER_FIRST_MIN_WORDS,
        "lead_preview": lead[:256],
    }


def _check_entity_value_proposition(facts: dict) -> tuple[str, dict]:
    headings = facts.get("headings") or {}
    identity = bool(headings.get("h1_texts"))
    traits = facts.get("page_traits") or ()
    contact_path = bool(facts.get("contact_points") or has_contact_form_fields(facts))
    lead = str(facts.get("first_answer_text") or "")
    value_proposition = len(lead.split()) >= ANSWER_FIRST_MIN_WORDS
    contract = _composite_contract("aeo.entity_value_proposition")
    atoms = [
        contract.atom_detail(
            "entity_identity", satisfied=identity, evidence=identity, page_traits=traits
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
            evidence={"word_count": len(lead.split())},
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
    headings = facts.get("headings") or {}
    subheadings = len(headings.get("h2_texts") or []) + len(
        headings.get("h3_texts") or []
    )
    if not subheadings:
        return RULE_OUTCOME_MISSING, {"reason": "no_subheadings"}
    ratio = float(facts.get("question_heading_ratio", 0.0) or 0.0)
    return _pass_fail(ratio > QUESTION_HEADINGS_MIN_RATIO), {
        "question_heading_ratio": ratio,
        "subheading_count": subheadings,
        "minimum_ratio": QUESTION_HEADINGS_MIN_RATIO,
    }


def _check_server_rendered_content(facts: dict) -> tuple[str, dict]:
    is_shell, evidence = server_render_signals(facts)
    return _pass_fail(not is_shell), evidence


def _check_no_expand_gating(facts: dict) -> tuple[str, dict]:
    ratio = float(facts.get("expand_gated_ratio", 0.0) or 0.0)
    return _pass_fail(ratio <= EXPAND_GATED_MAX_RATIO), {
        "expand_gated_ratio": ratio,
        "max_ratio": EXPAND_GATED_MAX_RATIO,
    }


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
    "technical.https": _check_https,
    "technical.single_h1": _check_single_h1,
    "technical.thin_content": _check_thin_content,
    "technical.canonical_conflict": _check_canonical_conflict,
    "technical.title_length_band": _check_title_length_band,
    "technical.meta_description_length_band": _check_meta_description_length_band,
    "technical.hsts_present": _check_hsts_present,
    "technical.ttfb_band": _check_ttfb_band,
    "technical.uncompressed_html": _check_uncompressed_html,
    **WEB_FUNDAMENTALS_CHECKS,
    "technical.ai_crawler_access": _check_ai_crawler_access,
    "search.crawler_access": _check_search_crawler_access,
    "search.snippet_access": _check_snippet_access,
    "aeo.structured_data_present": _check_structured_data_present,
    "aeo.open_graph_present": _check_open_graph_present,
    "aeo.llms_txt_present": _check_llms_txt_present,
    "aeo.schema_expected_for_type": check_schema_expected_for_type,
    "aeo.schema_required_valid": check_schema_required_valid,
    "aeo.schema_recommended_present": check_schema_recommended_present,
    "aeo.schema_matches_content": check_schema_matches_content,
    "aeo.author_present": _check_author_present,
    "aeo.content_date_present": _check_content_date_present,
    "aeo.outbound_citations": _check_outbound_citations,
    "aeo.organization_identity": check_organization_identity,
    "aeo.trust_path_present": check_trust_path_present,
    "aeo.answer_first": _check_answer_first,
    "aeo.editorial_lead_present": _check_editorial_lead_present,
    "aeo.entity_value_proposition": _check_entity_value_proposition,
    "aeo.question_headings": _check_question_headings,
    "aeo.server_rendered_content": _check_server_rendered_content,
    "aeo.no_expand_gating": _check_no_expand_gating,
    "aeo.heading_hierarchy": check_heading_order,
    "aeo.product_answer_facts": _check_product_answer_facts,
    "aeo.product_evidence_facts": check_product_evidence_facts,
    "aeo.product_brand_identity": check_product_brand_identity,
    "aeo.offer_freshness_signal": check_offer_freshness_signal,
    "aeo.listing_answer_set": _check_listing_answer_set,
    "aeo.listing_item_facts": check_listing_item_facts,
    "aeo.assortment_freshness_signal": check_assortment_freshness_signal,
    "technical.soft_error": _check_soft_error,
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
        return RULE_OUTCOME_UNAVAILABLE, reason
    if reason in UNKNOWN_REASONS:
        return RULE_OUTCOME_UNKNOWN, reason
    if reason in STRUCTURAL_NA_REASONS:
        return outcome, reason
    bounded_reason = reason or "insufficient_evidence"
    evidence["reason"] = bounded_reason
    return RULE_OUTCOME_UNKNOWN, bounded_reason


def _triggered_evidence_present(rule: SiteHealthRule, facts: dict) -> bool:
    if rule.rule_id.startswith("aeo.schema_"):
        expectation = schema_expectation_for(facts)
        found_types = set((facts.get("structured_data") or {}).get("types") or ())
        return bool(found_types.intersection(expectation.expected_types))
    return True


def _profile_membership(rule: SiteHealthRule, facts: dict) -> bool:
    """Freeze expected membership from structural context before evaluation."""
    page_kind = str(facts.get("page_kind") or "other")
    expected = expected_checkpoints(
        page_kind,
        observed_traits(facts),
        {"is_site_root": facts.get("site") is not None},
    )
    if not rule.readiness_dimension:
        return True
    profile_member = rule.rule_id in expected
    if rule.kind_evidence == KIND_EVIDENCE_TRIGGERED:
        return profile_member and _triggered_evidence_present(rule, facts)
    return profile_member


def _measurement_metadata(rule: SiteHealthRule, facts: dict) -> dict[str, Any]:
    profile_member = _profile_membership(rule, facts)
    score_roles = rule.score_roles if profile_member else ()
    return {
        "score_applicability": bool(score_roles),
        "expected_profile_membership": profile_member,
        "score_roles": score_roles,
        "checkpoint_family": rule.checkpoint_family,
        "readiness_dimension": rule.readiness_dimension,
        "readiness_weight": rule.readiness_weight,
    }


def evaluate_rule(rule: SiteHealthRule, facts: dict) -> RuleEvaluation:
    """Evaluate one rule; preserve check failures as explicit ERROR outcomes."""
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
            _measurement_metadata(rule, facts)
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
    check = _CHECKS.get(rule.rule_id)
    if check is None:
        reason = "no_check_mapped"
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": reason},
            reason_code=reason,
            **_measurement_metadata(rule, facts),
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
            **_measurement_metadata(rule, facts),
            **base,
        )
    outcome, reason = _normalized_outcome(rule, outcome, evidence)
    return RuleEvaluation(
        outcome=outcome,
        evidence=evidence,
        display_applicability=True,
        reason_code=reason,
        **_measurement_metadata(rule, facts),
        **base,
    )


def evaluate_all(facts: dict) -> list[RuleEvaluation]:
    """Evaluate every catalog rule against ``facts`` (catalog order)."""
    return [evaluate_rule(rule, facts) for rule in SITE_HEALTH_RULES]


def rule_for(rule_id: str) -> SiteHealthRule | None:
    """Convenience lookup of a catalog rule by id (or None)."""
    return SITE_HEALTH_RULES_BY_ID.get(rule_id)
