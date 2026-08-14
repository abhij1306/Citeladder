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
from app.models.attribution import AttributionLink, AttributionSnapshot
from app.models.audit import (
    Audit,
    AuditEngineSnapshot,
    AuditEvent,
    AuditPromptSnapshot,
    AuditShoppingSurfaceSnapshot,
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
    CommerceCandidateReview,
    CommerceDiscoveryArtifact,
    CommerceDiscoveryCandidate,
    CommerceDiscoveryRun,
    CommerceDiscoveryTask,
    CompetitorComparisonSnapshot,
    FeedIssue,
    OrderFact,
)
from app.models.content import (
    ContentGeneration,
    ContentGenerationAttempt,
)
from app.models.demand import (
    DemandSignal,
    DemandSnapshot,
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
    OpportunityOrder,
    OpportunitySnapshot,
    OpportunityStatusEvent,
)
from app.models.product import (
    CompetitorProduct,
    MerchantMention,
    Product,
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic
from app.models.provider import (
    DiscoveryModelConfig,
    ProviderConnection,
    ProviderConnectionTest,
    ProviderRoute,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlEvent,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteFetchAttempt,
    SiteHealthProfile,
    SiteHealthSnapshot,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
    WorkspaceSiteHealthRuntime,
)
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

__all__ = [
    "AccountGrant",
    "AgentTaskRun",
    "AgentToolAttempt",
    "AiReferralsSnapshot",
    "AnalyticsTask",
    "AttributionLink",
    "AttributionSnapshot",
    "Audit",
    "AuditEngineSnapshot",
    "AuditEvent",
    "AuditPromptSnapshot",
    "AuditShoppingSurfaceSnapshot",
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
    "BillingAccount",
    "BillingCustomer",
    "BillingSubscription",
    "BillingWebhookEvent",
    "Citation",
    "Competitor",
    "CompetitorComparisonSnapshot",
    "CompetitorMention",
    "CompetitorProduct",
    "ContentGeneration",
    "ContentGenerationAttempt",
    "CommerceCandidateReview",
    "CommerceDiscoveryArtifact",
    "CommerceDiscoveryCandidate",
    "CommerceDiscoveryRun",
    "CommerceDiscoveryTask",
    "ConsumableLedger",
    "DiscoveryModelConfig",
    "DemandSignal",
    "DemandSnapshot",
    "ExecutionCostProjection",
    "FeedIssue",
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
    "MerchantMention",
    "MetricSnapshot",
    "PromptMetricSnapshot",
    "Opportunity",
    "OpportunityGuidance",
    "OpportunityOrder",
    "OpportunitySnapshot",
    "OpportunityStatusEvent",
    "OrderFact",
    "OwnedDomain",
    "ObservedEntityCandidate",
    "PendingActivation",
    "Product",
    "ProductMention",
    "ProductMetricSnapshot",
    "ProductResponseAnalysis",
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
    "SiteCrawlEvent",
    "SiteCrawlTask",
    "SiteFetchArtifact",
    "SiteFetchAttempt",
    "SiteHealthProfile",
    "SiteHealthSnapshot",
    "SiteIssue",
    "SiteLinkReference",
    "SitePageAnalysis",
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
