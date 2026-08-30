# Cross-page / cross-time rule evaluation (v2 P2 — spec §5.3, crawl_finalize
# scope).
#
# The two ``crawl_finalize`` rules cannot be evaluated at per-page time:
# ``technical.sitemap_orphan`` needs the complete discovered-vs-sitemap set,
# and ``technical.hreflang_conflict``
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
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    RULE_OUTCOME_UNAVAILABLE,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_link_metrics import COVERAGE_STATE_COMPLETE
from app.core.config.site_health_rule_types import SiteHealthRule

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
    expected = bool(rule.score_roles) and outcome != RULE_OUTCOME_NOT_APPLICABLE
    return RuleEvaluation(
        rule_id=rule.rule_id,
        rule_version=rule.rule_version,
        dimension=rule.dimension,
        category=rule.category,
        severity=rule.severity,
        finding_class=rule.finding_class,
        scope=rule.scope,
        weight=float(rule.weight),
        outcome=outcome,
        evidence=evidence,
        description=rule.description,
        remediation=rule.remediation,
        display_applicability=outcome != RULE_OUTCOME_NOT_APPLICABLE,
        score_applicability=expected,
        expected_profile_membership=expected,
        reason_code=str(evidence.get("reason") or ""),
        score_roles=rule.score_roles if expected else (),
        checkpoint_family=rule.checkpoint_family,
        readiness_dimension=rule.readiness_dimension,
        readiness_weight=rule.readiness_weight,
    )


def _entity_set_evaluation(
    rule_id: str,
    *,
    total_count: int,
    checked_count: int,
    failing_urls: list[str],
) -> RuleEvaluation:
    rule = _catalog_rule(rule_id)
    total = max(0, int(total_count))
    checked = min(total, max(0, int(checked_count)))
    failures = min(checked, len(failing_urls))
    if total == 0:
        return _evaluation(
            rule,
            RULE_OUTCOME_SATISFIED,
            {
                "total_count": 0,
                "checked_count": 0,
                "normalized_score": 1.0,
                "normalized_coverage": 1.0,
            },
        )
    if checked == 0:
        return _evaluation(
            rule,
            RULE_OUTCOME_UNKNOWN,
            {
                "reason": "insufficient_evidence",
                "total_count": total,
                "checked_count": 0,
            },
        )
    score = (checked - failures) / checked
    coverage = checked / total
    outcome = (
        RULE_OUTCOME_SATISFIED
        if score == 1.0
        else RULE_OUTCOME_MISSING
        if score == 0.0
        else RULE_OUTCOME_PARTIAL
    )
    return _evaluation(
        rule,
        outcome,
        {
            "total_count": total,
            "checked_count": checked,
            "failure_count": failures,
            "failing_urls": _bounded_urls(list(dict.fromkeys(failing_urls))),
            "normalized_score": score,
            "normalized_coverage": coverage,
        },
    )


def evaluate_broken_internal_links(
    *, total_count: int, checked_count: int, broken_urls: list[str]
) -> RuleEvaluation:
    return _entity_set_evaluation(
        "technical.broken_internal_link",
        total_count=total_count,
        checked_count=checked_count,
        failing_urls=broken_urls,
    )


def evaluate_sitemap_url_unreachable(
    *, total_count: int, checked_count: int, unreachable_urls: list[str]
) -> RuleEvaluation:
    if total_count <= 0:
        return _evaluation(
            _catalog_rule("technical.sitemap_url_unreachable"),
            RULE_OUTCOME_NOT_APPLICABLE,
            {"reason": "no_sitemap"},
        )
    return _entity_set_evaluation(
        "technical.sitemap_url_unreachable",
        total_count=total_count,
        checked_count=checked_count,
        failing_urls=unreachable_urls,
    )


def evaluate_canonical_resolvable(
    *, target_url: str, checked: bool, status_code: int | None, redirected: bool
) -> RuleEvaluation:
    rule = _catalog_rule("technical.canonical_resolvable")
    if not checked or status_code is None:
        return _evaluation(
            rule,
            RULE_OUTCOME_UNKNOWN,
            {"reason": "insufficient_evidence", "target_url": target_url},
        )
    healthy = status_code < 400 and not redirected
    return _evaluation(
        rule,
        RULE_OUTCOME_SATISFIED if healthy else RULE_OUTCOME_MISSING,
        {
            "target_url": target_url,
            "status_code": status_code,
            "redirected": redirected,
        },
    )


def evaluate_sitemap_orphan(
    *, sitemap_url_count: int, orphan_urls: list[str], coverage_state: str
) -> RuleEvaluation:
    """``technical.sitemap_orphan`` for the whole crawl (root-anchored).

    ``sitemap_url_count`` is the number of sitemap-sourced URLs the crawl
    admitted; ``orphan_urls`` the bounded subset never observed through
    internal links. Unavailable when crawl coverage is incomplete. Not
    applicable when the crawl ingested no sitemap URLs (Free sample crawls
    never ingest sitemaps; a site without a sitemap has nothing to orphan).
    """
    rule = _catalog_rule("technical.sitemap_orphan")
    if coverage_state != COVERAGE_STATE_COMPLETE:
        return _evaluation(
            rule,
            RULE_OUTCOME_UNAVAILABLE,
            {"reason": "coverage_not_complete", "coverage_state": coverage_state},
        )
    if sitemap_url_count <= 0:
        return _evaluation(rule, RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_sitemap"})
    outcome = RULE_OUTCOME_MISSING if orphan_urls else RULE_OUTCOME_SATISFIED
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
    hreflang alternates. Unavailable when none of its alternates were analyzed
    (nothing could be verified — absence fabricates nothing).
    """
    rule = _catalog_rule("technical.hreflang_conflict")
    if alternate_count <= 0:
        return _evaluation(rule, RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_hreflang"})
    if checked_count <= 0:
        return _evaluation(
            rule,
            RULE_OUTCOME_UNAVAILABLE,
            {
                "reason": "no_checkable_alternates",
                "alternate_count": int(alternate_count),
                "unchecked_count": int(unchecked_count),
            },
        )
    outcome = RULE_OUTCOME_MISSING if missing_return_tags else RULE_OUTCOME_SATISFIED
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
