# ORM model registry.
#
# Import the shared declarative ``Base`` and re-export it so Alembic's
# ``migrations/env.py`` binds autogeneration to a single metadata object.
# Model modules are imported here so their tables register on
# ``Base.metadata`` before autogenerate / create_all runs.
from __future__ import annotations

from app.core.database import Base
from app.models.abuse import QueueWorkspaceTurn, UsageWindow
from app.models.agent import AgentTaskRun, AgentToolAttempt
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    MetricSnapshot,
    PromptMetricSnapshot,
    ResponseAnalysis,
)
from app.models.analytics import (
    AiReferralsSnapshot,
    AnalyticsTask,
    ReferralClassification,
    ReferralEvent,
)
from app.models.audit import (
    Audit,
    AuditEngineSnapshot,
    AuditEvent,
    AuditPromptSnapshot,
    AuditTask,
    ExecutionCostProjection,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.models.audit_schedule import AuditSchedule
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingCustomer,
    BillingSubscription,
    BillingWebhookEvent,
    ConsumableLedger,
    GrantRevocation,
    IdempotencyRecord,
    PendingActivation,
    WorkspaceBillingLink,
)
from app.models.brand import (
    Brand,
    BrandAlias,
    BrandLogoAsset,
    BrandProfile,
    Competitor,
    ObservedEntityCandidate,
    OwnedDomain,
    UnintendedDomain,
)
from app.models.commerce import (
    CommerceCategory,
    CommerceCompetitorAttempt,
    CommerceCompetitorCandidate,
    CommerceCsvImport,
    CommerceObservationCitation,
    CommerceProduct,
    CommerceProductCategory,
    CommerceProductObservation,
    CommercePromptTarget,
    CommerceRecommendationObservation,
    CommerceShelfSnapshot,
)
from app.models.content import (
    ContentGeneration,
    ContentGenerationAttempt,
)
from app.models.demand import (
    BrandedQueryOverride,
    DemandSignal,
    DemandSnapshot,
    QueryEvidenceRow,
    QueryEvidenceSnapshot,
)
from app.models.discovery import BrandDiscovery, BrandResearchSnapshot
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationImportArtifact,
    IntegrationMetricRow,
    IntegrationOAuthGrant,
    IntegrationOAuthState,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.opportunity import (
    Opportunity,
    OpportunityGuidance,
    OpportunityImplementationEvent,
    OpportunityOrder,
    OpportunitySnapshot,
    OpportunityStatusEvent,
    OpportunityVerificationEvent,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic
from app.models.provider import (
    DiscoveryModelConfig,
    ProviderConnection,
    ProviderConnectionTest,
    ProviderRoute,
)
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health.acquisition import SiteFetchArtifact, SiteFetchAttempt
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.architecture import SiteObservedArchitecture
from app.models.site_health.crawl import (
    SiteCrawl,
    SiteCrawlPhaseRun,
    SiteDiscoveryFrontier,
)
from app.models.site_health.events import SiteCrawlEvent
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile, WorkspaceSiteHealthRuntime
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "AccountGrant",
    "AgentTaskRun",
    "AgentToolAttempt",
    "AiReferralsSnapshot",
    "AnalyticsTask",
    "Audit",
    "AuditEngineSnapshot",
    "AuditEvent",
    "AuditPromptSnapshot",
    "AuditTask",
    "AuditSchedule",
    "Base",
    "Brand",
    "BrandAlias",
    "BrandLogoAsset",
    "BrandProfile",
    "BrandMention",
    "BrandDiscovery",
    "BrandResearchSnapshot",
    "BrandedQueryOverride",
    "BillingAccount",
    "BillingCustomer",
    "BillingSubscription",
    "BillingWebhookEvent",
    "Citation",
    "Competitor",
    "CompetitorMention",
    "ContentGeneration",
    "ContentGenerationAttempt",
    "ConsumableLedger",
    "DiscoveryModelConfig",
    "DemandSignal",
    "DemandSnapshot",
    "QueryEvidenceRow",
    "QueryEvidenceSnapshot",
    "ExecutionCostProjection",
    "CommerceCategory",
    "CommerceCompetitorAttempt",
    "CommerceCompetitorCandidate",
    "CommerceCsvImport",
    "CommerceObservationCitation",
    "CommerceProduct",
    "CommerceProductCategory",
    "CommerceProductObservation",
    "CommercePromptTarget",
    "CommerceRecommendationObservation",
    "CommerceShelfSnapshot",
    "GrantRevocation",
    "IdempotencyRecord",
    "IntegrationConnection",
    "IntegrationEvent",
    "IntegrationImportArtifact",
    "IntegrationMetricRow",
    "IntegrationOAuthGrant",
    "IntegrationOAuthState",
    "IntegrationPropertyMapping",
    "IntegrationSyncRun",
    "MetricSnapshot",
    "PromptMetricSnapshot",
    "Opportunity",
    "OpportunityGuidance",
    "OpportunityImplementationEvent",
    "OpportunityVerificationEvent",
    "OpportunityOrder",
    "OpportunitySnapshot",
    "OpportunityStatusEvent",
    "OwnedDomain",
    "ObservedEntityCandidate",
    "PendingActivation",
    "Project",
    "Prompt",
    "PromptSet",
    "ProviderAttempt",
    "ProviderConnection",
    "ProviderConnectionTest",
    "ProviderRoute",
    "RawResponseArtifact",
    "QueueWorkspaceTurn",
    "ReferralClassification",
    "ReferralEvent",
    "ResponseAnalysis",
    "MonitoredSiteUrl",
    "SiteCrawl",
    "SiteCrawlPhaseRun",
    "SiteCrawlEvent",
    "SiteCrawlTask",
    "SiteDiscoveryFrontier",
    "SiteChangeObservation",
    "SiteChangeSnapshot",
    "SiteFetchArtifact",
    "SiteFetchAttempt",
    "SiteHealthProfile",
    "SiteHealthSnapshot",
    "SiteIssue",
    "SitePageAnalysis",
    "SitePageLinkMetric",
    "SiteObservedArchitecture",
    "SiteRuleEvaluation",
    "SiteUrl",
    "SiteUrlObservation",
    "WorkspaceSiteHealthRuntime",
    "Topic",
    "TrafficPageStat",
    "TrafficQueryStat",
    "TrafficSnapshot",
    "UnintendedDomain",
    "UsageWindow",
    "User",
    "Workspace",
    "WorkspaceBillingLink",
    "WorkspaceMember",
]
