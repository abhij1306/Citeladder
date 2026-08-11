"""Deterministic Content Intelligence projections and user-save workflow."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime
from itertools import islice
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.content_intelligence import (
    AUTOMATIC_BRIEF_STATES,
    CONTENT_ARTIFACT_LIST_LIMIT,
    CONTENT_BRIEF_BUILDER_VERSION,
    CONTENT_CONTEXT_MAX_CHARS,
    CONTENT_CONTEXT_MAX_FACTS,
    CONTENT_CONTEXT_MAX_SOURCES,
    CONTENT_CONTEXT_POLICY_VERSION,
    CONTENT_INVENTORY_LIST_LIMIT,
    CONTENT_PROJECTION_VERSION,
    CONTENT_REVISION_MAX_CHARS,
    CONTENT_STRATEGY_VERSION,
    CONTENT_VALIDATOR_VERSION,
    CONTENT_VERIFIER_VERSION,
    REVISION_TRANSITIONS,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.site_health.normalization import canonical_identity
from app.models.content import (
    ContentBrief,
    ContentGeneration,
    ContentInventoryItem,
    ContentRevision,
    ContentRevisionTransition,
    ContentStrategySnapshot,
    ContentValidation,
    ContentVerification,
    TaskContextPackage,
)
from app.models.demand import DemandSnapshot
from app.models.project import Project
from app.models.site_health import (
    SiteFetchArtifact,
    SiteHealthSnapshot,
    SitePageAnalysis,
    SiteUrl,
)

_UUID_NAMESPACE = uuid.UUID("23819dcb-309a-4d0d-97cf-a91d2cc853b4")
_CLAIM_TOKEN = re.compile(
    r"(?<![\w])(?:[$€£₹]\s*)?\d{2,}(?:[.,]\d+)?(?:\s*(?:%|percent|USD|EUR|GBP|INR))?",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s)>\]]+")


class ContentNotFoundError(LookupError):
    pass


class ContentConflictError(RuntimeError):
    pass


class ContentValidationBlockedError(RuntimeError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_id(kind: str, *parts: object) -> uuid.UUID:
    return uuid.uuid5(
        _UUID_NAMESPACE, "\x1f".join([kind, *(str(part) for part in parts)])
    )


async def _project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if project is None:
        raise ContentNotFoundError("Project not found")
    return project


async def _latest_site_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SiteHealthSnapshot:
    snapshot = await session.scalar(
        select(SiteHealthSnapshot)
        .where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
        )
        .order_by(SiteHealthSnapshot.created_at.desc(), SiteHealthSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        raise ContentConflictError("site_snapshot_unavailable")
    return snapshot


async def recompute_strategy(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[ContentStrategySnapshot, bool]:
    """Persist deterministic inventory and one idempotent strategy snapshot."""
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    site = await _latest_site_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    demand = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )
    source_hash = _hash(
        {
            "site_snapshot_id": str(site.id),
            "demand_snapshot_id": str(demand.id) if demand else None,
            "projection_version": CONTENT_PROJECTION_VERSION,
            "strategy_version": CONTENT_STRATEGY_VERSION,
        }
    )
    existing = await session.scalar(
        select(ContentStrategySnapshot).where(
            ContentStrategySnapshot.project_id == project_id,
            ContentStrategySnapshot.source_hash == source_hash,
        )
    )
    if existing is not None:
        return existing, False

    await _persist_inventory(
        session, workspace_id=workspace_id, project_id=project_id, snapshot=site
    )
    # Question coverage and its priority ranking came from the Site
    # Intelligence projection, which is deleted. The inventory above is the
    # part built from Site Health evidence (one row per analyzed page, grouped
    # by page kind) and it still runs; the question program is empty until a
    # replacement evidence source exists.
    coverage: dict = {}
    priorities: list[dict] = []
    inventory_summary = await _inventory_summary(
        session, workspace_id=workspace_id, project_id=project_id, snapshot_id=site.id
    )
    strategy = _new_strategy(
        workspace_id=workspace_id,
        project_id=project_id,
        site=site,
        demand=demand,
        source_hash=source_hash,
        coverage=coverage,
        priorities=priorities,
        inventory_summary=inventory_summary,
    )
    return await _commit_strategy(session, strategy)


def _new_strategy(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    site: SiteHealthSnapshot,
    demand: DemandSnapshot | None,
    source_hash: str,
    coverage: dict,
    priorities: list[dict],
    inventory_summary: dict,
) -> ContentStrategySnapshot:
    return ContentStrategySnapshot(
        id=_stable_id("strategy", project_id, source_hash),
        workspace_id=workspace_id,
        project_id=project_id,
        site_snapshot_id=site.id,
        demand_snapshot_id=demand.id if demand else None,
        source_hash=source_hash,
        inventory_summary=inventory_summary,
        coverage=coverage,
        priorities=priorities,
        program=[
            {
                "sequence": index + 1,
                "action": item["action"],
                "question_id": item["question_id"],
            }
            for index, item in enumerate(priorities[:20])
        ],
        limitations=([] if demand else ["demand_evidence_unavailable"]),
        source_versions={
            "projection": CONTENT_PROJECTION_VERSION,
            "strategy": CONTENT_STRATEGY_VERSION,
            "site_intelligence": site.analyzer_version,
            "demand_formula": demand.formula_version if demand else "",
        },
    )


async def _commit_strategy(
    session: AsyncSession, strategy: ContentStrategySnapshot
) -> tuple[ContentStrategySnapshot, bool]:
    session.add(strategy)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(ContentStrategySnapshot).where(
                ContentStrategySnapshot.project_id == strategy.project_id,
                ContentStrategySnapshot.source_hash == strategy.source_hash,
            )
        )
        if winner is None:
            raise
        return winner, False
    await session.refresh(strategy)
    return strategy, True


async def _persist_inventory(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot: SiteHealthSnapshot,
) -> None:
    rows = (
        await session.execute(
            select(SitePageAnalysis, SiteUrl, SiteFetchArtifact)
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .join(
                SiteFetchArtifact, SiteFetchArtifact.id == SitePageAnalysis.artifact_id
            )
            .where(
                SitePageAnalysis.workspace_id == workspace_id,
                SitePageAnalysis.project_id == project_id,
                SitePageAnalysis.crawl_id == snapshot.crawl_id,
                SitePageAnalysis.is_current.is_(True),
            )
            .order_by(SiteUrl.normalized_url, SitePageAnalysis.id)
        )
    ).all()
    values = [
        _inventory_value(
            analysis,
            site_url,
            artifact,
            workspace_id=workspace_id,
            project_id=project_id,
            snapshot_id=snapshot.id,
        )
        for analysis, site_url, artifact in rows
    ]
    await _upsert_inventory(session, values)


def _inventory_value(
    analysis: SitePageAnalysis,
    site_url: SiteUrl,
    artifact: SiteFetchArtifact,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> dict[str, Any]:
    facts = dict(artifact.normalized_facts or {})
    return {
        "id": _stable_id("inventory", snapshot_id, analysis.id),
        "workspace_id": workspace_id,
        "project_id": project_id,
        "site_snapshot_id": snapshot_id,
        "site_analysis_id": analysis.id,
        "site_url_id": site_url.id,
        "canonical_url": site_url.normalized_url,
        "page_kind": analysis.page_kind,
        "purpose": {
            "title": str(facts.get("title") or "")[:512],
            "headings": _inventory_headings(facts),
        },
        "coverage": {
            "technical_score": analysis.technical_score,
            "aeo_score": analysis.aeo_score,
            "status": analysis.status,
        },
        "evidence": {
            "artifact_id": str(artifact.id),
            "content_hash": artifact.content_hash or "",
        },
        "source_versions": {
            "analyzer": analysis.analyzer_version,
            "classifier": analysis.classifier_version,
        },
    }


def _inventory_headings(facts: dict[str, Any]) -> list[Any]:
    headings = facts.get("headings")
    if not isinstance(headings, dict):
        return []
    h1_texts = headings.get("h1_texts")
    if not isinstance(h1_texts, list):
        return []
    return list(islice(h1_texts, 5))


async def _upsert_inventory(
    session: AsyncSession, values: list[dict[str, Any]]
) -> None:
    if not values:
        return
    statement = pg_insert(ContentInventoryItem).values(values)
    update_fields = {
        name: getattr(statement.excluded, name)
        for name in (
            "canonical_url",
            "page_kind",
            "purpose",
            "coverage",
            "evidence",
            "source_versions",
        )
    }
    await session.execute(
        statement.on_conflict_do_update(
            constraint="uq_content_inventory_source", set_=update_fields
        )
    )


async def _inventory_summary(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> dict:
    rows = list(
        (
            await session.scalars(
                select(ContentInventoryItem).where(
                    ContentInventoryItem.workspace_id == workspace_id,
                    ContentInventoryItem.project_id == project_id,
                    ContentInventoryItem.site_snapshot_id == snapshot_id,
                )
            )
        ).all()
    )
    # Grouped by PAGE KIND. This grouped by pack-assigned industry role until
    # that classifier was deleted; page kind is the taxonomy the product
    # actually reasons about (a product page and an FAQ page are audited
    # differently), so it is the honest grouping for a content inventory too.
    by_page_kind: dict[str, int] = {}
    for row in rows:
        kind = row.page_kind or "unclassified"
        by_page_kind[kind] = by_page_kind.get(kind, 0) + 1
    return {"total": len(rows), "by_page_kind": by_page_kind}


async def latest_strategy(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> ContentStrategySnapshot | None:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return await session.scalar(
        select(ContentStrategySnapshot)
        .where(
            ContentStrategySnapshot.workspace_id == workspace_id,
            ContentStrategySnapshot.project_id == project_id,
        )
        .order_by(
            ContentStrategySnapshot.created_at.desc(), ContentStrategySnapshot.id.desc()
        )
        .limit(1)
    )


async def list_inventory(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = CONTENT_INVENTORY_LIST_LIMIT,
) -> list[ContentInventoryItem]:
    strategy = await latest_strategy(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if strategy is None:
        return []
    return list(
        (
            await session.scalars(
                select(ContentInventoryItem)
                .where(
                    ContentInventoryItem.workspace_id == workspace_id,
                    ContentInventoryItem.project_id == project_id,
                    ContentInventoryItem.site_snapshot_id == strategy.site_snapshot_id,
                )
                .order_by(ContentInventoryItem.canonical_url, ContentInventoryItem.id)
                .limit(max(1, min(limit, CONTENT_INVENTORY_LIST_LIMIT)))
            )
        ).all()
    )


async def create_faq_brief(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    question_id: str,
    kind: str,
    target_url: str,
    title: str,
) -> tuple[ContentBrief, bool]:
    strategy = await latest_strategy(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if strategy is None:
        raise ContentConflictError("content_strategy_unavailable")
    questions = list((strategy.coverage or {}).get("questions") or [])
    question = next(
        (item for item in questions if item.get("question_id") == question_id), None
    )
    if question is None:
        raise ContentNotFoundError("Question gap not found")
    state = str(question.get("state") or "")
    if kind == "faq" and state not in AUTOMATIC_BRIEF_STATES:
        raise ContentConflictError(f"question_not_briefable:{state}")

    evidence = await _brief_evidence(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        strategy=strategy,
        question=question,
    )
    evidence_hash = _hash(evidence)
    target = {
        "url": target_url,
        "question_id": question_id,
    }
    identity_hash = _hash(
        {
            "project_id": str(project_id),
            "kind": kind,
            "target": target,
            "evidence_hash": evidence_hash,
            "builder": CONTENT_BRIEF_BUILDER_VERSION,
        }
    )
    existing = await session.scalar(
        select(ContentBrief).where(
            ContentBrief.project_id == project_id,
            ContentBrief.identity_hash == identity_hash,
        )
    )
    if existing is not None:
        return existing, False
    prior = await session.scalar(
        select(ContentBrief)
        .where(
            ContentBrief.workspace_id == workspace_id,
            ContentBrief.project_id == project_id,
            ContentBrief.kind == kind,
            ContentBrief.target["question_id"].astext == question_id,
        )
        .order_by(ContentBrief.version.desc(), ContentBrief.created_at.desc())
        .limit(1)
    )
    brief = _new_content_brief(
        workspace_id=workspace_id,
        project_id=project_id,
        strategy=strategy,
        prior=prior,
        kind=kind,
        title=title,
        target=target,
        question=question,
        evidence=evidence,
        evidence_hash=evidence_hash,
        identity_hash=identity_hash,
        question_id=question_id,
    )
    return await _commit_brief(session, brief)


async def _brief_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    strategy: ContentStrategySnapshot,
    question: dict,
) -> dict:
    """Brief evidence envelope.

    ``allowed_facts`` / ``prohibited_claims`` / ``source_refs`` are EMPTY.
    They were populated from Site Intelligence knowledge assertions, which no
    longer exist. The keys are retained because persisted briefs and the
    generation prompt both read this shape; an empty allow-list means the
    generator has no grounded facts to cite rather than being handed unverified
    ones. Restoring grounded facts needs a new evidence source — see
    docs/plans/site-health-debt-audit.md.
    """
    return {
        "site_snapshot_id": str(strategy.site_snapshot_id),
        "question": question,
        "allowed_facts": [],
        "prohibited_claims": [],
        "source_refs": [],
    }


def _new_content_brief(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    strategy: ContentStrategySnapshot,
    prior: ContentBrief | None,
    kind: str,
    title: str,
    target: dict,
    question: dict,
    evidence: dict,
    evidence_hash: str,
    identity_hash: str,
    question_id: str,
) -> ContentBrief:
    return ContentBrief(
        id=_stable_id("brief", project_id, identity_hash),
        workspace_id=workspace_id,
        project_id=project_id,
        strategy_snapshot_id=strategy.id,
        prior_brief_id=prior.id if prior else None,
        version=(prior.version + 1 if prior else 1),
        identity_hash=identity_hash,
        kind=kind,
        title=title.strip() or f"FAQ: {question_id}",
        target=target,
        requirements={
            "questions": [question],
            "visible_content_required": True,
            "structured_data_must_match_visible": True,
        },
        allowed_facts=evidence["allowed_facts"],
        prohibited_claims=evidence["prohibited_claims"],
        source_refs=evidence["source_refs"],
        verification_criteria=[
            {"type": "question_observed", "question_id": question_id},
            {"type": "visible_answer_observed", "question_id": question_id},
        ],
        brief_builder_version=CONTENT_BRIEF_BUILDER_VERSION,
        evidence_hash=evidence_hash,
    )


async def _commit_brief(
    session: AsyncSession, brief: ContentBrief
) -> tuple[ContentBrief, bool]:
    session.add(brief)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(ContentBrief).where(
                ContentBrief.project_id == brief.project_id,
                ContentBrief.identity_hash == brief.identity_hash,
            )
        )
        if winner is None:
            raise
        return winner, False
    await session.refresh(brief)
    return brief, True


async def list_briefs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[ContentBrief]:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return list(
        (
            await session.scalars(
                select(ContentBrief)
                .where(
                    ContentBrief.workspace_id == workspace_id,
                    ContentBrief.project_id == project_id,
                )
                .order_by(ContentBrief.created_at.desc(), ContentBrief.id.desc())
                .limit(CONTENT_ARTIFACT_LIST_LIMIT)
            )
        ).all()
    )


async def get_brief(
    session: AsyncSession, *, workspace_id: uuid.UUID, brief_id: uuid.UUID
) -> ContentBrief:
    brief = await session.scalar(
        select(ContentBrief).where(
            ContentBrief.id == brief_id, ContentBrief.workspace_id == workspace_id
        )
    )
    if brief is None:
        raise ContentNotFoundError("Content brief not found")
    return brief


def _render_task_context(brief: ContentBrief) -> tuple[dict[str, Any], list[dict]]:
    """Select bounded brief evidence and trim facts to the character budget."""
    rendered: dict[str, Any] = {
        "brief": {
            "id": str(brief.id),
            "kind": brief.kind,
            "target": brief.target,
            "requirements": brief.requirements,
            "verification_criteria": brief.verification_criteria,
        },
        "allowed_facts": list(brief.allowed_facts)[:CONTENT_CONTEXT_MAX_FACTS],
        "prohibited_claims": list(brief.prohibited_claims),
        "sources": list(brief.source_refs)[:CONTENT_CONTEXT_MAX_SOURCES],
    }
    omissions: list[dict] = []
    while (
        len(_canonical(rendered)) > CONTENT_CONTEXT_MAX_CHARS
        and rendered["allowed_facts"]
    ):
        omitted = rendered["allowed_facts"].pop()
        omissions.append(
            {"kind": "fact", "id": omitted.get("assertion_id"), "reason": "budget"}
        )
    if len(_canonical(rendered)) > CONTENT_CONTEXT_MAX_CHARS:
        raise ContentConflictError("content_context_budget_exceeded")
    return rendered, omissions


def _context_manifest(
    brief: ContentBrief, rendered: dict[str, Any], omissions: list[dict]
) -> dict[str, Any]:
    """Project exact included evidence and policy provenance into a manifest."""
    allowed_facts = rendered["allowed_facts"]
    sources = rendered["sources"]
    return {
        "brief_id": str(brief.id),
        "evidence_hash": brief.evidence_hash,
        "assertion_ids": [item.get("assertion_id") for item in allowed_facts],
        "source_ids": sorted(
            str(item.get("source_id") or item.get("artifact_id") or "")
            for item in sources
            if item.get("source_id") or item.get("artifact_id")
        ),
        "correction_ids": sorted(
            str(item["correction"].get("id"))
            for item in allowed_facts
            if isinstance(item.get("correction"), dict) and item["correction"].get("id")
        ),
        "included_counts": {
            "facts": len(allowed_facts),
            "sources": len(sources),
        },
        "omitted_count": len(omissions),
        "policy_version": CONTENT_CONTEXT_POLICY_VERSION,
    }


def _new_task_context_package(
    *,
    brief: ContentBrief,
    rendered: dict[str, Any],
    omissions: list[dict],
    manifest: dict[str, Any],
    manifest_hash: str,
) -> TaskContextPackage:
    """Construct the immutable context package without persistence."""
    return TaskContextPackage(
        id=_stable_id("context", brief.id, manifest_hash),
        workspace_id=brief.workspace_id,
        project_id=brief.project_id,
        brief_id=brief.id,
        task_type=f"content:{brief.kind}",
        manifest=manifest,
        rendered_context=rendered,
        omissions=omissions,
        selection_policy_version=CONTENT_CONTEXT_POLICY_VERSION,
        manifest_hash=manifest_hash,
        char_count=len(_canonical(rendered)),
    )


async def build_task_context(
    session: AsyncSession, *, workspace_id: uuid.UUID, brief_id: uuid.UUID
) -> tuple[TaskContextPackage, bool]:
    brief = await get_brief(session, workspace_id=workspace_id, brief_id=brief_id)
    rendered, omissions = _render_task_context(brief)
    manifest = _context_manifest(brief, rendered, omissions)
    manifest_hash = _hash(
        {"manifest": manifest, "rendered": rendered, "omissions": omissions}
    )
    existing = await session.scalar(
        select(TaskContextPackage).where(
            TaskContextPackage.brief_id == brief.id,
            TaskContextPackage.manifest_hash == manifest_hash,
        )
    )
    if existing is not None:
        return existing, False
    package = _new_task_context_package(
        brief=brief,
        rendered=rendered,
        omissions=omissions,
        manifest=manifest,
        manifest_hash=manifest_hash,
    )
    session.add(package)
    return await _commit_context(
        session,
        package=package,
        brief_id=brief.id,
        manifest_hash=manifest_hash,
    )


async def _commit_context(
    session: AsyncSession,
    *,
    package: TaskContextPackage,
    brief_id: uuid.UUID,
    manifest_hash: str,
) -> tuple[TaskContextPackage, bool]:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(TaskContextPackage).where(
                TaskContextPackage.brief_id == brief_id,
                TaskContextPackage.manifest_hash == manifest_hash,
            )
        )
        if winner is None:
            raise
        return winner, False
    await session.refresh(package)
    return package, True


def validate_output(
    *, output_text: str, brief: ContentBrief, context: TaskContextPackage
) -> tuple[str, list[dict]]:
    """Validate structure, claims, links and context-bound citations."""
    text = output_text.strip()
    checks = [_check("non_empty", bool(text), "Generated output is empty")]
    checks.extend(_required_question_checks(text, brief))
    checks.append(_sensitive_claim_check(text, context))
    checks.append(_selected_link_check(text, brief, context))
    blocking = any(not item["passed"] for item in checks)
    return ("blocked" if blocking else "passed"), checks


def _required_question_checks(text: str, brief: ContentBrief) -> list[dict]:
    checks = []
    questions = list((brief.requirements or {}).get("questions") or [])
    for question in questions:
        question_id = str(question.get("question_id") or "")
        label = str(question.get("question") or question.get("label") or "")
        present = label.lower() in text.lower() if label else False
        checks.append(
            _check(
                f"required_question:{question_id}",
                present,
                "Required question is absent",
            )
        )
    return checks


def _sensitive_claim_check(text: str, context: TaskContextPackage) -> dict:
    allowed_tokens = _allowed_claim_tokens(context)
    unknown_claims = sorted(
        {token for token in _CLAIM_TOKEN.findall(text) if token not in allowed_tokens}
    )
    return _check(
        "unsupported_sensitive_claims",
        not unknown_claims,
        "Numeric or time-sensitive claims are absent from context",
        evidence=unknown_claims[:20],
    )


def _allowed_claim_tokens(context: TaskContextPackage) -> set[str]:
    return {
        token
        for fact in (context.rendered_context or {}).get("allowed_facts") or []
        for token in _CLAIM_TOKEN.findall(_canonical(fact.get("value")))
    }


def _selected_link_check(
    text: str, brief: ContentBrief, context: TaskContextPackage
) -> dict:
    allowed_urls = {
        str(ref.get("url") or ref.get("locator", {}).get("url") or "")
        for ref in (context.rendered_context or {}).get("sources") or []
    }
    target_url = str((brief.target or {}).get("url") or "")
    if target_url:
        allowed_urls.add(target_url)
    output_urls = {url.rstrip(".,;:!?") for url in _URL.findall(text)}
    unknown_urls = sorted(url for url in output_urls if url not in allowed_urls)
    return _check(
        "internal_links",
        not unknown_urls,
        "Output contains an unselected URL",
        evidence=unknown_urls[:20],
    )


def _check(
    check_id: str, passed: bool, message: str, *, evidence: list | None = None
) -> dict:
    return {
        "check_id": check_id,
        "passed": passed,
        "blocking": not passed,
        "message": message,
        "evidence": evidence or [],
    }


async def persist_validation(
    session: AsyncSession, *, generation: ContentGeneration
) -> ContentValidation | None:
    if (
        not generation.brief_id
        or not generation.context_package_id
        or not generation.output_text
    ):
        return None
    existing = await session.scalar(
        select(ContentValidation).where(
            ContentValidation.content_generation_id == generation.id
        )
    )
    if existing is not None:
        return existing
    brief = await session.get(ContentBrief, generation.brief_id)
    context = await session.get(TaskContextPackage, generation.context_package_id)
    if brief is None or context is None:
        raise ContentConflictError("generation_provenance_missing")
    status, checks = validate_output(
        output_text=generation.output_text, brief=brief, context=context
    )
    validation = ContentValidation(
        id=_stable_id("validation", generation.id, CONTENT_VALIDATOR_VERSION),
        workspace_id=generation.workspace_id,
        project_id=generation.project_id,
        content_generation_id=generation.id,
        status=status,
        blocking=status == "blocked",
        checks=checks,
        validator_version=CONTENT_VALIDATOR_VERSION,
        brief_evidence_hash=brief.evidence_hash,
        context_manifest_hash=context.manifest_hash,
    )
    session.add(validation)
    generation.validator_snapshot = {
        "validator_version": CONTENT_VALIDATOR_VERSION,
        "status": status,
        "validation_id": str(validation.id),
    }
    return validation


async def get_validation(
    session: AsyncSession, *, workspace_id: uuid.UUID, generation_id: uuid.UUID
) -> ContentValidation:
    row = await session.scalar(
        select(ContentValidation).where(
            ContentValidation.workspace_id == workspace_id,
            ContentValidation.content_generation_id == generation_id,
        )
    )
    if row is None:
        raise ContentNotFoundError("Content validation not found")
    return row


async def create_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    generation_id: uuid.UUID,
    user_id: uuid.UUID,
    visible_content: str | None,
    structured_data: dict | None,
) -> tuple[ContentRevision, bool]:
    generation = await session.scalar(
        select(ContentGeneration).where(
            ContentGeneration.id == generation_id,
            ContentGeneration.workspace_id == workspace_id,
        )
    )
    if generation is None:
        raise ContentNotFoundError("Content generation not found")
    if generation.status != TASK_STATUS_SUCCEEDED or not generation.output_text:
        raise ContentConflictError("generation_not_complete")
    validation = await get_validation(
        session, workspace_id=workspace_id, generation_id=generation.id
    )
    existing = await session.scalar(
        select(ContentRevision).where(
            ContentRevision.content_generation_id == generation.id
        )
    )
    if existing is not None:
        return existing, False
    body = (
        visible_content if visible_content is not None else generation.output_text
    ).strip()
    if not body or len(body) > CONTENT_REVISION_MAX_CHARS:
        raise ContentConflictError("revision_content_invalid")
    revision = ContentRevision(
        id=_stable_id("revision", generation.id),
        workspace_id=generation.workspace_id,
        project_id=generation.project_id,
        content_generation_id=generation.id,
        state="draft",
        visible_content=body,
        structured_data=structured_data,
        content_hash=_hash({"visible": body, "structured_data": structured_data}),
        validation_snapshot={
            "validator_version": validation.validator_version,
            "status": validation.status,
            "checks": validation.checks,
            "source": "generation",
        },
        created_by_user_id=user_id,
    )
    session.add(revision)
    session.add(
        ContentRevisionTransition(
            workspace_id=generation.workspace_id,
            project_id=generation.project_id,
            revision_id=revision.id,
            from_state="",
            to_state="draft",
            actor_user_id=user_id,
            reason=f"validation:{validation.status}",
        )
    )
    return await _commit_revision(
        session, revision=revision, generation_id=generation.id
    )


async def _commit_revision(
    session: AsyncSession, *, revision: ContentRevision, generation_id: uuid.UUID
) -> tuple[ContentRevision, bool]:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(ContentRevision).where(
                ContentRevision.content_generation_id == generation_id
            )
        )
        if winner is None:
            raise
        return winner, False
    await session.refresh(revision)
    return revision, True


async def update_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    revision_id: uuid.UUID,
    user_id: uuid.UUID,
    visible_content: str,
    structured_data: dict | None,
) -> ContentRevision:
    revision = await _revision_for_update(
        session, workspace_id=workspace_id, revision_id=revision_id
    )
    if revision.state not in {"draft", "edited"}:
        raise ContentConflictError("revision_not_editable")
    body = visible_content.strip()
    _validate_visible_schema_parity(body, structured_data)
    generation = await session.get(ContentGeneration, revision.content_generation_id)
    if (
        generation is None
        or generation.brief_id is None
        or generation.context_package_id is None
    ):
        raise ContentConflictError("revision_provenance_missing")
    brief = await session.get(ContentBrief, generation.brief_id)
    context = await session.get(TaskContextPackage, generation.context_package_id)
    if brief is None or context is None:
        raise ContentConflictError("revision_provenance_missing")
    validation_status, checks = validate_output(
        output_text=body, brief=brief, context=context
    )
    previous = revision.state
    revision.visible_content = body
    revision.structured_data = structured_data
    revision.content_hash = _hash({"visible": body, "structured_data": structured_data})
    revision.validation_snapshot = {
        "validator_version": CONTENT_VALIDATOR_VERSION,
        "status": validation_status,
        "checks": checks,
        "source": "revision",
    }
    revision.state = "edited"
    session.add(_transition(revision, previous, "edited", user_id, "content_edited"))
    await session.commit()
    await session.refresh(revision)
    return revision


async def transition_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    revision_id: uuid.UUID,
    user_id: uuid.UUID,
    state: str,
    target_url: str,
    reason: str,
) -> ContentRevision:
    revision = await _revision_for_update(
        session, workspace_id=workspace_id, revision_id=revision_id
    )
    if state not in REVISION_TRANSITIONS.get(revision.state, frozenset()):
        raise ContentConflictError(
            f"revision_transition_invalid:{revision.state}:{state}"
        )
    if state in {"saved", "published_claimed"}:
        validation_status = str(
            (revision.validation_snapshot or {}).get("status") or ""
        )
        if validation_status != "passed":
            raise ContentValidationBlockedError("content_validation_blocked")
        _validate_visible_schema_parity(
            revision.visible_content, revision.structured_data
        )
    publication_target = ""
    if state == "published_claimed":
        publication_target = _canonical_publication_target(target_url)
    previous = revision.state
    revision.state = state
    now = datetime.now(UTC)
    if state == "saved":
        revision.saved_at = now
    if state == "published_claimed":
        revision.publication_target_url = publication_target
        revision.publication_claimed_at = now
    session.add(_transition(revision, previous, state, user_id, reason))
    await session.commit()
    await session.refresh(revision)
    return revision


def _canonical_publication_target(target_url: str) -> str:
    if not target_url.strip():
        raise ContentConflictError("publication_target_required")
    try:
        return canonical_identity(target_url)[0]
    except UrlPolicyError as exc:
        raise ContentConflictError("publication_target_invalid") from exc


def _validate_visible_schema_parity(visible: str, structured_data: dict | None) -> None:
    if structured_data is None:
        return
    if structured_data.get("@type") != "FAQPage":
        raise ContentValidationBlockedError("structured_data_type_not_allowed")
    entities = structured_data.get("mainEntity")
    if not isinstance(entities, list) or not entities:
        raise ContentValidationBlockedError("faq_schema_empty")
    normalized_visible = " ".join(visible.lower().split())
    for item in entities:
        question, answer = _faq_entity(item)
        if (
            " ".join(question.lower().split()) not in normalized_visible
            or " ".join(answer.lower().split()) not in normalized_visible
        ):
            raise ContentValidationBlockedError("faq_visible_schema_mismatch")


def _faq_entity(item: Any) -> tuple[str, str]:
    if not isinstance(item, dict):
        raise ContentValidationBlockedError("faq_schema_invalid")
    accepted_answer = item.get("acceptedAnswer")
    if not isinstance(accepted_answer, dict):
        raise ContentValidationBlockedError("faq_schema_invalid")
    question = str(item.get("name") or "").strip()
    answer = str(accepted_answer.get("text") or "").strip()
    if not question or not answer:
        raise ContentValidationBlockedError("faq_schema_invalid")
    return question, answer


async def _revision_for_update(
    session: AsyncSession, *, workspace_id: uuid.UUID, revision_id: uuid.UUID
) -> ContentRevision:
    revision = await session.scalar(
        select(ContentRevision)
        .where(
            ContentRevision.id == revision_id,
            ContentRevision.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if revision is None:
        raise ContentNotFoundError("Content revision not found")
    return revision


def _transition(
    revision: ContentRevision,
    from_state: str,
    to_state: str,
    actor_user_id: uuid.UUID,
    reason: str,
) -> ContentRevisionTransition:
    return ContentRevisionTransition(
        workspace_id=revision.workspace_id,
        project_id=revision.project_id,
        revision_id=revision.id,
        from_state=from_state,
        to_state=to_state,
        actor_user_id=actor_user_id,
        reason=reason.strip()[:512],
    )


async def list_revisions(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[ContentRevision]:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return list(
        (
            await session.scalars(
                select(ContentRevision)
                .where(
                    ContentRevision.workspace_id == workspace_id,
                    ContentRevision.project_id == project_id,
                )
                .order_by(ContentRevision.created_at.desc(), ContentRevision.id.desc())
                .limit(CONTENT_ARTIFACT_LIST_LIMIT)
            )
        ).all()
    )


async def get_revision(
    session: AsyncSession, *, workspace_id: uuid.UUID, revision_id: uuid.UUID
) -> ContentRevision:
    revision = await session.scalar(
        select(ContentRevision).where(
            ContentRevision.id == revision_id,
            ContentRevision.workspace_id == workspace_id,
        )
    )
    if revision is None:
        raise ContentNotFoundError("Content revision not found")
    return revision


async def verify_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    revision_id: uuid.UUID,
    site_snapshot_id: uuid.UUID,
) -> tuple[ContentVerification, bool]:
    revision = await _revision_for_update(
        session, workspace_id=workspace_id, revision_id=revision_id
    )
    if revision.state != "published_claimed":
        raise ContentConflictError("publication_not_claimed")
    existing = await session.scalar(
        select(ContentVerification).where(
            ContentVerification.revision_id == revision.id,
            ContentVerification.site_snapshot_id == site_snapshot_id,
        )
    )
    if existing is not None:
        return existing, False
    snapshot = await session.scalar(
        select(SiteHealthSnapshot).where(
            SiteHealthSnapshot.id == site_snapshot_id,
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == revision.project_id,
        )
    )
    if snapshot is None:
        raise ContentNotFoundError("Site snapshot not found")
    if (
        revision.publication_claimed_at is not None
        and snapshot.created_at <= revision.publication_claimed_at
    ):
        raise ContentConflictError("verification_snapshot_not_later")
    generation = await session.get(ContentGeneration, revision.content_generation_id)
    brief = (
        await session.get(ContentBrief, generation.brief_id)
        if generation and generation.brief_id
        else None
    )
    if brief is None:
        raise ContentConflictError("revision_brief_missing")
    page = await _verification_page(
        session,
        workspace_id=workspace_id,
        crawl_id=snapshot.crawl_id,
        target_url=revision.publication_target_url,
    )
    requirements = _verification_requirements(brief, page)
    status, observed_count = _verification_status(requirements)
    demand = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == revision.project_id,
            DemandSnapshot.site_snapshot_id == snapshot.id,
        )
        .order_by(DemandSnapshot.created_at.desc())
        .limit(1)
    )
    verification = _new_verification(
        revision=revision,
        snapshot=snapshot,
        demand=demand,
        status=status,
        requirements=requirements,
        observed_count=observed_count,
        target_page_available=page is not None,
    )
    session.add(verification)
    await session.commit()
    await session.refresh(verification)
    return verification, True


async def _verification_page(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    target_url: str,
) -> SiteFetchArtifact | None:
    return await session.scalar(
        select(SiteFetchArtifact)
        .join(SitePageAnalysis, SitePageAnalysis.artifact_id == SiteFetchArtifact.id)
        .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
        .where(
            SitePageAnalysis.crawl_id == crawl_id,
            SitePageAnalysis.workspace_id == workspace_id,
            SiteUrl.normalized_url == target_url,
        )
        .order_by(SitePageAnalysis.created_at.desc())
        .limit(1)
    )


def _verification_requirements(
    brief: ContentBrief, page: SiteFetchArtifact | None
) -> list[dict]:
    observed_text = _canonical(page.normalized_facts or {}) if page else ""
    requirements = []
    for criterion in brief.verification_criteria:
        question_id = str(criterion.get("question_id") or "")
        question: dict[str, Any] = next(
            (
                item
                for item in (brief.requirements or {}).get("questions") or []
                if item.get("question_id") == question_id
            ),
            {},
        )
        label = str(question.get("question") or question.get("label") or question_id)
        observed = bool(page and label.lower() in observed_text.lower())
        requirements.append(
            {**criterion, "state": "observed" if observed else "absent"}
        )
    return requirements


def _verification_status(requirements: list[dict]) -> tuple[str, int]:
    observed_count = sum(item["state"] == "observed" for item in requirements)
    if requirements and observed_count == len(requirements):
        return "observed", observed_count
    if observed_count:
        return "partial", observed_count
    return "absent", observed_count


def _new_verification(
    *,
    revision: ContentRevision,
    snapshot: SiteHealthSnapshot,
    demand: DemandSnapshot | None,
    status: str,
    requirements: list[dict],
    observed_count: int,
    target_page_available: bool,
) -> ContentVerification:
    return ContentVerification(
        id=_stable_id("verification", revision.id, snapshot.id),
        workspace_id=revision.workspace_id,
        project_id=revision.project_id,
        revision_id=revision.id,
        site_snapshot_id=snapshot.id,
        demand_snapshot_id=demand.id if demand else None,
        status=status,
        requirements=requirements,
        comparison={
            "publication_claimed_at": revision.publication_claimed_at.isoformat()
            if revision.publication_claimed_at
            else None,
            "site_snapshot_created_at": snapshot.created_at.isoformat(),
            # Site Health no longer owns a comparison projection. Retain the
            # stable response shape while making the unavailable observation
            # explicit rather than fabricating a comparison.
            "site_comparison": None,
            "demand_comparison": demand.comparison if demand else None,
            "causality": "descriptive_only",
        },
        coverage={
            "observed": observed_count,
            "required": len(requirements),
            "target_page_available": target_page_available,
        },
        verifier_version=CONTENT_VERIFIER_VERSION,
    )


async def list_verifications(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[ContentVerification]:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return list(
        (
            await session.scalars(
                select(ContentVerification)
                .where(
                    ContentVerification.workspace_id == workspace_id,
                    ContentVerification.project_id == project_id,
                )
                .order_by(
                    ContentVerification.created_at.desc(), ContentVerification.id.desc()
                )
                .limit(CONTENT_ARTIFACT_LIST_LIMIT)
            )
        ).all()
    )
