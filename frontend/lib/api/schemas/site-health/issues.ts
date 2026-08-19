import { z } from 'zod';

import { pageKindSchema } from './crawl';
import { responseObject, uuid } from './core';
import { cursorPageSchema } from './pagination';

// Issue severity + dimension enums (config-owned rule catalog).
export const issueSeveritySchema = z.enum(['critical', 'high', 'medium', 'low', 'info']);
export const issueDimensionSchema = z.enum(['technical', 'aeo']);
export const findingClassSchema = z.enum(['defect', 'advisory']);

// A single affected-URL summary on an issue projection. `page_kind` is the
// affected page's classification; it is OPTIONAL — the v1 backend DTO has no
// such key, so the badge renders only when the projection carries it (same
// absent-or-null treatment as the Free-redacted count fields).
export const affectedUrlSchema = responseObject({
  site_url_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  page_kind: pageKindSchema.nullable().optional(),
});

// One issue catalog row (failure projection with remediation snapshot).
export const siteIssueSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  rule_id: z.string(),
  // Page TYPES this group affects. Pack-free page-kind ids, sorted.
  page_kinds: z.array(z.string()),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  title: z.string(),
  description: z.string(),
  remediation: z.string(),
  affected_url_count: z.number().int(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
});

// Grouped-issue catalog summary (occurrence + severity + affected-page counts).
// `severity_counts` keys are the severity vocabulary; `dimension_counts` keys
// are the rule dimensions (technical/aeo); values are occurrence counts.
export const issuesSummarySchema = responseObject({
  issue_count: z.number().int(),
  defect_issue_type_count: z.number().int(),
  advisory_issue_type_count: z.number().int(),
  occurrence_count: z.number().int(),
  severity_counts: z.record(z.string(), z.number().int()),
  dimension_counts: z.record(z.string(), z.number().int()),
  affected_url_count: z.number().int(),
  monitored_affected_url_count: z.number().int(),
});

// Full grouped-issue detail — remediation + evidence + keyset-paginated
// affected URLs. `id` is the stable canonical (representative) issue id for the
// rule group; `affected_url_count` is the full deduplicated total and
// `next_cursor` walks the affected-URL page.
export const siteIssueDetailSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  rule_id: z.string(),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  title: z.string(),
  description: z.string(),
  remediation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  affected_urls: z.array(affectedUrlSchema),
  affected_url_count: z.number().int(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
  next_cursor: z.string().nullable().optional(),
});

// Grouped-issue catalog page — cursor page + API-owned summary (mockup 710).
export const siteIssuesPageSchema = cursorPageSchema(siteIssueSchema).extend({
  summary: issuesSummarySchema,
});
