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
  auditEventSchema,
  auditScheduleCadenceSchema,
  auditScheduleSchema,
  auditSchema,
  auditStatusSchema,
  authResponseSchema,
  registrationResponseSchema,
  connectionTestResultSchema,
  competitorSchema,
  measurementModeSchema,
  modelProvenanceSchema,
  providerConnectionStateEntrySchema,
  providerConnectionStateSchema,
  providerConnectionStatesSchema,
  providerProbeSchema,
  brandProfileDraftSchema,
  brandProfileSchema,
  brandProfileSourceSchema,
  benchmarkModeSchema,
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
  crawlFailureSummarySchema,
  crawlOverallStatusSchema,
  crawlCountersSchema,
  deliveryFactsSchema,
  inventoryPageSchema,
  inventoryRowSchema,
  issueDimensionSchema,
  issueHistoryPageSchema,
  issueSeveritySchema,
  issuesSummarySchema,
  monitoredUrlSchema,
  monitoredUrlsResponseSchema,
  pageAnalysisStatusSchema,
  pageDetailSchema,
  pageSummarySchema,
  pagesPageSchema,
  pageKindSchema,
  pageKindScoreSummarySchema,
  phaseMutationResponseSchema,
  phaseRunSchema,
  rerunPageResponseSchema,
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
  contentOutputTypeSchema,
  groundingStatusSchema,
  groundingEnvelopeSummarySchema,
  // Products (agentic commerce)
  buyerDestinationKindSchema,
  buyerDestinationMixSchema,
  competitorCoPlacementSchema,
  competitorProductSchema,
  competitorProductVisibilityEntrySchema,
  priceRelationCountsSchema,
  priceRelationSchema,
  productAuditReferencesSchema,
  productCompletenessSchema,
  productEvidenceItemSchema,
  productEvidenceKindSchema,
  productEvidenceResponseSchema,
  productImportResponseSchema,
  productImportRowErrorSchema,
  productImportSummarySchema,
  productOriginSchema,
  productSchema,
  productVariantSchema,
  productVisibilityEntrySchema,
  productVisibilitySchema,
  productVisibilityTrendResponseSchema,
  // Commerce (catalog feed health)
  commerceCatalogHealthSchema,
  commerceConnectionSummarySchema,
  commerceSyncSummarySchema,
  feedHealthStatusSchema,
  feedIssueSeveritySchema,
  productFeedHealthSchema,
  commerceComparisonSchema,
  // Attribution (A1/A2 snapshot + recompute)
  attributionDeltaSchema,
  attributionDeltaStateSchema,
  attributionDataStateSchema,
  attributionDeterministicSchema,
  attributionMethodMetricsSchema,
  attributionMethodSchema,
  attributionMetricSetSchema,
  attributionMetricsSchema,
  attributionProductRowSchema,
  attributionRecomputeSchema,
  attributionSnapshotSchema,
  attributionSourceGranularitySchema,
  attributionSourceRowSchema,
  attributionStatisticalSchema,
  attributionTaskStatusSchema,
  statisticalAllocationRowSchema,
  unattributedMetricsSchema,
  // Opportunities
  opportunitiesPageSchema,
  implementationEventSchema,
  implementationEventsPageSchema,
  implementationStateSchema,
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
export type BrandProfileSource = z.infer<typeof brandProfileSourceSchema>;
export type BrandProfileDraft = z.infer<typeof brandProfileDraftSchema>;
export type BrandProfile = z.infer<typeof brandProfileSchema>;
export type PromptIntent = z.infer<typeof promptIntentSchema>;
export type Prompt = z.infer<typeof promptSchema>;
export type PromptStatus = z.infer<typeof promptStatusSchema>;
export type PromptSet = z.infer<typeof promptSetSchema>;
export type Topic = z.infer<typeof topicSchema>;
export type PromptGenerateResponse = z.infer<typeof promptGenerateResponseSchema>;
export type BenchmarkMode = z.infer<typeof benchmarkModeSchema>;
export type Project = z.infer<typeof projectSchema>;
export type Competitor = z.infer<typeof competitorSchema>;
export type TransportProvider = z.infer<typeof transportProviderSchema>;
export type LogicalEngine = z.infer<typeof logicalEngineSchema>;
export type ProviderConnection = z.infer<typeof providerConnectionSchema>;
export type ProviderCatalog = z.infer<typeof providerCatalogSchema>;
export type ConnectionTestResult = z.infer<typeof connectionTestResultSchema>;
// The authenticated workspace projection — distinct from public availability.
export type ProviderConnectionState = z.infer<typeof providerConnectionStateSchema>;
export type ProviderConnectionStateEntry = z.infer<typeof providerConnectionStateEntrySchema>;
export type ProviderConnectionStates = z.infer<typeof providerConnectionStatesSchema>;
export type ProviderProbe = z.infer<typeof providerProbeSchema>;
export type MeasurementMode = z.infer<typeof measurementModeSchema>;
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
export type CrawlCounters = z.infer<typeof crawlCountersSchema>;
export type CrawlDiscoveryStatus = z.infer<typeof crawlDiscoveryStatusSchema>;
export type CrawlAnalysisStatus = z.infer<typeof crawlAnalysisStatusSchema>;
export type PageAnalysisStatus = z.infer<typeof pageAnalysisStatusSchema>;
export type PageKind = z.infer<typeof pageKindSchema>;
export type PageKindScoreSummary = z.infer<typeof pageKindScoreSummarySchema>;
export type SiteScoreSummary = z.infer<typeof siteScoreSummarySchema>;
export type CrawlFailureSummary = z.infer<typeof crawlFailureSummarySchema>;
export type RootError = z.infer<typeof rootErrorSchema>;
export type SiteCrawl = z.infer<typeof siteCrawlSchema>;
export type PhaseRun = z.infer<typeof phaseRunSchema>;
export type PhaseMutationResponse = z.infer<typeof phaseMutationResponseSchema>;
export type UrlPreviewResponse = z.infer<typeof urlPreviewResponseSchema>;
export type InventoryRow = z.infer<typeof inventoryRowSchema>;
export type InventoryPage = z.infer<typeof inventoryPageSchema>;
export type SiteCrawlListPage = z.infer<typeof siteCrawlListPageSchema>;
export type MonitoredUrl = z.infer<typeof monitoredUrlSchema>;
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
export type ReadinessDimension = z.infer<typeof readinessDimensionSchema>;
export type ChangeSummary = z.infer<typeof changeSummarySchema>;
export type ChangeObservation = z.infer<typeof changeObservationSchema>;
export type ChangesPage = z.infer<typeof changesPageSchema>;
export type VisibilityTrendRankingRow = z.infer<typeof visibilityTrendRankingRowSchema>;
export type VisibilityTrendPoint = z.infer<typeof visibilityTrendPointSchema>;
export type VisibilityExecutionEvidence = z.infer<typeof visibilityExecutionEvidenceSchema>;
export type VisibilityEvidenceResponse = z.infer<typeof visibilityEvidenceResponseSchema>;

