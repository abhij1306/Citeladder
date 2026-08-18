# Site Health crawl planner (Task 3 — invariant 9 determinism, invariant 3 freeze).
#
# Owns crawl CREATION for the Site Health subsystem, mirroring the audit
# ``planner.create_audit`` freeze/flush/seed/transition/commit shape:
#
#   1. Load + authorize the workspace-scoped project and derive the crawl root
#      from ``Project.website_url`` (canonicalized through the URL policy).
#   2. Derive + FREEZE the primary registrable domain (offline PSL), root
#      URL/host, and the validated include/exclude narrowing globs onto the
#      project's ``SiteHealthProfile`` (created on first crawl).
#   3. Refresh the workspace runtime row; a zero monitored-URL allowance
#      freezes ``sample_mode=True`` and locks the row so the workspace-wide
#      Free allowance is serialized at creation time.
#   4. Freeze the operational settings + runtime projection + rule/scoring
#      into ``SiteCrawl.configuration`` so a live env change never alters an
#      in-flight run (invariant 9), store the normalized 64-bit ``random_seed``.
#   5. Seed the in-scope root ``discover`` task (generation 0), plus re-seed the
#      persistent monitored set's ``analyze`` tasks on a recrawl.
#   6. Drive the crawl DRAFT -> VALIDATING -> QUEUED (overall) and
#      PENDING -> RUNNING (discovery) through ``state_events`` guards, record
#      the lifecycle events, and commit with the root task ``queued`` so the
#      worker can claim it.
#
# A second active crawl for the same project is rejected (409
# ``crawl_already_active`` / ``CODE_CRAWL_ALREADY_ACTIVE``).
from __future__ import annotations

