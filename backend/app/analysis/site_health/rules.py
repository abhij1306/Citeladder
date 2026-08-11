# Deterministic rule evaluation (Task 5; expanded to sh-rules-2 in v2 P2).
#
# Evaluates the config-owned ``SITE_HEALTH_RULES`` catalog against a page-facts
# dict (produced by ``parser.extract_page_facts``) into one ``RuleEvaluation``
# per rule. Each evaluation carries an outcome
# (pass / fail / not_applicable / error), a bounded exact ``evidence`` dict, and
# the rule's dimension/category/severity/weight/version for provenance.
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

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from app.core.config.site_health import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_BLOCK,
    ANSWER_FIRST_MIN_WORDS,
    APPLICABILITY_CRAWL_FINALIZE,
    APPLICABILITY_OBSERVED_CONTENT,
    APPLICABILITY_SITE_ROOT,
    EXPAND_GATED_MAX_RATIO,
    META_DESCRIPTION_LENGTH_BAND,
    PAGE_KIND_APPLICABILITY_PREFIX,
    PAGE_KIND_CONTENT_APPLICABILITY_PREFIX,
    PAGE_KIND_EXPECTED_SCHEMA,
    PAGE_KIND_OTHER,
    PAGE_KIND_PROFILES,
    QUESTION_HEADINGS_MIN_RATIO,
    RENDER_BLOCKING_MAX_RESOURCES,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
    SCHEMA_CONTENT_MATCH_MAX_CANDIDATES,
    SERVER_RENDERED_MIN_WORDS,
    SITE_HEALTH_RULES,
    SITE_HEALTH_RULES_BY_ID,
    SOCIAL_DOMAINS,
    TITLE_LENGTH_BAND,
    TTFB_WARN_MS,
    PageKindProfile,
    PageKindSchemaExpectation,
    SiteHealthRule,
)
from app.core.config.site_health_page_profiles import (
    PRODUCT_ANALYSIS_RULES,
    PRODUCT_ANALYSIS_RULES_BY_ID,
    PRODUCT_PARITY_FIELDS,
    PRODUCT_PARITY_NORMALIZATION_PATTERN,
    PRODUCT_PARITY_SCHEMA_FACT_KEYS,
    PRODUCT_SCHEMA_EXPECTATION,
    PRODUCT_SCHEMA_URI_SEPARATOR,
)


def _profile_for(facts: dict) -> PageKindProfile | None:
    """The config profile for ``facts["page_kind"]`` (None when unknown)."""
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    return PAGE_KIND_PROFILES.get(page_kind)


def _sufficient_word_minimum(facts: dict) -> tuple[int, str]:
    """Per-type thin-content minimum, falling back to the ``other`` profile.

    Returns ``(minimum, page_kind)`` so the check evidence records exactly
    which profile drove the outcome.
    """
    profile = _profile_for(facts) or PAGE_KIND_PROFILES[PAGE_KIND_OTHER]
    return profile.min_sufficient_words, profile.page_kind


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
    weight: float
    outcome: str
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation: str = ""


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
    robots = facts.get("robots") or {}
    noindex = bool(robots.get("noindex"))
    # noindex -> fail (not indexable); otherwise pass.
    return _pass_fail(not noindex), {
        "noindex": noindex,
        "nofollow": bool(robots.get("nofollow")),
    }


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
    body = facts.get("body") or {}
    word_count = int(body.get("word_count", 0) or 0)
    minimum, page_kind = _sufficient_word_minimum(facts)
    return _pass_fail(word_count >= minimum), {
        "word_count": word_count,
        "minimum": minimum,
        "page_kind": page_kind,
    }


# --- v2 P2: hygiene checks -------------------------------------------------


def _normalized_url_for_compare(url: str) -> str:
    """Canonical form for canonical-vs-final comparison (deterministic).

    Lowercases scheme/host, strips the fragment, drops default ports, and
    strips trailing slashes (except the root path). NOT the admission-time
    canonicalizer — a comparison-only normalization local to this check.
    """
    raw = str(url or "").strip()
    try:
        parts = urlsplit(raw)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        try:
            port = parts.port
        except ValueError:
            port = None
    except Exception:
        return raw.lower()
    if not scheme or not host:
        return raw.lower()
    netloc = host
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    path = parts.path or ""
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    out = f"{scheme}://{netloc}{path or '/'}"
    if parts.query:
        out += f"?{parts.query}"
    return out