// --- Content ---
export type ContentGenerationStatus = z.infer<typeof contentGenerationStatusSchema>;
export type ContentOutputType = z.infer<typeof contentOutputTypeSchema>;
export type GroundingStatus = z.infer<typeof groundingStatusSchema>;
export type GroundingEnvelopeSummary = z.infer<typeof groundingEnvelopeSummarySchema>;
export type ContentGenerationListItem = z.infer<typeof contentGenerationListItemSchema>;
export type ContentGenerationDetail = z.infer<typeof contentGenerationDetailSchema>;

// --- Products (agentic commerce) ---
export type ProductVariant = z.infer<typeof productVariantSchema>;
export type ProductCompleteness = z.infer<typeof productCompletenessSchema>;
export type ProductOrigin = z.infer<typeof productOriginSchema>;
export type Product = z.infer<typeof productSchema>;
export type CompetitorProduct = z.infer<typeof competitorProductSchema>;
export type ProductImportRowError = z.infer<typeof productImportRowErrorSchema>;
export type ProductImportSummary = z.infer<typeof productImportSummarySchema>;
export type ProductImportResponse = z.infer<typeof productImportResponseSchema>;
export type ProductAuditReferences = z.infer<typeof productAuditReferencesSchema>;
export type BuyerDestinationKind = z.infer<typeof buyerDestinationKindSchema>;
export type BuyerDestinationMix = z.infer<typeof buyerDestinationMixSchema>;
export type CompetitorCoPlacement = z.infer<typeof competitorCoPlacementSchema>;
export type PriceRelationCounts = z.infer<typeof priceRelationCountsSchema>;
export type PriceRelation = z.infer<typeof priceRelationSchema>;
export type ProductVisibilityEntry = z.infer<typeof productVisibilityEntrySchema>;
export type CompetitorProductVisibilityEntry = z.infer<
  typeof competitorProductVisibilityEntrySchema
