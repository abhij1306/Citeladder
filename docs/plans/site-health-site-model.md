# Site Health: observed site model

Four sequential PRs, each merged before the next starts, each in its own chat. Every stage below is
self-contained enough to hand to a fresh session.

**Status:** all four PRs implemented.

**Guiding constraint:** CiteLadder may confidently report **what it observed**. It must be extremely
conservative about claiming what a site's structure *is* or what it *must* contain.

**Versions:** every shipped semantic change bumps the relevant replay token, even pre-launch. PR1
ships `sh-extractor-11`, `sh-classifier-7`, `sh-analyzer-6`, `sh-rules-5`, and `sh-scoring-3`.
Later PRs must bump the exact extractor, classifier, analyzer, rule, scoring, or formula versions they
change. A disposable database reset does not replace provenance.

PR3 ships extractor `sh-extractor-12`, analyzer `sh-analyzer-7`, rule catalog
`sh-rules-6`, architecture formula `sh-architecture-1`, and archetype policy
`sh-archetypes-1`. Classifier and scoring semantics remain unchanged.

PR4 bumps nothing: it is a read/presentation layer over the same persisted
evidence. The archetype correction is applied at read time under the SAME
`sh-archetypes-1` policy and never rewrites a persisted row, so no replay token
moves.

---

## Context

Two ChatGPT documents propose improvements — `citeladder_link_graph_page_type_plan.md` (classifier +
link graph + PageRank) and `citeladder_site_health_report.md` (site modelling: site type → hierarchy
→ tree → expected-vs-observed). A third document reviewed a draft of this plan and cut roughly a
third of the machinery. That review is adopted; its conclusions are folded in below.

Everything here is verified against the **real ilovedooney.com crawl in the dev DB**
(`7adfc697-23f9-443e-8d53-e3f2e72ae1e3`, 99 pages) and against git history.

### What the real crawl proves is broken

| Observed | Evidence |
|---|---|
| 11 `/pages/*` pages classify `other`, `classified_by=none`, confidence `0` | care-cleaning, refund-policy, store-locator, shipping-policy, orders-payments, our-promise, track-your-order, register-my-dooney, the-dooney-guarantee, accessibility-policy, featured-blog-categories |
| `other` pages **score higher** (93.2 avg) than classified ones, because every page-kind-scoped rule is N/A | `aeo.schema_expected_for_type` not_applicable ×11 |
| `commerce.visible_price` is `"$1"` on **all 99 pages**, context `\+\*]/g,"\\$&")+"\\s*\\=…` | `_PRICE.search(text_of(root))` in [commerce_facts.py](../../backend/app/analysis/site_health/commerce_facts.py) scans inline `<script>` text |
| `aeo.product_visible_schema_parity` fails 36/37 PDPs | it parity-checks `gtin` and `availability` (`https://schema.org/OutOfStock`) against visible text — those can never match |
| `aeo.schema_matches_content` fails 36/37 PDPs | exact substring: schema `"Dillen Letter Carrier, Caramel"` vs visible `"Dillen Letter Carrier"` |
| Listing structure is invisible | `commerce.product_cards` / `category_links` are `0` and `category_role` is `"unknown"` on all 99 pages — `_cards()` matches class tokens no real theme used |
| Nav dominates every link-derived signal | **every** page carries ~63 `/collections/*` and ~5 `/products/*` links. `/collections/totes` has 42 product links; `/collections/new-arrivals` has the same 5 as a policy page (JS-hydrated grid) |
| Crawl coverage was ~2% | `requested_page_limit: 100`, analyzed 99, on a site with thousands of products |

Your assessment — *"current analysis is not good enough to present any valuable information"* — is
correct, and this is why.

**The single mechanism behind most false signals:** everything reads the *whole document* — nav,
footer, inline scripts, recommendation modules. One structurally-scoped primary region fixes the
price bug, the listing bug and the carousel risk together.

### Corrections to the source documents

