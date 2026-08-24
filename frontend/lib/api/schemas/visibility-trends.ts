import { z } from 'zod';
import { modelProvenanceSchema } from './audits';
import { rankingRowSchema } from './visibility';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Cross-run Visibility trend history (projection over persisted snapshots)
// ---------------------------------------------------------------------------

// Both Share-of-Voice definitions for one trend point (B backend
// `VisibilityTrendSov`). `response` is the response-level SOV (brand
// response-presence share vs competitors); `mention` is the mention-level SOV
// derived from the persisted `share_of_voice.mention_counts`. Both are
// deterministic reprojections of persisted metrics (invariant 7) and are
// nullable when the source metric is absent.
export const visibilityTrendSovSchema = responseObject({
  response: z.number().nullable(),
  mention: z.number().nullable(),
});

// One brand-vs-competitor ranking-history row within a trend point (backend
// `VisibilityTrendRankingRow`). Field-for-field identical to `rankingRowSchema`
// — aliased so the two contracts can't drift apart silently.
export const visibilityTrendRankingRowSchema = rankingRowSchema;

// One point in the cross-run Visibility trend (backend `VisibilityTrendPoint`).
// A raw per-run point carries a set `audit_id`; a week/month bucket folds many
// snapshots (`audit_id` is null) and carries the full provenance list. Version
// metadata lists every distinct analyzer/scoring version the point folds, with
// `spans_version_boundary` set when a bucket mixes versions. `sentiment` /
// `avg_position` stay null (decision B-2 / invariant 9).
export const visibilityTrendPointSchema = responseObject({
  audit_id: uuid().nullable(),
  completed_at: z.string(),
  logical_engine: z.string().nullable(),
  visibility_score: z.number().nullable(),
  brand_mention_rate: z.number().nullable(),
  owned_citation_rate: z.number().nullable(),
  sov: visibilityTrendSovSchema,
  rankings: z.array(visibilityTrendRankingRowSchema),
  sentiment: z.string().nullable(),
  avg_position: z.number().nullable(),
  // Measurement identity partition (invariant 7): a point folds only inside
  // one (transport_model, retrieval_enabled) identity, so
  // the client must never recombine points across these. `transport_model` is
  // null when the point spans several models — see `model_provenance`.
  transport_model: z.string().nullable().default(null),
  retrieval_enabled: z.boolean().nullable().default(null),
  model_provenance: z.array(modelProvenanceSchema).default([]),
  // Provenance (invariant 4): every source snapshot this point folds.
  source_snapshot_ids: z.array(uuid()),
  // Distinct versions across the folded snapshots (invariant 4).
  analyzer_versions: z.array(z.string()),
  scoring_rule_versions: z.array(z.string()),
  spans_version_boundary: z.boolean(),
});

// The trends endpoint returns a chronological list of points (never wrapped).
export const visibilityTrendListSchema = z.array(visibilityTrendPointSchema);
