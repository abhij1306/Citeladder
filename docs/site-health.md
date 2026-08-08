# Site Health: shipped foundation for Site Intelligence

> **Current owner:** `backend/app/domain/site_health`, `analysis/site_health`, Site Health workers,
> and the `/site-health` frontend
> **Target owner:** Site Intelligence, as specified in
> [`plans/site-intelligence-primary-product.md`](plans/site-intelligence-primary-product.md)

Site Health is the existing first-party crawler and deterministic issue engine. It remains the
only owner of URL discovery, secure acquisition, crawl tasks, immutable fetch attempts/artifacts,
normalized HTML facts, rule evaluations, issues, snapshots, exports, and page/crawl projections.
The Site Intelligence implementation extends this subsystem; it does not create a new crawler or
parallel page-analysis pipeline.

## Current guarantees

- workspace-scoped UUID resources and projection-only reads;
- config-owned URL admission, acquisition, parser, classifier, rule, and scoring versions;
- SSRF-safe acquisition with validated redirects, resource bounds, robots handling, and redacted
  diagnostics;
- PostgreSQL queue leases, heartbeats, retries, cancellation, and persisted events;
- immutable fetch artifacts and attempt provenance;
- deterministic generic page classification and page-level rule evaluation;
- grouped issues, per-URL evidence/history, snapshots, and authenticated exports;
- explicit null/unavailable states rather than fabricated scores.

## Required corrections before Site Intelligence — shipped

All seven are implemented:

1. Terminal crawl/discovery/analysis state agrees with drained task state. A drained crawl with no
   RUNNING phase-run row now terminalizes its phase sub-states instead of parking PAUSED while
   `analysis_status` stayed `running`.
2. Stop/continue controls are idempotent. `_pause_if_idle` settles both sub-states from the
   outstanding-task count, so a second Stop (or a stop after the phase already drained) cannot
   leave a RUNNING phase no task backs.
3. A URL failure is counted once: `failed_url_count` counts DISTINCT failed `url_hash` across
   discover+analyze rather than summing per-kind task failures.
4. The acquisition ladder is `secure_httpx -> curl_cffi -> patchright`. ScraperAPI is fully
   removed — rung, settings, and columns.
5. Corpus disposition (`analyze` | `inventory_only` | `exclude`) is first-class on `SiteUrl` with
   its reason, version, and `item_kind`.
6. `page_type` is split: `page_kind` (generic structural) and `industry_role` (pack-governed) are
   separate columns with independent vocabularies and evidence.
7. Supported documents (PDF/Office) are admitted to corpus inventory as `item_kind=document` with
   `inventory_only` disposition, so they count toward coverage without entering the HTML analyzer.

## Target evidence flow

```text
seed, sitemap, links, uploads, catalog
  -> URL/document inventory
  -> analyze | inventory_only | exclude
  -> safe acquisition or document extraction
  -> immutable normalized artifact
  -> page kind + industry role
  -> entities, assertions, questions, sections, schema, journey support
  -> deterministic findings and grouped actions
  -> Site Intelligence snapshot/report
  -> recrawl comparison and verification
```

The active industry profile contributes role checks and expectations but never bypasses URL safety,
workspace authorization, evidence immutability, or deterministic hard validation.

## Page classification

Classification uses configured URL, title, headings, visible content, forms/CTAs, internal-link
context, media type, and structured-data signals. Structured data is optional evidence; missing
schema is itself a possible gap after role classification.

`SitePageAnalysis` stores `page_kind`, `industry_role_id`, the exact frozen pack manifest (catalog
version, pack id/version, content hash, classifier version), confidence, winner margin,
alternatives, conflicts, and bounded signal evidence.

The row is append-only, keyed by `(artifact_id, analyzer_version, industry_pack_id,
industry_pack_version)` with a partial unique index enforcing one `is_current` row per artifact.
Recomputing under a new pack version writes a NEW row; it never mutates the old one, which is what
recrawl comparison needs and what stops a pack upgrade from reinterpreting history.

Three role states stay distinct and must not be collapsed:

- **selected** — a role id with score, margin, and confidence band;
- **executed abstention** — `industry_role_id IS NULL` WITH `role_abstention_reason` (the
  classifier ran and declined: `schema_only`, `ambiguous_margin`, `below_minimum_score`, …);
- **never ran** — no pack frozen on the crawl, so the API returns `industry_role: null` entirely.
"We did not look" and "we looked and could not tell" are different facts, and only the second is
evidence about the page.

Pack resolution happens ONCE at crawl creation and freezes into `SiteCrawl.configuration`. Read
endpoints render the frozen manifest and never re-resolve a pack. An unknown or ambiguous industry
label leaves the project unpacked rather than falling back to `general_business`.

## Documents

Separate policies govern:

- unsafe/unsupported hard exclusions;
- inventory-supported document types;
- document types eligible for bounded extraction;
- project/pack disposition and temporal state.

A historical fee PDF can remain useful evidence while being prohibited from supplying current fee
truth without review. Extraction coverage and source coordinates are explicit.

## APIs and compatibility

Existing crawl, pages, issues, detail, events, monitored URL, Site Health projection, and export
routes remain compatible during migration. New Site Intelligence reads project only persisted
snapshots and evidence. No read route crawls, classifies, calls a model, or repairs lifecycle state.

The detailed visibility-era runtime reference is archived at
`archive/subsystems/site-health-detailed-runtime-reference.md`; use it only for historical
comparison and verify every implementation claim against code.