- *"url-detail.tsx already has a Links tab"* — **false**; there are no tabs in that view. A link-graph
  subsystem existed and was deleted in `3a629f8c`.
- *"Recommendation carousels turn policy pages into products"* — **not observed**;
  `/pages/refund-policy` has no cart marker in body text at all.
- *"nofollow/sponsored flags"* — anchors store a raw untokenized `rel` string only
  ([fact_links.py](../../backend/app/analysis/site_health/fact_links.py)).
- *"Listing signal from repeated product links"* — site nav puts a constant ~63-link baseline on every
  page; whole-page counting types the entire site `category`.

### Industry-pack post-mortem

The pack subsystem shipped `d6fdf01f` (2026-08-07) and was deleted in `89fca81e` (2026-08-11) — it
lived four days, and the removal was **−83,927 lines across 178 files**: 16 packs, 232 page roles,
347 question contracts, 230 assertion predicates, knowledge/assertion/relation/corrections tables, and
a six-tab workspace that wrapped the existing dashboard as its own "Pages" tab.

Why it could not work:

1. **Industry knowledge did the classifying.** Every role carried its own weighted keyword classifier
   (`title contains_any ["shop","store","brand"] weight 3.0`) with `minimum_score`/`minimum_margin`,
   plus a **second page taxonomy** alongside `page_kind`.
2. **It was never trusted to speak.** Only 2 of 16 packs were calibrated and
   `authoritative_findings_enabled` was `false` in **all 16** — the catalog never made an
   authoritative claim in production. Its own notes admit bugs that "published `true` as a fee of
   1.00" and `NaN` as "INR nan".
3. **The cheap mechanism already existed unwired.** The archived audit: *"The mechanism is built and
   unused… The work is classifying the catalog, not building machinery."*

Point 3 has since largely been done — of today's 32 rules, 11 are `page_kind`-gated and the remaining
`always`/`has_html` ones (title, canonical, indexable, https, TTFB, compression) are genuinely
universal. Issues are already grouped per rule with an affected-page count, so the "hundreds of
duplicate warnings" complaint is also addressed. **What is left is classification accuracy and a
site-level model.**

This plan does not revive any of it: no second taxonomy, no new page kinds, no knowledge/entity
tables, no corrections ledger, no per-vertical classifier, no parallel workspace. The archetype layer
**expects, it does not classify**, and it can only produce advisories.

**Explicit non-goal:** `docs/site-health.md` records that the removal left content briefs with an
empty fact/source envelope and that replacing it is a separate product decision. This plan does not
refill it. Nothing here extracts or persists durable business facts.

### Archetype source

Onboarding already resolves closed business facets — no new classifier needed:
[`BusinessContextProfile`](../../backend/app/domain/projects/onboarding/context_profile.py) persisted on
`BrandProfile.business_context`, read via
[`project_business_context()`](../../backend/app/domain/projects/shim.py). `business_model` is a closed
9-value vocabulary ([brand_discovery.py](../../backend/app/core/config/brand_discovery.py)) carrying
`knowledge_strength` and `field_confidence`.

Caveat that shapes the design: onboarding's review screen only asks the user to confirm *what you
sell*, *who buys it* (`business_type`), *where they buy it* (`market_scope`). **`business_model` is
model-written and never user-confirmed**, and `business_context` can be absent entirely. So the
archetype must be broad, corroborated, abstain freely, and never produce a defect.

---

## Design principles

1. **Observed, not asserted.** Positive observations are safe; absence claims require completeness.
2. **Structure over vocabulary.** Region detection and secondary-module detection are structural. No
   keyword list decides what content is.
3. **Tiers, not weights.** Deterministic evidence tiers (decisive → corroborating → weak), not score
   accumulation with magic numbers.
4. **Confidence is a label.** `high | medium | low | unknown`, plus the evidence list. Never a decimal
   that looks like a probability.
5. **One taxonomy, frozen.** `page_kind` stays coarse and **no new kinds are added**. No parallel tag
   gating vocabulary either.