>;
export type ProductVisibility = z.infer<typeof productVisibilitySchema>;
export type ProductVisibilityTrend = z.infer<typeof productVisibilityTrendResponseSchema>;
export type ProductEvidenceKind = z.infer<typeof productEvidenceKindSchema>;
export type ProductEvidenceItem = z.infer<typeof productEvidenceItemSchema>;
export type ProductEvidenceResponse = z.infer<typeof productEvidenceResponseSchema>;

// --- Commerce (catalog feed health) ---
export type FeedHealthStatus = z.infer<typeof feedHealthStatusSchema>;
export type FeedIssueSeverity = z.infer<typeof feedIssueSeveritySchema>;
export type CommerceSyncSummary = z.infer<typeof commerceSyncSummarySchema>;
export type CommerceConnectionSummary = z.infer<typeof commerceConnectionSummarySchema>;
export type ProductFeedHealth = z.infer<typeof productFeedHealthSchema>;
export type CommerceCatalogHealth = z.infer<typeof commerceCatalogHealthSchema>;
export type CommerceComparison = z.infer<typeof commerceComparisonSchema>;

// --- Attribution (A1/A2 snapshot + recompute) ---
export type AttributionMethod = z.infer<typeof attributionMethodSchema>;
export type AttributionDataState = z.infer<typeof attributionDataStateSchema>;
export type AttributionSourceGranularity = z.infer<typeof attributionSourceGranularitySchema>;
export type AttributionMetricSet = z.infer<typeof attributionMetricSetSchema>;
export type AttributionSourceRow = z.infer<typeof attributionSourceRowSchema>;
export type AttributionProductRow = z.infer<typeof attributionProductRowSchema>;
export type AttributionMethodMetrics = z.infer<typeof attributionMethodMetricsSchema>;
export type AttributionDeltaState = z.infer<typeof attributionDeltaStateSchema>;
export type AttributionDelta = z.infer<typeof attributionDeltaSchema>;
export type UnattributedMetrics = z.infer<typeof unattributedMetricsSchema>;
export type StatisticalAllocationRow = z.infer<typeof statisticalAllocationRowSchema>;
export type AttributionStatistical = z.infer<typeof attributionStatisticalSchema>;
export type AttributionDeterministic = z.infer<typeof attributionDeterministicSchema>;
export type AttributionMetrics = z.infer<typeof attributionMetricsSchema>;
export type AttributionSnapshot = z.infer<typeof attributionSnapshotSchema>;
export type AttributionTaskStatus = z.infer<typeof attributionTaskStatusSchema>;
export type AttributionRecompute = z.infer<typeof attributionRecomputeSchema>;

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
export type ImplementationEventsPage = z.infer<typeof implementationEventsPageSchema>;
export type ImplementationState = z.infer<typeof implementationStateSchema>;
