# Growth Intelligence Delivery Tracker

> **Status:** active implementation handoff.
>
> **Authority:** tracks delivery only. Product and implementation decisions remain in the
> canonical [Demand](demand-intelligence.md), [Site](site-intelligence-primary-product.md), and
> [Content](content-intelligence.md) plans.

## Branch sequence

| Order | Branch | Scope | Status | Pull request | Merge commit |
|---|---|---|---|---|---|
| 1 | `feature/demand-intelligence` | Demand D0-D5 | `ready_to_ship` | pending | pending |
| 2 | `feature/site-intelligence-s5` | Corrections, contradiction decisions, Site S5 | `not_started` | — | — |
| 3 | `feature/content-intelligence` | Content C0-C5 | `not_started` | — | — |

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
  empty-workspace snapshot.
- Deliberate deferrals: paid media, CRM, email, and social remain future connectors per the
  canonical plan. Composite workspace foreign keys across the entire audit/analysis/raw-artifact
  graph remain with that owning persistence redesign: raw artifacts do not currently carry a
  workspace column, so constraining only downstream analysis rows would leave a partial,
  misleading boundary. Workspace authorization remains enforced on reads and writes. No D0-D5
  acceptance item is deferred.

## Branch 2 — Pending Site Intelligence

Canonical sources: [Site Intelligence](site-intelligence-primary-product.md) and the
[knowledge kernel](knowledge-kernel-and-industry-pack-spec.md).

- [ ] Durable corrections and append-only transitions.
- [ ] Inline contradiction decisions with all observed evidence preserved.
- [ ] Correction precedence across recomputation and withdrawal.
- [ ] Compatible snapshot comparison across facts, questions, rules, journeys, dimensions, scores,
  and coverage.
- [ ] Evidence-only `verified | partial | unresolved` action resolution.
- [ ] Education and Commerce calibration; every other pack remains explicitly unproven.

**Acceptance gate:** corrections survive recrawl, unresolved conflicts cannot become authoritative
output, and later evidence resolves actions without mutating earlier snapshots.

### Site implementation record

- Implemented behavior: pending.
- Public contract changes: pending.
- Schema changes: pending.
- Verification: pending.
- Gotchas and conflict resolutions: pending.
- Deliberate deferrals: pending.

## Branch 3 — Content Intelligence

Canonical source: [Content Intelligence](content-intelligence.md).

- [ ] **C0:** reconcile Content v1 ownership and lifecycle.
- [ ] **C1:** question gaps, semantic match candidates, immutable briefs, selective context.
- [ ] **C2:** provider-neutral generation, versioned skills, automatic validation.
- [ ] **C3:** revisions, revalidation, save/export, publication claims, recrawl verification.
- [ ] **C4:** inventory, strategy, Demand-aware priorities, Education then Commerce skills.
- [ ] **C5:** Strategy, Inventory, Briefs, Drafts, Revisions, and Verification experience.

**Acceptance gate:** Education and Commerce fixtures complete gap → brief → context → generation →
validation → edit → save → publication claim → recrawl verification without invented facts,
fact promotion, score mutation, or autonomous publishing.

### Content implementation record

- Implemented behavior: pending.
- Public contract changes: pending.
- Schema changes: pending.
- Verification: pending.
- Gotchas and conflict resolutions: pending.
- Deliberate deferrals: pending.

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
