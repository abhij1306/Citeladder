"""Pure, deterministic observed-site architecture derivation."""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median
from urllib.parse import urlsplit, urlunsplit

from app.analysis.site_health.rules import RuleEvaluation, rule_for
from app.core.config.site_health_archetypes import (
    ARCHETYPE_BUSINESS_MODEL_CONFIDENCE_FLOOR,
    ARCHETYPE_BY_BUSINESS_MODEL,
    ARCHETYPE_CONTRADICTING_PAGE_KINDS,
    ARCHETYPE_CONTRADICTION_MIN_PAGES,
    ARCHETYPE_CONTRADICTION_SHARE,
    ARCHETYPE_CORROBORATING_PAGE_KINDS,
    ARCHETYPE_OTHER,
    ARCHETYPE_SOURCE_ABSTAINED,
    ARCHETYPE_SOURCE_ONBOARDING,
    ARCHITECTURE_DETAIL_PAGE_KINDS,
    ARCHITECTURE_DUPLICATE_METADATA_MIN_URLS,
    ARCHITECTURE_DUPLICATE_METADATA_RATE,
    ARCHITECTURE_EXCESSIVE_DEPTH_MIN,
    ARCHITECTURE_HUB_PAGE_KINDS,
    ARCHITECTURE_MAX_EVIDENCE_ITEMS,
    ARCHITECTURE_MAX_FAMILIES,
    ARCHITECTURE_MAX_PAGES,
    ARCHITECTURE_UNHUBBED_FAMILY_MIN_URLS,
    COMMON_STRUCTURES,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_link_metrics import COVERAGE_STATE_COMPLETE
from app.core.config.site_health_taxonomy import PAGE_KIND_HOMEPAGE

_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ArchitecturePage:
    site_url_id: uuid.UUID
    analysis_id: uuid.UUID
    artifact_id: uuid.UUID
    link_metric_id: uuid.UUID
    url: str
    title: str
    meta_description: str
    page_kind: str
    depth_from_home: int | None
    inbound_count: int
    indexable: bool
    facts: dict


@dataclass(frozen=True, slots=True)
class ArchetypeAssessment:
    archetype: str
    source: str
    reason: str
    business_model: str
    profile_evidence: dict | None = None
    observed: tuple[dict, ...] = ()
    not_observed: tuple[dict, ...] = ()

    def as_dict(self) -> dict:
        return {
            "archetype": self.archetype,
            "source": self.source,
            "reason": self.reason,
            "business_model": self.business_model,
            "profile_evidence": self.profile_evidence or {},
            "observed": list(self.observed),
            "not_observed": list(self.not_observed),
        }


@dataclass(frozen=True, slots=True)
class ObservedArchitecture:
    pages: tuple[dict, ...]
    families: tuple[dict, ...]
    archetype: ArchetypeAssessment
    page_kind_counts: dict[str, int]


def path_template(url: str) -> str:
    """Replace only the final path segment with ``*``."""
    path = urlsplit(url).path.rstrip("/") or "/"
    if path == "/":
        return "/"
    parent = path.rsplit("/", 1)[0]
    return f"{parent or ''}/*"


def _metadata_signature(page: ArchitecturePage) -> tuple[str, str] | None:
    title = _SPACE.sub(" ", page.title).strip().casefold()
    description = _SPACE.sub(" ", page.meta_description).strip().casefold()
    return (title, description) if title or description else None


def _duplicate_metadata_count(members: list[ArchitecturePage]) -> int:
    signatures = Counter(
        signature
        for page in members
        if (signature := _metadata_signature(page)) is not None
    )
    return sum(count for count in signatures.values() if count > 1)


def _family_orphan_count(
    members: list[ArchitecturePage], *, coverage_state: str
) -> int | None:
    if coverage_state != COVERAGE_STATE_COMPLETE:
        return None
    return sum(
        1
        for page in members
        if page.page_kind != PAGE_KIND_HOMEPAGE and page.inbound_count == 0
    )


def _family_row(
    template: str, members: list[ArchitecturePage], *, coverage_state: str
) -> dict:
    depths = [
        page.depth_from_home for page in members if page.depth_from_home is not None
    ]
    duplicate_count = _duplicate_metadata_count(members)
    return {
        "family": template,
        "url_count": len(members),
        "page_kind_distribution": dict(
            sorted(Counter(page.page_kind for page in members).items())
        ),
        "median_depth": float(median(depths)) if depths else None,
        "indexable_count": sum(1 for page in members if page.indexable),
        "metadata_duplication_rate": round(duplicate_count / len(members), 4),
        "duplicate_metadata_count": duplicate_count,
        "orphan_count": _family_orphan_count(members, coverage_state=coverage_state),
        "site_url_ids": [str(page.site_url_id) for page in members],
    }


def _family_rows(pages: list[ArchitecturePage], *, coverage_state: str) -> list[dict]:
    grouped: dict[str, list[ArchitecturePage]] = defaultdict(list)
    for page in pages:
        grouped[path_template(page.url)].append(page)
    rows: list[dict] = []
    for template in sorted(grouped)[:ARCHITECTURE_MAX_FAMILIES]:
        members = sorted(
            grouped[template], key=lambda item: (item.url, str(item.site_url_id))
        )
        rows.append(_family_row(template, members, coverage_state=coverage_state))
    return rows


def _immediate_parent_url(url: str) -> str | None:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if not path:
        return None
    parent = path.rsplit("/", 1)[0] or "/"
    return urlunsplit((parts.scheme, parts.netloc, parent, "", ""))


def _resolved_candidate(
    urls: list[str], *, current_id: uuid.UUID, id_by_url: dict[str, uuid.UUID]
) -> uuid.UUID | None:
    for url in reversed(urls):
        candidate = id_by_url.get(url)
        if candidate is not None and candidate != current_id:
            return candidate
    return None


def _visible_breadcrumb_urls(facts: dict) -> list[str]:
    commerce = facts.get("commerce") or {}
    return [
        str(item.get("url") or "")
        for item in commerce.get("breadcrumb_links") or []
        if isinstance(item, dict) and item.get("url")
    ]


def _structured_relationship_urls(facts: dict) -> list[str]:
    schema_breadcrumbs: list[str] = []
    is_part_of: list[str] = []
    for block in facts.get("structured_data") or []:
        if not isinstance(block, dict):
            continue
        schema_breadcrumbs.extend(
            str(value) for value in block.get("breadcrumb_items") or [] if value
        )
        if block.get("is_part_of_url"):
            is_part_of.append(str(block["is_part_of_url"]))
    return [*schema_breadcrumbs, *is_part_of]


def _relationship_urls(page: ArchitecturePage) -> tuple[list[str], list[str]]:
    return (
        _visible_breadcrumb_urls(page.facts),
        _structured_relationship_urls(page.facts),
    )


def _break_parent_cycles(rows: list[dict]) -> list[dict]:
    parent_by_id = {row["site_url_id"]: row["parent_site_url_id"] for row in rows}
    for row in rows:
        current = row["site_url_id"]
        parent = parent_by_id.get(current)
        seen: set[str] = set()
        in_cycle = False
        while parent is not None and parent not in seen:
            if parent == current:
                in_cycle = True
                break
            seen.add(parent)
            parent = parent_by_id.get(parent)
        row["cycle_suppressed"] = in_cycle
        if not row["cycle_suppressed"]:
            continue
        row["parent_site_url_id"] = None
        row["parent_source"] = "unknown"
        parent_by_id[current] = None
    return rows


def _safe_path_parent(
    page: ArchitecturePage,
    *,
    id_by_url: dict[str, uuid.UUID],
    kind_by_id: dict[uuid.UUID, str],
) -> uuid.UUID | None:
    parent = id_by_url.get(_immediate_parent_url(page.url) or "")
    if parent is None or kind_by_id.get(parent) in ARCHITECTURE_HUB_PAGE_KINDS:
        return parent
    return None


def _parent_source(
    breadcrumb_parent: uuid.UUID | None,
    explicit_parent: uuid.UUID | None,
    path_parent: uuid.UUID | None,
) -> str:
    if breadcrumb_parent:
        return "breadcrumb"
    if explicit_parent:
        return "explicit_structure"
    if path_parent:
        return "url_family"
    return "unknown"


def _hierarchy_row(
    page: ArchitecturePage,
    *,
    id_by_url: dict[str, uuid.UUID],
    kind_by_id: dict[uuid.UUID, str],
) -> dict:
    breadcrumb_urls, explicit_urls = _relationship_urls(page)
    breadcrumb_parent = _resolved_candidate(
        breadcrumb_urls, current_id=page.site_url_id, id_by_url=id_by_url
    )
    explicit_parent = _resolved_candidate(
        explicit_urls, current_id=page.site_url_id, id_by_url=id_by_url
    )
    path_parent = _safe_path_parent(page, id_by_url=id_by_url, kind_by_id=kind_by_id)
    parent = breadcrumb_parent or explicit_parent or path_parent
    return {
        "site_url_id": str(page.site_url_id),
        "url": page.url,
        "title": page.title,
        "page_kind": page.page_kind,
        "family": path_template(page.url),
        "parent_site_url_id": str(parent) if parent else None,
        "parent_source": _parent_source(
            breadcrumb_parent, explicit_parent, path_parent
        ),
        "breadcrumb_parent_site_url_id": (
            str(breadcrumb_parent) if breadcrumb_parent else None
        ),
        "explicit_parent_site_url_id": (
            str(explicit_parent) if explicit_parent else None
        ),
        "depth_from_home": page.depth_from_home,
    }


def _hierarchy_rows(pages: list[ArchitecturePage]) -> list[dict]:
    ids_by_url: dict[str, list[uuid.UUID]] = defaultdict(list)
    for page in pages:
        ids_by_url[page.url].append(page.site_url_id)
    # Redirect collisions are ambiguous. Abstain instead of choosing whichever
    # row happened to sort last.
    id_by_url = {url: ids[0] for url, ids in ids_by_url.items() if len(ids) == 1}
    kind_by_id = {page.site_url_id: page.page_kind for page in pages}
    rows = [
        _hierarchy_row(page, id_by_url=id_by_url, kind_by_id=kind_by_id)
        for page in sorted(pages, key=lambda item: (item.url, str(item.site_url_id)))
    ]
    return _break_parent_cycles(rows)


def _abstain(
    reason: str, business_model: str = "", profile_evidence: dict | None = None
) -> ArchetypeAssessment:
    return ArchetypeAssessment(
        archetype=ARCHETYPE_OTHER,
        source=ARCHETYPE_SOURCE_ABSTAINED,
        reason=reason,
        business_model=business_model,
        profile_evidence=profile_evidence,
    )


def _materially_contradicted(archetype: str, counts: Counter[str]) -> bool:
    total = sum(counts.values())
    if total < ARCHETYPE_CONTRADICTION_MIN_PAGES:
        return False
    corroborating = sum(
        counts[kind] for kind in ARCHETYPE_CORROBORATING_PAGE_KINDS[archetype]
    )
    contradicting = sum(
        counts[kind] for kind in ARCHETYPE_CONTRADICTING_PAGE_KINDS[archetype]
    )
    return corroborating == 0 and contradicting / total >= ARCHETYPE_CONTRADICTION_SHARE


def _path_segments(url: str) -> set[str]:
    return {segment.casefold() for segment in urlsplit(url).path.split("/") if segment}


def _profile_evidence(business_context: dict) -> dict:
    raw_confidence = (business_context.get("field_confidence") or {}).get(
        "business_model"
    )
    try:
        confidence = float(raw_confidence or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "knowledge_strength": str(business_context.get("knowledge_strength") or "none"),
        "business_model_confidence": confidence,
        "market_scope": str(business_context.get("market_scope") or ""),
    }


def common_structure_observations(
    *, archetype: str, pages: Sequence[tuple[str, str]], market_scope: str
) -> tuple[list[dict], list[dict]]:
    """Split an archetype's common structures into observed / not observed.

    ``pages`` is ``(page_kind, url)`` rather than the richer dataclass so the
    read path can re-run the SAME policy over a persisted hierarchy when the
    user corrects the archetype — without re-reading artifacts or writing a
    second implementation of the rule.
    """
    observed: list[dict] = []
    not_observed: list[dict] = []
    page_segments = [(page_kind, _path_segments(url)) for page_kind, url in pages]
    for structure in COMMON_STRUCTURES[archetype]:
        if structure.local_market_only and market_scope not in {"local", "regional"}:
            continue
        seen = any(
            page_kind in structure.page_kinds
            or bool(segments & structure.path_segments)
            for page_kind, segments in page_segments
        )
        row = {"key": structure.key, "label": structure.label}
        (observed if seen else not_observed).append(row)
    return observed, not_observed


def resolve_archetype(
    *, business_context: dict, pages: list[ArchitecturePage], coverage_state: str
) -> ArchetypeAssessment:
    """Resolve only from onboarding; crawl evidence may veto, never assign."""
    if not business_context:
        return _abstain("profile_absent")
    business_model = str(business_context.get("business_model") or "")
    profile_evidence = _profile_evidence(business_context)
    if profile_evidence["knowledge_strength"] == "none":
        return _abstain("knowledge_strength_none", business_model, profile_evidence)
    confidence = profile_evidence["business_model_confidence"]
    if confidence < ARCHETYPE_BUSINESS_MODEL_CONFIDENCE_FLOOR:
        return _abstain(
            "business_model_confidence_below_floor",
            business_model,
            profile_evidence,
        )
    archetype = ARCHETYPE_BY_BUSINESS_MODEL.get(business_model, ARCHETYPE_OTHER)
    if archetype == ARCHETYPE_OTHER:
        return _abstain("business_model_not_mapped", business_model, profile_evidence)
    counts = Counter(page.page_kind for page in pages)
    if _materially_contradicted(archetype, counts):
        return _abstain(
            "crawl_materially_contradicts_profile",
            business_model,
            profile_evidence,
        )

    observed, not_observed = common_structure_observations(
        archetype=archetype,
        pages=[(page.page_kind, page.url) for page in pages],
        market_scope=profile_evidence["market_scope"],
    )
    # Absence advisories are unavailable unless the crawl proved completeness.
    if coverage_state != COVERAGE_STATE_COMPLETE:
        not_observed = []
    return ArchetypeAssessment(
        archetype=archetype,
        source=ARCHETYPE_SOURCE_ONBOARDING,
        reason="profile_supported",
        business_model=business_model,
        profile_evidence=profile_evidence,
        observed=tuple(observed),
        not_observed=tuple(not_observed),
    )


def build_observed_architecture(
    *, pages: list[ArchitecturePage], coverage_state: str, business_context: dict
) -> ObservedArchitecture:
    bounded = sorted(pages, key=lambda item: (item.url, str(item.site_url_id)))[
        :ARCHITECTURE_MAX_PAGES
    ]
    counts = dict(sorted(Counter(page.page_kind for page in bounded).items()))
    return ObservedArchitecture(
        pages=tuple(_hierarchy_rows(bounded)),
        families=tuple(_family_rows(bounded, coverage_state=coverage_state)),
        archetype=resolve_archetype(
            business_context=business_context,
            pages=bounded,
            coverage_state=coverage_state,
        ),
        page_kind_counts=counts,
    )


def _evaluation(rule_id: str, outcome: str, evidence: dict) -> RuleEvaluation:
    rule = rule_for(rule_id)
    if rule is None:
        raise RuntimeError(f"architecture rule missing from catalog: {rule_id!r}")
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


def _coverage_evaluation(
    rule_id: str, coverage_state: str, evidence: dict
) -> RuleEvaluation:
    if coverage_state != COVERAGE_STATE_COMPLETE:
        return _evaluation(
            rule_id,
            RULE_OUTCOME_NOT_APPLICABLE,
            {"reason": "coverage_not_complete", "coverage_state": coverage_state},
        )
    return _evaluation(
        rule_id,
        RULE_OUTCOME_FAIL if int(evidence.get("count") or 0) else RULE_OUTCOME_PASS,
        evidence,
    )


def _deep_pages(model: ObservedArchitecture) -> list[dict]:
    return [
        row
        for row in model.pages
        if (row.get("depth_from_home") or 0) >= ARCHITECTURE_EXCESSIVE_DEPTH_MIN
    ]


def _hierarchy_conflicts(model: ObservedArchitecture) -> list[dict]:
    return [
        row
        for row in model.pages
        if row.get("breadcrumb_parent_site_url_id")
        and row.get("explicit_parent_site_url_id")
        and row["breadcrumb_parent_site_url_id"] != row["explicit_parent_site_url_id"]
    ]


def _duplicate_families(model: ObservedArchitecture) -> list[dict]:
    return [
        family
        for family in model.families
        if family["url_count"] >= ARCHITECTURE_DUPLICATE_METADATA_MIN_URLS
        and family["metadata_duplication_rate"] >= ARCHITECTURE_DUPLICATE_METADATA_RATE
    ]


def _orphan_pages(
    model: ObservedArchitecture, *, by_id: dict[str, ArchitecturePage]
) -> list[dict]:
    return [
        row
        for row in model.pages
        if row["page_kind"] != PAGE_KIND_HOMEPAGE
        and by_id[row["site_url_id"]].inbound_count == 0
    ]


def _parentless_pages(model: ObservedArchitecture) -> list[dict]:
    return [
        row
        for row in model.pages
        if row["page_kind"] in ARCHITECTURE_DETAIL_PAGE_KINDS
        and row["parent_site_url_id"] is None
    ]


def _family_is_unhubbed(
    family: dict,
    *,
    by_id: dict[str, ArchitecturePage],
    parent_by_id: dict[str, str | None],
) -> bool:
    if family["url_count"] < ARCHITECTURE_UNHUBBED_FAMILY_MIN_URLS:
        return False
    for site_url_id in family["site_url_ids"]:
        if by_id[site_url_id].page_kind not in ARCHITECTURE_DETAIL_PAGE_KINDS:
            return False
        if parent_by_id[site_url_id] is not None:
            return False
    return True


def _unhubbed_families(
    model: ObservedArchitecture, *, by_id: dict[str, ArchitecturePage]
) -> list[dict]:
    parent_by_id = {
        row["site_url_id"]: row["parent_site_url_id"] for row in model.pages
    }
    return [
        family
        for family in model.families
        if _family_is_unhubbed(family, by_id=by_id, parent_by_id=parent_by_id)
    ]


def _rule_evidence(rows: list[dict], key: str, *, coverage_state: str) -> dict:
    return {
        "count": len(rows),
        key: rows[:ARCHITECTURE_MAX_EVIDENCE_ITEMS],
        "coverage_state": coverage_state,
    }


def evaluate_architecture_rules(
    *,
    model: ObservedArchitecture,
    source_pages: list[ArchitecturePage],
    coverage_state: str,
) -> list[RuleEvaluation]:
    """Evaluate one aggregated, root-anchored occurrence per structural rule."""
    by_id = {str(page.site_url_id): page for page in source_pages}
    deep = _deep_pages(model)
    conflicts = _hierarchy_conflicts(model)
    duplicate_families = _duplicate_families(model)
    orphans = _orphan_pages(model, by_id=by_id)
    parentless = _parentless_pages(model)
    unhubbed = _unhubbed_families(model, by_id=by_id)

    def evidence(rows: list[dict], key: str) -> dict:
        return _rule_evidence(rows, key, coverage_state=coverage_state)

    return [
        _evaluation(
            "architecture.excessive_depth",
            RULE_OUTCOME_FAIL if deep else RULE_OUTCOME_PASS,
            evidence(deep, "pages"),
        ),
        _evaluation(
            "architecture.breadcrumb_hierarchy_conflict",
            RULE_OUTCOME_FAIL if conflicts else RULE_OUTCOME_PASS,
            evidence(conflicts, "pages"),
        ),
        _evaluation(
            "architecture.duplicate_metadata_in_family",
            RULE_OUTCOME_FAIL if duplicate_families else RULE_OUTCOME_PASS,
            evidence(duplicate_families, "families"),
        ),
        _coverage_evaluation(
            "architecture.orphan_pages", coverage_state, evidence(orphans, "pages")
        ),
        _coverage_evaluation(
            "architecture.parentless_detail_pages",
            coverage_state,
            evidence(parentless, "pages"),
        ),
        _coverage_evaluation(
            "architecture.unhubbed_family",
            coverage_state,
            evidence(unhubbed, "families"),
        ),
    ]


__all__ = [
    "ArchitecturePage",
    "ArchetypeAssessment",
    "ObservedArchitecture",
    "build_observed_architecture",
    "evaluate_architecture_rules",
    "path_template",
    "resolve_archetype",
]
