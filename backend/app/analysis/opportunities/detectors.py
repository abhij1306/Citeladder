# Opportunities deterministic detectors (pure — no DB, no I/O, invariants 7+9).
#
# Each detector is a pure function over typed, already-persisted evidence
# bundles (``VisibilityEvidence`` / ``SiteEvidence``) and returns
# ``DetectorHit`` projections. A hit carries the validated catalog
# ``rule_id``, the deterministic ``target_key`` identity, a JSON-ready
# evidence dict, the stringified source-row id lists (provenance, invariant
# 4), and the ``value_factor`` / ``gap_factor`` inputs the scoring formula
# turns into the priority. Detectors never score (``scoring.py`` owns the
# formula), never read the DB, and never call a provider or an LLM. A
# catalog-disabled rule is never emitted, even if a detector is invoked.
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.analysis.opportunities.scoring import (
    gap_factor_visibility,
    value_factor_for_intent,
)
from app.analysis.opportunities.source_patterns import (
    CitationEvidence,
    summarize_source_pattern,
)
from app.core.config.opportunities import (
    COMMERCE_GAP_FACTOR,
    COMMERCE_VALUE_FACTOR,
    OPPORTUNITY_RULES_BY_ID,
    SITE_GAP_FACTOR,
    SITE_ISSUE_TO_OPPORTUNITY_RULE_ID,
    SITE_VALUE_FACTOR,
    OpportunityRule,
)

# Catalog rule ids this module emits (validated by the catalog lookup itself).
RULE_BRAND_ABSENT = "brand_absent_high_value_prompt"
RULE_OWNED_PAGE_NOT_CITED = "owned_page_not_cited"
RULE_PRODUCT_NOT_MENTIONED = "product_not_mentioned"
RULE_CITED_ALTERNATIVES = "cited_alternatives_without_uploaded_presence"
RULE_CATALOG_FIELDS_MISSING = "catalog_fields_missing"


# =========================================================================
# Typed evidence bundles (frozen input projections)
# =========================================================================
@dataclass(frozen=True)
class AnalysisEvidence:
    """One persisted ``ResponseAnalysis`` reduced to its citation signals."""

    analysis_id: uuid.UUID
    prompt_index: int
    logical_engine: str
    # Owned-classified citations on this repetition.
    owned_citation_count: int
    # Competitor citation-or-mention names on this repetition (deduped later).
    competitor_names: tuple[str, ...]
    # The persisted citations behind this repetition, in ordinal order. Used
    # ONLY to describe the observed source pattern beside a gap — never to
    # change whether a rule fires. Defaults to empty so a caller that has no
    # citation rows (or predates them) still builds valid evidence.
    citations: tuple[CitationEvidence, ...] = ()


@dataclass(frozen=True)
class PromptSnapshotEvidence:
    """One frozen ``AuditPromptSnapshot`` (text/theme/intent + prompt link)."""

    prompt_index: int
    prompt_id: uuid.UUID | None
    text: str
    theme: str
    intent: str


@dataclass(frozen=True)
class VisibilityEvidence:
    """The visibility slice one audit offers the detectors."""

    audit_id: uuid.UUID
    analyses: tuple[AnalysisEvidence, ...]
    prompt_snapshots: tuple[PromptSnapshotEvidence, ...]
    owned_domains: tuple[str, ...]


@dataclass(frozen=True)
class SiteIssueEvidence:
    """One persisted ``SiteIssue`` for the selected crawl."""

    issue_id: uuid.UUID
    rule_id: str
    severity: str
    category: str
    site_url_id: uuid.UUID
    evidence: dict[str, Any] | None
    finding_class: str = "defect"


@dataclass(frozen=True)
class SiteUrlEvidence:
    """The ``site_url_id -> normalized_url`` identity map entry."""

    site_url_id: uuid.UUID
    normalized_url: str


