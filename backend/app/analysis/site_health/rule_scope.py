"""Applicability policy for deterministic Site Health rules."""

from __future__ import annotations

from typing import Any

from app.core.config.site_health_contracts import (
    APPLICABILITY_CRAWL_FINALIZE,
    APPLICABILITY_OBSERVED_CONTENT,
    APPLICABILITY_SITE_ROOT,
    SKIP_REASON_LOW_CONFIDENCE_KIND,
)
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_ADVISORY,
    KIND_EVIDENCE_EXPECTATION,
    SiteHealthRule,
)
from app.core.config.site_health_rules import SERVER_RENDERED_MIN_WORDS
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_APPLICABILITY_PREFIX,
    PAGE_KIND_CONTENT_APPLICABILITY_PREFIX,
    PAGE_KIND_HTML_APPLICABILITY_PREFIX,
    PAGE_KIND_PROFILES,
    PAGE_KIND_TIER_STRUCTURAL,
    PageKindProfile,
)


def profile_for(facts: dict) -> PageKindProfile | None:
    page_kind = str(facts.get("page_kind") or "").strip().lower()
    return PAGE_KIND_PROFILES.get(page_kind)


def observed_traits(facts: dict) -> set[str]:
    observed = facts.get("page_traits")
    if isinstance(observed, list | tuple):
        return {str(trait) for trait in observed}
    return set()


def server_render_signals(facts: dict) -> tuple[bool, dict[str, Any]]:
    """Return the JS-shell verdict and the evidence that produced it."""
    body = facts.get("body") or {}
    word_count = int(body.get("word_count", 0) or 0)
    text_chars = len(str(body.get("text") or ""))
    inline_script_chars = int(facts.get("inline_script_chars", 0) or 0)
    is_shell = (
        word_count < SERVER_RENDERED_MIN_WORDS and inline_script_chars > text_chars
    )
    return is_shell, {
        "word_count": word_count,
        "minimum_words": SERVER_RENDERED_MIN_WORDS,
        "body_text_chars": text_chars,
        "inline_script_chars": inline_script_chars,
    }


def _observed_content(facts: dict) -> tuple[bool, str]:
    if not facts.get("has_html"):
        return False, "no_html"
    is_shell, _evidence = server_render_signals(facts)
    return not is_shell, "content_not_server_rendered"


def _tokens(key: str, prefix: str) -> set[str]:
    return {token for token in key[len(prefix) :].split("|") if token}


def _page_kind_scope(key: str, prefix: str, facts: dict) -> tuple[bool, str]:
    profile = profile_for(facts)
    if profile is None:
        return False, "other_page_kind"
    return profile.page_kind in _tokens(key, prefix), "other_page_kind"


def _kind_expectation_allowed(rule: SiteHealthRule, facts: dict) -> tuple[bool, str]:
    if (
        rule.kind_evidence != KIND_EVIDENCE_EXPECTATION
        or rule.finding_class == FINDING_CLASS_ADVISORY
    ):
        return True, ""
    evidence = facts.get("page_kind_evidence")
    tier = str(evidence.get("tier") or "") if isinstance(evidence, dict) else ""
    if not tier or tier == PAGE_KIND_TIER_STRUCTURAL:
        return True, ""
    return False, SKIP_REASON_LOW_CONFIDENCE_KIND


def _kind_scoped(
    rule: SiteHealthRule,
    key: str,
    prefix: str,
    facts: dict,
    requirement: str,
) -> tuple[bool, str]:
    applies, reason = _page_kind_scope(key, prefix, facts)
    if not applies:
        return False, reason
    allowed, reason = _kind_expectation_allowed(rule, facts)
    if not allowed:
        return False, reason
    if requirement == "content":
        return _observed_content(facts)
    if requirement == "html":
        return bool(facts.get("has_html")), "no_html"
    return True, ""


def _prefixed_scope(
    rule: SiteHealthRule, key: str, facts: dict
) -> tuple[bool, str] | None:
    kind_scopes = (
        (PAGE_KIND_CONTENT_APPLICABILITY_PREFIX, "content"),
        (PAGE_KIND_HTML_APPLICABILITY_PREFIX, "html"),
        (PAGE_KIND_APPLICABILITY_PREFIX, ""),
    )
    for prefix, requirement in kind_scopes:
        if key.startswith(prefix):
            return _kind_scoped(rule, key, prefix, facts, requirement)
    return None


def applicability(rule: SiteHealthRule, facts: dict) -> tuple[bool, str]:
    """Return whether a rule applies and the persisted skip reason if not."""
    key = (rule.applicability_key or "always").strip().lower()
    if key == "always":
        return True, ""
    if key == "has_html":
        return bool(facts.get("has_html")), "no_html"
    if key == APPLICABILITY_OBSERVED_CONTENT:
        return _observed_content(facts)
    if scoped := _prefixed_scope(rule, key, facts):
        return scoped
    if key == APPLICABILITY_SITE_ROOT:
        return facts.get("site") is not None, "not_site_root"
    if key == APPLICABILITY_CRAWL_FINALIZE:
        return False, "crawl_finalize_scope"
    return False, "unknown_applicability"
