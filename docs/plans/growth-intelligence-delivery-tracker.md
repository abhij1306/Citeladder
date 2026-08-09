# Growth Intelligence Delivery Tracker

> **Status:** active implementation handoff.
>
> **Authority:** tracks delivery only. Product and implementation decisions remain in the
> canonical [Demand](demand-intelligence.md), [Site](site-intelligence-primary-product.md), and
> [Content](content-intelligence.md) plans.

## Branch sequence

| Order | Branch | Scope | Status | Pull request | Merge commit |
|---|---|---|---|---|---|
| 1 | `feature/demand-intelligence` | Demand D0-D5 | `merged` | [#57](https://github.com/abhij1306/Citeladder/pull/57) | `0f5915ac5c2e1eb935f72c56e9e745303662614f` |
| 2 | `feature/site-intelligence-s5` | Corrections, contradiction decisions, Site S5 | `merged` | [#58](https://github.com/abhij1306/Citeladder/pull/58) | `70d5894be96d8bfb0f50c76bb6f83eabb2c4e640` |
| 3 | `feature/content-intelligence` | Content C0-C5 | `ready_to_ship` | [#59](https://github.com/abhij1306/Citeladder/pull/59) | — |

Statuses are exact: `not_started | in_progress | ready_to_ship | merged`. A branch starts from
freshly synchronized `main` only after its predecessor is merged.

## Delivery rules

- Extend current owners before adding persistence, queues, adapters, projections, or UI systems.
- Treat touched subsystems as greenfield: prefer small explicit contracts, remove obsolete paths,
  and do not preserve technical debt merely for compatibility in this pre-launch product.
- Use UUIDs, direct workspace/project authorization, immutable evidence, append-only attempts and
  transitions, coded API errors, projection-only reads, and config-owned policy.
- Fold schema changes into `migrations/versions/0001_initial.py`; never add `0002+`.
- Use focused tests while building. Run the complete backend, frontend, and browser suites once
  locally only after the branch is otherwise complete, then run them again in CI through
  `$ship-main`.
- Reset only a resolved, verified disposable database. Rebuild Compose images before branch
  acceptance and record service failures or environmental limitations.
- Resolve technical conflicts from current `main`; ask the user only when product intent is needed.
- Before shipping, update this tracker and every affected canonical/current-runtime document with
  implemented behavior, public contract changes, migration changes, verification, gotchas, and
  deliberate deferrals.

## Branch 1 — Demand Intelligence

Canonical source: [Demand Intelligence](demand-intelligence.md).

- [x] **D0 — Data correctness:** combined GSC/GA4 provenance, refresh idempotency, canonical
  landing paths, join coverage, engaged sessions/key events, null/zero semantics, Cube27 fixtures.
- [x] **D1 — Report families:** query-page GSC, Search Appearance, GA4 capability discovery and
  compatible landing/session/event/key-event reports, coverage and truncation metadata.
- [x] **D2 — Identity and journeys:** canonical Site/GSC/GA4 page identity, versioned journeys,
  configured outcomes, stable join rates, explicit unmatched reasons.
- [x] **D3 — Signals and priorities:** `DemandSignal`, `DemandSnapshot`, deterministic candidates,
  bounded semantic mapping, comparison, and Opportunity integration.
- [x] **D4 — Prompt strategist:** grounded generation, validators, portfolio coverage, active/archive
  lifecycle, and frozen Demand provenance.
- [x] **D5 — Outcome loop:** manual/scheduled Visibility linkage, descriptive comparisons, and the
  complete Demand Intelligence workspace.

**Acceptance gate:** sanitized Cube27 and Asian School fixtures pass; every result traces to exact
evidence and windows; reads make no external calls; unavailable is never rendered as zero.

### Demand implementation record

- Implemented behavior: combined GSC/GA4 Traffic projections now use source-revision idempotency,
  canonical relative landing URLs, engaged sessions/key events, and complete contributing
  provenance. Six GSC and seven Demand/session GA4 report families persist coverage/provider
  metadata and optional GA4 compatibility. Versioned Education/Commerce journeys feed immutable
  Demand snapshots/signals, prompt portfolio summaries, descriptive Visibility outcomes, and the
  shared Opportunity store. Prompt generation is Demand-grounded and active/archive only; audit
  prompt snapshots freeze generation evidence. `/demand` ships six accessible panels.
- Public contract changes: added persisted-only `/api/v1/projects/{project_id}/demand/capabilities`,
  snapshot list/detail/recompute, and journey list/versioned PUT routes; prompt status input is now
  `active | archived`; Traffic refresh payloads include `source_revision`.
- Schema changes: folded `journey_definitions`, `journey_definition_versions`, `demand_snapshots`,
  and `demand_signals` into `0001_initial.py`; added frozen `generation_evidence` to
  `audit_prompt_snapshots`; added Demand snapshot/revision provenance to Opportunity snapshots;
  made analysis-derived rows require their immutable raw-response artifact with cascading
  retention. No `0002+` migration exists.
- Verification: focused backend Demand, Traffic, integration, prompt, audit, Opportunity, queue,
  migration-baseline and configuration tests passed (179 tests). The completed branch passed Ruff
  format/check, mypy across 355 source files, and the complexity ratchet with eight measured
  improvements and no baseline relaxation. Frontend format, ESLint, TypeScript, design-system
  policy, architecture policy, and contract checks passed. Documentation validation reported 30
  active documents and 47 archived files; all 16 industry packs and their fixtures validated.
  From-zero migration reset/upgrade/check passed against the confirmed disposable development
  database at `127.0.0.1:55432/citeladder`, with only `0001_initial.py`. Compose images rebuilt
  with force recreation; migration completed, API health passed, and required workers started.
  The complete backend suite passed with 2,504 passed and 7 skipped; the complete frontend suite
  passed 1,248 tests in 144 files; all 26 browser tests and the Demand visual snapshot passed; the
  production build passed with a server-only `BACKEND_ORIGIN`. CI is pending the pull request.
- Gotchas and conflict resolutions: GA4 optional report incompatibility is a persisted unavailable
  capability, not a failed whole sync; provider-reported metadata is immutable evidence. GA4
  landing pages include configured organic plus classified AI traffic. An observed zero key-event
  value remains distinct from unavailable. Exact dimension tuples route GSC and GA4 fixture
  responses, and pack journey provisioning uses an atomic conflict-safe insert. A legacy Cube27
  fixture that represented a 28-day aggregate as a daily row was corrected to an honest one-day
  window. Opportunity freshness includes Demand identity and revision. Prompt approval was removed
  because audit execution or scheduling is the user decision. The branch also repaired stale
  browser fixtures and assertions left by the current `main` contract, and serialized Playwright
  workers because its single lazy-compiled development server produced nondeterministic navigation
  races under six workers. The missing visual-test configuration now owns a deterministic Demand
  empty-workspace snapshot. Pre-merge Sonar review reported 20 new maintainability findings even
  though its quality gate passed; the API capability mapper, coded errors, snapshot inputs,
  Opportunity mapping, provider/model constants, and frontend panels were simplified before merge
  rather than accepting the green badge alone.
- Deliberate deferrals: paid media, CRM, email, and social remain future connectors per the
  canonical plan. Composite workspace foreign keys across the entire audit/analysis/raw-artifact
  graph remain with that owning persistence redesign: raw artifacts do not currently carry a
  workspace column, so constraining only downstream analysis rows would leave a partial,
  misleading boundary. Workspace authorization remains enforced on reads and writes. No D0-D5
  acceptance item is deferred.

## Branch 2 — Pending Site Intelligence

Canonical sources: [Site Intelligence](site-intelligence-primary-product.md) and the
[knowledge kernel](knowledge-kernel-and-industry-pack-spec.md).

- [x] Durable corrections and append-only transitions.
- [x] Inline contradiction decisions with all observed evidence preserved.
- [x] Correction precedence across recomputation and withdrawal.
- [x] Compatible snapshot comparison across facts, questions, rules, journeys, dimensions, scores,
  and coverage.
- [x] Evidence-only `verified | partial | unresolved` action resolution.
- [x] Education and Commerce calibration preserved; every other pack remains explicitly unproven.

**Acceptance gate:** corrections survive recrawl, unresolved conflicts cannot become authoritative
output, and later evidence resolves actions without mutating earlier snapshots.

### Site implementation record

- Implemented behavior: project-stable typed corrections for entities, assertions, and relations
  persist across recomputation and overlay rather than mutate observed rows. Create/withdraw
  transitions are append-only; withdrawal restores the latest derived value. Contradictions keep
  every side visible and accept an inline reasoned correction. The later Site snapshot freezes a
  bounded compatible comparison across facts, questions, rules, journeys, dimensions, scores,
  and coverage plus evidence-only Site action resolution.
- Public contract changes: knowledge entity/assertion/relation items now expose `effective_value`
  and correction provenance; contradiction groups expose `corrected | unresolved` and the active
  correction. Added persisted-only correction list/create/withdraw routes. Site Intelligence
  overview now exposes `prior_snapshot_id` and the frozen `comparison` projection.
- Schema changes: folded `corrections` and `correction_transitions` into `0001_initial.py`; extended
  `site_health_snapshots` with self-referential `prior_snapshot_id` and bounded `comparison` JSONB.
  No approved-memory table, contradiction-group table, or `0002+` migration exists.
- Verification: backend `2510 passed, 7 skipped`; frontend `1251 passed`; Playwright `26 passed`
  with one worker. Ruff format/check, mypy, complexity ratchet, Prettier, ESLint, TypeScript,
  frontend policy/contract, production build, documentation validation, and the 16-pack catalog
  validator passed. `pip-audit` found no known vulnerabilities and the committed-baseline secrets
  scan passed. The verified disposable `127.0.0.1:55432/citeladder` database was reset,
  `0001_initial.py` upgraded from empty with no ORM drift, all Compose images were rebuilt and
  force-recreated, migration exited 0, all services started, and `/health` returned 200. Pull
  request [#58](https://github.com/abhij1306/Citeladder/pull/58) passed all nine CI checks; Sonar
  reported zero open pull-request issues after its findings were resolved.
- Gotchas and conflict resolutions: correction target identity excludes crawl IDs and, for an
  assertion, the observed value; this is what lets a corrected value outrank a changed recrawl
  derivation. Entity scope outranks project scope only when it matches the projected entity,
  assertion subject, or relation source; unrelated entity scopes are ignored. Journey/content/
  prompt scopes remain unadvertised until their projections apply corrections. Snapshot compatibility is
  fail-closed on the immediately preceding snapshot's pack manifest and analyzer/scoring/projection
  versions. Only a persisted later `pass` verifies an
  action; missing, error, not-applicable, or fail evidence cannot. Opportunity target keys remain
  owned by the existing Site-issue mapping. The raw-artifact composite-FK redesign remains out of
  scope because raw artifacts still lack `workspace_id`.
- Review resolution: correction DTO expansion is explicit; shared target builders own all lookup
  identities; active/withdrawn state and reason limits are shared and database-constrained;
  concurrent insert conflicts map to 409; idempotent withdrawal releases its transaction;
  comparison reads rank analyses deterministically and expose full action-state totals beside
  bounded items. Review also added entity-context matching and regression coverage so simultaneous
  scoped corrections cannot leak into unrelated projections. Crawl overlap needed no new lock: project-locked creation already permits only one
  active crawl, so an earlier crawl terminalizes before a recrawl can be created. Object-valued
  corrections remain withdrawable even though the inline editor cannot create them.
- Deliberate deferrals: Content Intelligence context packages, briefs, generation, publication,
  and post-publication verification remain Branch 3. The fourteen non-Education/Commerce packs
  remain structurally valid but explicitly uncalibrated.

## Branch 3 — Content Intelligence

Canonical source: [Content Intelligence](content-intelligence.md).

- [x] **C0:** reconcile Content v1 ownership and lifecycle.
- [x] **C1:** question gaps, semantic match candidates, immutable briefs, selective context.
- [x] **C2:** provider-neutral generation, versioned skills, automatic validation.
- [x] **C3:** revisions, revalidation, save/export, publication claims, recrawl verification.
- [x] **C4:** inventory, strategy, Demand-aware priorities, Education then Commerce skills.
- [x] **C5:** Strategy, Inventory, Briefs, Drafts, Revisions, and Verification experience.

**Acceptance gate:** Education and Commerce fixtures complete gap → brief → context → generation →
validation → edit → save → publication claim → recrawl verification without invented facts,
fact promotion, score mutation, or autonomous publishing.

### Content implementation record

- Implemented behavior: deterministic inventory/strategy projections over compatible Site and
  optional Demand snapshots; immutable question-grounded briefs and bounded context manifests;
  brief-driven generation through the existing queue; automatic output validation; revision
  revalidation, save/export, publication claim, and later recrawl verification; and the six-panel
  Content Intelligence workspace. Education and Commerce fake-provider acceptance flows pass from
  missing question through observed recrawl evidence.
- Public contract changes: added persisted-only strategy, inventory, brief, context, validation,
  revision, transition, export, publication-claim, and verification endpoints under `/api/v1/content`.
  `ContentGeneration` responses now expose brief/context/skill/validator provenance. Feedback is
  reaction metadata only and no longer saves generated text into Brand Knowledge.
- Schema changes: folded content inventory, strategy, briefs, task context packages, validations,
  revisions, append-only revision transitions, and verifications into `0001_initial.py`; extended
  `content_generations` with brief, context-package, skill-version, and validator provenance. The
  obsolete generated-prose `brand_knowledge_artifacts` table was removed. No `0002+` migration or
  approved-memory store exists.
- Verification: Ruff format/check, mypy, the tightened complexity ratchet, `2521 passed, 7
  skipped` backend tests, `1254 passed` frontend tests, frontend format/lint/type/policy/contract,
  the production build, and `26 passed` single-worker Playwright tests pass. Documentation and the
  16-pack catalog validate; `pip-audit` reports no known vulnerabilities and the committed-baseline
  secrets scan passes. The verified disposable database passes downgrade, a from-zero
  `0001_initial.py` upgrade, and zero Alembic drift. All Compose images rebuild, the migration
  container exits 0, every long-running service remains up, and `/health` returns 200. CI and Sonar
  results are recorded after the pull request opens.
- Gotchas and conflict resolutions: a generation validation is immutable; an edited revision gets
  its own validation snapshot so a corrected blocked draft can pass without rewriting history.
  Verification rejects a snapshot at or before the publication claim and reports associations as
  `descriptive_only`. Corrections supply effective allowed values while original observed values
  remain untouched. Existing Site S5 evidence-only action resolution remains the sole resolver.
  Concurrent context/revision creates converge on their unique winner; inventory persistence is a
  single PostgreSQL upsert. Validation compares claims only with canonical allowed fact values,
  never metadata. Authenticated revision exports carry active-workspace context. `/content`
  defaults to Strategy, while custom generation remains the Drafts panel and deep-linked revisions
  select the requested revision without refetches discarding unsaved edits.
- Deliberate deferrals: raw-artifact/downstream composite workspace foreign keys require the owning
  raw-artifact `workspace_id` redesign. The fourteen non-Education/Commerce packs remain explicitly
  uncalibrated. There is no autonomous publishing, approved-memory store, or generated-fact path.

## Final branch verification record

For each branch, record exact results for formatting, Ruff, mypy, complexity ratchet, frontend
format/lint/type/policy/contract/build checks, documentation and industry-pack validation,
from-zero migration verification, Compose rebuild/smoke checks, and CI suites. Tighten the
complexity baseline only for genuine improvements; never use it to admit regression.

## Fresh-chat handoff template

```text
Continue CiteLadder Growth Intelligence delivery on <next branch>.

Start from freshly synchronized main. Read Agents.md, docs/plans/growth-intelligence-delivery-tracker.md,
and the canonical plan(s) linked for that branch. The previous branch merged in <PR> at <commit>.

Confirmed shipped state:
- <behavior and contracts>

Known gotchas/product decisions:
- <gotchas>

Start with:
- <first unfinished slice and acceptance gate>

Follow the tracker rules: focused verification while building; update canonical docs and the
tracker before shipping; use $ship-main for a non-draft PR, green CI, merge, and local-main sync.
Do not rely on context from the previous chat.
```
