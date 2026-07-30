"""Pure Site Health presentation: ORM rows -> the strict wire contracts.

Split out of the 2,000-line service module (plan P3.2/P3.3). Everything here is
a pure function over already-loaded rows — no session, no IO — which is exactly
why it belongs in one place: these are the projection rules the plan pins down
(model aliases, Free count redaction, the ``blocked`` vs ``error`` split,
current-catalog titles), and being pure they are directly unit-testable instead
of only reachable through a component test with a database.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.core.config.site_health import (
    PAGE_ANALYSIS_STATUS_COMPLETED,
    PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    POLICY_BLOCKING_ERROR_CODES,
    SCORING_VERSION,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_INFO,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
    SITE_HEALTH_RULES_BY_ID,
    capability_profile,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
)

# Deterministic severity ordering (critical worst). Used for the grouped-issue
# keyset sort and the issues summary rollup.
_SEVERITY_RANK: dict[str, int] = {
    SEVERITY_CRITICAL: 0,
    SEVERITY_HIGH: 1,
    SEVERITY_MEDIUM: 2,
    SEVERITY_LOW: 3,
    SEVERITY_INFO: 4,
}
# Rank of a severity token the catalog no longer defines: sorts after every
# known severity (never silently ahead of a critical row).
_UNRANKED_SEVERITY = 99
_SEVERITY_ORDER = (
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    SEVERITY_INFO,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


# Rules whose single condition covers OPPOSITE failures need the persisted
# evidence to say which one happened. Each entry maps a rule to the function
# that picks its ``display_label_variants`` key; the copy itself stays in the
# catalog (invariant 1) — only the choice lives here, because only the
# projection has the evidence in hand.
def _single_h1_variant(evidence: dict) -> str:
    """``technical.single_h1`` fails on ``h1_count != 1`` — say which way.

    Returns ``""`` for the PASSING count. Evaluations are projected for every
    outcome, not just failures, so a selector that split the world into
    "none"/"multiple" labelled a healthy one-H1 page "More than one H1
    heading". No variant means the neutral catalog title stands.
    """
    count = int(evidence.get("h1_count", 0) or 0)
    if count == 0:
        return "none"
    if count > 1:
        return "multiple"
    return ""


_LABEL_VARIANT_KEY: dict[str, Callable[[dict], str]] = {
    "technical.single_h1": _single_h1_variant,
}


def display_label_for(rule_id: str, evidence: dict | None = None) -> str:
    """Current human-facing catalog title for a rule id (unknown -> rule_id).

    With ``evidence``, a rule that declares ``display_label_variants`` resolves
    to the variant its evidence selects, so a row reads "Missing H1 heading"
    rather than the both-cases-at-once "Missing or duplicate H1". Without
    evidence (or with an unmatched variant) the plain catalog title stands.
    """
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    if rule is None:
        return rule_id
    selector = _LABEL_VARIANT_KEY.get(rule_id)
    if evidence and selector is not None:
        try:
            key = selector(evidence)
        except (ValueError, TypeError):
            # Malformed persisted evidence (a non-numeric ``h1_count`` from an
            # older writer or a hand-edited row) must not decide a LABEL and
            # must never fail the request: the selectors coerce evidence, and
            # `int("abc")` raised straight out of a page-detail projection as a
            # 500. An unreadable variant key is simply no variant.
            key = ""
        variant = rule.display_label_variants.get(key)
        if variant:
            return variant
    return rule.display_label


# =========================================================================
# Crawl projection (model aliases -> strict contract)
# =========================================================================
def _crawl_count_disclosure(crawl: SiteCrawl) -> bool:
    """Whether this crawl may disclose total/discovered counts (Free = never).

    Reads the frozen ``configuration.count_disclosure`` snapshot first (so a
    later capability change never retroactively reveals a sample crawl's
    counts); falls back to the capability profile derived from the frozen
    ``capability`` key.
    """
    config = crawl.configuration or {}
    if "count_disclosure" in config:
        return bool(config.get("count_disclosure"))
    capability = str(config.get("capability") or "")
    return capability_profile(capability).count_disclosure


def _score_summary(crawl: SiteCrawl) -> dict | None:
    """Project the worker-written ``score_summary`` into the strict shape."""
    summary = crawl.score_summary or None
    if not summary:
        return None
    # v2 P1 per-page-type breakdown; absent on pre-P1 summaries (empty map).
    by_page_type: dict[str, dict] = {}
    for page_type, values in (summary.get("by_page_type") or {}).items():
        values = values or {}
        by_page_type[str(page_type)] = {
            "analyzed_count": int(values.get("analyzed_count", 0) or 0),
            "technical_score": values.get("technical_score"),
            "aeo_score": values.get("aeo_score"),
            "overall_score": values.get("overall_score"),
        }
    return {
        "overall_score": summary.get("overall_score"),
        "technical_score": summary.get("technical_score"),
        "aeo_score": summary.get("aeo_score"),
        "selected_count": int(summary.get("selected_count", 0) or 0),
        "analyzed_count": int(
            summary.get("analyzed_count", summary.get("analyzed_url_count", 0)) or 0
        ),
        "issue_count": int(summary.get("issue_count", 0) or 0),
        "scoring_version": str(
            summary.get("scoring_version") or crawl.scoring_version or SCORING_VERSION
        ),
        "by_page_type": by_page_type,
    }


def project_crawl(crawl: SiteCrawl) -> dict:
    """Project a ``SiteCrawl`` to the strict crawl contract (with redaction).

    Aliases model columns to the contract (``random_seed -> seed``,
    ``admitted_url_count -> visible_url_count``, ``analyzed_url_count ->
    analyzed_count``, ``failed_url_count -> failed_count``,
    ``rule_catalog_version -> rule_version``). For a Free (non-disclosing)
    crawl the discovered/total/has-more fields are ``None`` so no full-site
    count ever leaks.
    """
    disclose = _crawl_count_disclosure(crawl)
    return {
        "id": crawl.id,
        "workspace_id": crawl.workspace_id,
        "project_id": crawl.project_id,
        "profile_id": crawl.profile_id,
        "status": crawl.status,
        "discovery_status": crawl.discovery_status,
        "analysis_status": crawl.analysis_status,
        "root_url": crawl.root_url,
        "sample_mode": crawl.sample_mode,
        "seed": crawl.random_seed,
        "inventory_complete": crawl.inventory_complete,
        "visible_url_count": int(crawl.admitted_url_count or 0),
        "analyzed_count": int(crawl.analyzed_url_count or 0),
        "failed_count": int(crawl.failed_url_count or 0),
        "discovered_count": (
            int(crawl.discovered_url_count or 0) if disclose else None
        ),
        "total_url_count": (
            int(crawl.discovered_url_count or 0)
            if (disclose and crawl.inventory_complete)
            else None
        ),
        "has_more_site_urls": ((not crawl.inventory_complete) if disclose else None),
        "score_summary": _score_summary(crawl),
        # v2 P2: bounded site-level facts (robots AI-crawler stance, llms.txt,
        # sitemap files). Contains no discovered totals — safe for Free.
        "site_facts": crawl.site_facts or None,
        "extractor_version": crawl.extractor_version,
        "analyzer_version": crawl.analyzer_version,
        "rule_version": crawl.rule_catalog_version,
        "scoring_version": crawl.scoring_version,
        "error_message": crawl.error_message or "",
        "created_at": _iso(crawl.created_at),
        "updated_at": _iso(crawl.updated_at),
        "started_at": _iso(crawl.started_at),
        "completed_at": _iso(crawl.completed_at),
    }


# =========================================================================
# Presentation status derivation (plan projection rules)
# =========================================================================
def presentation_status_for(
    *,
    analysis: SitePageAnalysis | None,
    monitored: bool,
    latest_analyze_task: SiteCrawlTask | None,
) -> tuple[str, str]:
    """Derive the mockup-facing ``(analysis_status, error_code)`` for a URL.

    Rules (plan §Projection):
      - a completed analysis -> its persisted status (``completed`` /
        ``partially_completed``);
      - no analysis + a cancelled latest analyze task -> ``cancelled`` (with
        its error code): a run the user stopped, or one the live
        membership/entitlement guard denied, is not an error;
      - no analysis + the latest analyze task ended under a policy denial code
        (robots/SSRF) -> ``blocked`` (with the error code);
      - no analysis + any other terminal-unsuccessful analyze task -> ``error``;
      - an in-flight analyze task -> ``pending`` / ``running``;
      - a monitored URL with no analyze task yet -> ``pending``;
      - an un-monitored URL with nothing -> ``not_selected``.
    ``failed`` is never surfaced as page copy (it maps to ``error``/``blocked``).
    """
    if analysis is not None and analysis.status in (
        PAGE_ANALYSIS_STATUS_COMPLETED,
        PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    ):
        return analysis.status, ""

    task = latest_analyze_task
    if task is not None:
        if task.status == TASK_STATUS_CANCELLED:
            return "cancelled", task.error_code or ""
        if task.status == TASK_STATUS_FAILED:
            code = task.error_code or ""
            if code in POLICY_BLOCKING_ERROR_CODES:
                return "blocked", code
            return "error", code
        if task.status == TASK_STATUS_SUCCEEDED:
            # Succeeded fetch but no completed analysis row yet: still resolving.
            return "pending", ""
        # queued / leased / running / retry_wait -> in-flight.
        if task.status in (TASK_STATUS_RUNNING, TASK_STATUS_LEASED):
            return "running", ""
        return "pending", ""

    if monitored:
        return "pending", ""
    return "not_selected", ""


# =========================================================================
# Inventory (keyset (normalized_url, id) over SiteUrl)
# =========================================================================
def _page_type_matches(analysis: SitePageAnalysis | None, wanted: str | None) -> bool:
    """The v2 P1 page_type filter predicate (inventory + pages share it).

    An unfiltered request (``wanted is None``) matches everything; a filtered
    one requires a classified analysis of exactly that type — URLs without
    an analysis never match, and an unknown value simply matches nothing
    (the same ignore-unknown convention as the other filters).
    """
    if wanted is None:
        return True
    return analysis is not None and analysis.page_type == wanted


# =========================================================================
# Pages (CursorPage<PageSummary> ordered (normalized_url, site_url_id))
# =========================================================================
# `error_or_blocked` is accepted as a combined presentation filter (mockup 710
# groups the two terminal-unsuccessful states).
_ERROR_OR_BLOCKED = "error_or_blocked"


def _matches_page_status(pres_status: str, wanted: str | None) -> bool:
    if wanted is None:
        return True
    if wanted == _ERROR_OR_BLOCKED:
        return pres_status in ("error", "blocked")
    return pres_status == wanted


# =========================================================================
# Page detail (persisted facts/delivery/scores/issues/provenance; no network)
# =========================================================================
def _page_facts(facts: dict | None) -> dict:
    facts = facts or {}
    robots = facts.get("robots") or {}
    directives: list[str] = []
    if robots.get("noindex"):
        directives.append("noindex")
    if robots.get("nofollow"):
        directives.append("nofollow")
    headings = facts.get("headings") or {}
    images = facts.get("images") or {}
    body = facts.get("body") or {}
    structured = facts.get("structured_data") or {}
    links = facts.get("links") or {}
    anchors = links.get("anchors") or []
    internal = sum(1 for a in anchors if a.get("is_internal"))
    external = len(anchors) - internal
    heading_counts = headings.get("counts") or {}
    heading_total = sum(int(v or 0) for v in heading_counts.values())
    return {
        "title": facts.get("title") or None,
        "meta_description": facts.get("meta_description") or None,
        "canonical_url": facts.get("canonical_url") or None,
        "robots_directives": directives,
        "h1_count": int(headings.get("h1_count", 0) or 0),
        "heading_count": int(heading_total),
        "image_count": int(images.get("count", 0) or 0),
        "image_missing_alt_count": int(images.get("missing_alt", 0) or 0),
        "word_count": int(body.get("word_count", 0) or 0),
        "internal_link_count": int(internal),
        "external_link_count": int(external),
        "structured_data_types": list(structured.get("types") or []),
    }


def _delivery_facts(facts: dict | None, *, html_bytes: int | None) -> dict:
    facts = facts or {}
    delivery = facts.get("delivery") or {}
    blocking = facts.get("blocking_resources") or {}
    compression = delivery.get("content_encoding") or None
    return {
        "field_cwv_available": False,
        "status_code": delivery.get("status_code"),
        "ttfb_ms": delivery.get("ttfb_ms"),
        "wire_bytes": delivery.get("wire_bytes"),
        "decoded_bytes": delivery.get("decoded_bytes"),
        "html_bytes": html_bytes,
        "http_version": delivery.get("http_version") or None,
        "compression": compression,
        "cache_control": (delivery.get("cache_control") or None),
        "blocking_resource_count": (
            int(blocking.get("total", 0)) if blocking else None
        ),
    }


# Bound the exact evidence/link projections so a pathological artifact can
# never balloon a detail response (plan §Projection: bounded evidence/links).
_MAX_EVALUATIONS = 200
_MAX_LINK_REFERENCES = 200


def _evaluation_row(evaluation: SiteRuleEvaluation) -> dict:
    """Project one persisted rule evaluation with the CURRENT display label."""
    return {
        "id": evaluation.id,
        "rule_id": evaluation.rule_id,
        "title": display_label_for(evaluation.rule_id, evaluation.evidence),
        "dimension": evaluation.dimension,
        "category": evaluation.category,
        "severity": evaluation.severity,
        "outcome": evaluation.outcome,
        "weight": evaluation.weight,
        "evidence": evaluation.evidence or {},
        "analyzer_version": evaluation.analyzer_version,
        "rule_version": evaluation.rule_version,
        "created_at": _iso(evaluation.created_at),
    }


def _link_reference_row(link: SiteLinkReference) -> dict:
    """Project one deduplicated link reference (target status where known)."""
    return {
        "id": link.id,
        "kind": link.kind,
        "target_url": link.target_url,
        "is_internal": link.is_internal,
        "rel": link.rel or "",
        "anchor_text": link.anchor_text or "",
        "target_artifact_id": link.target_artifact_id,
    }


def _issue_row(issue: SiteIssue, affected_count: int) -> dict:
    return {
        "id": issue.id,
        "crawl_id": issue.crawl_id,
        "rule_id": issue.rule_id,
        "dimension": issue.dimension,
        "category": issue.category,
        "severity": issue.severity,
        # Sole caller is the per-URL page detail (``affected_count`` is always
        # 1), so this row describes ONE occurrence and can name which side of
        # a two-sided rule fired.
        "title": display_label_for(issue.rule_id, issue.evidence),
        "remediation": issue.remediation or "",
        "affected_url_count": affected_count,
        "analyzer_version": issue.analyzer_version,
        "rule_version": issue.rule_version,
        "created_at": _iso(issue.created_at),
    }