6. **Abstain loudly.** `other`, `unknown`, `partial`, `not_applicable` stay distinct.
7. **Nothing analytical may break a crawl.** Derived architecture work is retryable and idempotent and
   runs outside the locked finalize transaction.
8. **No eval gates.** No 200-URL runner, no gold-label thresholds. Ordinary unit tests plus a small
   set of real-HTML fixtures capturing bugs already found.

---

## PR 1 — Structurally scoped facts, classifier tiers, honest findings

Nothing downstream is trustworthy until this lands.

### 1.1 Structural region scoping — `backend/app/analysis/site_health/fact_regions.py` (new)

Pure and bounded, sibling of `fact_links.py` / `fact_signals.py`, called from `parser.py` near
[parser.py](../../backend/app/analysis/site_health/parser.py).

**Primary region — structural only, no vocabulary:**
1. first `<main>` or `[role=main]`; else first `<article>`; else `<body>`
2. remove `<header> <nav> <footer> <aside> <script> <style> <template> <noscript>` and
   `[role=banner|navigation|contentinfo|complementary]`

Nothing is removed because of what its heading says. Instead, **tag** structures:

- `repeated_card_list` — a container with ≥3 structurally similar children (same tag, similar child
  shape, each containing a link). This is what a recommendation carousel, a product grid and a
  related-posts strip all are. Tagging it costs nothing and is theme-independent.

That tag is what protects against carousel contamination, replacing the earlier keyword approach:
product evidence must come from **outside** a `repeated_card_list`. A policy page's "You May Also
Like" strip is structurally a repeated card list; a PDP's buy box is not.

Export the region helper so `commerce_facts.py` reuses it for `visible_price` — this alone fixes the
`"$1"` value on all 99 pages.

**Per-anchor region** (this is how chrome is identified — from the DOM, not from graph statistics):
extend `fact_links._anchor_assets` to record `region: header|nav|main|footer|aside|other` for each
anchor. The DOM is right there; do not reverse-engineer boilerplate from link frequency later.

**Emitted facts** — bounded counts and booleans only:

```
entity:
  region:   {source, card_list_count}
  product:  {has_primary_price, has_purchase_control,
             has_variant_control, has_sku_marker}
  listing:  {largest_card_list_size, distinct_card_list_targets, has_result_count,
             has_sort_control, has_filter_control}
  location: {address_entity_count, has_phone, has_hours}
```

### 1.2 Classifier — evidence tiers

Keep purity, config-owned tables, evidence/alternatives/conflicts, fail-closed `other`, and the rule
that structured data never self-certifies.

PR1 replaces the old first-match ordering and hardcoded content/path exception
with **three explicit tiers resolved by rules, not scores**:

- **Tier A — decisive structural evidence.** A purchase control plus visible price outside any card
  list with one corroborator (variant control, SKU, product `og:type`, or one Product+Offer schema
  node) → `product`; schema is never sufficient by itself. A listing structure (largest card list
  above a config size **and** ≥1 of result-count / sort control / filter control, with
  `ItemList`/`CollectionPage` allowed only as a corroborator) → `category`.
  A single primary-region address entity under a `/store|/location` route → `local`.
- **Tier B — route family.** The existing `PAGE_KIND_PATH_PATTERNS`. Applies when no Tier A evidence
  contradicts it.
- **Tier C — weak fallback.** Title/H1 semantic match (`PAGE_KIND_TITLE_KEYWORDS`, bounded generic
  vocabulary) mapping only onto page kinds **already in the taxonomy** — `trust_policy`, `guide`,
  `service`, `about_contact`, `faq`. Applies only when A and B produced nothing. This is what
  resolves the 11 verified `other` pages.

Resolution is a short deterministic rule: highest tier with evidence wins; a Tier A/Tier B conflict is
recorded and Tier A wins; ambiguity within a tier → `other`.

