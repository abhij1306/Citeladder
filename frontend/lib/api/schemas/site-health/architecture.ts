import { z } from 'zod';

import { responseObject, uuid } from './core';

/**
 * Observed architecture — the read-only projection of the model a crawl's
 * post-terminal architecture task persisted.
 *
 * `coverage_state` travels with every site-level number, and `orphan_count` is
 * an absence claim the backend blanks unless the crawl proved complete
 * coverage. The client renders what it is given and never re-derives either.
 */
export const coverageStateSchema = z.enum(['complete', 'partial', 'unknown']);
export const architectureFamilySchema = responseObject({
  family: z.string(),
  url_count: z.number().int(),
  page_kind_distribution: z.record(z.string(), z.number().int()),
  median_depth: z.number().nullable(),
  indexable_count: z.number().int(),
  metadata_duplication_rate: z.number(),
  // Null unless coverage is complete — an orphan count is an absence claim.
  orphan_count: z.number().int().nullable(),
});

// One page in the observed tree. `parent_site_url_id` is null when no evidence
// resolved a parent; such a page renders under its family rather than being
// attached somewhere plausible.
export const architectureNodeSchema = responseObject({
  site_url_id: uuid(),
  url: z.string(),
  title: z.string(),
  page_kind: z.string(),
  family: z.string(),
  parent_site_url_id: uuid().nullable(),
  parent_source: z.enum(['breadcrumb', 'explicit_structure', 'url_family', 'unknown']),
  depth_from_home: z.number().int().nullable(),
});

export const architectureSchema = responseObject({
  state: z.enum(['available', 'unavailable']),
  crawl_id: uuid().nullable(),
  coverage_state: coverageStateSchema,
  page_count: z.number().int(),
  page_kind_counts: z.record(z.string(), z.number().int()),
  families: z.array(architectureFamilySchema),
  nodes: z.array(architectureNodeSchema),
  architecture_formula_version: z.string(),
  limitations: z.array(z.string()),
});