def _check_canonical_conflict(facts: dict) -> tuple[str, dict]:
    canonical = (facts.get("canonical_url") or "").strip()
    if not canonical:
        # No canonical declared: the v1 presence rule owns that finding.
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_canonical"}
    delivery = facts.get("delivery") or {}
    final_url = str(delivery.get("final_url") or "")
    match = _normalized_url_for_compare(canonical) == _normalized_url_for_compare(
        final_url
    )
    return _pass_fail(match), {
        "canonical_url": canonical[:2048],
        "final_url": final_url[:2048],
        "matches_final_url": match,
    }


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


# --- v2 P2: per-type schema validity checks --------------------------------


def _expectation_for(facts: dict) -> PageKindSchemaExpectation:
    """The config schema expectation for the page's classified type.

    Falls back to the ``other`` expectation for an absent/unknown page type
    (same fallback convention as the thin-content minimum).
    """
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    if page_kind == PRODUCT_SCHEMA_EXPECTATION.page_kind:
        return PRODUCT_SCHEMA_EXPECTATION
    return PAGE_KIND_EXPECTED_SCHEMA.get(
        page_kind, PAGE_KIND_EXPECTED_SCHEMA[PAGE_KIND_OTHER]
    )


def _expected_blocks(facts: dict, expectation: PageKindSchemaExpectation) -> list[dict]:
    """Structured-data blocks whose type is expected for the page type."""
    sd = facts.get("structured_data") or {}
    expected = set(expectation.expected_types)
    return [
        block
        for block in (sd.get("blocks") or [])
        if str(block.get("type") or "") in expected
    ]


def _check_schema_expected_for_type(facts: dict) -> tuple[str, dict]:
    expectation = _expectation_for(facts)
    sd = facts.get("structured_data") or {}
    found_types = sorted(str(t) for t in (sd.get("types") or []))
    blocks = _expected_blocks(facts, expectation)
    return _pass_fail(bool(blocks)), {
        "page_kind": expectation.page_kind,
        "expected_types": list(expectation.expected_types),
        "found_types": found_types[:20],
    }


def _missing_paths(block: dict, paths: tuple[str, ...]) -> list[str]:
    present = set(block.get("props_present") or [])
    return [path for path in paths if path not in present]


def _schema_property_check(facts: dict, *, recommended: bool) -> tuple[str, dict]:
    """Shared body for the required/recommended schema-property rules.

    The best-annotated expected-type block decides: one complete block
    passes. N/A when the page carries no expected-type block (the
    ``aeo.schema_expected_for_type`` rule owns that failure — these rules
    never double-report it, and can never be circular since the page type
    comes from URL/content signals first, spec §5.1) or — recommended only —
    when the expectation recommends nothing.
    """
    label = "recommended" if recommended else "required"
    expectation = _expectation_for(facts)
    paths = (
        expectation.recommended_properties
        if recommended
        else expectation.required_properties
    )
    if not paths:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": f"no_{label}_properties"}
    blocks = _expected_blocks(facts, expectation)
    if not blocks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_expected_type_block"}
    best_missing = min((_missing_paths(block, paths) for block in blocks), key=len)
    evidence = {
        "page_kind": expectation.page_kind,
        "expected_types": list(expectation.expected_types),
        label: list(paths),
        "missing": best_missing,
        "checked_blocks": len(blocks),
    }
    if best_missing and any(
        str(block.get("syntax") or "") == "microdata"
        and not (block.get("props_present") or [])
        for block in blocks
    ):
        # Microdata extraction is shallow (no per-property walk): a failing
        # block with empty props_present may be fully marked up in the HTML.
        # Record the limitation so the UI can explain the finding.
        evidence["extraction"] = "microdata_shallow"
    return _pass_fail(not best_missing), evidence


