# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.site_health_contracts import (
    PAGE_ANALYSIS_STATUS_PENDING,
)
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER
from app.core.database import Base

from .common import (
    _FK_PROJECT,
    _FK_SITE_CRAWL,
    _FK_SITE_FETCH_ARTIFACT,
    _FK_SITE_OBSERVED_ARCHITECTURE,
    _FK_SITE_PAGE_ANALYSIS,
    _FK_SITE_RULE_EVALUATION,
    _FK_SITE_URL,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _utcnow,
)


class SitePageAnalysis(Base):
    """The single page-understanding owner (append-only; DTO ``PageUnderstanding``).

    Carries the Technical/AEO/overall scores, the analysis status, the
    analyzer/scoring versions, the generic ``page_kind``, and the source
    evaluation/artifact ID arrays for full provenance.

    APPEND-ONLY, with its own UUID identity and one ``is_current`` row per page
    in a crawl. ``artifact_id`` is provenance and may be reused by repeated
    analyses of the same immutable discovery evidence.

    ``PageUnderstanding`` is this row's API/DTO name, NOT a second table.
    """

    __tablename__ = "site_page_analyses"
    __table_args__ = (
        # The UUID primary key owns row identity. This page-scoped constraint
        # matches the writer's supersede boundary without making reusable
        # artifact provenance unique.
        Index(
            "uq_site_page_analysis_current",
            "crawl_id",
            "site_url_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_PROJECT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), default=PAGE_ANALYSIS_STATUS_PENDING
    )
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aeo_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    scoring_version: Mapped[str] = mapped_column(String(32), default="")
    # v2 P1: the deterministic page-type classification + its version
    # (invariant 4). ``other`` is the fail-safe default when no signal
    # classifies the page.
    page_kind: Mapped[str] = mapped_column(String(24), default=PAGE_KIND_OTHER)
    classifier_version: Mapped[str] = mapped_column(String(32), default="")
    # The bounded classifier evidence (ranked signals / confidence / schema
    # suggestion) behind the classification — the same dict
    # ``PageKindAssessment.to_evidence()`` produces, persisted for the per-URL
    # detail "why this type?" disclosure.
    page_kind_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Observed page traits, independent of the primary kind: a product page
    # with an FAQ block retains both observations without the taxonomy growing
    # a product_with_faq. Stored as a queryable array rather
    # than nested in the evidence blob so the pages and issues surfaces can
    # slice by trait. Traits carry their own version: they are derived from
    # the same facts but never from the classification.
    page_traits: Mapped[list | None] = mapped_column(ARRAY(String(32)), nullable=True)
    traits_version: Mapped[str] = mapped_column(String(32), default="")

    # Exactly one live row per page within a crawl (see the partial index).
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)

    # Source provenance arrays (evaluation + artifact IDs).
    source_evaluation_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SiteRuleEvaluation(Base):
    """Immutable per-rule evaluation for one analysis and evidence scope.

    The nullable architecture identity distinguishes crawl-level structural
    evaluations from ordinary page/finalize evaluations. ``NULLS NOT DISTINCT``
    preserves one ordinary evaluation per analysis/rule while allowing each
    immutable architecture projection to carry its own result.
    """

    __tablename__ = "site_rule_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "rule_id",
            "source_architecture_id",
            name="uq_site_rule_evaluation",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "outcome IN ('pass', 'fail', 'not_applicable', 'error')",
            name="ck_site_rule_evaluations_outcome",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_PAGE_ANALYSIS, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    source_architecture_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_OBSERVED_ARCHITECTURE, ondelete=_ON_DELETE_CASCADE),
        nullable=True,
        index=True,
    )
    rule_id: Mapped[str] = mapped_column(String(64))
    dimension: Mapped[str] = mapped_column(String(16), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(16), default="")
    finding_class: Mapped[str] = mapped_column(String(16), default="defect")
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    outcome: Mapped[str] = mapped_column(String(16), default="")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    supporting_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    rule_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SiteIssue(Base):
    """Failure projection of one failed rule evaluation (unique per evaluation).

    Unique ``evaluation_id``: one issue per ``fail`` evaluation. Snapshots the
    rule's dimension/category/severity, exact evidence, description, and
    remediation text at evaluation time so a later rule-catalog change never rewrites
    history. Indexed for issue filtering (``crawl_id, severity, category,
    rule_id``) and per-URL history (``site_url_id, created_at``).
    """

    __tablename__ = "site_issues"
    __table_args__ = (
        UniqueConstraint("evaluation_id", name="uq_site_issue_evaluation"),
        Index(
            "ix_site_issues_filter",
            "crawl_id",
            "finding_class",
            "severity",
            "category",
            "rule_id",
        ),
        Index(
            "ix_site_issues_url_created",
            "site_url_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_PROJECT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_PAGE_ANALYSIS, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    evaluation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_RULE_EVALUATION, ondelete=_ON_DELETE_CASCADE),
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_CASCADE),
    )
    rule_id: Mapped[str] = mapped_column(String(64))
    dimension: Mapped[str] = mapped_column(String(16), default="")
    category: Mapped[str] = mapped_column(String(32), default="")
    severity: Mapped[str] = mapped_column(String(16), default="")
    finding_class: Mapped[str] = mapped_column(String(16), default="defect")
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    remediation: Mapped[str] = mapped_column(Text, default="")
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    rule_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
