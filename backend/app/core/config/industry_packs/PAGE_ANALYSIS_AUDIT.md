# Current Page Analysis Audit and Industry-Role Migration Contract

**Audit date:** 2026-08-06  
**Scope:** shipped Site Health page-type classification, persistence, scoring, API presentation,
and the boundary for future industry-role wiring  
**Decision:** preserve the existing generic classifier; add pack-specific understanding beside it

## Current shipped flow

The current runtime is generic and deterministic:

```text
fetch artifact
  -> bounded HTML extraction
  -> generic page_type classifier
  -> page_type-aware rule evaluation and scoring
  -> SitePageAnalysis persistence
  -> dashboard/API projections
  -> badges, filters, score breakdown, and "Why this type?" UI
```

The principal owners are:

- [`../../../analysis/site_health/page_kinds.py`](../../../analysis/site_health/page_kinds.py) — pure generic classifier and evidence record;
- [`../site_health.py`](../site_health.py) — vocabulary, path patterns, heuristics, weights, and per-page-kind profiles;
- [`../../../workers/site_health/phases/analyze.py`](../../../workers/site_health/phases/analyze.py) — invocation, rule-context injection, persistence, evaluations, issues, and scores;
- [`../../../../tests/unit/test_site_health_page_kinds.py`](../../../../tests/unit/test_site_health_page_kinds.py) — current classifier regression tests;
- [`../../../../../frontend/lib/site-health/page-kinds.ts`](../../../../../frontend/lib/site-health/page-kinds.ts) — frontend labels and evidence shaping;
- [`../../../../../frontend/components/site-health/page-kind-badge.tsx`](../../../../../frontend/components/site-health/page-kind-badge.tsx), [`../../../../../frontend/components/site-health/page-kind-select.tsx`](../../../../../frontend/components/site-health/page-kind-select.tsx), [`../../../../../frontend/components/site-health/page-kind-scores.tsx`](../../../../../frontend/components/site-health/page-kind-scores.tsx), and [`../../../../../frontend/components/site-health/url-detail.tsx`](../../../../../frontend/components/site-health/url-detail.tsx) — presentation and filtering.

The vocabulary is `homepage`, `article`, `product`, `category`, `pricing`, `docs`, `faq`,
`about_contact`, `service`, `local`, `guide`, `comparison`, `case_study_review`, `trust_policy`, and
`other`.

## What is already sound

The current implementation has several properties worth preserving:

- deterministic and model-free classification;
- bounded URL/content/schema evidence;
- frozen classifier version on the analysis row;
- explicit signal weights and a configured confidence threshold;
- URL/content signals outranking structured data;
- persisted evidence and schema-disagreement disclosure;
- server-backed page-type filters and score breakdowns;
- generic page-type applicability and per-type scoring profiles;
- tests for vocabulary, paths, heuristics, schema, alternatives, conflicts, and malformed input.

The migration must extend these strengths, not replace them with a model-only classifier or a
second crawler.

## Findings

### 1. Generic page kind and business purpose are conflated

`page_type` currently serves three jobs: generic structure, rule applicability, and an implicit
business-purpose hint. Paths such as `/services`, `/locations`, `/pricing`, and `/products` are
useful generic priors but cannot express Education admissions/program/campus roles, Commerce
PDP/category/variant/policy roles, or equivalent domain-specific purposes.

**Migration:** retain a generic `page_kind` projection derived from the existing classifier and add
an independent `industry_role` produced by the active pack. Do not rename role IDs into the
current enum or use one field as both concepts.

### 2. Missing URL input is normalized into a homepage candidate

The current `_normalized_path` treats an empty or malformed URL as an empty root path, and the
root-path signal classifies it as `homepage`. The current unit test preserves that behavior.
Missing acquisition identity should instead be distinguishable from a real root URL.

**Migration:** the pack classifier already abstains with `invalid_input` when neither a valid URL
path nor an explicit path is available. Production wiring must not feed fabricated root paths.
The generic classifier may be corrected only in its own reviewed compatibility slice.

### 3. Confidence is a sum of matched signals, not a winner-versus-runner decision

The generic classifier chooses one candidate per signal in fixed priority, sums all matched signal
weights into one confidence value, and selects the first matched signal's page type as the final
answer. Contradictory signals can therefore increase confidence even when they support different
types. It records alternatives/conflicts, but it has no independent per-role score table or minimum
winner margin.

**Migration:** compute each pack role's positive and negative score independently, rank all
candidates deterministically, require both minimum score and minimum margin, and abstain on a tie
or ambiguous margin. Persist alternatives and conflicts even when a role is selected.

### 4. Hard-coded paths are useful but brittle

The generic table is ordered and intentionally bounded. It is nevertheless English-centric,
assumes first path segments such as `/products`, `/blog`, `/services`, or `/faq`, and depends on a
curated locale-root allowlist. Real sites use localized slugs, nested hubs, legacy routes, opaque
CMS IDs, and overloaded terms such as `/home`.

