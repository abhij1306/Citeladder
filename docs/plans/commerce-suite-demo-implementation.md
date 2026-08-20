# Commerce Suite demo implementation

## Summary

Replace the incomplete Commerce workspace with five focused tabs: Overview,
Catalog, AI Visibility, Competitors, and Opportunities. Reuse the working
catalog, product-analysis pipeline, persisted visibility evidence,
deterministic matching, and shared Opportunity owner. Delete the broken
discovery workflow and superseded Commerce frontend/backend paths.

This is a focused product cutover. Every shipped view reads the real catalog,
audit, comparison, and opportunity owners; there are no hardcoded UI values or
mock production responses. It adds no external write-back, new recommendation
store, scheduler, ML matching, or infrastructure.

## Implementation changes

### Backend and data

- Retain Product and CompetitorProduct CRUD/import, audit-time product analysis,
  mentions, metric snapshots, evidence export, and catalog health.
- Extend product visibility with server-owned summary metrics and per-product
  visibility rate, top-three rate, and prior-audit delta.
- Add a read-only product trend projection over persisted audit snapshots.
- Reuse deterministic matching and CompetitorComparisonSnapshot, but persist a
  typed, audit-bound comparison during audit finalization rather than exposing
  manual comparison creation.
- Move product opportunity rules under `opportunity_type=commerce` and add one
  deterministic product attribute-gap rule backed by persisted comparison
  evidence.
- Keep recommendation confirmation frontend-only.
- Keep the optional local development seed realistic by populating three
  completed audits with visibility history, comparisons, attribute gaps, and
  opportunities. The seed is not a production fallback.

### Frontend

- Make Overview the default `/products?tab=` view and expose Overview, Catalog,
  AI Visibility, Competitors, and Opportunities through the existing Commerce
  screen owner.
- Show a compact overview, SKU visibility table, readable product comparison,
  commerce-filtered opportunity list, and confirmation-only recommendation
  action.
- Retain the working Catalog and product evidence drill-down, adding a simple
  three-snapshot visibility history above the evidence.

### Debt removal

- Delete the Discover tab and its frontend hooks, schemas, query keys, API
  methods, components, and tests.
- Delete Commerce discovery routes, DTOs, services, queue configuration,
  worker, models/tables, migration entries, exports, and tests.
- Delete the manual comparison mutation and superseded generic comparison and
  AI Conversations presentation after their replacements are live.
- Preserve attribution, order facts, connector ingestion, catalog health, and
  other non-surface commerce capabilities.

## Public interfaces

- Keep product CRUD/import and evidence contracts.
- Extend `ProductVisibilityResponse` with summary and per-product metrics.
- Add `ProductVisibilityTrendResponse` with ordered audit points.
- Replace comparison history/list output with a typed read-only audit comparison
  response.
- Reuse the Opportunities API with `type=commerce` and add no Commerce-specific
  recommendation mutation.
- Fold schema changes into `migrations/versions/0001_initial.py`.

## Test plan

- Backend: visibility calculations, three-audit trends, automatic comparison
  provenance, attribute-gap opportunities, workspace isolation, and removed
  discovery routes/tables.
- Frontend: five-tab URL contract, inactive-query gating, retained Catalog,
  populated Overview, trends, comparison, and confirmation-only action.
- Seed: deterministic content for all five tabs.
- Verification: focused pytest/Ruff, frontend tests/lint/build, migration from
  empty plus Alembic drift, documentation validation, `git diff --check`, and
  final searches for superseded discovery/tab symbols.

## Assumptions

- Persisted audits remain the source of truth; production UI never falls back
  to mocks.
- Catalog remains operational and visible.
- Attribution and connector ingestion remain unchanged.
- The product does not claim observed differences caused answer-engine ranking.