def _check_schema_required_valid(facts: dict) -> tuple[str, dict]:
    return _schema_property_check(facts, recommended=False)


def _check_schema_recommended_present(facts: dict) -> tuple[str, dict]:
    return _schema_property_check(facts, recommended=True)


def _check_schema_matches_content(facts: dict) -> tuple[str, dict]:
    expectation = _expectation_for(facts)
    blocks = _expected_blocks(facts, expectation)
    if not blocks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_expected_type_block"}
    candidates = [
        str(block.get("name") or "").strip()
        for block in blocks
        if str(block.get("name") or "").strip()
    ][:SCHEMA_CONTENT_MATCH_MAX_CANDIDATES]
    if not candidates:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_schema_names"}
    headings = facts.get("headings") or {}
    haystacks = [str(facts.get("title") or "")]
    haystacks += [str(t) for t in (headings.get("h1_texts") or [])]
    lowered = [hay.lower() for hay in haystacks if hay]
    matched = any(
        candidate.lower() in hay for candidate in candidates for hay in lowered
    )
    return _pass_fail(matched), {
        "page_kind": expectation.page_kind,
        "candidates": [c[:256] for c in candidates],
        "matched_visible_content": matched,
    }


def _product_block(facts: dict) -> dict | None:
    """The bounded Product fact, only when Product markup is actually present."""
    product = (facts.get("structured_data") or {}).get("product") or {}
    return product if int(product.get("schema_product_count", 0) or 0) else None


def _check_product_offer_details(facts: dict) -> tuple[str, dict]:
    """Validate Product/Offer completeness without inferring optional claims."""
    product = _product_block(facts)
    if product is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_product_schema"}
    offer_declared = _product_offer_declared(facts)
    missing = _missing_product_offer_fields(product, offer_declared=offer_declared)
    return _pass_fail(not missing), _product_offer_evidence(
        product, offer_declared=offer_declared, missing=missing
    )


def _product_offer_declared(facts: dict) -> bool:
    blocks = (facts.get("structured_data") or {}).get("blocks") or []
    return any(
        block.get("type") == "Product"
        and "offers" in (block.get("props_present") or [])
        for block in blocks
    )


def _missing_product_offer_fields(product: dict, *, offer_declared: bool) -> list[str]:
    missing: list[str] = []
    if not (product.get("sku") or product.get("gtin") or product.get("mpn")):
        missing.append("identifier")
    if not product.get("brand"):
        missing.append("brand")
    if offer_declared:
        for field, key in (
            ("price", "price"),
            ("priceCurrency", "price_currency"),
            ("availability", "availability"),
        ):
            if not product.get(key):
                missing.append(f"offers.{field}")
    return missing


def _product_offer_evidence(
    product: dict, *, offer_declared: bool, missing: list[str]
) -> dict:
    return {
        "schema_product_count": product["schema_product_count"],
        "offer_declared": offer_declared,
        "missing": missing,
        "sku": product.get("sku") or [],
        "gtin": product.get("gtin") or [],
        "brand": product.get("brand") or [],
        "price": product.get("price") or [],
        "price_currency": product.get("price_currency") or [],
        "availability": product.get("availability") or [],
        "variants": product.get("variants") or [],
        "ratings": product.get("ratings") or [],
        "shipping": bool(product.get("shipping")),
        "returns": bool(product.get("returns")),
    }


def _parity_text(facts: dict) -> str:
    headings = facts.get("headings") or {}
    visible = " ".join(
        [str(facts.get("title") or "")]
        + [str(value) for value in (headings.get("h1_texts") or [])]
        + [str((facts.get("body") or {}).get("text") or "")]
    )
    return re.sub(PRODUCT_PARITY_NORMALIZATION_PATTERN, "", visible.lower())