@dataclass(frozen=True)
class SiteEvidence:
    """The Site Health slice one crawl offers the detectors."""

    crawl_id: uuid.UUID
    issues: tuple[SiteIssueEvidence, ...]
    urls: tuple[SiteUrlEvidence, ...]
    coverage: dict[str, Any]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ProductEntryEvidence:
    """One frozen catalog entry + its persisted aggregate for the audit.

    Identity (``name``/``sku``/``competitor_name``) comes from the audit's
    FROZEN catalog (``Audit.configuration``) so evidence survives later
    catalog edits (invariant 9); the metrics come from the persisted
    ``ProductMetricSnapshot`` rows (invariant 7). ``snapshot_id`` /
    ``source_analysis_ids`` are empty when no snapshot exists for the entry
    (never measured).
    """

    entry_id: str
    kind: str  # "product"
    name: str
    sku: str
    competitor_name: str
    mention_count: int
    sov_share: float
    price_mismatch_rate: float | None
    snapshot_id: uuid.UUID | None
    source_analysis_ids: tuple[str, ...]
    category: str = ""
    missing_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class CommerceEvidence:
    """The commerce slice one audit offers the detectors."""

    audit_id: uuid.UUID
    entries: tuple[ProductEntryEvidence, ...]
    category_citations: tuple[CategoryCitationEvidence, ...] = ()


@dataclass(frozen=True)
class CategoryCitationEvidence:
    category: str
    third_party_citation_count: int
    uploaded_destination_citation_count: int
    source_analysis_ids: tuple[str, ...]


@dataclass(frozen=True)
class DetectorHit:
    """One deterministic rule firing on one target (JSON-ready projection)."""

    rule_id: str
    target_key: str
    target_prompt_id: uuid.UUID | None
    target_url: str | None
    target_theme: str | None
    evidence: dict[str, Any]
    # Provenance (stringified UUIDs, invariant 4) — at least one populated.
    source_analysis_ids: tuple[str, ...]
    source_issue_ids: tuple[str, ...]
    source_metric_ids: tuple[str, ...]
    value_factor: float
    gap_factor: float


# =========================================================================
# Visibility detectors
# =========================================================================
def _prompt_target(
    *,
    audit_id: uuid.UUID,
    snapshot: PromptSnapshotEvidence | None,
    prompt_index: int,
) -> tuple[str, uuid.UUID | None, str | None]:
    """Deterministic ``(target_key, target_prompt_id, target_theme)`` (D4).

    Prefers the live prompt identity; falls back to the frozen
    ``prompt-index:{audit_id}:{prompt_index}`` key when the prompt was deleted
    after the audit (the snapshot id is null), so the row stays valid.
    """
    theme = (snapshot.theme or None) if snapshot is not None else None
    if snapshot is not None and snapshot.prompt_id is not None:
        return f"prompt:{snapshot.prompt_id}", snapshot.prompt_id, theme
    return f"prompt-index:{audit_id}:{prompt_index}", None, theme


def _gap_source_pattern(analyses: list[AnalysisEvidence]) -> dict[str, Any]:
    """Observed source pattern across every repetition of one prompt.

    Repetitions are flattened before summarizing so the distinct-domain counts
    describe the PROMPT, not one engine call. Kept out of
    ``_visibility_gap_hits`` so that function's complexity budget is unchanged.
    """
    return summarize_source_pattern(
        citation for analysis in analyses for citation in analysis.citations
    )


def _group_by_prompt_index(
    analyses: tuple[AnalysisEvidence, ...],
) -> dict[int, list[AnalysisEvidence]]:
    groups: dict[int, list[AnalysisEvidence]] = {}
    for analysis in analyses:
        groups.setdefault(analysis.prompt_index, []).append(analysis)
    return groups


