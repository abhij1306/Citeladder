import { z } from 'zod';

import { pageAnalysisStatusSchema, pageKindSchema } from './crawl';
import { analysisSummaryFields } from './inventory';
import { responseObject, uuid } from './core';
import {
  findingClassSchema,
  issueDimensionSchema,
  issueSeveritySchema,
  siteIssueSchema,
} from './issues';
import { cursorPageSchema } from './pagination';

// Deterministic HTTP delivery facts. `field_cwv_available` is a literal false —
// the HTTP-first crawler never fabricates field Core Web Vitals (no LCP/CLS/INP).
export const deliveryFactsSchema = responseObject({
  field_cwv_available: z.literal(false),
  status_code: z.number().int().nullable(),
  ttfb_ms: z.number().nullable(),
  wire_bytes: z.number().int().nullable(),
  decoded_bytes: z.number().int().nullable(),
  html_bytes: z.number().int().nullable(),
  http_version: z.string().nullable(),
  compression: z.string().nullable(),
  cache_control: z.string().nullable(),
  blocking_resource_count: z.number().int().nullable(),
});

// Bounded normalized page facts (deterministic; extractor-versioned).
export const pageFactsSchema = responseObject({
  title: z.string().nullable(),
  meta_description: z.string().nullable(),
  canonical_url: z.string().nullable(),
  robots_directives: z.array(z.string()),
  h1_count: z.number().int(),
  heading_count: z.number().int(),
  image_count: z.number().int(),
  image_missing_alt_count: z.number().int(),
  word_count: z.number().int(),
  internal_link_count: z.number().int(),
  external_link_count: z.number().int(),
  structured_data_types: z.array(z.string()),
});

// Analyzed-page summary row (`/pages` list). Scores/issue-count are null when
// analysis has not completed; `error_code` is '' when there is no error.
export const pageSummarySchema = responseObject({
  site_url_id: uuid(),
  crawl_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  monitored: z.boolean(),
  analysis_status: pageAnalysisStatusSchema,
  error_code: z.string(),
  ...analysisSummaryFields,
  // Persisted internal-link metrics for this crawl. `null` means UNMEASURED —
  // the crawl wrote no metric row for the URL — never "nothing links here".
  inbound_count: z.number().int().nullable(),
  main_content_inbound_count: z.number().int().nullable(),
  depth_from_home: z.number().int().nullable(),
});

// One REAL root-target network call the crawl lost (SH-4 — B3). Deliberately
// NOT a page row: a root failure never creates a SiteUrl, so there is no
// `site_url_id` and no PageDetail link — the Errors & Blocked tab renders
// these as a distinct non-clickable block above the table.
export const rootErrorSchema = responseObject({
  method: z.string(),
  target: z.string(),
  outcome: z.string(),
  error_code: z.string(),
  status_code: z.number().int().nullable(),
  latency_ms: z.number().int().nullable(),
});

export const pagesPageSchema = cursorPageSchema(pageSummarySchema).extend({
  // REQUIRED (backend always serializes); empty unless the crawl's root fetch
  // failed terminally. Never enters the keyset pagination of `items`.
  root_errors: z.array(rootErrorSchema),
});

// One persisted rule evaluation on a page (all outcomes, current label).
const ruleEvaluationSchema = responseObject({
  id: uuid(),
  rule_id: z.string(),
  title: z.string(),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  outcome: z.enum(['pass', 'fail', 'not_applicable', 'error']),
  weight: z.number(),
  evidence: z.record(z.string(), z.unknown()),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
});

// One bounded top-N neighbour of a page in the crawl's internal link graph.
const linkNeighbourSchema = responseObject({
  site_url_id: uuid().nullable(),
  url: z.string(),
  anchor_count: z.number().int(),
  main_content: z.boolean(),
  nofollow: z.boolean(),
  rel: z.array(z.string()),
});

// A page's persisted internal-link metrics. `depth_from_home` is shortest-path
// over ALL followable internal links (a nav link is a real click);
// `main_content_inbound_count` is the separate "genuinely linked, or only in
// the menu" signal, taken from each anchor's DOM region — never from link
// frequency.
export const internalLinksSchema = responseObject({
  inbound_count: z.number().int(),
  outbound_count: z.number().int(),
  main_content_inbound_count: z.number().int(),
  main_content_outbound_count: z.number().int(),
  nofollow_inbound_count: z.number().int(),
  depth_from_home: z.number().int().nullable(),
  source_page_count: z.number().int(),
  top_inbound: z.array(linkNeighbourSchema),
  top_outbound: z.array(linkNeighbourSchema),
  formula_version: z.string(),
});

// Full analyzed-page detail (persisted facts/delivery/scores/issues/provenance).
export const pageDetailSchema = responseObject({
  site_url_id: uuid(),
  crawl_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  analysis_status: pageAnalysisStatusSchema,
  error_code: z.string(),
  field_cwv_available: z.literal(false),
  technical_score: z.number().nullable(),
  aeo_score: z.number().nullable(),
  overall_score: z.number().nullable(),
  issue_count: z.number().int().nullable(),
  last_audited: z.string().nullable(),
  page_kind: pageKindSchema.nullable(),
  // Bounded classifier evidence behind page_kind ("why this kind?"
  // disclosure); null until the URL has an analysis.
  page_kind_evidence: z.record(z.string(), z.unknown()).nullable(),
  // Pack-governed industry role. `null` = the pack classifier never ran.
  // A present object with `role_id: null` plus an `abstention_reason` is an
  // EXECUTED abstention — a different fact, rendered differently.
  facts: pageFactsSchema,
  delivery: deliveryFactsSchema,
  // Null when this crawl persisted no link metric for the URL.
  internal_links: internalLinksSchema.nullable(),
  issues: z.array(siteIssueSchema),
  evaluations: z.array(ruleEvaluationSchema),
  artifact_id: uuid().nullable(),
  extractor_version: z.string(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  scoring_version: z.string(),
});

// Identity/status returned by the per-page rerun (202). "Re-audit this page"
// is normally invoked from a COMPLETED (terminal) source crawl; the backend
// mints a fresh single-page rerun crawl in that case (`created_new_crawl`),
// so the client must poll the returned `crawl_id`/`site_url_id` (the fresh
// run) rather than the terminal source crawl it was invoked from.
export const rerunPageResponseSchema = responseObject({
  crawl_id: uuid(),
  site_url_id: uuid(),
  task_id: uuid(),
  created_new_crawl: z.boolean(),
  analysis_status: pageAnalysisStatusSchema,
});