**Migration:** keep path evidence as a high-value signal but combine it with title, H1, headings,
body, CTA, forms, link context, media type, generic page kind, and structured data. Allow reviewed
project overlays to map local public labels without mutating shared packs.

### 5. Content heuristics are intentionally narrow

Current content heuristics cover question-heading ratios for FAQ, price plus cart markers for
Product, and byline/date co-location for Article. They are defensible generic checks but miss many
valid pages and can collide with embedded widgets, navigation, recommendation blocks, or stale
content.

**Migration:** use role-specific multi-field signals and negative evidence. A single widget,
keyword, schema block, or numeric token must not become authoritative page purpose.

### 6. Structured data is a signal, not truth

The generic classifier maps a small Schema.org type table and chooses a deterministic suggestion.
This is appropriate as supporting evidence, but a schema declaration may be stale, copied,
hidden from visible content, applied at the wrong scope, or valid only for a nested entity.

**Migration:** preserve schema as a lower-priority signal; add pack-owned recommended types and
visible/schema parity requirements; never classify from schema alone; never infer a current offer,
fee, job, event, medical fact, or other assertion solely from markup.

### 7. The frontend drops part of the persisted evidence contract

The backend `PageTypeAssessment.to_evidence()` can emit alternatives, conflicts, and an
`other_reason`. The current frontend parser exposes the winner, signals, threshold, and schema
conflict only. Users therefore cannot see all ambiguity already persisted by the backend.

**Migration:** introduce separate typed views for generic page-kind evidence and industry-role
evidence. Render abstention reason, runner-up scores/margins, negative signals, and conflicts in a
bounded disclosure. Keep unclassified values as `—`; never fabricate a role for display.

### 8. No pack manifest is frozen on current Site Health analyses

`SitePageAnalysis` stores classifier/analyzer/scoring versions but not an industry pack ID,
version, or content hash. That is correct for the current generic runtime, but insufficient for
pack-governed findings, briefs, or generated outputs.

**Migration:** freeze the resolved pack manifest on the crawl or immutable understanding snapshot,
then copy the exact manifest into every derived context that depends on it. Resolution happens at
crawl/snapshot creation, not dynamically while reading historical rows.

### 9. Corpus, temporal, and document states remain broader than `page_type`

A generic HTML page type cannot represent PDF/document inventory, historical/discontinued
content, excluded-but-known corpus items, conflicting current evidence, or unsupported media.
Treating all of these as `other` loses important state.

**Migration:** introduce explicit corpus disposition, item kind/media type, temporal state,
knowledge state, contradiction records, and coverage warnings before issuing industry findings.

## Required production data model

The next slice should persist or project these distinct concepts:

| Concept | Required behavior |
|---|---|
| `CorpusItem` | Inventory every discovered owned surface; distinguish `analyze`, `inventory_only`, and `exclude` |
| `PageUnderstanding` | Generic page kind plus pack-specific role, scores, margin, evidence, alternatives, conflicts, abstention, temporal state, and manifest |
| `KnowledgeEntity` | Project-scoped typed identity with evidence and review state |
| `KnowledgeAssertion` | Typed scoped claim with source refs, dates, knowledge state, and contradiction group |
| `KnowledgeRelation` | Typed directional relation with source refs and temporal/review state |
| `QuestionAnswer` | Required-question coverage and evidence-backed answer units |
| `JourneyDefinition` | Versioned stages/outcomes and role/question requirements |
| `Finding` / `Opportunity` | Versioned rule result and grouped action, never an unversioned string |
| `TaskContextPackage` | Frozen selective context, omissions, contradictions, approved memory, and pack manifest |
| `GeneratedAttempt` / `Verification` | Append-only generation provenance and before/after evidence |

[`core.json`](core.json) defines machine-readable minimum fields for these concepts. Persistence
shape may reuse existing tables where they already own equivalent durable state; duplication is a
review failure.

## Safe wiring sequence

1. Resolve and freeze one exact pack when the crawl/snapshot is created.
2. Keep the current generic classifier output as `page_kind`/compatibility `page_type`.
3. Compile the frozen pack once per worker process or task scope, not once per page.
4. Feed only bounded extracted facts into the pure role classifier.
5. Shadow-persist role result, abstention, evidence, alternatives, conflicts, temporal state, and
   manifest without changing existing scores or UI behavior.
6. Evaluate Education and Commerce fixture/field corpora and inspect disagreement distributions.
7. Add pack-aware rules as new versioned findings; do not silently reinterpret old rule rows.
8. Add API/frontend fields and filters beside existing page type.
9. Enable role-dependent briefs/generation only after evidence, contradiction, and review gates.
10. Recompute through an explicit versioned job when a pack changes; never reinterpret history on
    read.

The implementation sequence and acceptance gates are in
[`../../../../../docs/plans/codex-site-intelligence-wiring-handoff.md`](../../../../../docs/plans/codex-site-intelligence-wiring-handoff.md).