`confidence` becomes a label: `high` (Tier A), `medium` (Tier B, or Tier A with a recorded conflict),
`low` (Tier C), `unknown` (`other`). The current numeric confidence is actively misleading — it sums
*all* signal weights including disagreeing ones, so a `/Categories/…` PDP reports 1.3 while
classifying `category`.

Note on a deliberate deviation from the review: it suggests keeping `page_kind` coarse and adding
non-exclusive tags for policy/support/guide. `trust_policy`, `guide`, `service`, `about_contact` and
`faq` are **already shipped page kinds** with profiles and schema contracts, so Tier C uses what
exists rather than growing anything — and a tag layer would need its own rule-gating vocabulary,
which is the second-taxonomy trap. **No new page kinds are added, now or later.**

`local` vs locator: `local` requires exactly one primary-region address entity; zero or many falls
through, so a store finder never inherits the `LocalBusiness` contract.

### 1.3 Honest findings

`defect` vs `advisory` is already a first-class, server-filtered product concept
(`docs/site-health.md`), and only defects feed severity filters and Opportunities — so this fits the
shipped model exactly.

1. **Missing schema is always advisory; invalid schema is a defect.** Simpler and more defensible than
   a per-page-kind required/advisory split. `aeo.schema_expected_for_type` → LOW advisory for every
   page kind. `aeo.schema_recommended_present` → advisory. `aeo.schema_required_valid` stays a defect
   and already returns `not_applicable` when no expected block exists
   ([schema_rules.py](../../backend/app/analysis/site_health/schema_rules.py)); extend it to also flag
   contradictory markup.
   Without this, correctly classifying the 11 `other` pages would make each newly fail a HIGH weight-3
   rule for lacking optional `WebPage`/`Service` markup, dropping them from ~93 for no real defect.
2. **`aeo.product_visible_schema_parity`** — drop `gtin` from parity; map `availability` enums to a
   visible vocabulary (`InStock` → "in stock"/"add to cart", `OutOfStock` → "out of stock"/"sold out")
   instead of matching the raw schema.org URL. Failing 36/37 PDPs today.
3. **`aeo.schema_matches_content`** — normalized token-set overlap above a config ratio instead of
   exact substring containment. Failing 36/37 PDPs today.
4. **`commerce_facts.visible_price`** — read from the primary region.

**Files:** `analysis/site_health/fact_regions.py` (new), `parser.py`, `fact_links.py`,
`commerce_facts.py`, `page_kinds.py`, `content_heuristics.py`, `rules.py`, `schema_rules.py`,
`core/config/site_health_taxonomy.py`, `site_health_rules.py`.
`backend/app/analysis/site_health/.ruff.toml` bans bare `except Exception` here — route DOM failures
through `dom.dom_failure()`.

**Verify:** unit tests for region selection, card-list detection, each entity signal, and tier
resolution including conflict and abstention. A small `backend/tests/fixtures/site_health/*.html` set
capturing the bugs above (script-embedded price, PDP with carousel, JS-hydrated listing, policy page
with no signals). Then re-crawl ilovedooney and confirm by SQL: the 11 pages leave `other`;
`visible_price` is no longer `"$1"`; the three product rules stop failing on ~every PDP.

---

## PR 2 — Internal link metrics and coverage state

No PageRank, no authority metric, no persisted edge table.

### 2.1 Coverage state (prerequisite for everything in PR3)

Persist an explicit `coverage_state` on the crawl snapshot: `complete | partial | unknown`.

- `complete` only when the discovery frontier was exhausted, no page budget was hit, and no
  truncation occurred
- `partial` when the budget was hit (the reference crawl: 99 analyzed against
  `requested_page_limit: 100` on a multi-thousand-page site) or discovery was cut short
- `unknown` otherwise — discovery can fail without hitting a limit, so not hitting the limit does not
  prove completeness