def _gap_hit(
    *,
    evidence: VisibilityEvidence,
    rule: OpportunityRule,
    prompt_index: int,
    analyses: list[AnalysisEvidence],
    snapshot: PromptSnapshotEvidence | None,
    competitor_names: list[str],
    extras: Callable[[list[AnalysisEvidence], list[str]], dict[str, Any]],
) -> DetectorHit:
    target_key, prompt_id, theme = _prompt_target(
        audit_id=evidence.audit_id,
        snapshot=snapshot,
        prompt_index=prompt_index,
    )
    intent = snapshot.intent if snapshot is not None else ""
    return DetectorHit(
        rule_id=rule.rule_id,
        target_key=target_key,
        target_prompt_id=prompt_id,
        target_url=None,
        target_theme=theme,
        evidence={
            "prompt_text": snapshot.text if snapshot is not None else "",
            "prompt_intent": intent,
            "prompt_theme": snapshot.theme if snapshot is not None else "",
            "prompt_index": prompt_index,
            "repetitions": len(analyses),
            "owned_citation_count": 0,
            "source_pattern": _gap_source_pattern(analyses),
            **extras(analyses, competitor_names),
            "audit_id": str(evidence.audit_id),
        },
        source_analysis_ids=tuple(
            str(a.analysis_id)
            for a in sorted(analyses, key=lambda a: str(a.analysis_id))
        ),
        source_issue_ids=(),
        source_metric_ids=(),
        value_factor=value_factor_for_intent(intent),
        gap_factor=gap_factor_visibility(
            competitor_count=len(competitor_names), owned_citation_rate=0.0
        ),
    )


def _visibility_gap_hits(
    evidence: VisibilityEvidence,
    *,
    rule: OpportunityRule,
    require_competitor: bool,
    extras: Callable[[list[AnalysisEvidence], list[str]], dict[str, Any]],
) -> list[DetectorHit]:
    """Per-prompt hits for the "zero owned citations" visibility rules.

    Both visibility rules share the firing condition (NO repetition of the
    prompt carries an owned citation), the ``prompt_index`` grouping, the
    deterministic target identity, and the scoring inputs; they differ only
    in whether a competitor must be present (``require_competitor``) and in
    the rule-specific evidence ``extras``.
    """
    snapshots = {s.prompt_index: s for s in evidence.prompt_snapshots}
    groups = _group_by_prompt_index(evidence.analyses)
    hits: list[DetectorHit] = []
    for prompt_index in sorted(groups):
        analyses = groups[prompt_index]
        if any(a.owned_citation_count > 0 for a in analyses):
            continue
        competitor_names = sorted(
            {name for a in analyses for name in a.competitor_names if name}
        )
        if require_competitor and not competitor_names:
            continue
        hits.append(
            _gap_hit(
                evidence=evidence,
                rule=rule,
                prompt_index=prompt_index,
                analyses=analyses,
                snapshot=snapshots.get(prompt_index),
                competitor_names=competitor_names,
                extras=extras,
            )
        )
    return hits


def detect_brand_absent_high_value_prompt(
    evidence: VisibilityEvidence,
) -> list[DetectorHit]:
    """Fire per prompt with no owned citation and >=1 competitor present.

    A prompt fires when NO repetition carries an owned citation AND at least
    one competitor citation-or-mention appears across the repetitions.
    """
    rule = OPPORTUNITY_RULES_BY_ID[RULE_BRAND_ABSENT]
    if not rule.enabled:
        return []
    return _visibility_gap_hits(
        evidence,
        rule=rule,
        require_competitor=True,
        extras=lambda analyses, competitor_names: {
            "competitor_names": competitor_names,
            "engines": sorted({a.logical_engine for a in analyses if a.logical_engine}),
        },
    )


