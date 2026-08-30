# Deterministic rule evaluation (Task 5; page-kind scoped in sh-rules-3).
#
# Evaluates the config-owned ``SITE_HEALTH_RULES`` catalog against a page-facts
# dict (produced by ``parser.extract_page_facts``) into one ``RuleEvaluation``
# per rule. Each evaluation carries the explicit measurement outcome, a bounded
# exact ``evidence`` dict, and rule/measurement metadata for provenance.
#
# PURE + deterministic (no I/O, no ORM). Applicability is driven by the rule's
# ``applicability_key`` ("always" | "has_html" | "page_kind:<type>" (v2 P1) |
# "site_root" | "crawl_finalize" (v2 P2, spec §5.2/§5.3)). ``site_root`` rules
# resolve against the worker-injected ``facts["site"]`` (present only in the
# crawl root's own analysis, so they evaluate exactly once per crawl);
# ``crawl_finalize`` rules are NEVER applicable here — the finalize-writer in
# the worker owns their rows (single-writer per rule scope), and the analyze
# writer filters them out before persisting. If a rule's check raises, its
# outcome is ERROR (preserved, given zero scoring credit) — a single broken
# check never aborts the whole evaluation. Per-type thin-content minimums and
# rule-weight overrides are config-owned (``PAGE_KIND_PROFILES``, invariant 1);
# the v1 analysis-owned ``MIN_SUFFICIENT_WORDS`` constant moved there in v2.
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.analysis.site_health.indexing import (
    canonical_origin,
    evaluate_indexability,
    normalized_url_for_compare,
    resolve_canonical,
)
from app.analysis.site_health.product_rules import (
    check_product_offer_details,
    check_product_visible_schema_parity,
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
)
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_UNAVAILABLE,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    READINESS_CHECKPOINTS,
    SCORE_ROLE_AEO,
    SCORE_ROLE_TECHNICAL,
    UNAVAILABLE_REASONS,
    UNKNOWN_REASONS,
)
from app.core.config.site_health_page_profiles import (
    PRODUCT_ANALYSIS_RULES,
    PRODUCT_ANALYSIS_RULES_BY_ID,
    PRODUCT_SCHEMA_EXPECTATION,
)
from app.core.config.site_health_rule_types import (
    KIND_EVIDENCE_TRIGGERED,
    SiteHealthRule,
)
from app.core.config.site_health_rules import (
    ANSWER_FIRST_MIN_WORDS,
    EXPAND_GATED_MAX_RATIO,
    META_DESCRIPTION_LENGTH_BAND,
    QUESTION_HEADINGS_MIN_RATIO,
    RENDER_BLOCKING_MAX_RESOURCES,
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
    """``(signal, satisfied)`` for a short page that may still be complete.

    Only ever ADDS a way to pass. Nothing here can fail a page the word floor
    would have passed, so the check reports fewer pages than the floor alone
    would, never more.
    """
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    if page_kind in CONTENT_SUFFICIENCY_PRICE_KINDS:
        return "price", _has_price_evidence(facts)
    wanted = CONTENT_SUFFICIENCY_TRAITS.get(page_kind)
    if wanted:
        return "|".join(wanted), bool(observed_traits(facts) & set(wanted))
    return "", False


@dataclass(frozen=True)
class RuleEvaluation:
    """The bounded, deterministic result of evaluating one rule.

    Immutable value type the worker persists as a ``SiteRuleEvaluation`` row.
    ``outcome`` is a config ``RULE_OUTCOME_*`` token; ``evidence`` is a small
    JSON-safe dict of exactly what drove the outcome.
    """

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


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_PASS if condition else RULE_OUTCOME_FAIL


# --- individual checks: (facts) -> (outcome, evidence) --------------------


def _check_title_present(facts: dict) -> tuple[str, dict]:
    title = (facts.get("title") or "").strip()
    return _pass_fail(bool(title)), {
        "title_length": len(title),
        "present": bool(title),
    }


def _check_meta_description_present(facts: dict) -> tuple[str, dict]:
    desc = (facts.get("meta_description") or "").strip()
    return _pass_fail(bool(desc)), {
        "description_length": len(desc),
        "present": bool(desc),
    }


def _check_canonical_present(facts: dict) -> tuple[str, dict]:
    canonical = (facts.get("canonical_url") or "").strip()
    return _pass_fail(bool(canonical)), {
        "canonical_url": canonical,
        "present": bool(canonical),
    }


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
    """Report an EMPTY page, not a short one.

    This used to compare the word count against a per-page-kind minimum
    ranging from 40 to 300. Segmenting by kind beat one global threshold, but
    the premise underneath was still that length proves substance, and it does
    not: there is no magical minimum word count and no ideal page length. A
    category page with 25 words over 60 well-organized products, a contact
    page complete in 30 words, and a product page with 65 words plus price,
    availability and specifications were all reported as thin.

    The verdict is now emptiness, against one low universal floor, with word
    count kept as EVIDENCE rather than as the judgement. Below the floor a
    page can still prove itself structurally -- a listing that lists, a
    location with findable details, a commercial page with a price -- which
    only ever adds a way to pass.
    """
    body = facts.get("body") or {}
    word_count = int(body.get("word_count", 0) or 0)
    profile = profile_for(facts) or PAGE_KIND_PROFILES[PAGE_KIND_OTHER]
    evidence: dict[str, Any] = {
        "word_count": word_count,
        "minimum": MIN_MEANINGFUL_WORDS,
        "page_kind": profile.page_kind,
    }
    if word_count >= MIN_MEANINGFUL_WORDS:
        return RULE_OUTCOME_PASS, evidence
    signal, satisfied = _structural_sufficiency(facts)
    evidence["structural_signal"] = signal
    evidence["structurally_sufficient"] = satisfied
    return _pass_fail(satisfied), evidence


# --- v2 P2: hygiene checks -------------------------------------------------


def _hreflang_alternate_urls(facts: dict) -> list[str]:
    alternates = facts.get("hreflang_alternates") or []
    return [
        str(entry.get("url") or "")
        for entry in alternates
        if isinstance(entry, dict) and entry.get("url")
    ]


def _check_canonical_conflict(facts: dict) -> tuple[str, dict]:
    """Fail on a canonical that is BROKEN, not on one that merely points away.

    The old check failed whenever the canonical was not the page's own final
    URL. That is the ordinary, intended use of the element: consolidating a
    sorted, filtered or paginated view onto its parent is what rel=canonical
    exists to do, and a canonical declaration is not even mandatory.

    Worse, it contradicted this package's own indexing logic, which reads the
    identical condition as evidence that the page is DELIBERATELY excluded
    (``_canonical_intent``). One module treated a cross-canonical as a mistake
    while the other treated it as an intention.

    So a plain cross-canonical passes, and only positive evidence of a broken
    target fails. Evidence needing crawl-wide state -- a canonical pointing at
    a 404 or at a noindex page -- is not available in the per-page pass and is
    not guessed at here.
    """
    declared = (facts.get("canonical_url") or "").strip()
    if not declared:
        # No canonical declared: the presence rule owns that finding.
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
        return RULE_OUTCOME_PASS, evidence

    origin = canonical_origin(canonical)
    if not origin:
        # Not an absolute http(s) URL even after resolution: this cannot
        # consolidate anything.
        evidence["problem"] = "invalid_canonical"
        return RULE_OUTCOME_FAIL, evidence

    final_origin = canonical_origin(final_url)
    if final_origin and origin != final_origin:
        # Handing indexing authority to another origin is almost never what a
        # site owner meant, and it is not something consolidation requires.
        evidence["problem"] = "cross_origin_canonical"
        return RULE_OUTCOME_FAIL, evidence

    alternates = {
        normalized_url_for_compare(url) for url in _hreflang_alternate_urls(facts)
    }
    if alternates and normalized_url_for_compare(canonical) in alternates:
        # A page in an hreflang cluster must canonicalise to ITSELF. Pointing
        # at a sibling language tells the two systems opposite things about
        # which URL represents this content.
        evidence["problem"] = "hreflang_canonical_conflict"
        return RULE_OUTCOME_FAIL, evidence

    evidence["reason"] = "intentional_consolidation"
    return RULE_OUTCOME_PASS, evidence


def _length_band_check(
    value: object, *, band: tuple[int, int], empty_reason: str, length_key: str
) -> tuple[str, dict]:
    """Shared body for the title / meta-description length-band rules.

    N/A when the field is empty (the v1 presence rules own that finding);
    otherwise pass when the length falls inside the inclusive config band.
    """
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


def _check_render_blocking(facts: dict) -> tuple[str, dict]:
    blocking = facts.get("blocking_resources") or {}
    total = int(blocking.get("total", 0) or 0)
    return _pass_fail(total <= RENDER_BLOCKING_MAX_RESOURCES), {
        "scripts": int(blocking.get("scripts", 0) or 0),
        "stylesheets": int(blocking.get("stylesheets", 0) or 0),
        "total": total,
        "max_allowed": RENDER_BLOCKING_MAX_RESOURCES,
    }


# --- v2 P2: site_root checks (facts["site"] injected by the worker) --------


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


# --- v2 P2: citability checks -----------------------------------------------


def _check_author_present(facts: dict) -> tuple[str, dict]:
    author = (facts.get("author") or "").strip()
    return _pass_fail(bool(author)), {
        "present": bool(author),
        "author": author[:256],
    }


def _check_date_present(facts: dict) -> tuple[str, dict]:
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


def _check_organization_identity(facts: dict) -> tuple[str, dict]:
    sd = facts.get("structured_data") or {}
    org_blocks = [
        block
        for block in (sd.get("blocks") or [])
        if str(block.get("type") or "") == "Organization"
    ]
    same_as: list[str] = []
    for block in org_blocks:
        for entry in block.get("same_as") or []:
            text = str(entry).strip()
            if text and text not in same_as:
                same_as.append(text)
    return _pass_fail(bool(same_as)), {
        "has_organization": bool(org_blocks),
        "same_as_count": len(same_as),
        "same_as": same_as[:8],
    }


# --- v2 P2: extractability checks -------------------------------------------


def _check_answer_first(facts: dict) -> tuple[str, dict]:
    headings = facts.get("headings") or {}
    counts = headings.get("counts") or {}
    has_heading = (
        int(headings.get("h1_count", 0) or 0) > 0 or int(counts.get("h2", 0) or 0) > 0
    )
    if not has_heading:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_headings"}
    answer = str(facts.get("first_answer_text") or "")
    word_count = len(answer.split())
    return _pass_fail(word_count >= ANSWER_FIRST_MIN_WORDS), {
        "answer_word_count": word_count,
        "minimum_words": ANSWER_FIRST_MIN_WORDS,
        "answer_preview": answer[:256],
    }


def _check_question_headings(facts: dict) -> tuple[str, dict]:
    headings = facts.get("headings") or {}
    subheadings = len(headings.get("h2_texts") or []) + len(
        headings.get("h3_texts") or []
    )
    if not subheadings:
        # ``question_heading_ratio`` is questions / subheadings and is 0.0 when
        # there are NO subheadings at all -- indistinguishable, to the ratio
        # alone, from subheadings that are all badly phrased. A page with no
        # sections is not a page with poorly written sections, so there is
        # nothing here to judge.
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_subheadings"}
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


# Map each config rule_id to its concrete check. A rule in the catalog with no
# mapped check evaluates to ERROR (a wiring bug, preserved with zero credit).
# ``crawl_finalize`` rules are deliberately ABSENT here: their checks live in
# ``analysis/site_health/finalize.py`` (the finalize-writer owns those rows).
_CHECKS: dict[str, Callable[[dict], tuple[str, dict]]] = {
    "technical.title_present": _check_title_present,
    "technical.meta_description_present": _check_meta_description_present,
    "technical.canonical_present": _check_canonical_present,
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
    "technical.render_blocking": _check_render_blocking,
    "technical.ai_crawler_access": _check_ai_crawler_access,
    "aeo.structured_data_present": _check_structured_data_present,
    "aeo.open_graph_present": _check_open_graph_present,
    "aeo.llms_txt_present": _check_llms_txt_present,
    "aeo.schema_expected_for_type": check_schema_expected_for_type,
    "aeo.schema_required_valid": check_schema_required_valid,
    "aeo.schema_recommended_present": check_schema_recommended_present,
    "aeo.schema_matches_content": check_schema_matches_content,
    "aeo.author_present": _check_author_present,
    "aeo.date_present": _check_date_present,
    "aeo.outbound_citations": _check_outbound_citations,
    "aeo.organization_identity": _check_organization_identity,
    "aeo.answer_first": _check_answer_first,
    "aeo.question_headings": _check_question_headings,
    "aeo.server_rendered_content": _check_server_rendered_content,
    "aeo.no_expand_gating": _check_no_expand_gating,
    "aeo.product_offer_details": check_product_offer_details,
    "aeo.product_visible_schema_parity": check_product_visible_schema_parity,
}


def _weight_for(rule: SiteHealthRule, facts: dict) -> float:
    """The rule's weight, with any per-(rule_id, page_kind) config override.

    Resolved at evaluation time from ``PAGE_KIND_PROFILES`` so the emitted
    ``RuleEvaluation`` carries exactly the weight scoring will credit.
    """
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
        and outcome == RULE_OUTCOME_FAIL
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
    return outcome, reason


def _profile_membership(
    rule: SiteHealthRule, facts: dict, outcome: str, reason: str
) -> bool:
    tier = str((facts.get("page_kind_evidence") or {}).get("tier") or "")
    profile_member = outcome != RULE_OUTCOME_NOT_APPLICABLE
    checkpoint = READINESS_CHECKPOINTS.get(rule.rule_id)
    if checkpoint is not None and rule.kind_evidence != KIND_EVIDENCE_TRIGGERED:
        profile_member = profile_member and tier in ("", "structural")
    if checkpoint is not None and rule.kind_evidence == KIND_EVIDENCE_TRIGGERED:
        profile_member = profile_member and not reason.startswith("no_")
    return profile_member


def _score_roles(rule: SiteHealthRule, profile_member: bool) -> tuple[str, ...]:
    score_roles: list[str] = []
    if rule.finding_class == "defect" and profile_member:
        score_roles.append(SCORE_ROLE_TECHNICAL)
    if rule.rule_id in READINESS_CHECKPOINTS and profile_member:
        score_roles.append(SCORE_ROLE_AEO)
    return tuple(score_roles)


def _measurement_metadata(
    rule: SiteHealthRule, facts: dict, outcome: str, reason: str
) -> dict[str, Any]:
    checkpoint = READINESS_CHECKPOINTS.get(rule.rule_id)
    profile_member = _profile_membership(rule, facts, outcome, reason)
    score_roles = _score_roles(rule, profile_member)
    return {
        "score_applicability": bool(score_roles),
        "expected_profile_membership": profile_member,
        "score_roles": score_roles,
        "checkpoint_family": checkpoint.family if checkpoint else "",
        "readiness_dimension": checkpoint.dimension if checkpoint else "",
        "readiness_weight": checkpoint.weight if checkpoint else 0.0,
    }


def evaluate_rule(rule: SiteHealthRule, facts: dict) -> RuleEvaluation:
    """Evaluate one rule against ``facts`` into a ``RuleEvaluation``.

    Not-applicable rules short-circuit to NOT_APPLICABLE (excluded from
    scoring). A check that raises yields ERROR (preserved, zero credit). Never
    raises.
    """
    base: dict[str, Any] = dict(
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        dimension=rule.dimension,
        category=rule.category,
        severity=rule.severity,
        finding_class=rule.finding_class,
        weight=_weight_for(rule, facts),
        description=rule.description,
        remediation=rule.remediation,
    )
    applicable, skip_reason = applicability(rule, facts)
    if not applicable:
        return RuleEvaluation(
            outcome=RULE_OUTCOME_NOT_APPLICABLE,
            evidence={"reason": skip_reason or "not_applicable"},
            display_applicability=False,
            reason_code=skip_reason or "not_applicable",
            **base,
        )
    check = _CHECKS.get(rule.rule_id)
    if check is None:
        reason = "no_check_mapped"
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": reason},
            reason_code=reason,
            **_measurement_metadata(rule, facts, RULE_OUTCOME_ERROR, reason),
            **base,
        )
    try:
        outcome, evidence = check(facts)
    # The one blind catch this package keeps, because it does not swallow:
    # ANY failure of a rule check becomes an explicit RULE_OUTCOME_ERROR
    # carrying the exception type, which invariant 7 keeps distinct from a
    # pass, a fail, and a not-applicable. Narrowing it would let an
    # unanticipated defect crash the whole page evaluation instead.
    except Exception as exc:  # noqa: BLE001
        reason = "check_error"
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": f"{type(exc).__name__}: {exc}"[:512]},
            reason_code=reason,
            **_measurement_metadata(rule, facts, RULE_OUTCOME_ERROR, reason),
            **base,
        )
    outcome, reason = _normalized_outcome(rule, outcome, evidence)
    return RuleEvaluation(
        outcome=outcome,
        evidence=evidence,
        display_applicability=True,
        reason_code=reason,
        **_measurement_metadata(rule, facts, outcome, reason),
        **base,
    )


def evaluate_all(facts: dict) -> list[RuleEvaluation]:
    """Evaluate every catalog rule against ``facts`` (catalog order)."""
    supplemental = (
        PRODUCT_ANALYSIS_RULES
        if str(facts.get("page_kind") or "").lower()
        == PRODUCT_SCHEMA_EXPECTATION.page_kind
        else ()
    )
    return [evaluate_rule(rule, facts) for rule in (*SITE_HEALTH_RULES, *supplemental)]


def rule_for(rule_id: str) -> SiteHealthRule | None:
    """Convenience lookup of a catalog rule by id (or None)."""
    return SITE_HEALTH_RULES_BY_ID.get(rule_id) or PRODUCT_ANALYSIS_RULES_BY_ID.get(
        rule_id
    )