Persist the config-owned coverage-formula version and bounded evidence behind the state (budget,
frontier, observation, and discovery-task counts plus reason codes). Do not derive this from
`inventory_complete`: the shipped lifecycle uses that field as an inventory-read projection and it
can be true after a non-empty discovery without proving frontier exhaustion. PR2 persists the state;
PR4 renders every site-level number beside it. This is the single most important guard against
confidently wrong output.

### 2.2 Transient graph, persisted metrics — `backend/app/analysis/site_health/link_graph.py` (new)

Build the graph **in memory** from already-persisted anchor facts. Persist only:

**`SitePageLinkMetric`** — `backend/app/models/site_health/links.py` (new), one row per
`(crawl_id, site_url_id)`: `inbound_count`, `outbound_count`, `main_content_inbound_count`,
`main_content_outbound_count`, `nofollow_inbound_count`, `depth_from_home`, `source_page_count`,
bounded `top_inbound` / `top_outbound` JSONB, exact `source_artifact_ids`, `extractor_version`, the
config-owned link-metric `formula_version`, and `created_at`. Follow the `SiteUrlObservation` tenancy
pattern (bare `mapped_column` for
`project_id`/`crawl_id`/`site_url_id`, composite `ForeignKeyConstraint` on
`(workspace_id, project_id, crawl_id)` and `(workspace_id, project_id, site_url_id)`).

Raw edges are **not** persisted — ~100k rows per 500-page crawl buys storage, retention and query
complexity for no product feature yet. Bounded top-N inbound/outbound neighbours per page are stored
as part of the page's metric row (JSONB, capped), which is all the URL-detail view needs. Add an edge
table later only if a feature actually requires it.

- `depth_from_home` is ordinary shortest-path depth over **all** followable internal links.
  Navigation links are real clicks; the earlier "contextual depth" idea (nav edges removed) is
  conceptually wrong and makes legitimate pages look unreachable. `main_content_inbound_count` is
  exposed separately as the "is this genuinely linked, or only in the menu" signal, using the
  per-anchor `region` recorded in PR1 — chrome comes from the DOM, not from link frequency.
- `rel` is tokenized here (`nofollow`, `sponsored`, `ugc`), plus page-level
  `facts["robots"]["nofollow"]`.
- URL identity reuses `domain/site_health/normalization.canonical_identity` and
  `url_policy.canonicalize(href, base_url=source_final_url)` — no second normalizer. Nodes resolve via
  `SiteUrl (project_id, url_hash)`. Redirect aliases use the current analysis artifact's acquired
  `final_url`, augmented by immutable `SiteUrlObservation` aliases: early admission observations can
  predate the fetch and therefore cannot own redirect truth alone. Off-crawl internal targets are
  counted but are never nodes.

**Migration:** one new table folded into `migrations/versions/0001_initial.py` per repo policy; bump
the table-count assertion in `backend/tests/unit/test_migration_revision_baseline.py:38` `109` → `110`.

### 2.3 Wiring — outside the finalize lock

Run as a **post-terminal queued task**, following the existing `change_intel` pattern
(`domain/site_health/change_queue.py`, `workers/site_health/phases/change_intel.py`, task kinds in
`site_health_contracts.py`). Idempotent, retryable, and incapable of failing crawl finalization — the
review is right that an analytical feature must never make the core crawl transaction fragile.

**Verify:** unit tests for depth BFS, duplicate-link collapse, nofollow handling, redirect resolution,
off-crawl targets, main-content vs chrome counts, determinism under shuffled input. Component tests
for tenant isolation and idempotent re-run.

---

## PR 3 — Observed architecture

Everything here is derived from PR1 kinds and PR2 metrics. No new crawl, no LLM.

### 3.1 Page families

Group the crawl's `SiteUrl` rows by path template (final segment → `*`). Per family: URL count,
page-kind distribution, median depth, indexable count, metadata-duplication rate, and — **only when
`coverage_state == complete`** — orphan count. Not a template identity owner for indexability, which
`docs/site-health.md` puts out of scope.