def _check_product_visible_schema_parity(facts: dict) -> tuple[str, dict]:
    """Compare only populated Product claims with persisted visible facts."""
    product = _product_block(facts)
    if product is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_product_schema"}
    visible = _parity_text(facts)
    checks: list[dict[str, object]] = []
    for parity_field in PRODUCT_PARITY_FIELDS:
        values = (
            product.get("name") or []
            if parity_field == "name"
            else product.get(PRODUCT_PARITY_SCHEMA_FACT_KEYS[parity_field]) or []
        )
        for value in values:
            normalized = re.sub(
                PRODUCT_PARITY_NORMALIZATION_PATTERN, "", str(value).lower()
            )
            if not normalized:
                continue
            comparable = re.sub(
                PRODUCT_PARITY_NORMALIZATION_PATTERN,
                "",
                str(value).rsplit(PRODUCT_SCHEMA_URI_SEPARATOR, 1)[-1].lower(),
            )
            checks.append(
                {
                    "field": parity_field,
                    "schema_value": str(value)[:256],
                    "visible_match": normalized in visible or comparable in visible,
                }
            )
    if not checks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_comparable_product_claims"}
    mismatches = [check for check in checks if not check["visible_match"]]
    return _pass_fail(not mismatches), {
        "checked_claim_count": len(checks),
        "mismatch_count": len(mismatches),
        "checks": checks,
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
    ratio = float(facts.get("question_heading_ratio", 0.0) or 0.0)
    return _pass_fail(ratio > QUESTION_HEADINGS_MIN_RATIO), {
        "question_heading_ratio": ratio,
        "minimum_ratio": QUESTION_HEADINGS_MIN_RATIO,
    }


def _server_render_signals(facts: dict) -> tuple[bool, dict]:
    """``(is_js_shell, evidence)`` for the server-rendered-content signal.

    Shared by ``_check_server_rendered_content`` (which reports it) and
    ``_applicability`` (which uses it to skip the rules that read content this
    page never delivered). One definition so the HIGH finding and the
    not-applicable rules can never disagree about whether a page is a shell.
    """
    body = facts.get("body") or {}
    word_count = int(body.get("word_count", 0) or 0)
    text_chars = len(str(body.get("text") or ""))
    inline_script_chars = int(facts.get("inline_script_chars", 0) or 0)
    # A page is a shell only when it is BOTH text-thin AND script-dominated:
    # the signature of a JS shell whose content never made it into the HTML.
    is_shell = (
        word_count < SERVER_RENDERED_MIN_WORDS and inline_script_chars > text_chars
    )
    return is_shell, {
        "word_count": word_count,
        "minimum_words": SERVER_RENDERED_MIN_WORDS,
        "body_text_chars": text_chars,
        "inline_script_chars": inline_script_chars,
    }


def _check_server_rendered_content(facts: dict) -> tuple[str, dict]:
    is_shell, evidence = _server_render_signals(facts)
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
    "aeo.schema_expected_for_type": _check_schema_expected_for_type,
    "aeo.schema_required_valid": _check_schema_required_valid,
    "aeo.schema_recommended_present": _check_schema_recommended_present,
    "aeo.schema_matches_content": _check_schema_matches_content,
    "aeo.author_present": _check_author_present,
    "aeo.date_present": _check_date_present,
    "aeo.outbound_citations": _check_outbound_citations,
    "aeo.organization_identity": _check_organization_identity,
    "aeo.answer_first": _check_answer_first,
    "aeo.question_headings": _check_question_headings,
    "aeo.server_rendered_content": _check_server_rendered_content,
    "aeo.no_expand_gating": _check_no_expand_gating,
    "aeo.product_offer_details": _check_product_offer_details,
    "aeo.product_visible_schema_parity": _check_product_visible_schema_parity,
}


def _observed_content(facts: dict) -> tuple[bool, str]:
    """Content-reading rules need content we actually RECEIVED.

    On a client-rendered shell the body is empty, so asserting "missing H1",
    "thin content" or "no outbound citations" would be reporting the absence of
    something we never had a chance to see — six derived findings, each scoring
    against the page, for one real problem. ``aeo.server_rendered_content``
    owns that problem and stays applicable (it is ``has_html``), so the shell is
    still reported once, at HIGH, with its remediation.
    """
    if not facts.get("has_html"):
        return False, "no_html"
    is_shell, _evidence = _server_render_signals(facts)
    return not is_shell, "content_not_server_rendered"