import csv
import secrets
import uuid
from datetime import UTC, datetime
from io import StringIO

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    classify_url_admission,
    registrable_domain,
    split_host_port,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    CLASSIFIER_VERSION,
    CODE_ADVANCED_CONTROLS_UNAVAILABLE,
    CODE_CRAWL_ALREADY_ACTIVE,
    CODE_DISCOVERY_LIMIT_EXCEEDED,
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_DRAFT,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_QUEUED,
    CRAWL_STATUS_VALIDATING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    EVENT_CRAWL_CREATED,
    EVENT_CRAWL_QUEUED,
    EXTRACTOR_VERSION,
    OBSERVATION_SOURCE_ROOT,
    RULE_CATALOG_VERSION,
    SCORING_VERSION,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    DISCOVERY_MODE_SAMPLE,
    INPUT_MODE_AUTO,
    INPUT_MODE_EXACT_URLS,
    INPUT_MODES,
    INVENTORY_SOURCE_CRAWL_IDS_KEY,
    MANUAL_PHASE_LIFECYCLE_KEY,
    PHASE_DISCOVERY,
    PHASE_RUN_RUNNING,
    URL_ADMISSION_POLICY_VERSION,
    URL_EXCLUSION_DUPLICATE,
    URL_EXCLUSION_INVALID,
)
from app.core.config.site_health_page_profiles import PAGE_PROFILE_RULE_VERSION
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.site_health_taxonomy import (
    PAGE_KINDS,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_workspace,
)
from app.domain.site_health.discovery import add_automatic_root
from app.domain.site_health.entitlements import lock_runtime
from app.domain.site_health.inventory_scope import freeze_inventory_lineage
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.selection import seed_monitored_targets
from app.domain.site_health.state_events import (
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.models.project import Project
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import SiteUrl, SiteUrlObservation


# Bound the number of include/exclude narrowing globs accepted at creation so a
# request can never freeze an unbounded pattern list into the crawl config.
class CrawlPlanError(ValueError):
    """Raised when a crawl cannot be created (bad root/globs, missing project).

    Carries a stable ``code`` so the API layer can map it to the right HTTP
    status (422 for validation, 409 for an already-active crawl).
    """

    code: str = "invalid_crawl_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class CrawlAlreadyActiveError(CrawlPlanError):
    """A project already has an active crawl (409)."""

    code = CODE_CRAWL_ALREADY_ACTIVE


def _normalize_seed(value: str | None) -> str:
    """Return a decimal string for a 64-bit unsigned seed (invariant 9).

    Accepts an explicit seed (any 64-bit-representable int) or generates a
    fresh 64-bit one when omitted, so the deterministic frontier order is
    stored and exactly replayable.
    """
    if value is None or not str(value).strip():
        return str(secrets.randbits(64))
    try:
        seed_int = int(str(value).strip())
    except ValueError as exc:
        raise CrawlPlanError("random_seed must be an integer") from exc
    return str(seed_int & ((1 << 64) - 1))


def _normalize_globs(globs: list[str] | None, *, label: str) -> list[str]:
    """Validate + normalize a bounded include/exclude glob list.

    Rejects a list longer than ``MAX_NARROWING_GLOBS`` or a single pattern
    longer than ``MAX_GLOB_LENGTH`` (422). Blank patterns are dropped. The
    result is stored verbatim on the profile and matched against canonical URLs
    by ``url_policy.narrow`` (exclusions win; globs only ever narrow scope).
    """
    if not globs:
        return []
    cleaned: list[str] = []
    for raw in globs:
        pattern = str(raw or "").strip()
        if not pattern:
            continue
        if len(pattern) > site_health_settings.max_glob_length:
            raise CrawlPlanError(
                f"{label} glob exceeds max length "
                f"{site_health_settings.max_glob_length}"
            )
        cleaned.append(pattern)
    if len(cleaned) > site_health_settings.max_narrowing_globs:
        raise CrawlPlanError(
            f"too many {label} globs (max {site_health_settings.max_narrowing_globs})"
        )
    return cleaned


async def _load_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    lock: bool = False,
) -> Project:
    stmt = select(Project).where(
        Project.id == project_id,
        Project.workspace_id == workspace_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    project = await session.scalar(stmt)
    if project is None:
        raise CrawlPlanError("Project not found", code="project_not_found")
    return project


async def _has_active_crawl(session: AsyncSession, *, project_id: uuid.UUID) -> bool:
    # A paused advanced-control crawl has no live tasks, so the product may
    # start a fresh crawl from that parked record. Running/queued work still
    # remains single-crawl-per-project.
    conflicting_statuses = CRAWL_ACTIVE_STATUSES - {CRAWL_STATUS_PAUSED}
    existing = await session.scalar(
        select(func.count())
        .select_from(SiteCrawl)
        .where(SiteCrawl.project_id == project_id)
        .where(SiteCrawl.status.in_(list(conflicting_statuses)))
    )
    return bool(existing and existing > 0)


async def _upsert_profile(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    root_url: str,
    root_host: str,
    root_registrable_domain: str,
    include_globs: list[str],
    exclude_globs: list[str],
) -> SiteHealthProfile:
    """Create or refresh the project's ``SiteHealthProfile`` (frozen scope).

    The profile is a project-owned mutable projection (unique ``project_id``):
    it holds the canonical root, the derived registrable domain, and the
    validated narrowing globs the worker enforces. Re-running a crawl refreshes
    them so a changed website URL / narrowing takes effect on the NEXT crawl
    without disturbing the persistent monitored set or ``selection_version``.
    """
    profile = await session.scalar(
        select(SiteHealthProfile).where(SiteHealthProfile.project_id == project_id)
    )
    if profile is None:
        profile = SiteHealthProfile(
            workspace_id=workspace_id,
            project_id=project_id,
        )
        session.add(profile)
    profile.root_url = root_url
    profile.root_host = root_host
    profile.registrable_domain = root_registrable_domain
    profile.include_globs = include_globs or None
    profile.exclude_globs = exclude_globs or None
    await session.flush()
    return profile


def _is_sample_mode(runtime) -> bool:
    """Single source of truth for whether a workspace crawls in sample mode.

    A zero monitored-URL allowance crawls a deterministic sample (no user
    selection); a positive allowance runs the full progressive inventory. Both
    ``_frozen_configuration`` and ``create_crawl`` derive ``sample_mode`` from
    the runtime row here so they can never diverge.
    """
    return runtime.discovery_mode == DISCOVERY_MODE_SAMPLE


def _manual_phase_configuration(enabled: bool) -> dict[str, bool]:
    return {MANUAL_PHASE_LIFECYCLE_KEY: True} if enabled else {}


def _frozen_configuration(
    *,
    root_registrable_domain: str,
    include_globs: list[str],
    exclude_globs: list[str],
    runtime,
    input_mode: str = INPUT_MODE_AUTO,
    requested_page_limit: int | None = None,
    seed_urls: list[str] | None = None,
    page_kinds: list[str] | None = None,
    manual_phase_lifecycle: bool = False,
) -> dict:
    """Freeze the operational settings + runtime projection (invariant 9).

    Everything the worker needs to run this crawl deterministically regardless
    of a later live env or entitlement change: the narrowing scope, the frozen
    neutral policy limits, the resolver provenance, the crawler bounds, and
    the rule/scoring versions.
    """
    s = site_health_settings
    configuration = {
        "discovery_mode": runtime.discovery_mode,
        "sample_mode": _is_sample_mode(runtime),
        "count_disclosure": bool(runtime.count_disclosure),
        "sample_url_limit": int(runtime.sample_url_limit),
        "monitored_url_limit": int(runtime.monitored_url_limit),
        "discovery_url_cap": runtime.discovery_url_cap,
        "resolved_registry_revision": runtime.resolved_registry_revision,
        "resolved_entitlement_lifecycle_version": int(
            runtime.resolved_entitlement_lifecycle_version
        ),
        "root_registrable_domain": root_registrable_domain,
        "include_globs": include_globs,
        "exclude_globs": exclude_globs,
        "url_admission_policy_version": URL_ADMISSION_POLICY_VERSION,
        "page_kind_classifier_version": CLASSIFIER_VERSION,
        "page_profile_rule_version": PAGE_PROFILE_RULE_VERSION,
        "input_mode": input_mode,
        "requested_page_limit": requested_page_limit,
        **_manual_phase_configuration(manual_phase_lifecycle),
        "max_discovery_urls": s.max_discovery_urls,
        "max_analysis_urls": s.max_analysis_urls,
        "seed_urls": list(seed_urls or []),
        "page_kinds": list(page_kinds or []),
        "max_frontier_urls": s.max_frontier_urls,
        "max_crawl_depth": s.max_crawl_depth,
        "admission_batch_size": s.admission_batch_size,
        "global_concurrency": s.global_concurrency,
        "per_host_concurrency": s.per_host_concurrency,
        "per_host_delay_seconds": s.per_host_delay_seconds,
        "request_timeout_seconds": s.request_timeout_seconds,
        "max_redirects": s.max_redirects,
        "max_response_wire_bytes": s.max_response_wire_bytes,
        "max_response_decoded_bytes": s.max_response_decoded_bytes,
        "max_attempts": s.max_attempts,
        "extractor_version": EXTRACTOR_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "rule_catalog_version": RULE_CATALOG_VERSION,
        "scoring_version": SCORING_VERSION,
    }
    if input_mode == INPUT_MODE_AUTO:
        entitlement_limit = (
            int(runtime.sample_url_limit)
            if _is_sample_mode(runtime)
            else int(runtime.monitored_url_limit)
        )
        configuration[AUTOMATIC_MONITOR_LIMIT_KEY] = min(
            int(requested_page_limit or 0), entitlement_limit
        )
    return configuration


def _controls_for_request(
    *,
    input_mode: str | None,
    requested_page_limit: int | None,
    seed_urls: list[str] | None,
    page_kinds: list[str] | None,
) -> tuple[str, int, list[str], list[str]]:
    """Validate development-only crawl controls and return frozen values."""
    mode = input_mode or INPUT_MODE_AUTO
    raw_seeds = list(seed_urls or [])
    selected_types = list(page_kinds or [])
    _validate_control_values(mode, raw_seeds, selected_types)
    if (
        _advanced_controls_requested(mode, raw_seeds, selected_types)
        and not site_health_settings.advanced_controls_enabled
    ):
        raise CrawlPlanError(
            "advanced crawl controls are unavailable",
            code=CODE_ADVANCED_CONTROLS_UNAVAILABLE,
        )
    if mode == INPUT_MODE_EXACT_URLS and not raw_seeds:
        raise CrawlPlanError(
            "exact_urls requires seed_urls", code="invalid_crawl_request"
        )
    limit = _resolved_page_limit(requested_page_limit)
    return mode, limit, raw_seeds, selected_types


def _validate_control_values(
    mode: str, raw_seeds: list[str], selected_types: list[str]
) -> None:
    if mode not in INPUT_MODES:
        raise CrawlPlanError("unknown input_mode", code="invalid_crawl_request")
    if len(raw_seeds) > site_health_settings.max_seed_urls:
        raise CrawlPlanError("too many seed_urls", code="invalid_crawl_request")
    if any(value not in PAGE_KINDS for value in selected_types):
        raise CrawlPlanError("unknown page kind", code="invalid_crawl_request")


def _advanced_controls_requested(
    mode: str,
    raw_seeds: list[str],
    selected_types: list[str],
) -> bool:
    return mode != INPUT_MODE_AUTO or bool(raw_seeds) or bool(selected_types)


def _resolved_page_limit(requested_page_limit: int | None) -> int:
    limit = (
        requested_page_limit
        if requested_page_limit is not None
        else site_health_settings.automatic_page_limit
    )
    maximum = (
        site_health_settings.max_discovery_urls
        if site_health_settings.advanced_controls_enabled
        else site_health_settings.max_requested_page_limit
    )
    if limit <= 0 or limit > maximum:
        raise CrawlPlanError(
            "requested_page_limit is outside the allowed range",
            code=CODE_DISCOVERY_LIMIT_EXCEEDED,
        )
    return int(limit)


def _admit_seed_urls(
    seed_urls: list[str], *, root_domain: str, includes: list[str], excludes: list[str]
) -> list[str]:
    """Normalize manual/upload seeds through the same hard admission gate."""
    accepted: list[str] = []
    seen: set[str] = set()
    for raw in seed_urls:
        decision = classify_url_admission(
            raw,
            root_registrable_domain=root_domain,
            include_globs=includes,
            exclude_globs=excludes,
        )
        if not decision.accepted or not decision.canonical_url:
            raise CrawlPlanError(
                "seed URL is not admissible",
                code=decision.reason_code or "invalid_crawl_request",
            )
        if decision.canonical_url not in seen:
            seen.add(decision.canonical_url)
            accepted.append(decision.canonical_url)
    return accepted


def _preview_input_rows(content: object, input_format: str) -> list[str]:
    """Parse bounded text/CSV/JSON preview input without any persistence."""
    if isinstance(content, list):
        return [str(value) for value in content]
    if isinstance(content, dict):
        values = content.get("urls", content.get("items", []))
        if not isinstance(values, list):
            raise CrawlPlanError("JSON preview input must contain a URL list")
        return [
            str(value.get("url", "")) if isinstance(value, dict) else str(value)
            for value in values
        ]
    raw = str(content or "")
    if len(raw.encode("utf-8")) > site_health_settings.max_preview_input_bytes:
        raise CrawlPlanError("preview input is too large")
    if input_format == "csv":
        return [row[0] if row else "" for row in csv.reader(StringIO(raw))]
    if input_format == "json":
        import json

        try:
            return _preview_input_rows(json.loads(raw), "json")
        except (TypeError, ValueError) as exc:
            raise CrawlPlanError("invalid JSON preview input") from exc
    return raw.splitlines()


async def preview_crawl_urls(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    content: object,
    input_format: str = "text",
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
) -> dict:
    """Build a bounded, workspace-authorized admission preview (no writes)."""
    project = await _load_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    try:
        root_url = canonicalize(str(project.website_url or ""))
    except UrlPolicyError as exc:
        raise CrawlPlanError(
            "Project has no usable website_url", code="invalid_root"
        ) from exc
    root_domain = registrable_domain(root_url)
    includes = _normalize_globs(include_globs, label="include")
    excludes = _normalize_globs(exclude_globs, label="exclude")
    rows: list[dict] = []
    seen: set[str] = set()
    aggregate: dict[str, int] = {"accepted": 0, "duplicate": 0, "rejected": 0}
    for row_number, raw in enumerate(
        _preview_input_rows(content, input_format), start=1
    ):
        if len(rows) >= site_health_settings.max_preview_rows:
            break
        decision = classify_url_admission(
            raw,
            root_registrable_domain=root_domain,
            include_globs=includes,
            exclude_globs=excludes,
        )
        reason = decision.reason_code
        accepted = decision.accepted
        if accepted and decision.canonical_url in seen:
            accepted = False
            reason = URL_EXCLUSION_DUPLICATE
            aggregate["duplicate"] += 1
        elif accepted:
            seen.add(decision.canonical_url or "")
            aggregate["accepted"] += 1
        else:
            aggregate["rejected"] += 1
        rows.append(
            {
                "row": row_number,
                "input": str(raw)[: site_health_settings.max_glob_length],
                "accepted": accepted,
                "canonical_url": decision.canonical_url,
                "reason_code": reason
                or (URL_EXCLUSION_INVALID if not accepted else None),
                "value_kind": decision.value_kind,
                "priority": decision.priority,
            }
        )
    return {
        "items": rows,
        "truncated": len(rows) >= site_health_settings.max_preview_rows,
        "counts": aggregate,
        "policy_version": URL_ADMISSION_POLICY_VERSION,
    }


async def _initial_discovery_phase_run_id(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    requested_count: int,
    enabled: bool,
) -> uuid.UUID | None:
    if not enabled:
        return None
    run = SiteCrawlPhaseRun(
        workspace_id=crawl.workspace_id,
        crawl_id=crawl.id,
        phase=PHASE_DISCOVERY,
        ordinal=1,
        status=PHASE_RUN_RUNNING,
        requested_count=requested_count,
    )
    session.add(run)
    await session.flush()
    return run.id


async def create_crawl(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    random_seed: str | None = None,
    input_mode: str | None = None,
    requested_page_limit: int | None = None,
    seed_urls: list[str] | None = None,
    page_kinds: list[str] | None = None,
    commit: bool = True,
) -> SiteCrawl:
    """Create + queue a Site Health crawl (freeze scope, seed the root task).

    Derives the crawl root from ``Project.website_url``, freezes the primary
    registrable domain + narrowing onto the profile and the operational
    settings + runtime projection into ``SiteCrawl.configuration``, seeds the in-scope
    root ``discover`` task (and re-seeds the persistent monitored set's
    ``analyze`` tasks), then drives the lifecycle to ``queued`` and commits so
    the worker can claim the root. Rejects a second active crawl for the same
    project (409). Caller owns nothing else — this commits.
    """
    # Lock the project row before checking active state so two concurrent
    # requests for the same project serialize instead of racing past
    # ``_has_active_crawl()`` and both creating a crawl.
    project = await _load_project(
        session, workspace_id=workspace_id, project_id=project_id, lock=True
    )

    if await _has_active_crawl(session, project_id=project_id):
        raise CrawlAlreadyActiveError("Project already has an active crawl")

    raw_root = str(project.website_url or "").strip()
    if not raw_root:
        raise CrawlPlanError("Project has no website_url to crawl", code="invalid_root")
    try:
        root_url = canonicalize(raw_root)
    except UrlPolicyError as exc:
        raise CrawlPlanError(f"invalid crawl root: {exc}", code="invalid_root") from exc

    root_host, _port = split_host_port(root_url)
    root_registrable_domain = registrable_domain(root_url)
    if not root_registrable_domain:
        raise CrawlPlanError(
            "could not derive a registrable domain from the root URL",
            code="invalid_root",
        )

    includes = _normalize_globs(include_globs, label="include")
    excludes = _normalize_globs(exclude_globs, label="exclude")
    root_decision = classify_url_admission(
        raw_root,
        root_registrable_domain=root_registrable_domain,
        include_globs=includes,
        exclude_globs=excludes,
    )
    if not root_decision.accepted:
        raise CrawlPlanError("crawl root is not admissible", code="invalid_root")
    mode, page_limit, raw_seeds, selected_types = _controls_for_request(
        input_mode=input_mode,
        requested_page_limit=requested_page_limit,
        seed_urls=seed_urls,
        page_kinds=page_kinds,
    )
    manual_phase_lifecycle = _advanced_controls_requested(
        mode, raw_seeds, selected_types
    )
    accepted_seeds = _admit_seed_urls(
        raw_seeds,
        root_domain=root_registrable_domain,
        includes=includes,
        excludes=excludes,
    )

    # Refresh (seed if missing) the runtime row BEFORE mutating the profile.
    # ``replace_monitored_set()`` locks the runtime row before profile, so
    # this path must match that lock order to avoid a deadlock cycle. In
    # automatic mode, LOCK the runtime row so root admission and the
    # workspace-wide allowance are serialized against concurrent projects.
    runtime = await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=datetime.now(UTC)
    )
    sample_mode = _is_sample_mode(runtime)
    if sample_mode or mode == INPUT_MODE_AUTO:
        runtime = await lock_runtime(session, workspace_id)
        # Re-derive sample_mode from the LOCKED row: the projection may have
        # changed between the unlocked refresh above and acquiring the lock.
        sample_mode = _is_sample_mode(runtime)

    profile = await _upsert_profile(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        root_url=root_url,
        root_host=root_host,
        root_registrable_domain=root_registrable_domain,
        include_globs=includes,
        exclude_globs=excludes,
    )

    seed = _normalize_seed(random_seed)
    configuration = _frozen_configuration(
        root_registrable_domain=root_registrable_domain,
        include_globs=includes,
        exclude_globs=excludes,
        runtime=runtime,
        input_mode=mode,
        requested_page_limit=page_limit,
        seed_urls=accepted_seeds,
        page_kinds=selected_types,
        manual_phase_lifecycle=manual_phase_lifecycle,
    )

    # Freeze the EXACT industry pack once, here. Resolving it per page (or at
    # read time) would let a later project-settings change silently reinterpret
    # this crawl's analyses under a different pack.

    # Keep a full-inventory project's earlier discovered URLs visible while
    # a new analysis crawl re-discovers the site. The lineage references
    # immutable observations; it never copies or fabricates evidence. Sample
    # crawls inherit nothing, preserving sample-mode count non-disclosure.
    if not sample_mode:
        previous_crawl = await session.scalar(
            select(SiteCrawl)
            .where(
                SiteCrawl.workspace_id == workspace_id,
                SiteCrawl.project_id == project_id,
                SiteCrawl.sample_mode.is_(False),
            )
            .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
            .limit(1)
        )
        lineage = freeze_inventory_lineage(
            previous_crawl,
            limit=site_health_settings.inventory_history_crawl_limit,
        )
        if lineage:
            configuration[INVENTORY_SOURCE_CRAWL_IDS_KEY] = lineage

    crawl = SiteCrawl(
        workspace_id=workspace_id,
        project_id=project_id,
        profile_id=profile.id,
        status=CRAWL_STATUS_DRAFT,
        root_url=root_url,
        random_seed=seed,
        configuration=configuration,
        sample_mode=sample_mode,
        discovery_requested_count=page_limit,
        extractor_version=EXTRACTOR_VERSION,
        analyzer_version=ANALYZER_VERSION,
        rule_catalog_version=RULE_CATALOG_VERSION,
        scoring_version=SCORING_VERSION,
    )
    session.add(crawl)
    await session.flush()  # assign crawl.id

    discovery_phase_run_id = await _initial_discovery_phase_run_id(
        session,
        crawl=crawl,
        requested_count=page_limit,
        enabled=bool(configuration.get(MANUAL_PHASE_LIFECYCLE_KEY)),
    )

    # All roots/manual seeds pass the same policy above. Exact mode deliberately
    # creates only the accepted explicit tasks; it cannot discover descendants.
    initial_urls = (
        accepted_seeds if mode == INPUT_MODE_EXACT_URLS else [root_url, *accepted_seeds]
    )[:page_limit]
    seen_initial: set[str] = set()
    for position, initial_url in enumerate(initial_urls):
        if initial_url in seen_initial:
            continue
        seen_initial.add(initial_url)
        _canonical, url_hash = canonical_identity(initial_url)
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=workspace_id,
                phase_run_id=discovery_phase_run_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=initial_url,
                url_hash=url_hash,
                depth=0,
                generation=0,
                idempotency_key=f"{crawl.id}:{TASK_KIND_DISCOVER}:{url_hash}:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=position,
            )
        )

    # Re-seed the persistent monitored set: on a recrawl the active monitored
    # URLs get fresh analyze tasks so their facts/scores refresh. On a first
    # crawl there is no monitored set yet, so this is a no-op.
    await seed_monitored_targets(session, crawl=crawl)
    if mode == INPUT_MODE_AUTO:
        await add_automatic_root(session, crawl, runtime=runtime)

    # Drive the lifecycle through the guarded state machine (invariant 9).
    apply_crawl_status(crawl, CRAWL_STATUS_VALIDATING)
    apply_crawl_status(crawl, CRAWL_STATUS_QUEUED)
    apply_discovery_status(crawl, DISCOVERY_STATUS_RUNNING)

    count_disclosure = bool(configuration.get("count_disclosure", False))
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_CREATED,
        message="crawl created",
        payload={
            "root_url": root_url,
            "sample_mode": sample_mode,
            "source_kind": OBSERVATION_SOURCE_ROOT,
        },
        count_disclosure=count_disclosure,
    )
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_QUEUED,
        message="crawl queued",
        count_disclosure=count_disclosure,
    )

    if not commit:
        return crawl
    await session.commit()
    return await get_crawl(session, workspace_id=workspace_id, crawl_id=crawl.id)


