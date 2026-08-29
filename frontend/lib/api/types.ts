/**
 * Inferred contract types (F2).
 *
 * Every type is derived from a zod schema in `schemas.ts` via `z.infer`, so the
 * schema is the single source of truth and the two can never drift. All `id` /
 * `*_id` fields are string UUIDs; there is no numeric id and no `user_id`.
 */
import type { z } from 'zod';

import type {
  aeoReadinessSchema,
  architectureFamilySchema,
  architectureNodeSchema,
  architectureSchema,
  auditEventSchema,
  auditScheduleCadenceSchema,
  auditScheduleSchema,
  auditSchema,
  auditStatusSchema,
  authResponseSchema,
  registrationResponseSchema,
  competitorSchema,
  modelProvenanceSchema,
  providerConnectionStateEntrySchema,
  providerConnectionStateSchema,
  brandProfileDraftSchema,
  brandProfileSchema,
  citationClassificationSchema,
  executionEvidenceSchema,
  executionSchema,
  executionStatusSchema,
  logicalEngineSchema,
  oauthStartResponseSchema,
  projectSchema,
  promptGenerateResponseSchema,
  promptIntentSchema,
  promptSchema,
  promptSetSchema,
  promptStatusSchema,
  providerCatalogSchema,
  providerConnectionSchema,
  rankingRowSchema,
  sessionUserSchema,
  transportProviderSchema,
  topicSchema,
  visibilityEngineSchema,
  visibilityEvidenceResponseSchema,
  visibilityExecutionEvidenceSchema,
  visibilitySchema,
  promptMetricItemSchema,
  observedCompetitorSchema,
  visibilityTrendPointSchema,
  visibilityTrendRankingRowSchema,
  workspaceSchema,
  productTourSchema,
  productTourStatusSchema,
  commandCenterSchema,
  // Site Health
  crawlAnalysisStatusSchema,
  changeObservationSchema,
  changeSummarySchema,
  changesPageSchema,
  crawlDiscoveryStatusSchema,
  crawlOverallStatusSchema,
  deliveryFactsSchema,
  inventoryPageSchema,
  issueDimensionSchema,
  issueHistoryPageSchema,
  issueSeveritySchema,
  issuesSummarySchema,
  monitoredUrlsResponseSchema,
  pageAnalysisStatusSchema,
  coverageStateSchema,
  pageDetailSchema,
  pageSummarySchema,
  pagesPageSchema,
  pageKindSchema,
  pageKindScoreSummarySchema,
  rerunPageResponseSchema,
  readinessCheckSchema,
  readinessDimensionSchema,
  rootErrorSchema,
  siteCrawlListPageSchema,
  siteCrawlSchema,
  urlPreviewResponseSchema,
  siteHealthDashboardSchema,
  siteHealthEntitlementSchema,
  siteIssueDetailSchema,
  siteIssueSchema,
  siteIssuesPageSchema,
  siteScoreSummarySchema,
  // Content
  contentGenerationDetailSchema,
  contentGenerationListItemSchema,
  contentGenerationStatusSchema,
  contentContextPreviewSchema,
  contentFeedbackReasonSchema,
  // Opportunities
  opportunitiesPageSchema,
  implementationEventSchema,
  opportunityDetailSchema,
  opportunitySchema,
  opportunitySeveritySchema,
  opportunityStatusSchema,
  opportunitySummarySchema,
  opportunityTypeSchema,
  recomputeResponseSchema,
} from './schemas';

export type SessionUser = z.infer<typeof sessionUserSchema>;
export type AuthResponse = z.infer<typeof authResponseSchema>;
export type RegistrationResponse = z.infer<typeof registrationResponseSchema>;
// OAuth provider ids are a request-input union (not a response payload), so
// they stay a plain literal type rather than a `z.infer`.
export type OAuthProvider = 'google' | 'github' | 'apple';
export type OAuthStartResponse = z.infer<typeof oauthStartResponseSchema>;
export type Workspace = z.infer<typeof workspaceSchema>;
export type ProductTourStatus = z.infer<typeof productTourStatusSchema>;
export type ProductTour = z.infer<typeof productTourSchema>;
export type CommandCenter = z.infer<typeof commandCenterSchema>;
export type BrandProfileDraft = z.infer<typeof brandProfileDraftSchema>;
export type BrandProfile = z.infer<typeof brandProfileSchema>;
export type PromptIntent = z.infer<typeof promptIntentSchema>;
export type Prompt = z.infer<typeof promptSchema>;
export type PromptStatus = z.infer<typeof promptStatusSchema>;
export type PromptSet = z.infer<typeof promptSetSchema>;
export type Topic = z.infer<typeof topicSchema>;
export type PromptGenerateResponse = z.infer<typeof promptGenerateResponseSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Competitor = z.infer<typeof competitorSchema>;
export type TransportProvider = z.infer<typeof transportProviderSchema>;
export type LogicalEngine = z.infer<typeof logicalEngineSchema>;
export type ProviderConnection = z.infer<typeof providerConnectionSchema>;
export type ProviderCatalog = z.infer<typeof providerCatalogSchema>;
// The authenticated workspace projection — distinct from public availability.
export type ProviderConnectionState = z.infer<typeof providerConnectionStateSchema>;
export type ProviderConnectionStateEntry = z.infer<typeof providerConnectionStateEntrySchema>;
export type ModelProvenance = z.infer<typeof modelProvenanceSchema>;
export type AuditEvent = z.infer<typeof auditEventSchema>;
export type AuditStatus = z.infer<typeof auditStatusSchema>;
export type Audit = z.infer<typeof auditSchema>;
export type AuditScheduleCadence = z.infer<typeof auditScheduleCadenceSchema>;
export type AuditSchedule = z.infer<typeof auditScheduleSchema>;
export type ExecutionStatus = z.infer<typeof executionStatusSchema>;
export type CitationClassification = z.infer<typeof citationClassificationSchema>;
export type Execution = z.infer<typeof executionSchema>;
export type PromptMetricItem = z.infer<typeof promptMetricItemSchema>;
export type ObservedCompetitor = z.infer<typeof observedCompetitorSchema>;
export type ExecutionEvidence = z.infer<typeof executionEvidenceSchema>;
export type VisibilityEngine = z.infer<typeof visibilityEngineSchema>;
export type RankingRow = z.infer<typeof rankingRowSchema>;
export type Visibility = z.infer<typeof visibilitySchema>;