def _page_kind_scope(key: str, prefix: str, facts: dict) -> tuple[bool, str]:
    """``<prefix><type>[|<type>...]`` resolved against ``facts["page_kind"]``.

    The token names every type the check is MEANT for, so a product page is
    never asked for an author byline and an FAQ is never asked for
    Product/offers markup. An absent or unknown page type is inapplicable
    (fail-closed) — we do not guess which checklist a page we could not
    classify should answer for.
    """
    profile = _profile_for(facts)
    if profile is None:
        return False, "other_page_kind"
    allowed = {token for token in key[len(prefix) :].split("|") if token}
    return profile.page_kind in allowed, "other_page_kind"


def _applicability(rule: SiteHealthRule, facts: dict) -> tuple[bool, str]:
    """``(applicable, skip_reason)`` for one rule against ``facts``.

    The reason is carried into the NOT_APPLICABLE evidence so a skipped rule
    can explain itself. A bare ``not_applicable`` is indistinguishable from a
    pass in the UI, which matters most for the shell case: the user needs to
    read "we could not see this page's content", not silence.
    """
    key = (rule.applicability_key or "always").strip().lower()
    if key == "always":
        return True, ""
    if key == "has_html":
        return bool(facts.get("has_html")), "no_html"
    if key == APPLICABILITY_OBSERVED_CONTENT:
        return _observed_content(facts)
    if key.startswith(PAGE_KIND_CONTENT_APPLICABILITY_PREFIX):
        # Page-kind scope AND the shell guard. Order matters only for the skip
        # reason: an article we could not render should say "we could not see
        # this page's content", not "wrong page kind".
        applies, reason = _page_kind_scope(
            key, PAGE_KIND_CONTENT_APPLICABILITY_PREFIX, facts
        )
        if not applies:
            return False, reason
        return _observed_content(facts)
    if key.startswith(PAGE_KIND_APPLICABILITY_PREFIX):
        return _page_kind_scope(key, PAGE_KIND_APPLICABILITY_PREFIX, facts)
    if key == APPLICABILITY_SITE_ROOT:
        # Site-level rules apply only inside the crawl root's own analysis,
        # where the worker injected facts["site"] from the crawl's
        # site_facts (spec §5.3 — exactly once per crawl).
        return facts.get("site") is not None, "not_site_root"
    if key == APPLICABILITY_CRAWL_FINALIZE:
        # Never applicable in the per-page pass: the finalize-writer owns
        # these rows (single-writer per rule scope) and the analyze writer
        # filters them out before persisting.
        return False, "crawl_finalize_scope"
    # Unknown applicability key: treat as inapplicable (fail-closed).
    return False, "unknown_applicability"


def _weight_for(rule: SiteHealthRule, facts: dict) -> float:
    """The rule's weight, with any per-(rule_id, page_kind) config override.

    Resolved at evaluation time from ``PAGE_KIND_PROFILES`` so the emitted
    ``RuleEvaluation`` carries exactly the weight scoring will credit.
    """
    profile = _profile_for(facts)
    if profile is not None:
        override = profile.rule_weight_overrides.get(rule.rule_id)
        if override is not None:
            return float(override)
    return float(rule.weight)


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
        weight=_weight_for(rule, facts),
        remediation=rule.remediation,
    )
    applicable, skip_reason = _applicability(rule, facts)
    if not applicable:
        return RuleEvaluation(
            outcome=RULE_OUTCOME_NOT_APPLICABLE,
            evidence={"reason": skip_reason or "not_applicable"},
            **base,
        )
    check = _CHECKS.get(rule.rule_id)
    if check is None:
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": "no_check_mapped"},
            **base,
        )
    try:
        outcome, evidence = check(facts)
    except Exception as exc:  # a broken check is ERROR, never a crash
        return RuleEvaluation(
            outcome=RULE_OUTCOME_ERROR,
            evidence={"error": f"{type(exc).__name__}: {exc}"[:512]},
            **base,
        )
    return RuleEvaluation(outcome=outcome, evidence=evidence, **base)


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