def detect_owned_page_not_cited(evidence: VisibilityEvidence) -> list[DetectorHit]:
    """Fire per prompt with zero owned citations across all repetitions.

    Requires at least one owned domain: with nothing to cite the rule cannot
    fire and is skipped entirely.
    """
    rule = OPPORTUNITY_RULES_BY_ID[RULE_OWNED_PAGE_NOT_CITED]
    if not rule.enabled or not evidence.owned_domains:
        return []
    return _visibility_gap_hits(
        evidence,
        rule=rule,
        require_competitor=False,
        extras=lambda _analyses, _competitor_names: {
            "owned_domains": sorted(evidence.owned_domains),
        },
    )


# =========================================================================
# Site detectors (one hit per mapped SiteIssue)
# =========================================================================
def _site_opportunity_rule_id(issue_rule_id: str) -> str | None:
    """Map a persisted SiteIssue rule id to its opportunity rule (config)."""
    return SITE_ISSUE_TO_OPPORTUNITY_RULE_ID.get(issue_rule_id)


def detect_site_issue_opportunities(evidence: SiteEvidence) -> list[DetectorHit]:
    """Project each mapped ``SiteIssue`` into a site-type opportunity hit.

    One hit per issue whose ``rule_id`` has a config-owned opportunity mapping,
    targeted at the issue's normalized URL. Issues whose URL identity is
    missing (cannot form the deterministic target key) are skipped.
    """
    urls = {u.site_url_id: u.normalized_url for u in evidence.urls}
    hits: list[DetectorHit] = []
    for issue in evidence.issues:
        if issue.finding_class != "defect":
            continue
        rule_id = _site_opportunity_rule_id(issue.rule_id)
        if rule_id is None:
            continue
        rule = OPPORTUNITY_RULES_BY_ID[rule_id]
        if not rule.enabled:
            continue
        normalized_url = urls.get(issue.site_url_id)
        if not normalized_url:
            continue
        hits.append(
            DetectorHit(
                rule_id=rule.rule_id,
                target_key=f"url:{normalized_url}",
                target_prompt_id=None,
                target_url=normalized_url,
                target_theme=None,
                evidence={
                    "issue_rule_id": issue.rule_id,
                    "issue_severity": issue.severity,
                    "category": issue.category,
                    "issue_evidence": issue.evidence or {},
                    "crawl_id": str(evidence.crawl_id),
                    # Deep-link identity for the drawer's Site Health page
                    # link (rendered only when present; older rows predate it).
                    "site_url_id": str(issue.site_url_id),
                    "url": normalized_url,
                    "coverage": evidence.coverage,
                    "limitations": list(evidence.limitations),
                },
                source_analysis_ids=(),
                source_issue_ids=(str(issue.issue_id),),
                source_metric_ids=(),
                value_factor=SITE_VALUE_FACTOR,
                gap_factor=SITE_GAP_FACTOR,
            )
        )
    hits.sort(key=lambda hit: (hit.rule_id, hit.target_key, hit.source_issue_ids))
    return hits


# =========================================================================
# Commerce detectors (persisted ProductMetricSnapshot/ProductMention rows)
# =========================================================================
def _commerce_hit(
    evidence: CommerceEvidence,
    entry: ProductEntryEvidence,
    *,
    rule: OpportunityRule,
    extras: dict[str, Any],
) -> DetectorHit:
    """One commerce-rule firing on one frozen catalog entry.

    Shared target identity (``product:{entry_id}`` /
    ``competitor-product:{entry_id}``), frozen-identity evidence payload, and
    provenance: the entry's ``ProductMetricSnapshot`` (metric ids) and the
    exact product-analysis rows it aggregated (analysis ids, invariant 4).
    """
    target_prefix = "product"
    return DetectorHit(
        rule_id=rule.rule_id,
        target_key=f"{target_prefix}:{entry.entry_id}",
        target_prompt_id=None,
        target_url=None,
        target_theme=None,
        evidence={
            # Frozen at detection (mirrors evidence.prompt_text): the drawer's
            # target label reads this without a catalog join.
            "product_name": entry.name,
            "product_sku": entry.sku,
            "product_kind": entry.kind,
            "mention_count": entry.mention_count,
            "sov_share": entry.sov_share,
            "audit_id": str(evidence.audit_id),
            **extras,
        },
        source_analysis_ids=entry.source_analysis_ids,
        source_issue_ids=(),
        source_metric_ids=(
            (str(entry.snapshot_id),) if entry.snapshot_id is not None else ()
        ),
        value_factor=COMMERCE_VALUE_FACTOR,
        gap_factor=COMMERCE_GAP_FACTOR,
    )


