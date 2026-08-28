import { z } from 'zod';

import { responseObject, uuid } from './core';

/**
 * Observed architecture — the read-only projection of the model a crawl's
 * post-terminal architecture task persisted.
 *
 * Two rules the shapes below encode, because they are what keep the tab
 * honest: `coverage_state` travels with every site-level number, and
 * `not_observed` / `orphan_count` are absence claims the backend blanks unless
 * the crawl proved complete coverage. The client renders what it is given; it
 * never re-derives either.
 */
export const coverageStateSchema = z.enum(['complete', 'partial', 'unknown']);
export const archetypeSchema = z.enum(['commerce', 'software', 'services', 'other']);

export const commonStructureSchema = responseObject({
  key: z.string(),
  label: z.string(),
});

// `source` says where the archetype came from — the onboarding profile, an
// abstention, or the user's own correction. This layer expects; it never
// classifies, produces no defect, and moves no score.
export const archetypeAssessmentSchema = responseObject({
  archetype: archetypeSchema,
  source: z.enum(['onboarding_profile', 'abstained', 'user_override']),
  reason: z.string(),
  business_model: z.string(),
  market_scope: z.string(),
  observed: z.array(commonStructureSchema),
  not_observed: z.array(commonStructureSchema),
});

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
  archetype: archetypeAssessmentSchema,
  families: z.array(architectureFamilySchema),
  nodes: z.array(architectureNodeSchema),
  architecture_formula_version: z.string(),
  archetype_policy_version: z.string(),
  limitations: z.array(z.string()),
});

export const archetypeOverrideSchema = responseObject({
  project_id: uuid(),
  archetype_override: archetypeSchema.nullable(),
});