async def create_page_rerun_crawl(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    profile: SiteHealthProfile,
    site_url: SiteUrl,
    runtime,
    random_seed: str | None = None,
) -> SiteCrawl:
    """Create a fresh, single-page rerun crawl for one already-known URL.

    A "Re-audit this page" action must work even when the project's most
    recent crawl is TERMINAL (completed/partial/failed): enqueuing an analyze
    task into a terminal crawl is cooperatively cancelled by the worker, so it
    would never run. Instead this mints a NEW active crawl whose ONLY work is a
    single ``analyze`` task for ``site_url`` — no ``discover`` root task, so it
    never re-crawls the whole site.

    The fresh crawl:

    - reuses the project's frozen ``SiteHealthProfile`` (root/scope/versions)
      and the current runtime projection, so scope/version provenance matches
      a normal crawl;
    - records the target's ``SiteUrlObservation`` up front (source_kind
      ``root``) so the page-detail projection — which scopes URLs to a crawl's
      admitted/observed set — resolves the URL on the new crawl immediately;
    - starts with ``discovery_status=completed`` and ``discovered_url_count=1``
      so the shared worker reconciliation terminalizes on the single analyze
      task alone (it is never mis-classified as a fully-failed discovery);
    - is left QUEUED with one QUEUED ``analyze`` task (generation 0 — a fresh
      crawl owns a fresh slot namespace) for the worker to claim.

    The caller owns the transaction boundary (flush, no commit), mirroring
    ``rerun_page``. Returns the new ``SiteCrawl`` (unrefreshed).
    """
    rerun_admission = classify_url_admission(
        site_url.normalized_url,
        root_registrable_domain=profile.registrable_domain or None,
        include_globs=list(profile.include_globs or []),
        exclude_globs=list(profile.exclude_globs or []),
    )
    if not rerun_admission.accepted:
        raise CrawlPlanError(
            "page is not admissible for rerun",
            code=rerun_admission.reason_code or "invalid_crawl_request",
        )
    sample_mode = _is_sample_mode(runtime)
    configuration = _frozen_configuration(
        root_registrable_domain=profile.registrable_domain or "",
        include_globs=list(profile.include_globs or []),
        exclude_globs=list(profile.exclude_globs or []),
        runtime=runtime,
        requested_page_limit=site_health_settings.automatic_page_limit,
    )
    # A rerun freezes its pack exactly as a full crawl does. Without this the
    # reanalyzed page came back UNPACKED — no industry role, no knowledge, no
    # provenance — so rerunning a page to check a fix silently discarded the
    # very classification the fix was meant to change.
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    seed = _normalize_seed(random_seed)

    crawl = SiteCrawl(
        workspace_id=workspace_id,
        project_id=project_id,
        profile_id=profile.id,
        status=CRAWL_STATUS_DRAFT,
        root_url=profile.root_url or site_url.normalized_url,
        random_seed=seed,
        configuration=configuration,
        sample_mode=sample_mode,
        extractor_version=EXTRACTOR_VERSION,
        analyzer_version=ANALYZER_VERSION,
        rule_catalog_version=RULE_CATALOG_VERSION,
        scoring_version=SCORING_VERSION,
        # A single-page rerun performs no discovery: pin the discovery
        # sub-state complete with one observed URL so reconciliation never
        # treats the empty discover plan as a fully-failed crawl.
        discovery_status=DISCOVERY_STATUS_COMPLETED,
        discovered_url_count=1,
        admitted_url_count=1,
        inventory_complete=True,
    )
    session.add(crawl)
    await session.flush()  # assign crawl.id

    # Record the target URL's observation so the page-detail projection (which
    # scopes URLs to a crawl's observed set) resolves it on this fresh crawl.
    from sqlalchemy.dialects.postgresql import insert as _pg_insert

    await session.execute(
        _pg_insert(SiteUrlObservation)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            crawl_id=crawl.id,
            site_url_id=site_url.id,
            source_kind=OBSERVATION_SOURCE_ROOT,
            parent_site_url_id=None,
            source_artifact_id=None,
            depth=0,
            observed_url=site_url.normalized_url,
            final_url=site_url.normalized_url,
            status_code=None,
            content_type="",
            title=site_url.latest_title or "",
        )
        .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
    )

    # Seed exactly ONE analyze task (generation 0) for the target URL.
    analyze_task = SiteCrawlTask(
        crawl_id=crawl.id,
        workspace_id=workspace_id,
        site_url_id=site_url.id,
        task_kind=TASK_KIND_ANALYZE,
        requested_url=site_url.normalized_url,
        url_hash=site_url.url_hash,
        depth=0,
        generation=0,
        idempotency_key=(f"{crawl.id}:{TASK_KIND_ANALYZE}:{site_url.url_hash}:0"),
        status=TASK_STATUS_QUEUED,
        randomized_position=0,
    )
    session.add(analyze_task)

    # Drive the lifecycle through the guarded state machine to QUEUED so the
    # worker can claim the analyze task (invariant 9). Analysis stays PENDING
    # until the worker moves it RUNNING on first claim.
    apply_crawl_status(crawl, CRAWL_STATUS_VALIDATING)
    apply_crawl_status(crawl, CRAWL_STATUS_QUEUED)

    count_disclosure = bool(configuration.get("count_disclosure", False))
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_CREATED,
        message="page rerun crawl created",
        payload={
            "root_url": crawl.root_url,
            "sample_mode": sample_mode,
            "source_kind": OBSERVATION_SOURCE_ROOT,
            "rerun_site_url_id": str(site_url.id),
        },
        count_disclosure=count_disclosure,
    )
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_QUEUED,
        message="crawl queued",
        count_disclosure=count_disclosure,
    )
    await session.flush()
    return crawl


async def get_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl:
    """Load a workspace-scoped crawl (eager events) or raise ``CrawlPlanError``."""
    crawl = await session.scalar(
        select(SiteCrawl)
        .options(selectinload(SiteCrawl.events))
        .where(
            SiteCrawl.id == crawl_id,
            SiteCrawl.workspace_id == workspace_id,
        )
    )
    if crawl is None:
        raise CrawlPlanError("Crawl not found", code="crawl_not_found")
    return crawl