def _sorted_commerce_hits(hits: list[DetectorHit]) -> list[DetectorHit]:
    hits.sort(key=lambda hit: (hit.rule_id, hit.target_key))
    return hits


def _has_provenance(entry: ProductEntryEvidence) -> bool:
    """True when the entry can back a hit's provenance (invariant 4).

    A ``ProductMetricSnapshot`` (metric id) or the analyses it aggregated —
    without either, a ``DetectorHit`` built from this entry would carry three
    empty provenance lists.
    """
    return entry.snapshot_id is not None or bool(entry.source_analysis_ids)


def _is_unmentioned_product(entry: ProductEntryEvidence) -> bool:
    """An own-catalog product MEASURED at zero mentions.

    "Never measured" (no snapshot, no analyses) is not evidence of "never
    mentioned", and would also breach the provenance contract — so it is
    excluded. Unmentioned entries DO get a zero-filled snapshot (invariant 7),
    so a genuinely unmentioned product still qualifies.
    """
    return (
        entry.kind == "product" and entry.mention_count == 0 and _has_provenance(entry)
    )


def detect_product_not_mentioned(evidence: CommerceEvidence) -> list[DetectorHit]:
    """Fire per frozen catalog product measured with zero mentions."""
    rule = OPPORTUNITY_RULES_BY_ID[RULE_PRODUCT_NOT_MENTIONED]
    if not rule.enabled:
        return []
    return _sorted_commerce_hits(
        [
            _commerce_hit(evidence, entry, rule=rule, extras={})
            for entry in evidence.entries
            if _is_unmentioned_product(entry)
        ]
    )


def detect_catalog_fields_missing(evidence: CommerceEvidence) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_CATALOG_FIELDS_MISSING]
    if not rule.enabled:
        return []
    return _sorted_commerce_hits(
        [
            _commerce_hit(
                evidence,
                entry,
                rule=rule,
                extras={"missing_fields": list(entry.missing_fields)},
            )
            for entry in evidence.entries
            if entry.kind == "product"
            and entry.missing_fields
            and _has_provenance(entry)
        ]
    )


def detect_cited_alternatives_without_uploaded_presence(
    evidence: CommerceEvidence,
) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_CITED_ALTERNATIVES]
    if not rule.enabled:
        return []
    mentioned_categories = {
        entry.category.casefold()
        for entry in evidence.entries
        if entry.kind == "product" and entry.mention_count > 0
    }
    return _sorted_commerce_hits(
        [
            DetectorHit(
                rule_id=rule.rule_id,
                target_key=f"category:{row.category.casefold()}",
                target_prompt_id=None,
                target_url=None,
                target_theme=row.category,
                evidence={
                    "category": row.category,
                    "third_party_citation_count": row.third_party_citation_count,
                    "uploaded_destination_citation_count": (
                        row.uploaded_destination_citation_count
                    ),
                    "audit_id": str(evidence.audit_id),
                },
                source_analysis_ids=row.source_analysis_ids,
                source_issue_ids=(),
                source_metric_ids=(),
                value_factor=COMMERCE_VALUE_FACTOR,
                gap_factor=COMMERCE_GAP_FACTOR,
            )
            for row in evidence.category_citations
            if row.third_party_citation_count > 0
            and row.uploaded_destination_citation_count == 0
            and row.category.casefold() not in mentioned_categories
            and row.source_analysis_ids
        ]
    )