### 3.2 Hierarchy — evidence-ordered, `unknown` is a valid answer

Parent resolution, strictly in this order:

1. **Breadcrumb parent** (`facts["commerce"]["breadcrumbs"]`, already extracted) resolved to a crawled
   URL
2. **Explicit structural relationship** — schema `BreadcrumbList` / `isPartOf`
3. **Safe URL/family relationship** — the immediate parent path when that URL was crawled and is a
   `category`/hub kind
4. **`unknown`**

The earlier "minimum-depth inbound neighbour" rule is dropped: it manufactures hierarchy from
arbitrary cross-links and produces a tree that looks authoritative while being wrong. Pages with an
unknown parent collapse into their family rather than being attached somewhere plausible.

The tree renders from resolved parents, large families collapsed to counts (`[142 Products]`), and is
labelled **Observed architecture — N pages sampled — coverage: partial/complete/unknown**.

### 3.3 Archetype — advisory only

New config `backend/app/core/config/site_health_archetypes.py`, following the
`PROMPT_EXEMPLARS: dict[business_model → …]` pattern in `visibility_prompts.py`.

**Four archetypes**, collapsing the nine business models so a wrong (and unconfirmed)
`business_model` rarely changes the outcome:

| archetype | from `business_model` | commonly observed |
|---|---|---|
| `commerce` | `retail`, `d2c_product`, `marketplace` | category listings, product detail, shipping/returns, contact, help hub, editorial |
| `software` | `b2b_saas` | pricing, product/feature, docs, about/contact, comparison, editorial |
| `services` | the existing `SERVICE_BUSINESS_MODELS` frozenset + `regulated_finance` — reuse `is_service_business()` ([brand_discovery.py](../../backend/app/core/config/brand_discovery.py)) | service pages, about/contact, trust policy, local pages (only when user-confirmed `market_scope` is `local`/`regional`), guides |
| `other` | anything else, or abstention | nothing evaluated |

**No role is "required".** Every counterexample is real — enterprise SaaS with no public pricing, a
single-product store with no category architecture, a small tool with no docs site. Output is
descriptive:

```
Commerce site
Observed:                     ✓ Product pages  ✓ Category pages  ✓ Returns  ✓ Contact
Common structures not observed: • Help / FAQ hub  • Editorial content
```

This is a recommendation surface. It never produces a defect, never affects any score, and is
suppressed entirely unless `coverage_state == complete` — absence is exactly what a partial crawl
cannot prove.

**Resolution, with three safety valves:** read `business_model` via `project_business_context()`;
abstain to `other` when the profile is absent, `knowledge_strength == "none"`, or
`field_confidence["business_model"]` is below a config floor; and abstain when the crawl's own
`page_kind` distribution materially contradicts the archetype. The crawl can veto the archetype; it
can never assign one. The Architecture tab shows the archetype with its source and lets the user
change it — that single field is the entire correction surface.

### 3.4 Structural findings — crawl-finalize rules

`crawl_finalize` applicability already exists with weight 0 (issues only, no score distortion) —
`technical.sitemap_orphan` and `technical.hreflang_conflict` are the precedent. Each rule emits **one**
aggregated issue with a count, which is the "root cause, not symptoms" requirement.

Safe on any coverage (positive observations):
- `architecture.excessive_depth` — pages beyond a config depth from home
- `architecture.breadcrumb_hierarchy_conflict` — breadcrumb parent contradicts explicit structure
- `architecture.duplicate_metadata_in_family` — a family sharing title/meta across many URLs

Requires `coverage_state == complete` (absence claims), otherwise `not_applicable` with reason
`coverage_not_complete`:
- `architecture.orphan_pages`
- `architecture.parentless_detail_pages`
- `architecture.unhubbed_family`

The same audit applies to the existing `technical.sitemap_orphan`, which today compares sitemap URLs
against links found in a possibly 2%-coverage crawl and can therefore be confidently wrong.

