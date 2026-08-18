# Cross-page / cross-time rule evaluation (v2 P2 — spec §5.3, crawl_finalize
# scope).
#
# The three ``crawl_finalize`` rules cannot be evaluated at per-page time:
# ``technical.broken_internal_link`` needs the link_check probe results (which
# the analyze task itself enqueues), ``technical.sitemap_orphan`` needs the
# complete discovered-vs-sitemap set, and ``technical.hreflang_conflict``
# needs counterpart pages' facts. They run as a SECOND evaluation pass inside
# the worker's ``_reconcile_crawl_status`` (after analysis terminalization,
# before the snapshot), with the finalize-writer as the sole owner of their
# rows (single-writer per rule scope; the analyze writer never persists
# placeholder rows for them).
#
# PURE + deterministic (no I/O, no ORM — invariant 9): each evaluator takes
# pre-normalized, bounded inputs the WORKER assembled from persisted rows
# (URL normalization happens in the worker via ``canonical_identity`` — this
# analysis layer never imports the domain layer). Outcomes reuse the
# ``RuleEvaluation`` value type; weights come from the config catalog (0.0 —
# these rules produce issues, never score denominators).
from __future__ import annotations

from app.analysis.site_health.rules import RuleEvaluation, rule_for
from app.core.config import site_health_acquisition as site_health_config
from app.core.config.site_health_acquisition import (
    SITE_HEALTH_MAX_URL_CHARS,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_rules import (
    SiteHealthRule,
)

# Evidence lists are bounded so a pathological crawl can never bloat a row.
_MAX_EVIDENCE_URLS = site_health_config.SITE_HEALTH_MAX_EVIDENCE_URLS


def _bounded_urls(urls: list[str]) -> list[str]:
    """The bounded, JSON-safe evidence form of a URL list."""
    return [str(url)[:SITE_HEALTH_MAX_URL_CHARS] for url in urls[:_MAX_EVIDENCE_URLS]]


def _catalog_rule(rule_id: str) -> SiteHealthRule:
    """The catalog entry for a finalize rule (a missing entry is a hard bug)."""
    rule = rule_for(rule_id)
    if rule is None:
        raise RuntimeError(f"crawl_finalize rule missing from catalog: {rule_id!r}")
    return rule


def _evaluation(rule: SiteHealthRule, outcome: str, evidence: dict) -> RuleEvaluation:
    """Build the finalize-pass ``RuleEvaluation`` for one catalog rule."""
    return RuleEvaluation(
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        dimension=rule.dimension,
        category=rule.category,
        severity=rule.severity,
        finding_class=rule.finding_class,
        weight=float(rule.weight),
        outcome=outcome,
        evidence=evidence,
        description=rule.description,
        remediation=rule.remediation,
    )


def evaluate_broken_internal_link(
    *, checked_count: int, broken_urls: list[str]
) -> RuleEvaluation:
    """``technical.broken_internal_link`` for ONE analysis's link probes.

    ``checked_count`` is the number of internal link targets probed for the
    page (all link kinds count as targets); ``broken_urls`` the bounded set
    that probed unreachable. Not applicable when the page references no
    internal targets at all (nothing was checked).
    """
    rule = _catalog_rule("technical.broken_internal_link")
    if checked_count <= 0:
        return _evaluation(
            rule, RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_internal_links"}
        )
    outcome = RULE_OUTCOME_FAIL if broken_urls else RULE_OUTCOME_PASS
    return _evaluation(
        rule,
        outcome,
        {
            "checked_count": int(checked_count),
            "broken_count": len(broken_urls),
            "broken_urls": _bounded_urls(broken_urls),
        },
    )


def evaluate_sitemap_orphan(
    *, sitemap_url_count: int, orphan_urls: list[str]
) -> RuleEvaluation:
    """``technical.sitemap_orphan`` for the whole crawl (root-anchored).

    ``sitemap_url_count`` is the number of sitemap-sourced URLs the crawl
    admitted; ``orphan_urls`` the bounded subset never observed through
    internal links. Not applicable when the crawl ingested no sitemap URLs
    (Free sample crawls never ingest sitemaps; a site without a sitemap has
    nothing to orphan).
    """
    rule = _catalog_rule("technical.sitemap_orphan")
    if sitemap_url_count <= 0:
        return _evaluation(rule, RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_sitemap"})
    outcome = RULE_OUTCOME_FAIL if orphan_urls else RULE_OUTCOME_PASS
    return _evaluation(
        rule,
        outcome,
        {
            "sitemap_url_count": int(sitemap_url_count),
            "orphan_count": len(orphan_urls),
            "orphan_urls": _bounded_urls(orphan_urls),
        },
    )


def evaluate_hreflang_conflict(
    *,
    alternate_count: int,
    checked_count: int,
    unchecked_count: int,
    missing_return_tags: list[str],
) -> RuleEvaluation:
    """``technical.hreflang_conflict`` for ONE analysis's hreflang cluster.

    ``alternate_count`` is the page's declared hreflang alternates;
    ``checked_count`` how many of those targets were themselves analyzed in
    this crawl (only they can be verified); ``unchecked_count`` the rest;
    ``missing_return_tags`` the bounded verified failures (alternates whose
    target page does not link back). Not applicable when the page declares no
    hreflang alternates, or when none of its alternates were analyzed
    (nothing could be verified — absence fabricates nothing).
    """
    rule = _catalog_rule("technical.hreflang_conflict")
    if alternate_count <= 0:
        return _evaluation(rule, RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_hreflang"})
    if checked_count <= 0:
        return _evaluation(
            rule,
            RULE_OUTCOME_NOT_APPLICABLE,
            {
                "reason": "no_checkable_alternates",
                "alternate_count": int(alternate_count),
                "unchecked_count": int(unchecked_count),
            },
        )
    outcome = RULE_OUTCOME_FAIL if missing_return_tags else RULE_OUTCOME_PASS
    return _evaluation(
        rule,
        outcome,
        {
            "alternate_count": int(alternate_count),
            "checked_count": int(checked_count),
            "unchecked_count": int(unchecked_count),
            "missing_return_tags": _bounded_urls(missing_return_tags),
        },
    )