// --- Site Health ---
export type SiteHealthEntitlement = z.infer<typeof siteHealthEntitlementSchema>;
export type CrawlOverallStatus = z.infer<typeof crawlOverallStatusSchema>;
export type CrawlDiscoveryStatus = z.infer<typeof crawlDiscoveryStatusSchema>;
export type CrawlAnalysisStatus = z.infer<typeof crawlAnalysisStatusSchema>;
export type PageAnalysisStatus = z.infer<typeof pageAnalysisStatusSchema>;
export type PageKind = z.infer<typeof pageKindSchema>;
export type PageKindScoreSummary = z.infer<typeof pageKindScoreSummarySchema>;
export type SiteScoreSummary = z.infer<typeof siteScoreSummarySchema>;
export type RootError = z.infer<typeof rootErrorSchema>;
export type SiteCrawl = z.infer<typeof siteCrawlSchema>;
export type UrlPreviewResponse = z.infer<typeof urlPreviewResponseSchema>;
export type InventoryPage = z.infer<typeof inventoryPageSchema>;
export type SiteCrawlListPage = z.infer<typeof siteCrawlListPageSchema>;
export type MonitoredUrlsResponse = z.infer<typeof monitoredUrlsResponseSchema>;
export type DeliveryFacts = z.infer<typeof deliveryFactsSchema>;
export type IssueSeverity = z.infer<typeof issueSeveritySchema>;
export type IssueDimension = z.infer<typeof issueDimensionSchema>;
export type SiteIssue = z.infer<typeof siteIssueSchema>;
export type SiteIssueDetail = z.infer<typeof siteIssueDetailSchema>;
export type SiteIssuesPage = z.infer<typeof siteIssuesPageSchema>;
export type IssuesSummary = z.infer<typeof issuesSummarySchema>;
export type IssueHistoryPage = z.infer<typeof issueHistoryPageSchema>;
export type PageSummary = z.infer<typeof pageSummarySchema>;
export type PagesPage = z.infer<typeof pagesPageSchema>;
export type PageDetail = z.infer<typeof pageDetailSchema>;
export type RerunPageResponse = z.infer<typeof rerunPageResponseSchema>;
export type SiteHealthDashboard = z.infer<typeof siteHealthDashboardSchema>;
export type AeoReadiness = z.infer<typeof aeoReadinessSchema>;
export type CoverageState = z.infer<typeof coverageStateSchema>;
export type ArchitectureFamily = z.infer<typeof architectureFamilySchema>;
export type ArchitectureNode = z.infer<typeof architectureNodeSchema>;
export type SiteArchitecture = z.infer<typeof architectureSchema>;
export type ReadinessDimension = z.infer<typeof readinessDimensionSchema>;
export type ReadinessCheck = z.infer<typeof readinessCheckSchema>;
export type ChangeSummary = z.infer<typeof changeSummarySchema>;
export type ChangeObservation = z.infer<typeof changeObservationSchema>;
export type ChangesPage = z.infer<typeof changesPageSchema>;
export type VisibilityTrendRankingRow = z.infer<typeof visibilityTrendRankingRowSchema>;
export type VisibilityTrendPoint = z.infer<typeof visibilityTrendPointSchema>;
export type VisibilityExecutionEvidence = z.infer<typeof visibilityExecutionEvidenceSchema>;
export type VisibilityEvidenceResponse = z.infer<typeof visibilityEvidenceResponseSchema>;

// --- Content ---
export type ContentGenerationStatus = z.infer<typeof contentGenerationStatusSchema>;
export type ContentContextPreview = z.infer<typeof contentContextPreviewSchema>;
export type ContentFeedbackReason = z.infer<typeof contentFeedbackReasonSchema>;
export type ContentGenerationListItem = z.infer<typeof contentGenerationListItemSchema>;
export type ContentGenerationDetail = z.infer<typeof contentGenerationDetailSchema>;

// --- Opportunities ---
export type OpportunityType = z.infer<typeof opportunityTypeSchema>;
export type OpportunitySeverity = z.infer<typeof opportunitySeveritySchema>;
export type OpportunityStatus = z.infer<typeof opportunityStatusSchema>;
export type Opportunity = z.infer<typeof opportunitySchema>;
export type OpportunityDetail = z.infer<typeof opportunityDetailSchema>;
export type OpportunitiesPage = z.infer<typeof opportunitiesPageSchema>;
export type OpportunitySummary = z.infer<typeof opportunitySummarySchema>;
export type RecomputeResponse = z.infer<typeof recomputeResponseSchema>;
export type ImplementationEvent = z.infer<typeof implementationEventSchema>;