**Verify:** unit tests for family grouping, each parent-resolution tier including `unknown`, each
rule's fire/not-fire and its coverage abstention, and archetype resolution including all three abstain
paths.

---

## PR 4 — UI

`site-health-screen.tsx` already has an `AnalysisTabs` slot (`pages | aeo-readiness | changes`). Add
**`architecture`**. All four layers move together because the frontend zod parse is strict:
`api_schemas.py` → `lib/api/schemas/site-health/*.ts` → `types.ts` → component.

**Architecture tab**
- *Site profile*: archetype with its source ("from your onboarding profile") and an edit control;
  pages analyzed; **coverage state stated plainly** whenever it is not `complete`
- *Observed architecture tree*: expandable, families collapsed to counts, unknown-parent pages shown
  under their family, click a node → existing URL detail
- *Common structures not observed*: the archetype advisory block, hidden unless coverage is complete
- *Page families* table: family, URL count, depth, indexable rate

**Pages table** ([pages-table.tsx](../../frontend/components/site-health/pages-table.tsx)): add Inbound,
Main-content inbound, and Depth columns, sortable. Backend adds a `sort` param with keyset over
`(sort_value, site_url_id)` joined to `SitePageLinkMetric`.

**URL detail** ([url-detail-view.tsx](../../frontend/components/site-health/url-detail-view.tsx)): a new
**Internal Links** section card matching the existing `HeaderCard`/`ScoreTile`/`DeliveryMetrics`
composition — inbound / outbound / main-content inbound, depth from home, top linking pages, top
linked pages. No Tabs primitive exists in this view; do not introduce one.

**Exports:** `analysis/site_health/exports.py` already renders Markdown — the ASCII tree belongs
there, where it is genuinely the right format.

---

## Explicitly deferred

PageRank / Internal Authority · frequency-based chrome inference · contextual (nav-stripped) depth ·
heuristic link-derived parent assignment · required archetype roles · archetype-driven defects · any
new page kind or tag taxonomy · persisted raw graph edges · curated per-industry reference
structures · refilling the content-brief fact envelope.

## Docs to amend (PR3)

Several files carry a blanket prohibition written after the 2026-08 removal. Nothing here is a pack
revival, but the archetype advisory layer is new authority and must be documented, stating plainly:
**it expects, it does not classify, and it cannot produce a defect.** Also record the coverage-state
contract and the new crawl-finalize rules.

- `AGENTS.md` — "Do not recreate the removed Site Intelligence workspace, industry-pack catalog,
  knowledge tables, corrections, or comparison system." Repo-wide agent rule and the strongest
  blocker; carve out the archetype advisory layer explicitly.
- `docs/site-health.md` L26–27, plus the Page-kind classification and Rule applicability sections.
- `docs/documentation-index.md` L58–68.
- `docs/frontend-architecture.md` L68–70 — the Architecture tab is a tab in the existing screen, not a
  second workspace.
- `docs/backend-architecture.md` L280–283 for the new metric table.

Leave `docs/site-health.md` L313–317 (empty content-brief fact envelope) unchanged — out of scope.

## Verification and gates

Per PR: the tests named in its section, then once, from the repo root: `.\scripts\check.ps1` then
`.\scripts\test.ps1`. DB reset + `alembic upgrade head` + `alembic check` for the folded migration in
PR2. Live confirmation against a re-crawl of ilovedooney.com using the SQL in this plan, plus 2–3
reference crawls (a WooCommerce store, a SaaS/docs site, a non-Shopify retailer) so thresholds are not
Shopify-shaped — crawling is free, so do this before finalizing any threshold.

Each PR is opened as a regular (non-draft) PR only once its implementation is complete, and merged
before the next PR's chat begins.

## Plan document

First action of PR1: commit this plan to `docs/plans/site-health-site-model.md` so each subsequent
chat has the full handoff, and register it in `docs/documentation-index.md` — `check.ps1` runs a
documentation-index check that fails on an unregistered doc.
