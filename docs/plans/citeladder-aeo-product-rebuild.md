# CiteLadder AEO Product Rebuild

> **Status:** ready for implementation; product decisions are locked below and implementation
> has not started. This rebuild reorganizes CiteLadder around one coherent outcome, removes
> confusing half-built surfaces, ships high-confidence features grounded in a live-data spike,
> and closes schema/image debt at the end.
> **Brand:** CiteLadder. This is **not** a rebrand — "AEO loop" is internal vocabulary only.
> **Companion authorities:** [`architecture.md`](../architecture.md),
> [`invariants.md`](../invariants.md), [`design.md`](../design.md),
> [`site-health.md`](../site-health.md).
> *(The former `vision.md` is archived research input, not an authority, and is deliberately
> not linked here.)*

## Governing principle — atomic replacement, then deletion

**There is no obsolete product debt to preserve and no retired route to redirect.** Where this
plan replaces something, the cutover order is always:

```text
build replacement -> migrate every caller -> verify replacement -> delete old path -> grep proof
```

The old implementation is **deleted in that same slice**, not deprecated, aliased, redirected,
or kept behind a compatibility shim. No `0002+` migration, no legacy route, no dual namespace,
and no "keep the old deep link working." "Delete and rebuild" never means deleting a working
owner before its replacement and migrated callers exist; it means the slice is incomplete until
the superseded implementation is gone.

This no-redirect policy is an explicit **pre-launch internal-contract decision**. If repository
inspection discovers a real current external/public consumer, stop that slice and record the
evidence here; do not invent a compatibility bridge silently.

### Replacement inventory and deletion proof

Before changing a replacement slice, record every old route, symbol, model/table, schema, API
client, query key, worker/task kind, nav/deep link, test/fixture, config entry, and active-doc
reference. Classify each as **migrate**, **delete**, or **retain** with a reason and removal
condition. After cutover, run repository searches again plus `git diff --name-status` and add the
result to the slice's completion note. A broad name match is not itself debt: for example,
`site-health` backend APIs, domain modules, API clients, query keys, and reusable components stay
because Site Health remains the owning capability; only the retired frontend route namespace and
browser-path literals are replaced.

### Codex execution protocol — one fresh chat equals one PR

There are exactly **six delivery waves, six fresh Codex chats, and no more than six PRs** for this
rebuild. One chat owns one complete wave from synchronized `main` through implementation, review,
green CI, merge, and local-`main` synchronization via `$ship-main`.

Each wave contains several **internal implementation sub-slices**. They are sequential checkpoints
inside the same chat—not separate chats, branches, handoffs, or PRs. They keep the work auditable
and allow focused verification before the agent moves to the next capability, but the agent does
not yield to the user between them.

The repository, active owner documents, commits, this ledger, and the handoff block are the durable
context. Remembered conversation is never required. Do not ask for confirmation at intermediate
gates unless repository evidence reveals a real product decision, missing authority, unavailable
credential, unsafe destructive operation, or external blocker outside the approved wave.

#### Per-wave chat workflow

1. **Bootstrap from durable context.** Read `AGENTS.md`, `docs/invariants.md`, this protocol, the
   selected wave row, all of that wave's sub-slice rows and workstream sections, and only their
   named active owner docs. Inspect `git status --short`, branch/upstream, merge base, and the prior
   wave completion note.
2. **Audit prior review debt.** Inspect the preceding merged wave PR for unresolved or
   newly arrived CodeRabbit/agent comments. Address actionable feedback as the first bounded commit
   of the new wave and record it; do not spend a seventh standalone PR. Non-actionable or absent
   optional review is recorded. The final Z01 audit repeats this across all five prior wave PRs.
3. **Preflight the entire PR.** Search for every current owner and its tests, prepare replacement
   inventories, estimate cumulative unique changed paths, identify oversized modules that require
   seams, and rebalance whole trailing sub-slices before implementation if needed.
4. **Create the wave branch.** Use the exact branch named in the wave ledger, based on synchronized
   `main`. Never mix another workstream or user-owned change into it.
5. **Execute all internal sub-slices in order.** For each row, implement its behavior, contracts,
   focused tests, baseline-migration changes, superseded-code deletion, active-doc updates, and
   sanitized evidence. Run its focused gate and record its completion note before continuing to the
   next row. Intermediate cohesive commits are encouraged, but there is no intermediate PR or user
   handoff.
6. **Track cumulative PR size continuously.** Count unique paths against the `main` merge base after
   every sub-slice, including production, tests, docs, migration edits, generated artifacts, and
   deletions. Do not wait until the end to discover that CodeRabbit cannot review the PR.
7. **Close and ship in the same chat.** After all wave rows pass, perform the wave-close workflow
   below and invoke `$ship-main`. The chat ends only after merge and local synchronization, with one
   copy-paste handoff prompt for the next wave/PR.

#### Wave size and rebalance rule

Each wave targets **75 or fewer unique changed files**, freezes feature additions at **85**, and
must close at **95 or fewer** so CodeRabbit fixes have headroom below its 100-file limit. Never omit
tests/docs, combine unrelated modules, or avoid necessary deletions to manipulate the count.

Before the first code edit in a wave, perform a read-only owner/file inventory for all its planned
sub-slices. If the projected cumulative diff exceeds 85, move a whole trailing sub-slice to a later
wave and rebalance the remaining wave table while preserving dependencies. Do not create a seventh
wave. If the locked scope genuinely cannot fit into six PRs below 100 files each, stop and present
the measured file inventory to the user; silently dropping scope or bypassing CodeRabbit is not an
option.

#### Wave-close workflow

After the final internal sub-slice, the same chat closes the wave:

1. Re-run the wave's focused cross-slice checks and documentation validator; schema-changing waves
   also run the clean-empty-database migration gate.
2. Review the cumulative diff against the merge base, repeat replacement greps, confirm the unique
   file count is at most 95, and ensure every sub-slice completion note is present.
3. Update the wave ledger to `ready_for_merge` and replace the handoff block with a prompt for the
   complete next wave.
4. Invoke `$ship-main`: push remaining commits, open one non-draft PR for the whole wave, wait for
   required CI and CodeRabbit/agent reviews, address actionable findings on the same branch, and
   merge only when green and mergeable. Then synchronize local `main`.
5. Report the PR URL, merge commit, final file count, CI/review disposition, and repeat the next
   handoff prompt verbatim. The next wave's first commit reconciles the preceding wave row with
   GitHub readback; do not trigger an extra full-CI run solely to write the just-created PR URL into
   the plan.

#### Focused local verification matrix

Choose the narrowest applicable row(s), replace placeholders with the actual changed owners, and
record the exact commands. GitHub CI runs the repository-wide suite after the PR is opened.

| Sub-slice shape | Required local proof before advancing inside the chat |
|---|---|
| Documentation only | `python docs/validate_documentation.py` |
| Pure backend analysis/config | Focused unit modules + `uv run ruff check <changed paths>` + targeted `uv run mypy <changed package>` + complexity check when executable logic changes |
| Backend persistence/API/worker | Focused unit/component/API modules + Ruff/mypy on changed owners + `uv run alembic upgrade head` and `uv run alembic check` against an empty disposable DB when schema changes |
| Frontend behavior/route replacement | Focused Vitest/Testing Library files + `pnpm lint` + `pnpm check:contract` + `pnpm check:policy` + `pnpm exec tsc --noEmit` + `pnpm build`; add focused Playwright only for a changed critical flow |
| Mixed backend/frontend | The applicable focused backend and frontend rows; still no broad local pytest/Vitest suite |
| Live-data/performance gate | Deterministic fixtures first, then the workstream's bounded live run; store sanitized measurements under `docs/evaluations/` |

All slices also run `git diff --check`; replacement slices additionally run the exact pre/post
repository searches named in their workstream. A local build or migration check may be omitted
only when demonstrably unrelated, and the completion note must say why.

#### Documentation and evidence contract

Before advancing past an internal implementation sub-slice, the implementer must:

1. update the named active owner documents in that slice's **Documentation update** block;
2. update this plan's ledger and add a completion note under **Sub-slice completion notes**;
3. update [`documentation-index.md`](../documentation-index.md) whenever an active document is
   added, renamed, archived, or changes role, and archive superseded guidance in the same slice;
4. store live-data measurements as dated, sanitized artifacts under `docs/evaluations/`;
5. run `python docs/validate_documentation.py` after all documentation edits.

Do not mark a slice complete while its owner documentation still describes the pre-slice runtime.
Do not leave `TODO`, "decide later," "recommended option," or an unresolved product choice in a
completed slice. New evidence may invalidate an assumption, but the implementer must then amend
this plan with the evidence and a concrete replacement decision before continuing.

### Six-PR delivery-wave ledger

| PR | Branch | Status | Sub-slices in order | Cumulative delivery outcome |
|---|---|---|---|---|
| W1 | `feat/aeo-wave-1-foundations` | ready_for_merge | R00 → X01 → D01 → D02 → A01 → A02 | Authorities, cross-source identity, window/honest-state primitives, branded classification, and the complete Act→Verify record. |
| W2 | `feat/aeo-wave-2-site-health` | pending | S01 → S02 → S03 → S04 → S05 → S06 | Crawl correctness/speed/progress, terminal refresh, historical issue copy, and trustworthy defect/advisory semantics. |
| W3 | `feat/aeo-wave-3-product-loop` | pending | I01 → I02 → I03 → P01 → O01 → O02 → O03 | Final route/navigation replacement, confirmed-ICP onboarding, useful no-audit Overview, Facts cutover, and Visibility cleanup. |
| W4 | `feat/aeo-wave-4-demand-content` | pending | G01 → Q01 → Q02 → Q03 | Grounded generation plus bounded query evidence and all approved GSC detectors. |
| W5 | `feat/aeo-wave-5-site-intelligence` | pending | L01 → L02 → E01 | Internal-link graph, link Opportunities/UI, and evidence-linked AEO Readiness. |
| W6 | `feat/aeo-wave-6-change-final` | pending | C01 → C02 → Z01 | Comparable crawl changes, Opportunities/UI, schema/image/route debt closure, clean-stack proof, and final review audit. |

`pending` means no sub-slice has started. `in_progress` means its one owning chat is implementing
the wave. `ready_for_merge` means all internal gates passed and `$ship-main` is closing the PR.
`completed` requires the wave PR merged and local `main` synchronized. Only one wave and one
sub-slice may be `in_progress` at a time.

### Implementation sub-slice ledger

Rows execute in the wave order above within their one owning chat. Completing a row means its
focused gate passed and its completion note was recorded; it does **not** create a new chat or PR.

| Slice | Wave | Status | Depends on | Implementable outcome |
|---|---|---|---|---|
| R00 | W1 | completed | — | WS0A authority realignment; validator green. |
| X01 | W1 | completed | R00 | X1 evidence-aware page equivalence, fixtures, owner docs. |
| D01 | W1 | completed | R00 | X2 exact-window/latest snapshot resolution plus X4 honest-state wire semantics and fixtures. |
| D02 | W1 | completed | D01 | X3 branded-query classifier, append-only overrides, ambiguity handling, versioning, and fixtures. |
| A01 | W1 | completed | X01 | WS0B implementation declaration: append-only model, create/list/detail API, idempotency/authorization, and explicit Opportunities UI action. |
| A02 | W1 | completed | A01 | WS0B verification observations: terminal triggers, bounded verifier task, persisted state projection, provenance and lifecycle tests. |
| S01 | W2 | pending | W1 | SH-1 link-extraction delimiter fix, rewrite provenance, negative fixtures, live proof. |
| S02 | W2 | pending | S01 | SH-2 extract-once acquisition, artifact reuse/fallback, host-rung observations, performance proof. |
| S03 | W2 | pending | S02 | SH-3 persisted blocked/failure progress contract and truthful crawl progress UI. |
| S04 | W2 | pending | S03 | SH-4 exactly-once post-terminal Demand/Opportunity refresh for usable partial/cancelled evidence. |
| S05 | W2 | pending | S04 | SH-5 frozen issue description schema/API and issue-row UI. |
| S06 | W2 | pending | S05 | SH-6 defect/advisory semantics, intentional-indexing policy, headline counts, and views. |
| I01 | W3 | pending | W2 | WS7 phase A: build `/site/crawls/...`, migrate callers, delete the `/site-health/**` browser route family, prove retained backend owner. |
| I02 | W3 | pending | I01 | WS7 phase A: top-bar Agent sheet, typed context, delete `/agent` route/nav/title/tests. |
| I03 | W3 | pending | I02 | WS7 phase A: five-station desktop/mobile navigation, conditional Commerce, settings-owned Providers, prompt route cleanup, and deletion of `/providers` + `/prompt-research`. |
| P01 | W3 | pending | I03 | WS2 structured field provenance plus confirmed-ICP-before-prompt-generation lifecycle and UI, with all producers/consumers migrated atomically. |
| O01 | W3 | pending | A02, P01 | WS1 no-audit command-center projection, evidence-state loop strip, next-action precedence, and capability projection. |
| O02 | W3 | pending | O01 | WS1 Facts drawer and competitor suggestions on Overview; migrate callers and delete `/knowledge-base` plus caller-free UI. |
| O03 | W3 | pending | O02 | WS1 Track summary; move retained Visibility capabilities to Trends, delete the Visibility `overview` surface, and finish WS7 phase B navigation cleanup. |
| G01 | W4 | pending | P01, O03 | WS7A frozen grounding envelope, adapter cutover, provider validation, truthful fallback/copy, and deletion of the superseded direct adapter path. |
| Q01 | W4 | pending | X01, D02 | WS3A bounded query↔page↔time projection, lifecycle, API, schema, provenance, and pagination. |
| Q02 | W4 | pending | Q01 | WS3B Wave 1 branded separation + striking-distance signals and Opportunity mapping. |
| Q03 | W4 | pending | Q02 | WS3B Wave 2 cannibalization, property-relative CTR gap, trend detectors, abstention states, and no mismatch placeholder. |
| L01 | W5 | pending | Q03, S06 | WS4 pure link-graph analysis plus immutable snapshot lifecycle/API/schema and post-crawl DAG. |
| L02 | W5 | pending | L01 | WS4 link opportunities and bounded Website Link Graph surface with table fallback. |
| E01 | W5 | pending | L02, S06 | WS5 config-owned AEO Readiness projection/API and evidence-linked Website surface; no score. |
| C01 | W6 | pending | A02, X01, L01 | WS6 deterministic comparable-crawl analyzer plus immutable snapshot lifecycle/API/schema and expected-event linkage. |
| C02 | W6 | pending | C01 | WS6 change-derived Opportunities and Website Changes surface with honest unavailable/non-comparable states. |
| Z01 | W6 | pending | all prior slices | WS8 clean-database/image/route/doc audit, clean-stack end-to-end proof, and plan completion. |

This cut line deliberately permits temporary, explicit coexistence only where a replacement spans
adjacent rows: A01 declarations remain `declared` until A02; the hidden Facts route remains until
O02; the Visibility overview remains until O03; backend graph/change projections exist one row
before their UI. Each predecessor must be fully tested and truthful on its own, and the named next
row is the removal condition. No other compatibility path is implied.

### Sub-slice completion notes

#### R00 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: product architecture, design, runtime authorities, README, and marketing positioning.
- Implemented: measurable observed-citation-share promise, five loop stations, locked route contract, Agent-sheet interaction contract, and active-plan registration.
- Deleted / retained until: archived `docs/vision.md` as research input; shipped routes remain until their atomic W3 cutovers.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 18
- Local verification: `python docs/validate_documentation.py` (valid: 28 active, 54 archived); `git diff --check` passed.
- Evaluation artifact: not applicable
- Advanced to internal slice: X01

#### X01 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: Demand cross-source page equivalence; Site Health evidence remains unchanged.
- Implemented: exact/resolved/ambiguous/unresolved outcomes, redirect/canonical proof, bounded ranked candidates, resolver version, and workspace/project isolation.
- Deleted / retained until: no crawler identity path replaced; `canonicalize`, `canonical_identity`, and `url_hash` intentionally retained unchanged.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 23
- Local verification: focused pytest 3 passed; Ruff, targeted mypy, and complexity policy passed.
- Evaluation artifact: not applicable (deterministic fixtures cover positive and encoded-path boundary cases)
- Advanced to internal slice: D01

#### D01 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: Traffic `load_snapshot` and dashboard wire projection.
- Implemented: exact-window versus explicit-latest fixtures and `not_run`/`observed_zero`/`available` response state.
- Deleted / retained until: existing resolver retained as the sole owner; no alternate latest selector added.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 28
- Local verification: backend focused pytest 10 passed; Ruff and targeted mypy passed; frontend focused Vitest 45 passed.
- Evaluation artifact: not applicable
- Advanced to internal slice: D02

#### D02 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: Demand query classification and the singular baseline migration.
- Implemented: canonical-name/alias/domain vocabulary, branded/non-branded/ambiguous outcomes, versioning, exact-query append-only override writes, latest-override precedence, and workspace isolation.
- Deleted / retained until: no legacy classifier existed; downstream detector consumption remains gated to Q02.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 33
- Local verification: focused pytest 5 passed; Ruff, targeted mypy, and complexity policy passed; clean disposable DB `alembic upgrade head` and `alembic check` passed.
- Evaluation artifact: not applicable
- Advanced to internal slice: A01

#### A01 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: Opportunities declaration persistence/API and the Opportunity detail action.
- Implemented: immutable snapshot-bound declarations, X1-authorized targets, discriminated expected checks, optional generation provenance, idempotent create/list/detail routes, coded conflicts, and **I implemented this**.
- Deleted / retained until: workflow status events remain separate; declarations intentionally projected `declared` until A02 observations.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 55
- Local verification: focused backend component pytest 2 passed; frontend Opportunities API/UI Vitest passed; Ruff and targeted mypy passed; clean disposable baseline migration gate passed at wave close.
- Evaluation artifact: not applicable
- Advanced to internal slice: A02

#### A02 — completed 2026-08-15
- Wave / branch: W1 / `feat/aeo-wave-1-foundations`
- Owners: Opportunities verification observations and the existing analytics queue.
- Implemented: immutable observation rows, crawl/audit terminal enqueue hooks, bounded versioned verifier, exact evidence provenance, honest limitations, persisted latest-event projection, and declared/observed/verified/contradicted UI states.
- Deleted / retained until: declaration rows remain immutable; unsupported traffic/direction-only checks remain observed or declared until a compatible post-boundary source exists.
- Commit: wave commit
- Cumulative changed files vs wave merge base: 66
- Local verification: focused backend pytest 64 passed across W1 owners plus 5 terminal-hook cases and final 6 declaration/hook regressions; Ruff, targeted mypy, and complexity policy passed; frontend Vitest 26 passed, lint/policy/build passed; empty disposable DB `alembic upgrade head` and `alembic check` passed; documentation validator and `git diff --check` passed.
- Evaluation artifact: not applicable (deterministic lifecycle fixtures cover every projection state)
- Advanced to internal slice: wave close

Add one heading per completed row. Use this exact compact schema so a fresh session can audit it:

```text
#### <slice> — completed YYYY-MM-DD
- Wave / branch:
- Owners:
- Implemented:
- Deleted / retained until:
- Commit: <SHA when committed separately, otherwise wave commit>
- Cumulative changed files vs wave merge base: <count>
- Local verification: <exact commands and results>
- Evaluation artifact: <path or not applicable>
- Advanced to internal slice: <next slice or wave close>
```

### Wave completion notes

Add one note per merged wave with branch, sub-slices, final unique-file count, PR URL, required CI,
CodeRabbit/agent disposition, merge commit, retained review debt, and local-main synchronization.
The next wave chat reconciles this note from GitHub readback.

### Current next-session handoff — W2

Copy and paste this entire prompt into a fresh Codex chat:

```text
Continue the CiteLadder AEO rebuild by implementing the complete W2 Site Health delivery wave from
docs/plans/citeladder-aeo-product-rebuild.md in one fresh chat. One chat equals one PR. Use the
citeladder-engineering skill throughout and finish with $ship-main. Implement all W2 internal
sub-slices in order: S01 → S02 → S03 → S04 → S05 → S06. Do not start W3.

Bootstrap only from synchronized `main`. Read AGENTS.md, docs/invariants.md, the plan's Codex
execution protocol, both ledgers, the merged W1 completion note, the W2 row, SH-1 through SH-6, the
SH gates, and the named Site Health/design/frontend/backend authorities. Reconcile W1's
`ready_for_merge` ledger row and completion note from GitHub readback before editing. Inspect git
status/branch/upstream and preserve unrelated work.

Before editing, inventory projected W2 files. Target at most 75 unique files, freeze additions at
85, and close at no more than 95. Rebalance only whole trailing sub-slices among the existing six
waves if required; never drop a gate or create a seventh PR. Create
`feat/aeo-wave-2-site-health` from synchronized main.

Execute S01–S06 sequentially with their validation spikes, deterministic positive/boundary
fixtures, and focused gates. Preserve crawler identity and security invariants. Prove the encoded
query delimiter fix without damaging legitimate encoded path content; extract once and reuse the
immutable artifact across analysis; persist honest blocked/failure progress; make post-terminal
Demand/Opportunity refresh exactly once for usable completed, partial, and cancelled evidence;
freeze issue descriptions; and separate defects from advisories with intentional-indexing
precedence and explicit headline-count semantics.

Run the required sanitized live recrawls for cube27, flipkart, and best&less and store the dated
evaluation artifact with before/after wall time, HTTP attempts, issue types by finding class,
occurrences, affected URLs, opportunity counts, blocked coverage, and cancellation coverage. Do
not run the repository-wide test suite locally. After S06, run the wave-close checks, update W2 to
ready-for-merge, record every completion note and cumulative file count, replace this handoff with
a concrete W3 prompt, and invoke $ship-main. Continue autonomously through one non-draft PR,
CodeRabbit/agent review, green required CI, merge, and local-main synchronization. In the final
response report the PR, merge commit, checks, review disposition, final file count, evaluation
artifact, and repeat the W3 handoff prompt verbatim.
```

---

## Context — the problem we are actually solving

Today the app "feels like random features." The sidebar groups every destination by
**internal system** (Site Health / Content Intelligence / Demand Intelligence), several surfaces
are empty until an unrelated action runs, two routes render the same screen, and one route is
a retired stub. A user cannot answer "what is this product *for*?"

**The one outcome:** make a brand **more likely to be recommended and cited by AI answer
engines** (ChatGPT, Perplexity, Gemini, Google AI Overviews). That depends on the same
substrate as SEO — a crawlable, well-structured, evidence-dense, authoritative site matched to
real search demand — **plus** answer-engine readiness (AEO) and measured citation share.
**SEO/AEO is the substrate; AI recommendation is the outcome we measure.**

### The measurable promise

"More likely to be recommended" is not directly measurable, and the product must not imply
causality it cannot prove. The **primary measured outcome** is:

> **Increase observed mention/citation share across a versioned prompt portfolio under
> comparable audit conditions.**

Crawl health, GSC demand coverage, and AEO readiness are **leading indicators**, not proof.
Every before/after surface says **observed**, never "CiteLadder caused." Comparability
(same portfolio version, same engines, same conditions) is part of the claim — an audit run
against a changed portfolio is not a comparison.

**The product is one loop:**

```text
Connect ──▶ Analyze ──▶ Act ──▶ Improve / Verify ──▶ Track ──▶ (recompute Analyze)
 evidence   find gaps   fix or    ship + recrawl,      are we cited more
                        generate  confirm the change   by AI engines?
```

**Vocabulary is normalized to these five words everywhere** (docs, IA, code comments).
`Improve / Verify` is a **transition**, not a sidebar destination: it is the recrawl-and-confirm
step between acting and tracking, surfaced inside Website (change feed) and Track (before/after).

> **Contract SELECTED: option (ii) — an explicit action record.** Without it the loop cannot
> honestly connect **Act → Verify**: Content Intelligence owns *generation results only* (no
> save, publication, implementation, or verification state), and WS6's `expected` change class
> would have no source. It is implemented in **WS0B** below, before Overview and Change
> Intelligence. Until WS0B lands, no surface uses "Acted" or "Verified" language.

This plan (1) **realigns the authority docs**, (2) **reframes the IA** around the loop,
(3) **removes dead/confusing code**, (4) ships **Overview redesign, editable ICP onboarding,
GSC Query Intelligence, Internal-Link Authority Graph, AEO Readiness, Change Intelligence**,
and (5) **closes schema and image debt** so nothing is left half-migrated.

### Grounding — backed by a live read-only spike, then verified against code

A spike against the running stack (real connected project **cube27.com**, Postgres
`127.0.0.1:55432`) established what is real. **cube27 is one small example, not the ceiling** —
features are designed against **what GSC/GA4 and the crawler expose in general** and must
**degrade honestly** on thin data.

| Capability | Ground truth (live DB) | Implication |
|---|---|---|
| GSC ingestion | 4,826 `integration_metric_rows`; `gsc_query_page_daily` = 1,296 rows, 26 days, real `position/ctr/clicks/impressions` | Query intelligence stands on fields every property exposes |
| GA4 ingestion | 17 days: channel / source-medium / landing / referrer / ecommerce | Attribution + AI-referral joins are real |
| Traffic projections | `traffic_query_stats` (126), `traffic_page_stats` (78) | Aggregates **by query** and **by page** *separately* — see WS3A |
| Crawler graph | `site_link_references` = 403 (250 internal **anchor** edges); `site_page_analyses` = 22 with real per-kind AEO/technical scores | Link graph + AEO readiness stand on existing evidence |
| Brand profile ("ICP") | `brand_profiles.target_audience` populated; `products_services` JSON array | ICP is real and already reaches *runtime* prompt generation |
| Recommendation spine | `opportunities` = 254 (198 `site` + 56 `traffic`), all `open`; `demand_signals` = 56 (all `high_impression_low_ctr`) | New detectors **emit into this one store** (invariant 1) |
| **The core UX bug** | **Zero `audits` / `response_analyses` / `citations` rows** despite all the above → Overview is empty | Overview must show state from crawl + demand + facts **before** any audit |

**Corrections to the first draft of this plan, verified in code:**

1. **The three `traffic_snapshots` are NOT duplication.** `TrafficSnapshot` is unique per
   `(project_id, window_start, window_end, granularity)`
   ([`models/traffic.py:64-89`](../../backend/app/models/traffic.py)); the refresh loops over
   `TRAFFIC_SNAPSHOT_GRANULARITIES`, so three rows = day/week/month for one window. A "latest
   snapshot selector" would be wrong → use **window-aware resolution** (below).
2. **`canonicalize()` does not collapse `http→https`, `www→non-www`, or trailing slash**
   ([`connectors/web_evidence/url_policy.py:340`](../../backend/app/connectors/web_evidence/url_policy.py)):
   it lowercases scheme, IDNA-normalizes host, strips default port + fragment, and normalizes
   path/query. `canonical_identity()` hashes exactly that
   ([`domain/site_health/normalization.py:27`](../../backend/app/domain/site_health/normalization.py)).
   **Do not change these semantics** → introduce a *separate* cross-source equivalence key.
3. **Branded queries dominate small corpora** (cube27's top queries are all brand variants) →
   query intelligence must separate branded vs non-branded.
4. **No paid SERP/keyword-volume data exists or is wanted** (confirmed: no DataForSEO). Never
   design a feature needing global search volume; keep it `unavailable`.

---

## Workstream 0A — Authority realignment (do first, blocks the IA work)

The new organizing outcome **conflicts with documents this plan calls authorities**:
`architecture.md` states AI Visibility "is no longer the organizing principle," and `design.md`
mandates sidebar grouping by Site/Content/Demand. That is a fine product decision but cannot
coexist as simultaneous implementation authority.

**Status:** this plan is now registered in `documentation-index.md` and the validator's
`ACTIVE_EXACT` allowlist, and `vision.md` has been archived to `docs/archive/vision.md`. The
remaining realignment below is still required.

Update **together, in one slice** — a partial pass leaves contradictory authorities:

- [`AGENTS.md`](../../AGENTS.md) (encodes the old hierarchy and the task-document map),
  [`documentation-index.md`](../documentation-index.md) (**register this plan**),
  [`architecture.md`](../architecture.md) (AI recommendation is the measured outcome; the four
  systems become *capabilities* behind loop stations),
  [`design.md`](../design.md) (sidebar grouping → loop stations; keep the insight object and
  all token/geometry rules), [`backend-architecture.md`](../backend-architecture.md),
  [`frontend-architecture.md`](../frontend-architecture.md),
  [`site-health.md`](../site-health.md), the subsystem plans under `docs/plans/`, `README.md`,
  and marketing positioning copy.
- **`vision.md` is research input, not an authority** — already archived. Never cite it as an
  implementation contract.
- Re-check [`invariants.md`](../invariants.md): **no invariant is repealed.** Invariant 12's
  "empty fact envelope" clause changes only when the grounding contract lands (WS7A).

**Authority order stays: `architecture.md` remains the highest product authority.** This plan
is the *delivery* authority for the rebuild and is subordinate to it — once 0A merges, the two
agree, and where they ever diverge, `architecture.md` wins.

**Documentation update:** this workstream is the documentation realignment. In addition to the
files above, add the locked route contract below to `frontend-architecture.md`, add the loop and
measurable-promise wording to `architecture.md`, replace the old navigation hierarchy in
`design.md`, and make each subsystem plan point back to this program for sequencing. Record the
completed authority inventory and validator result in the R00 completion note.

**Gate:** `python docs/validate_documentation.py` exits clean.

---

## Workstream 0B — The action record (makes Act → Verify real)

Prerequisite for WS1's "Acted" state, WS6's `expected` class, and any before/after claim.

**Owner: Opportunities** (invariant 1 — no parallel opportunity store). Add an
**`OpportunityImplementationEvent` table inside the existing Opportunities owner**, distinct
from the existing `OpportunityStatusEvent`, which is verified to be an
*"append-only audit trail for human opportunity workflow changes"* — i.e. status transitions
only. A status change to `resolved` is a workflow assertion; it is **not** evidence that the
site changed.

The persistence decision is final: the declaration row is immutable, and later observations are
separate immutable `OpportunityVerificationEvent` rows that reference it. The read API derives
the current state from the newest valid verification event; it never mutates a `state` column on
the declaration. This preserves append-only evidence while still exposing a persisted projection.

Release slice **A01** records each implementation declaration and exposes the explicit user action:

| Field | Purpose |
|---|---|
| `opportunity_id` | what this action addresses |
| `opportunity_snapshot_id` | the current immutable recommendation-cycle snapshot selected and authorized at declaration time |
| `target_site_url_ids[]` | workspace-authorized X1 `exact`/`resolved` identities; ambiguous or unresolved targets reject the declaration with a coded 409 |
| `generation_id` (optional) | the draft used, if any |
| `declared_implemented_at` | user-declared change time — the before/after boundary |
| `expected_checks[]` | discriminated checks: `site_rule`, `page_fact`, `visibility_metric`, or `traffic_metric`, each with target identity, expected direction/value, and comparison tolerance; feeds WS6 `expected` |
| `actor_user_id`, `workspace_id` | identity + isolation (invariant 3) |
| `idempotency_key` | prevents duplicate declarations for one explicit user action |

Release slice **A02** records each verification observation and activates terminal verification:

| Field | Purpose |
|---|---|
| `implementation_event_id` | immutable declaration being checked |
| `observation_kind` | `observed` · `verified` · `contradicted` |
| `observed_at` | evidence time, not processing time |
| `crawl_id` / `audit_id` / source IDs | exact evidence used; nullable only when not applicable to that observation kind |
| `verifier_version`, `limitations` | replayability and honest coverage |
| `workspace_id`, `idempotency_key` | isolation and retry safety |

Rules: workspace-scoped and idempotent; append-only (invariant 4); a generation alone **never**
creates one — the user explicitly declares the change; verification is an **observation**, never
a causal claim. Relationship to `OpportunityStatusEvent` must be documented: status events track
workflow, action events track site reality; neither derives the other.

`observed` means post-boundary evidence exists for at least one expected check but the full set is
not yet decidable; `verified` means every applicable expected check matches within tolerance;
`contradicted` means at least one applicable check deterministically moved opposite to the declared
expectation. Missing/not-applicable checks keep the state `observed` with limitations rather than
being coerced to success or contradiction.

**Lifecycle/API contract:** the user declaration is a normal authenticated write, not a queued
task. Crawl/audit terminalization enqueues the owning bounded verification task using the existing
PostgreSQL queue semantics. Add these routes under the existing owner:

- `POST|GET /api/v1/projects/{project_id}/opportunities/implementation-events`
- `GET /api/v1/projects/{project_id}/opportunities/implementation-events/{event_id}`

Verification observations are system-written and included in detail/list projections, not a
public mutation endpoint. Use coded 404/409 errors, default page size 50/hard maximum 200,
workspace-isolation tests, idempotency tests, and provenance tests. A01 folds the declaration
table/indexes into `0001_initial.py`; A02 folds the observation table/indexes into the same
baseline. Each internal sub-slice runs the empty-database gate, so the W1 branch remains migratable
after either gate and no unused verification table exists ahead of its owner.

**Documentation update:** A01 updates `backend-architecture.md` and `frontend-architecture.md`
with declaration persistence/API/UI. A02 adds the observation type, queue trigger, projection
rule, and verification UI states. Update `invariants.md` only to replace any now-stale wording,
not to weaken append-only rules; record schema, API, deletion/retention, and verification proof in
the matching A01/A02 completion notes.

**Gates:** A01 proves a duplicate declaration is idempotent, cross-workspace target IDs are
rejected, and the user action can produce an honest `declared` state. A02 proves a later crawl
appends verification evidence without mutating the declaration and the read projection returns
`declared`, `observed`, `verified`, or `contradicted` from persisted events only.

---

## Target information architecture

Collapse the system-grouped sidebar (currently 14 item literals in `nav-items.ts`) into
**5 loop stations.** The Growth Agent moves to the
top bar (per `design.md` screen geometry) rather than competing as a data destination.

| Stage | Sidebar group | Destinations | Made of today's |
|---|---|---|---|
| — | **Overview** | Loop status + company facts + one next action | `/projects` **+ folded** `/knowledge-base` |
| **Analyze** | Website | Pages · **AEO Readiness** (new) · **Link Graph** (new) · **Changes** (new) · Issues | `/site`, `/issues` (deletes `/site-health` duplicate) |
| | Demand | **Search Demand** (expanded) · Traffic | `/demand`, `/traffic` |
| **Act** | Opportunities | The one prioritized worklist | `/opportunities` |
| | Content | Grounded generation against an opportunity | `/content` |
| **Track** | AI Visibility | Citation share vs competitors · Runs · AI Referrals | `/visibility`, `/runs`, `/ai-referrals` |
| **Connect** | Setup | Integrations · Providers (BYOK) · Prompts · Settings | `/settings?tab=integrations`, `/settings?tab=providers`, `/prompts`, `/settings` |

**Commerce (`/products`):** appears as a **conditional destination inside Analyze**, rendered
only when commerce evidence exists for the project (`products` / `order_facts` non-empty).
It is otherwise hidden — not deleted, not a permanent nav item.

Rule: **one insight object** (`design.md`) is reused across every station; a station never
invents its own finding card. Date range + Agent stay in the top bar.

### Locked route contract

The table above lists five *stations* but more than five destinations; stations are navigation
groups, not routes. This contract is decided and must be copied into `frontend-architecture.md`
in WS0A.

| Desktop group | Label | Canonical browser location |
|---|---|---|
| — | Overview | `/projects` |
| Analyze | Website | `/site?tab=pages` (default), `?tab=aeo-readiness`, `?tab=link-graph`, `?tab=changes` |
| Analyze | Issues | `/issues` |
| Analyze | Search Demand | `/demand` |
| Analyze | Traffic | `/traffic` |
| Analyze | Commerce | `/products` when the capability rule below is true |
| Act | Opportunities | `/opportunities` |
| Act | Content | `/content` |
| Track | AI Visibility | `/visibility?tab=trends` (default), `?tab=mentions-citations`, `?tab=query-fanout` |
| Track | Runs | `/runs` and `/runs/[runId]` |
| Track | AI Referrals | `/ai-referrals` |
| Connect | Integrations | `/settings?tab=integrations` |
| Connect | Providers | `/settings?tab=providers` |
| Connect | Prompts | `/prompts` |
| Connect | Settings | `/settings` (Account default; Billing and Danger zone remain tabs) |

The five-slot mobile bar is exactly **Overview** (`/projects`), **Analyze** (`/site?tab=pages`),
**Act** (`/opportunities`), **Track** (`/visibility?tab=trends`), and **Connect**
(`/settings?tab=integrations`). All other destinations remain reachable from the corresponding
station's mobile menu/tab row; they are not duplicated into a second mobile navigation owner.

The mobile secondary navigation is also fixed: Analyze exposes Website tabs plus an overflow list
for Issues, Search Demand, Traffic, and conditional Commerce; Act switches between Opportunities
and Content; Track exposes the three Visibility tabs plus Runs and AI Referrals; Connect exposes
Integrations, Providers, Prompts, and Settings. Use one shared accessible station-navigation
component for desktop subnavigation and mobile overflow, not route-local copies. Active selection
uses pathname plus recognized `tab`/`mode` values, so multiple `/settings?...` entries never all
appear active. Missing/invalid tab values normalize to each canonical default via URL state without
creating a route redirect or compatibility alias.

The entire `/site-health/...` frontend route family is deleted. The page-detail route is rebuilt
as `/site/crawls/[crawlId]/pages/[siteUrlId]`. `/site-health`, `/prompt-research`,
`/knowledge-base`, `/agent`, and `/providers` are retired internal routes and are deleted after
their replacements are live; there are no redirects or aliases. Update every browser-path caller,
including dynamic deep links, `nav-items.ts`, `page-titles.ts`, `robots.ts`, route-state tests,
component tests, E2E tests, comments, and active docs. Persisted historical evidence IDs remain;
if a persisted UI link string exists, migrate or rebuild that projection inside the same slice.

**Conditional Commerce decision:** expose one workspace-authorized `has_commerce_evidence`
capability in the existing project/command-center projection. It is true when the active project
has at least one persisted Product or OrderFact. The nav item is hidden when false; direct access
to `/products` remains authorized and renders an honest no-commerce-evidence state so hiding
navigation never becomes authorization or a 404.

**Top-bar Agent decision:** replace the `/agent` page with one button in the authenticated top bar
that opens an accessible right-side sheet containing the existing `GrowthAgentWorkspace`. Its
typed context is limited to active workspace ID, active project ID, canonical route, selected date
range, and route-owned filters; it never receives DOM text or unpersisted page data. Escape,
close-button, and focus-return behavior are required. Project switching clears route-specific
context. Once the sheet and tests are live, delete the page route, nav entry, page-title entry, and
route-specific tests.

**Documentation update:** R00 publishes this route contract in `frontend-architecture.md` and the
navigation/Agent interaction in `design.md`. I01–I03 and O02–O03 update those documents from
planned to shipped and record the complete migrated/deleted/retained inventories in their
completion notes.

---

## Cross-cutting engineering (build before WS3/4/6 consume it)

### X1 — Cross-source page equivalence (do NOT touch Site Health identity)

Two **different** concepts, kept separate:

```text
Site Health URL identity            Cross-source owned-page equivalence
  canonical_identity() / url_hash     resolve_owned_page()
  exact, crawler-safe                 maps GSC/GA4 URL variants
  /foo ≠ /foo/                          ↓
  http ≠ https, www ≠ non-www         preferred SiteUrl identity
```

- **Leave `canonicalize()`, `canonical_identity()`, and `url_hash` untouched.**
- Add a new module (e.g. `backend/app/domain/demand/page_equivalence.py`) exposing
  `resolve_owned_page(project, url) -> Resolution`.
- **Resolution must be evidence-based, not a blind string collapse.** Scheme, `www`, and
  trailing slash *can* denote different resources. Prefer, in order: observed **redirect
  chains**, **canonical declarations**, **sitemap membership**, and the project's **configured
  preferred origin**. Only then fall back to variant heuristics.
- **Outcome decision:** an exact SiteUrl normalized-URL match returns `exact`. Only an observed
  redirect or canonical declaration pointing to one workspace-owned SiteUrl may return `resolved`.
  Sitemap membership and preferred origin rank candidates but do not prove equivalence. Variant
  heuristics may discover candidates; one candidate without redirect/canonical proof is still
  `ambiguous`, and zero is `unresolved`. Do not turn heuristic uniqueness into truth.
- Return an explicit outcome — **`exact` · `resolved` · `ambiguous` · `unresolved`** — with
  candidate list and **resolver version** (invariants 5 + 7). Ambiguous never silently becomes
  resolved.
- **Every resolver query and persisted relationship carries `workspace_id`** (invariant 3);
  cross-source resolution never crosses a workspace boundary.
- Rationale from the spike: 1,296 raw GSC query-page pairs collapse toward ~68 identities;
  without evidence-aware resolution, detectors produce false positives *or* wrongly merge
  distinct pages.

**Documentation update:** document the resolver contract, evidence order, outcomes, versioning,
and workspace boundary in `integrations-traffic-analytics.md` and `backend-architecture.md`; add a
warning to `site-health.md` that this does not change crawler identity; record fixture coverage and
repository searches in the X01 completion note.

### X2 — Window-aware snapshot resolution

Replace the (incorrect) "latest snapshot" idea: resolve the **exact**
`(window_start, window_end, granularity)` when the surface requests dates; fall back to the
newest snapshot **only** when a surface explicitly asks for current/latest state. Reuse the
existing resolver `load_snapshot()` in
[`backend/app/domain/traffic/query_support.py`](../../backend/app/domain/traffic/query_support.py).

**Documentation update:** update the date-window/read-projection contract in
`integrations-traffic-analytics.md` and the owning resolver entry in `backend-architecture.md`;
record exact-window and explicit-latest tests in the D01 completion note.

### X3 — Branded-query classifier

Vocabulary = **`Brand.name` (canonical) + `brand_aliases` + normalized owned-domain spellings**
(the canonical name is *not* stored as an alias). Config-owned; used to filter navigational
queries out of "opportunity."

The classifier returns `branded`, `non_branded`, or `ambiguous`, with matched terms and classifier
version. A user override is append-only evidence and wins over automatic classification for that
exact normalized query; generic single-token names require an exact-token match plus owned-domain
or explicit-override support and otherwise return `ambiguous`.

**Documentation update:** document vocabulary ownership, override precedence, ambiguity, and
versioning in `demand-intelligence.md` and `backend-architecture.md`; record classifier fixtures in
the D02 completion note.

### X3b — Lifecycle contract required for every new projection

WS3A, WS4, and WS6 each introduce a persisted projection. None may ship without specifying, in
its slice: **task trigger · queue owner · lease / cancellation / idempotency behaviour · source
hash · rebuild & supersession policy · row bounds · API routes · pagination · coded errors ·
workspace-isolation tests.** This is what invariants 3, 6, and 15 already require of every
existing owner; a new projection without it becomes the next piece of debt.

**Documentation update:** each consuming workstream writes its concrete lifecycle into the named
owner document before implementation and changes it from planned to shipped only after the gate.
No lifecycle contract may exist solely in code comments or this plan.

### X4 — Honest-state discipline

Invariant 7 everywhere: `unknown ≠ unavailable ≠ not-applicable ≠ not-run ≠ observed-zero ≠
low-confidence`. Thin data yields fewer / lower-confidence signals — **never** fabricated ones
or borrowed volume estimates.

**Documentation update:** add any newly introduced wire-state vocabulary to the owning subsystem
document and `api-error-contract.md` when it affects errors; add honest-state fixtures and the
result to the D01/D02 completion notes that introduce the affected states.

---

## Workstream 1 — Overview redesign (facts-first + loop status + next action)

**Problem:** Overview is empty until an audit completes, despite crawl + GSC + demand + 254
opportunities already existing.

- **Backend:** extend `backend/app/domain/command_center/service.py` + `schemas.py` so
  `get_command_center()` **no longer raises `LookupError` when no audit exists**; it projects
  what is present with explicit per-region states.
  - **Company facts block — compose from the canonical owners** (`Project`, `Brand`,
    `BrandProfile`, `Competitor`), **not** from
    `knowledge_base.build_brand_knowledge_data()`, which today supplies only brand_name /
    website_url / country / language / description / positioning / products_services /
    target_audience — **it has no industry or competitors**, and widening it would silently
    inject those fields into every AI context.
  - **Loop status strip** — each derived from existing snapshots, no new store:
    - **Connected** — integration connections present?
    - **Analyzed** — latest crawl + Search Demand snapshot present?
    - **Acted** — derive from the WS0B action-record projection. A completed **content generation is
      NOT "acted"**: it proves a draft exists, not that the site changed.
    - **Tracked** — latest audit, or an explicit `not run yet`.

  **Model each capability as an evidence state, not a boolean.** Every entry carries
  `state · observed_at · freshness · coverage · limitation`. Specifically:
  - **Analyzed** must not require Search Demand when GSC is simply unavailable — crawl-only is
    a legitimate analyzed state with stated coverage.
  - **Acted** must not latch permanently true after one historical event. The current cycle is
    keyed by the latest persisted `OpportunitySnapshot`; only implementation declarations whose
    frozen `opportunity_snapshot_id` equals that snapshot count. A newer Opportunity snapshot
    starts a new cycle. Historical actions remain visible in history but do not keep the current
    strip active.
  - The next-action chain needs a terminal **"monitor — no required action"** state so a
    healthy project isn't handed a fabricated task.
  - **Next-action resolver (explicit fallback chain):**
    ```text
    first user-ordered active opportunity (OpportunityOrder exists — service.py:1233+)
          ↓ none
    highest deterministic-priority open opportunity
          ↓ none
    next required loop action (connect GSC/GA4 · run first crawl · configure prompts · run first audit)
    ```
    This guarantees Overview always returns an **actionable or explicit monitor state** — never
    a blank — and respects the existing **user-orderable queue** rather than overriding it with
    raw deterministic priority.
- **Frontend:** `frontend/components/projects/dashboard-screen.tsx` renders facts + loop strip
  + next action in the no-audit state instead of the "Launch your first audit" dead end. Reuse
  the insight object.
- **Fold Facts atomically (moved here from WS0):** move
  `frontend/components/knowledge-base/brand-profile-panel.tsx` editing into an Overview drawer
  **and** remove the `Facts` nav item **in the same slice**, so the replacement is live before
  the entry point disappears.
- **Preserve the useful part of the retired Visibility Overview:** the Overview Track region shows
  the latest comparable observed citation share, change, engine coverage, and limitation from the
  existing persisted visibility projections. It links to `/visibility?tab=trends`; it does not
  duplicate full rankings/tables or issue a provider call. Competitor suggestions move into the
  company-facts drawer because accepting one mutates the canonical Competitor owner.

**Documentation update:** update `backend-architecture.md` with the no-audit command-center
projection and next-action precedence; update `frontend-architecture.md` and `design.md` with the
Overview regions, Facts drawer, Track summary, and honest empty states; delete active-doc mentions
of `/knowledge-base`; record backend evidence in O01, Facts cutover/deletion in O02, and Track/
Visibility cutover/deletion in O03.

**Gate:** on the live project (crawl + demand, **no audit**), Overview shows real facts, loop
status, and a real next action. Nothing that exists reads `unavailable`; nothing merely
not-run reads `0`.

---

## Workstream 2 — ICP confirmation before prompt generation (onboarding restructure)

**Problem (verified):** prompts are generated during discovery
(`process_discovery` → `row.prompt_suggestions = result.prompts`,
[`onboarding/service.py:250`](../../backend/app/domain/projects/onboarding/service.py)) and
`complete_discovery` only **persists the reviewed groups** (`_reviewed_prompts`, line 320+) —
it never regenerates. So "edit the ICP at review" **cannot** change prompts today.

**Restructure the lifecycle so the confirmed ICP actually drives generation:**

```text
Website ──▶ Discover profile ──▶ User confirms/edits ICP + positioning + offerings
        ──▶ Generate prompt portfolio FROM the confirmed profile
        ──▶ Create project ──▶ Crawl / connect / measure
```

- Add an editable **ICP step** before prompt generation in
  `frontend/components/onboarding/onboarding-screen.tsx` / `review-step.tsx`
  (fields already exist on `DiscoveryProfile`: `target_audience`, `positioning`,
  `products_services` — no schema change).
- Backend: **do not generate prompts during discovery.** Generate the portfolio exactly once from
  the submitted confirmed profile, then persist it with project creation. Returning to the ICP
  step invalidates any client preview; submitting again performs a fresh idempotent server
  generation from the new confirmed payload. Pass `target_audience` as an explicit context term in
  `backend/app/domain/projects/onboarding/prompt_generation.py` (today it uses
  `buyer_persona` + `products_services` only). Runtime generation
  (`domain/prompts/generation.py`) already injects the ICP via `<brand_knowledge_base>` — keep it.
- **Fix provenance — one contract, defined here and used everywhere.** Project creation marks
  **every non-empty supplied field `manual`**
  ([`domain/projects/service.py:187`](../../backend/app/domain/projects/service.py)), so an
  untouched AI suggestion is recorded as user-authored.

  Today `sources` already carries **three origin tokens** — `manual`, `web_evidence`,
  `ai_suggested` ([`core/config/brand_profile.py:22`](../../backend/app/core/config/brand_profile.py)).
  Adding a combined `user_confirmed_ai_suggested` token would keep conflating two independent
  concepts. **Split them per field instead:**

  | Field | Values |
  |---|---|
  | `origin` | `manual` · `web_evidence` · `ai_suggested` |
  | `review_state` | `unreviewed` · `confirmed` · `edited` |
  | `reviewed_by`, `reviewed_at` | reviewer provenance |

  An AI suggestion the user confirms is `origin=ai_suggested, review_state=confirmed` — not
  "manual." This is the **final** contract; WS7A does not supersede it.

  **Storage decision:** replace each `BrandProfile.sources[field]` string token with one structured
  object `{origin, review_state, reviewed_by, reviewed_at}`. Update every producer/consumer,
  Pydantic/Zod contract, fixture, and context adapter in the same slice; do not keep dual parsing
  for the old string form. User-entered values are `origin=manual, review_state=confirmed` at
  creation. AI/web suggestions remain `unreviewed` until the explicit confirmation step; editing
  changes `review_state` to `edited` without rewriting `origin`.

**Documentation update:** update `content-intelligence.md` and `backend-architecture.md` with the
confirmed-profile-before-generation lifecycle and structured provenance shape; update
`frontend-architecture.md` with the onboarding steps and validation/error states; update
`invariants.md` only if its fact-envelope wording becomes stale after WS7A, not during WS2; record
contract/test proof in the P01 completion note.

**Gate:** two different confirmed ICPs on the same site produce measurably different prompt
portfolios; `sources` preserves origin separately from review state, reviewer, and review time.

---

## Workstream 3 — GSC Query Intelligence

### WS3A — Query Evidence Projection (prerequisite; do not skip)

**Problem (verified):** `TrafficQueryStat` aggregates **by query** and `TrafficPageStat`
**by page**, in separate tables — **the query↔page relationship is already discarded**, and
there is no time grain. Cannibalization, query→page mismatch, and trend detection **cannot** be
built on them. But `gsc_query_page_daily` (1,296 rows, dims `query|page|date`) already holds
exactly what is needed.

Persist a **bounded query↔page↔time projection** sourced from `gsc_query_page_daily`:
normalized query + **resolved page identity via `resolve_owned_page()` (X1)** + date/window +
metrics (impressions/clicks/ctr/position) + provenance (source metric-row IDs, analyzer/formula
version) + coverage/limitations. Owned by Demand Intelligence; **extends the existing owner**,
adds no parallel store (invariant 1). Bound rows per project/window (config-owned).

**Lifecycle decision:** build this projection inside the existing Demand refresh that follows a
terminal GSC sync, before DemandSignal computation. The existing Demand queue owns claim/lease,
cancellation, and retry behavior. Idempotency identity is
`workspace_id + project_id + window + source_hash + analyzer_version`; a retry selects the same
immutable snapshot, while a changed source/version appends a superseding snapshot. Persist a
bounded snapshot header plus rows, default API page size 100 and hard maximum 500, and expose
workspace-authorized reads at:

- `GET /api/v1/projects/{project_id}/demand/query-evidence`
- `GET /api/v1/projects/{project_id}/demand/query-evidence/summary`

Both require `window_start` and `window_end`; list additionally accepts bounded cursor/limit and
filters, while summary does not paginate. Reads never trigger rebuild. Fold schema into
`0001_initial.py`; test isolation,
supersession, pagination, coded errors, and source-row provenance.

### WS3B — Detectors over that projection

In `backend/app/domain/demand/projection.py`, thresholds in `core/config/demand.py`
(invariant 2), each emitting a `DemandSignal` with full provenance (invariant 5):

**Ship in two waves — the safest detectors first.** Do not build every detector at once; the
second wave uses the stricter data/coverage contracts fixed below and needs separate fixtures.

**Wave 1 (safe, ship first):**
- **Branded vs non-branded separation** (X3) — a prerequisite, not a nicety.
- **Striking distance** — non-branded resolved queries with impression-weighted average position
  4–15 and at least 50 impressions in the selected window. Branded rows are visible in their own
  cohort but do not emit this Opportunity. The spike's 4–10 band held 1,278 impressions at 60
  clicks. Ambiguous/unresolved pages or missing coverage abstain.

**Wave 2 (definitions locked here; ship after Wave 1):**
- **Cannibalization** — define precisely as: *one query maps to **multiple distinct resolved
  pages** after URL variants are collapsed by X1*, where at least two pages each have at least
  20 impressions and 10% of that query's impressions in the selected window. Ambiguous/unresolved
  X1 results abstain; branded queries are reported separately and do not create opportunities.
- **Query→page mismatch is explicitly out of scope for this rebuild.** There is no source for
  "intended page." Do not implement the detector, placeholder UI, schema token, or dormant flag.
  A future approved plan must introduce a user-declared target or deterministic intent/page-kind
  owner before this capability can exist.
- **CTR gap** — use only a **property-relative non-branded cohort** in the selected window. Group
  resolved query-page rows by whole-number position band; require at least 20 cohort rows and 500
  cohort impressions. Flag a candidate only at 100+ impressions when its CTR is both at least 25%
  below the cohort median and at least 2 percentage points lower. Missing cohort coverage returns
  `unavailable`; never borrow a universal curve or dimensions not ingested by CiteLadder.
- **Emerging / declining query** — compare two adjacent, non-overlapping 14-day windows. Require
  at least 28 days of coverage, 50 total impressions, and 10 impressions in each window. Emerging
  means recent impressions are at least 1.5× prior with an absolute increase of 20; declining
  means recent impressions are at most 0.67× prior with an absolute decrease of 20. Below those
  gates, abstain. The current ~26-day sample must therefore return insufficient-history, while
  deterministic fixtures prove both positive classes.

**Brand classification (X3) needs evidence and overrides**, not just string matching: support a
user override, and guard against generic brand names (an "Apple" or "Best" rule that swallows
every generic query is worse than no classifier).

Signals map to opportunities by extending `_demand_hits` in `domain/opportunities/service.py`
plus rules in `core/config/opportunities.py`.

**Documentation update:** WS3A updates `demand-intelligence.md`,
`integrations-traffic-analytics.md`, and `backend-architecture.md` with the projection schema,
lifecycle, API, bounds, provenance, and supersession contract. Each WS3B wave adds its exact
detector semantics, thresholds, honest states, and Opportunity mapping to
`demand-intelligence.md`; remove any active-doc promise of query→page mismatch. Record the live
evaluation artifact and test/grep proof in Q01, Q02, and Q03 respectively.

**Gate:** each detector fires or correctly abstains on live GSC rows; a thin-data property
yields fewer signals with honest states, never fabricated ones.

---

## Workstream 4 — Internal-Link Authority Graph

**Problem:** link **edges** exist (250 internal anchors) but there is no assembled graph,
authority scoring, or link recommendation.

- New pure analyzer `backend/app/analysis/site_health/link_graph.py` (no I/O — invariants 6/9),
  consuming `site_link_references` filtered to `kind='anchor'`, `is_internal=true`.
- **Scope every graph to one crawl + its current analyses.** `SiteLinkReference` rows are tied
  to `source_analysis_id` and persist historically, so an unscoped read mixes crawls and
  analyzer versions. Persist `crawl_id` + exact source-analysis IDs on the snapshot with
  `analyzer_version` (invariant 5).
- **V1 graph contract is fixed:** nodes are SiteUrls with the selected/current successful HTML
  analysis in the one source crawl. Resolve an internal anchor through its target artifact/final
  URL when available; a redirect source is evidence metadata, while the final in-scope SiteUrl is
  the authority node. URL fragments do not create nodes. External and non-HTML targets remain
  counted evidence but are not nodes. Collapse repeated anchors for an ordered source/target pair
  to one unit-weight topology edge while preserving occurrence count and bounded anchor texts as
  metadata. Exclude `rel=nofollow` and page-level robots-nofollow edges from PageRank, but retain
  them as observed links. Keep dangling nodes and redistribute their mass using the standard
  deterministic PageRank rule. Click depth is BFS from the configured crawl root; unreachable is
  `unknown`, not infinity. Partial crawls expose coverage and descriptive observed topology only;
  they do not emit orphan/weak-authority Opportunities.
- Compute: internal PageRank (deterministic, iterative), click depth, **near-orphans**,
  weak inbound authority, authority concentration, over-linked pages, anchor-text distribution,
  hub pages.
- **V1 metric thresholds are fixed and config-owned:** PageRank damping `0.85`, convergence
  tolerance `1e-8`, maximum `100` iterations; near-orphan = non-root indexable HTML node with
  0–1 followed inbound topology edges; weak inbound authority = bottom PageRank quartile with at
  least one edge and at least 20 graph nodes; over-linked = 100+ distinct followed internal
  targets; hub = top outbound-link decile, depth ≤2, with at least 10 distinct targets. Authority
  concentration is descriptive when the top 10% of nodes hold >50% of PageRank and does not alone
  create an Opportunity. Suggested sources are top-PageRank nodes not already linking to the target
  with normalized path/title token Jaccard ≥0.20; return at most three, stable-sorted by score then
  SiteUrl ID. Properties below data gates return unavailable/empty with limitations.
- **Reuse, don't duplicate, orphan detection:** `technical.sitemap_orphan` already exists in
  `analysis/site_health/finalize.py` — surface its result; the graph adds only the *new*
  concepts above (invariant 1).
- **Link opportunities** ("page X should receive links from A/B/C") emit into the existing
  opportunity store. v1 uses **anchor/path/title heuristics only — no embeddings** (see WS7A).
- Surface: **Link Graph** tab under Website.

**Lifecycle decision:** Site Health owns one immutable graph snapshot per
`workspace_id + crawl_id + source_analysis_hash + analyzer_version`. A bounded Site Health queue
task runs after terminal crawl analysis has usable coverage. Retry is idempotent; changed source or
analyzer version appends a superseding snapshot. Maximum nodes, edges, iterations, and suggested
links are config-owned. The post-crawl dependency becomes `graph -> demand -> opportunities` when
traffic evidence exists and `graph -> opportunities` otherwise, so link opportunities never race
their source snapshot. Expose `GET /api/v1/projects/{project_id}/site-health/link-graph`, plus
`/nodes` and `/edges`, under the existing Site Health owner. Optional `crawl_id` selects an exact
persisted snapshot; omission selects the latest usable snapshot. Node/edge reads use cursor
pagination and coded unavailable/incomplete states. Fold schema into
`0001_initial.py`; test workspace isolation, partial coverage, idempotency, deterministic PageRank,
and provenance.

**Documentation update:** update `site-health.md` with graph semantics, coverage and opportunity
mapping; update `backend-architecture.md` with task/API/persistence lifecycle and revised post-crawl
DAG; update `frontend-architecture.md` and `design.md` with the Website tab and bounded graph/table
fallback; record backend lifecycle proof in L01 and Opportunity/UI proof in L02.

**Gate:** graph builds from the live edges scoped to one crawl; near-orphan/hub/authority lists
reconcile to the inventory; PageRank is stable across runs.

---

## Workstream 5 — AEO Readiness surface

**Problem:** Site Health already runs every AEO check (schema, author, dates, outbound
citations, answer-first, question-headings, server-rendered, AI-crawler access, llms.txt,
schema-matches-visible) — but there is no dimension-level readiness view.

- **Backend:** a pure projection (invariant 6) over existing `site_rule_evaluations` (705 rows)
  + `site_page_analyses` (22) that groups **current** evaluations into AEO dimensions
  (Answerability, Structure, Evidence, Machine-readability, Authority, Freshness, Crawlability).
- **This mapping is a config-owned presentation taxonomy, not existing scoring.** Persisted
  evaluations carry `dimension` (technical/aeo) + `category` (citability, content, structured
  data…), so the seven buckets are a **new taxonomy** and must be declared in
  `core/config/site_health.py` (invariant 2).
- **The v1 mapping is fixed, one rule ID to one presentation dimension:**
  - **Answerability:** `technical.thin_content`, `aeo.answer_first`,
    `aeo.question_headings`, `aeo.no_expand_gating`.
  - **Structure:** `technical.single_h1`, `aeo.schema_expected_for_type`,
    `aeo.schema_required_valid`, `aeo.schema_recommended_present`,
    `aeo.schema_matches_content`.
  - **Evidence:** `aeo.outbound_citations`.
  - **Machine-readability:** `aeo.structured_data_present`, `aeo.open_graph_present`,
    `aeo.llms_txt_present`.
  - **Authority:** `aeo.author_present`, `aeo.organization_identity`.
  - **Freshness:** `aeo.date_present`.
  - **Crawlability:** `aeo.server_rendered_content`, `technical.ai_crawler_access`,
    `technical.indexable`, `technical.https`.

  Unmapped technical rules remain in Site Health but outside AEO Readiness. Not-applicable rules
  stay in the denominator disclosure/coverage and never become failures. A new or renamed rule
  requires an explicit config mapping and taxonomy version bump; it never falls into a guessed
  bucket.
- **No new scores.** Show **pass / fail / not-applicable / coverage** per dimension with links
  to the underlying evaluations. Per `design.md`, dimension-level evidence — never one mystery
  "AEO 84."
- Expose the read-only projection over persisted evaluations at
  `GET /api/v1/projects/{project_id}/site-health/aeo-readiness`; optional `crawl_id` selects an
  exact crawl and omission selects the latest usable crawl. It performs no network/model work and
  returns the source crawl, taxonomy version, per-dimension counts/coverage, limitations, and
  bounded evaluation links.
- Surface: **AEO Readiness** tab under Website.

**Documentation update:** update `site-health.md` with the seven config-owned presentation
dimensions and explicit statement that no score is added; update `frontend-architecture.md` and
`design.md` with the tab, evidence drill-down, coverage, and not-applicable states; record exact
reconciliation tests in the E01 completion note.

**Gate:** each dimension reconciles exactly to its underlying rule evaluations (e.g. the
low-AEO `case_study_review` page traces to specific failing rules).

---

## Workstream 6 — Change Intelligence (crawl-to-crawl)

**Problem:** crawls are immutable and versioned but there is no diff surface. *(Only one crawl
exists today, so this ships against a recrawl / fixture pair.)*

- New deterministic analyzer `backend/app/analysis/site_health/change_intel.py` comparing
  **crawl A vs crawl B via `SiteUrlObservation` + each URL's selected/current
  `SitePageAnalysis` and its artifact** — not a loose scan of
  `site_fetch_artifacts.normalized_facts` (multiple artifact/task types and analysis versions
  exist).
- **Comparability contract (decided):** B is the selected/newest usable terminal crawl; A is its
  immediately preceding usable crawl for the same project, root origin, crawl-scope hash,
  extractor version, and analyzer version. If no such A exists, the projection is `unavailable`
  with a coded reason. When either crawl is incomplete/cancelled, compare only URLs observed in
  both and suppress added/removed claims. Added/removed classes require both crawls complete with
  identical scope hashes. Redirects are explicit changes keyed by the observed source URL and
  final target. A scope or relevant version mismatch is `non_comparable`, never a regression.
  Later comparable pairs append a new snapshot and supersede open change-derived Opportunities;
  historical observations remain immutable.
- Detect: title / meta description / H1 / canonical / robots-noindex / JSON-LD presence /
  internal-link-count / HTTP-status changes.
- **Classes: `improvement` · `neutral-change` · `potential-regression` · `critical-regression`**
  (config-owned). Rule-result fail→pass is improvement; pass→fail is potential regression, promoted
  to critical only when the owning rule severity is critical. HTTP 2xx→4xx/5xx and an explicitly
  intended-indexable page becoming non-indexable are critical; their deterministic inverses are
  improvements. Text/metadata changes with no rule-state change are neutral. `expected` is a
  separate boolean/linkage overlay, never a fifth severity class: it is true only when WS0B has an
  exact expected check for the target/field and the observed direction matches. A crawler cannot
  infer intent from the change alone.
- **Do not manufacture `SiteIssue` rows.** `SiteIssue` is strictly a 1:1 projection of a failing
  `SiteRuleEvaluation` (verified: `workers/site_health/phases/analyze.py:678` and
  `lifecycle.py:1066`). Persist change observations in the change-intelligence owner and emit
  **Opportunities**; if the change breaks a rule, the normal pipeline creates the issue.
- Surface: **Changes** tab under Website — this is the visible half of **Improve / Verify**.

**Lifecycle decision:** Site Health owns one immutable change snapshot per
`workspace_id + crawl_a_id + crawl_b_id + source_hash + analyzer_version`. A bounded queue task
runs after the newer crawl and WS4 graph snapshot terminalize; retry is idempotent, cancellation
leaves no partial readable projection, and a changed source/version appends a superseding snapshot.
Bounds and class thresholds are config-owned. Expose these routes under the existing Site Health
API owner:

- `GET /api/v1/projects/{project_id}/site-health/changes`
- `GET /api/v1/projects/{project_id}/site-health/changes/summary`
- `GET /api/v1/projects/{project_id}/site-health/changes/{observation_id}`

Supplying `crawl_a_id` and `crawl_b_id` selects an exact pair (both are required together);
omission selects the newest comparable pair. Use cursor pagination and coded
`unavailable`/`non_comparable` responses.
Reads never compute diffs. Fold schema into `0001_initial.py`; test isolation, no-op pairs,
partial-crawl suppression, version/scope mismatch, expected-event linkage, supersession, and exact
provenance.

**Documentation update:** update `site-health.md` with comparability, classes, action linkage, and
supersession; update `backend-architecture.md` with queue/API/persistence lifecycle; update
`frontend-architecture.md` and `design.md` with the Changes tab and limitation states; record the
fixture pair and backend proof in C01, then live/UI/Opportunity proof in C02.

**Gate:** diffing two crawls produces the expected classes; a no-op recrawl yields **zero**
false regressions.

---

## Workstream 7 — Debt removal

Confirmed dead/confusing surfaces. **Gate:** grep inbound references before deleting; each
removal ships as its own reviewed slice, and never before its replacement is live.

| Target | Evidence | Action |
|---|---|---|
| `frontend/app/(app)/site-health/**` (whole family) | Index renders the **same** `SiteHealthScreen` as `/site`; split namespace | Build `/site/crawls/...`, migrate callers/tests, verify, then **delete the entire family**. No redirect or alias. |
| Browser literals for `/site-health` | Dynamic links exist in Site Health Issues/pages/detail and Opportunities; route/title/robots/E2E/tests also refer to it | Migrate to `/site` or `/site/crawls/...`. Retain backend `/api/v1/.../site-health`, `components/site-health/**`, `lib/site-health/**`, API clients, schemas, and query keys because they remain the canonical capability owner. |
| `frontend/app/(app)/prompt-research/**` | Redirect-only retired page | **Delete** after confirming `/prompts` owns default/manage modes; purge route/title/robots/tests/comments. |
| `frontend/app/(app)/providers/page.tsx` | Redirect-only retired page; Settings already owns Providers | **Delete**; migrate callers to `/settings?tab=providers`; purge route/title/robots/tests/comments. |
| `frontend/app/(app)/agent/page.tsx` | Separate destination conflicts with the locked top-bar interaction | Build/test the Agent sheet, migrate invocation callers, then **delete** the route/nav/title/tests. Retain and reuse `GrowthAgentWorkspace` and its typed backend tools inside the sheet. |
| Visibility `overview` tab | Command Center and Visibility both claim Overview | First move the latest comparable summary to WS1, keep latest/start rankings in Trends, move `EngineComparison` and prompt movement into Trends, and move competitor suggestions into the WS1 facts drawer. Then delete the `overview` tab token, `VisibilityOverview`, `OverviewSummary`, duplicated selected-run rankings composition, overview-only queries, tests, and comments. `/visibility` defaults to `trends`. |
| Standalone Facts route/nav | Facts render at `/knowledge-base` | In WS1 move `brand-profile-panel.tsx` into the Overview drawer, migrate competitor-suggestion acceptance, then delete the route, `BrandKnowledgeScreen` if caller-free, nav/title/robots/tests/docs. Retain canonical Brand/BrandProfile APIs and the reusable editor panel. |
| Commerce | Real conditional capability | Retain `/products` and product owners; remove only the unconditional nav item and use `has_commerce_evidence`. |

**Required pre/post searches:** search non-archive code/docs for `/site-health`,
`/prompt-research`, `/providers`, `/knowledge-base`, `/agent`, `VisibilityOverview`,
`OverviewSummary`, `BrandKnowledgeScreen`, and the old visibility `overview` tab token. Classify
every survivor. Also inspect `frontend/app/robots.ts`, `sitemap.ts` and tests, `nav-items.ts`,
`page-titles.ts`, route-state tests, component tests, Playwright specs, marketing previews, and
active architecture/design docs. Do not edit `sitemap.ts` merely because it is on the checklist;
it currently enumerates public marketing routes, so a clean search is a valid retained/no-change
result.

**Documentation update:** change the locked route table from planned to shipped in
`frontend-architecture.md`; update `design.md` with final desktop/mobile navigation and Agent
sheet; remove retired-route and Visibility-Overview guidance from every active doc and README;
archive superseded UI plans/screenshots when still historically useful; record each completed
replacement inventory, pre/post search, deletion, retained owner, and check in I01–I03 and
O02–O03, according to the route/surface that each internal sub-slice replaces.

> Do **not** re-add what the 2026-08 simplification deliberately removed (broad "LLM analytics"
> surface, industry-pack / knowledge-kernel, a second crawler).

### WS7A — Content grounding: a real workstream, not an open question

**This is a prerequisite for any UI or marketing copy that says "grounded generation."** The IA
above already implies grounding, so it must be implemented rather than deferred indefinitely.

Scope: ground generation on **user-confirmed `BrandProfile` facts + exact crawl-*observed*
evidence carrying source refs** — explicitly **not** "verified truth" (invariant 4: persisted
means *observed*). Deliver as a specified contract, not a vibe:

- an exact **fact-envelope schema**;
- **allowed claim classes**, with numeric, pricing, policy, regulated, date and identity claims
  requiring explicit confirmation or omission;
- **source-fragment requirements** per asserted fact;
- **contradiction behaviour** when two sources disagree;
- **enforcement tests** proving a provider cannot cite an absent artifact.

A full Verified Evidence Graph (per-claim sources + site-wide contradiction resolution) is
**explicitly out of scope for this rebuild**. Until WS7A lands, generated output is labelled an
**ungrounded draft** and no surface claims otherwise.

**Provenance** uses the `origin` + `review_state` contract defined in **WS2** — WS7A consumes
it and does not redefine it. Only fields with `review_state = confirmed` (or `edited`) may be
asserted as user-confirmed facts in the envelope.

**Concrete adapter decision:** add `backend/app/domain/content/grounding.py` inside the existing
Content owner. Its public seam is
`build_grounding_envelope(session, workspace_id, project_id) -> GroundingEnvelope`.
`content.service.enqueue_generation()` freezes the returned envelope on `ContentGeneration`, and
`content.message_builder.build_messages()` consumes it. Replace the narrower direct
`WebsiteContext` message parameter rather than running both adapters; `website_context.py` remains
the bounded crawl-fragment selector used internally by the new adapter.

The exact v1 envelope is:

```text
GroundingEnvelope
  status: included | unavailable | conflicting
  version: string
  allowed_facts[]:
    fact_id, field, value, claim_class,
    source_ref_ids[], review_state, limitations[]
  prohibited_claims[]:
    claim_class, reason_code, instruction
  source_refs[]:
    source_ref_id, source_kind(profile_field | crawl_fragment),
    source_id, field_or_fragment, observed_at,
    origin, review_state, extractor_version?, content_hash?
  omissions[]: reason_code, count?
  budget: selected_count, omitted_count, character_count
```

Only `BrandProfile` fields with `review_state=confirmed|edited` become `allowed_facts`. Crawl
fragments are untrusted observed references for terminology, tone, structure, and explicitly
attributed statements such as "the current site says"; they do not become verified business facts.
Numeric, pricing, policy, regulated, date, safety, and identity claims are prohibited unless an
exact confirmed profile fact of the matching class is present. Conflicting confirmed fields make
the affected class prohibited and set envelope status `conflicting`; the model is instructed to
omit it, never choose a winner. Each allowed claim must reference only IDs present in
`source_refs`; validation rejects provider output metadata that cites an absent ID.

**Retrieval decision:** v1 is lexical/graph-only using config-owned bounds and the existing
deterministic page selection. Do not add embeddings, vector columns, dependencies, feature flags,
or placeholder interfaces in this rebuild. Embeddings require a separately approved future plan.

**Documentation update:** update `content-intelligence.md` with the envelope schema, allowed and
prohibited claim classes, conflict behavior, adapter call path, provider-validation contract, and
ungrounded fallback; update `backend-architecture.md` with module ownership and frozen provenance;
update `invariants.md` to replace the empty-envelope clause only when this slice ships; update
marketing copy in the same slice so "grounded" appears only after the gate; record enforcement
tests and removed adapter paths in the G01 completion note.

**Gate:** generation freezes the exact envelope; only confirmed/edited profile fields are allowed
facts; crawl text remains labelled observed/untrusted; conflicts prohibit the claim; absent source
IDs fail validation; and no second context/grounding adapter remains callable.

---

## Workstream 7B — Site Health crawl reliability, trust, and speed

Site Health is the **substrate for every other station** — if the crawl is slow, blocked, or
flags noise, Analyze/Act/Track all inherit it. A live audit of three real crawls
(**cube27** 22 URLs completed · **flipkart** cancelled · **best&less** 150 URLs) found six
root causes. Every claim below is from the live DB.

| Crawl | Status | Discovered / Admitted / Analyzed / Failed | Wall time |
|---|---|---|---|
| cube27 | completed | 22 / 22 / 22 / 0 | 28s |
| flipkart | cancelled (`analysis_status=partially_completed`) | 114 / 150 / 114 / **36** | 416s |
| best&less | cancelled (analysis had finished 150/150) | 150 / 150 / 150 / 0 | ~194s |

### SH-1 — URL normalization bug destroys crawl budget **and** fabricates critical issues

**Verified:** 36 of best&less's 150 discovered URLs contain `%3F` — an **encoded `?`** pushed
into the *path*:

```text
https://www.bestandless.com.au/men%3Fintpromo%3Dhomepage_top-roundel-strip_11_roundel
                                   ^^^ encoded "?" — never parsed as a query string
```

Because the `?` never becomes a query, `_normalize_query()`'s tracking-parameter stripping
(`connectors/web_evidence/url_policy.py`) **never runs**, so each tracking variant becomes a
distinct page identity. Consequences, all confirmed:

- **24% of the crawl budget** was spent re-crawling ~15 category pages as duplicates.
- **Those exact 36 URLs are the 36 `technical.indexable` CRITICAL issues** — a perfect 1:1
  match. The entire critical-severity count for best&less is a **normalization artifact, not a
  site defect.**

**Do NOT globally decode `%3F`/`%26`.** `url_policy.py` *deliberately* preserves reserved-byte
escapes — its own comment states that decoding `%2F`/`%25` would make "two server-distinct URLs
canonicalize to the same identity." A blanket decode would corrupt URL identity site-wide.

**Fix, narrowly scoped:**
1. **Prove the boundary first.** Confirmed starting point: all 36 URLs have
   `latest_source_kind = 'link'` — they entered through **link extraction**, not sitemaps. Find
   whether the href is already encoded in the HTML or whether relative-resolution/`quote()`
   encodes a literal `?` during extraction.
2. **Repair only that boundary.** If extraction is encoding a delimiter that the source markup
   intended as a query separator, fix it there and record a **rewrite reason + version** on the
   observation so the change is auditable. Never decode `%26` globally; interpret it only
   *after* a positively identified encoded query delimiter.
3. **Negative fixtures required:** legitimate `%3F`, `%26`, `%2F`, and `%25` inside real path
   segments must survive unchanged.

This is a **link-extraction correctness fix**, not a change to `canonicalize()` or
`canonical_identity()` semantics (X1 still stands).

**Documentation update (SH-1):** update `site-health.md` with the extraction-boundary rewrite,
rewrite-reason/version provenance, and preserved reserved-byte semantics; add the negative-fixture
and live re-crawl result to the WS7B evaluation artifact and S01 completion note.

### SH-2 — Every URL is fetched twice (the speed regression, issue #5)

**Verified:** `discover` and `analyze` are separate tasks that each perform their **own HTTP
GET**, persisting separate artifacts keyed `(task_id, fetch_purpose)`:

| Project | Unique URLs | GET attempts | Amplification |
|---|---|---|---|
| best&less | 150 | **300** | 2.0× |
| cube27 | 22 | 56 | 2.5× (incl. redirects) |
| flipkart | 150 admitted | **540** | 3.6× |

flipkart is worst because of a **second** multiplier: rung-1 `httpx` returns **403 on 232
attempts**, then rung-2 `curl_cffi` retries and succeeds (224×, avg **851ms**). So a flipkart
page costs up to **four** HTTP round trips (discover 403 → discover curl → analyze 403 →
analyze curl).

**A naive "reuse the discover artifact" fix cannot work.** `SiteFetchArtifact` has **no raw HTML
body column** and carries bounded normalized facts **for analyze tasks only**
([`models/site_health.py:823`](../../backend/app/models/site_health.py)); discovery parses links
from an in-memory response and discards the body. There is nothing stored for analysis to
re-extract from.

**Design selected: extract once at acquisition.** Run the complete bounded fact extractor on the
*discover* response and persist those facts. **No schema widening is required** —
`SiteFetchArtifact.normalized_facts` and `fetch_purpose` already exist; today facts are simply only
written for analyze artifacts. Discovery and analysis keep separate lifecycle results and
versioning; only acquisition is shared. The accepted tradeoff is more discovery CPU per page in
exchange for eliminating the second network acquisition.

**Analysis resolution for the selected design:**

```text
analyze task
  ├─ a complete discover artifact exists for this site_url
  │  AND its extractor_version satisfies the required version   → REUSE (no HTTP)
  └─ otherwise                                                  → normal analyze fetch
```

**A discover artifact is not guaranteed.** Verified: a **Free sample URL is fetched ONLY by its
analyze task** (`phases/analyze.py:551`) — there is no per-URL discover run — so the fallback
path is required, not defensive.

**Reference decision:** `SiteFetchArtifact` remains owned by the discover task; the analyze task
sets its existing `result_artifact_id` to that discover artifact and creates `SitePageAnalysis`
against the same artifact rather than inserting a duplicate. Immutability holds — one artifact,
two referents, never mutated (invariant 4).

**Transport handling — do not mutate `SiteCrawl.configuration`.** It is a **frozen** snapshot
("Freezes the entitlement/config/rule/version snapshots"). Instead add **bounded per-crawl host
observations** recording rung outcomes. The fallback/recovery rule is fixed: two consecutive
rung-1 403/429 responses for a host prefer rung 2 for the next 20 acquisitions; then one rung-1
probe is attempted. A successful probe immediately restores rung 1; another 403/429 starts a new
20-acquisition interval. Timeouts/5xx remain normal retry evidence and do not pin a transport.

Re-measure wall time and request count on all three sites; record before/after in the PR.

**Documentation update (SH-2):** update `site-health.md` and `backend-architecture.md` with the
single-acquisition ownership, artifact reuse/fallback, extractor-version gate, and host-rung
observation/recovery policy; update the evaluation artifact with request amplification and wall
time; record proof that no fetch-artifact schema widening occurred.

### SH-3 — flipkart was not "stuck": it was blocked, and the UI could not say so

**Verified:** flipkart's 36 failures are **70 `robots_denied`** + **2 `http_5xx`** task errors
(across discover+analyze). `discovery_status=completed`, `analysis_status=partially_completed`.

The crawl was progressing; it simply stopped *advancing the visible counter* because failures
don't read as progress — so "114/150" looked frozen and you cancelled a working crawl.

**Fix:** surface a live **blocked/failed breakdown** next to the progress counter
(`robots_denied`, `http_4xx`, `http_5xx`, `timeout`) with the honest states of invariant 7, so
"36 blocked by robots.txt" is visible rather than looking like a hang. Derive stalled/waiting state from **backend evidence** — task lease ownership and expiry,
heartbeat age, queue depth/availability, and host-gate (rate-limit / robots) state — not merely
"no row changed for N seconds," which cannot distinguish a slow host from a dead worker.

**Documentation update (SH-3):** update `site-health.md`, `frontend-architecture.md`, and
`design.md` with the persisted progress/error categories and evidence-derived waiting/stalled
states; record API/UI fixtures and the flipkart live result in the S03 completion note.

### SH-4 — Cancelled crawls silently skip the post-crawl refresh (issue #2)

**Verified root cause** — `workers/site_health/lifecycle.py:550`:

```python
if crawl.status != CRAWL_STATUS_RUNNING:
    return                      # ← cancel already moved status off RUNNING
...
await _enqueue_post_crawl_refresh(session, crawl=crawl)   # never reached
```

Cancelling moves the crawl off `RUNNING`, so terminalization returns early and
`_enqueue_post_crawl_refresh()` never runs. Result, confirmed: **flipkart has 673 issues and
`0` opportunities**, while cube27 (completed) has 254 and best&less has 65.

A second gap in the same function: when a `TrafficSnapshot` exists it refreshes **Demand and
`return`s**, so Opportunities only refresh via Demand's chained enqueue — fragile for a
site-only project.

**Fix:** run the post-crawl refresh for **every terminal outcome that produced usable
evidence** (`completed`, `partially_completed`, and `cancelled`-after-analysis), not only the
clean `RUNNING→completed` path. Opportunities computed from partial evidence must carry
explicit coverage/limitations (invariants 5 + 7).

**Preserve the dependency order — do not enqueue both concurrently.** Demand's refresh already
enqueues an Opportunity refresh after persisting its snapshot
([`domain/demand/service.py:257`](../../backend/app/domain/demand/service.py)); firing both in
parallel could compute Opportunities *before* the new Demand signals exist, then redundantly
recompute. The correct DAG:

```text
Traffic evidence exists  → enqueue Demand → (Demand enqueues) → Opportunities
No Traffic/Demand input  → enqueue Opportunities directly
```

**Invariant: each terminal crawl results in exactly one eventual Opportunity refresh.**

**Documentation update (SH-4):** update `site-health.md` and `backend-architecture.md` with terminal
outcomes, coverage rules, and the post-crawl DAG; update it again in WS4 when graph becomes a new
predecessor; record exactly-once/idempotency and cancelled-crawl tests in the S04 completion note.

### SH-5 — Issue rows already carry detail; the table just doesn't show it (issue #3)

**Verified:** every `site_issues` row has populated `remediation` **and** `evidence`, e.g.
`remediation = "Serve Strict-Transport-Security on HTTPS responses…"`,
`evidence = {"scheme":"https","present":false}`. `components/site-health/issues-catalog.tsx:247`
already renders remediation — the `/issues` **table** does not.

**Correction: a per-rule `description` already exists** in `core/config/site_health.py`
(rule definitions carry `description=` alongside `remediation=`). It is simply **not exposed** —
`domain/site_health/api_schemas.py` has no `description` field, and the frontend cannot read
Python config.

**Fix (not frontend-only — needs an API contract change):**
1. Expose the existing rule `description` through the persisted/API projection so the row can
   show *what is wrong* while `remediation` stays *how to fix it*.
2. **Policy selected: freeze `description` onto the issue row at creation**, like `remediation`,
   with the rule/catalog version. Reads never substitute current catalog copy into historical
   issues. Fold the column into `0001_initial.py` and prove an old issue remains stable after a
   catalog-copy fixture changes.
3. Frontend renders subtitle + evidence chip, with remediation on expand. Match the reference
   layout: severity chip, affected-page count, category tabs, plain-language name + subtitle.

**Documentation update (SH-5):** update `site-health.md` and `backend-architecture.md` with frozen
description provenance and the API field; update `frontend-architecture.md`/`design.md` with issue
row anatomy; record clean-database and historical-copy tests in the S05 completion note.

### SH-6 — Issue *semantics*, not raw counts (issue #4)

**First, a correction to this plan's earlier draft.** The catalog **already groups occurrences
by rule** and shows one row per rule with a DISTINCT affected-URL count
([`service/issues.py::_load_issue_groups`](../../backend/app/domain/site_health/service/issues.py)).
So the user never sees "766 issues." The real numbers:

| Project | Occurrences | **Issue types (what the UI groups to)** | Affected URLs |
|---|---|---|---|
| cube27 | 94 | **16** | 22 |
| flipkart | 766 | **22** | 114 |
| best&less | 526 | **14** | 150 |

**Keep per-evaluation occurrences.** They are the per-page evidence and history; deleting them
to shrink a number would destroy the audit trail (invariants 4 + 5). The problem is therefore
**not** row volume — it is three semantic defects:

**(a) Headline metrics conflate three different quantities.** "52 outstanding issues" must
never mix *issue types*, *affected URLs*, and *occurrences*. **Decision: the headline is defect
issue types**; affected URLs and occurrences are explicitly labelled supporting counts.

**(b) Advisory heuristics rank equal to real defects.** `title_length_band` (103 flipkart / 79
best&less) and `meta_description_length_band` (95) are opinionated preferences.
→ Add **`finding_class = defect | advisory`** to the rule catalog. *(Not "confidence" — a
deterministic advisory can have perfectly high evidence confidence.)* Only `defect` feeds
headline counts, severity chips, and opportunities; advisories get their own view. V1 marks
`technical.title_length_band` and `technical.meta_description_length_band` advisory; all other
existing rules remain defect except an indexability result whose intent evidence is unknown, which
is projected as advisory/uncertain and does not create an Opportunity.

**(c) Intentional non-indexing is flagged CRITICAL.** flipkart's hits are ad/promo landers
(`/rakhi-2026-at-store`, `/twowheelers-at-store`); best&less's are SH-1 artifacts. Both are
*correctly* `noindex`.
→ **Do not infer intent from weak signals.** "Promo-like path" and "no inbound links" are not
proof. Use **explicit user policy, canonical declarations, sitemap membership, or robots
evidence**; where intent is genuinely unknown, emit an **advisory/uncertain observation**, never
a critical defect (invariant 7: `not_applicable ≠ fail`).

**On host-scoped rules:** `technical.hsts_present` writes 112 occurrences on flipkart with
byte-identical evidence for **one** host header. Grouping already hides this from the user, so
it is an *evidence-efficiency* concern, not a UI inflation bug. **Host-scoped evaluation and
template scope are explicitly out of scope for this rebuild.** Keep current per-page evidence;
do not add either scope token, dormant config, or placeholder owner. A future host-scope change
needs its own plan, and template scope additionally requires a deterministic template identity
owner, which does not exist today.

**Gate:** every remaining `finding_class = defect` traces to a real, reproducible problem on the
live site; every headline metric names which quantity it counts (**issue types** vs
**occurrences** vs **affected URLs**); no rule emits a critical for a page whose non-indexing is
explicitly intended.

**Documentation update (SH-6):** update `site-health.md` with `finding_class`, headline-count
semantics, intentional-indexing evidence precedence, and the decision not to add host/template scope;
update `design.md`/`frontend-architecture.md` with defect/advisory views; record per-site before/
after classifications in the WS7B evaluation artifact and S06 completion note.

### SH gates

- Re-crawl cube27, flipkart, and best&less; record before/after **wall time**, **HTTP request
  count**, **issue types by `finding_class`** (plus occurrences and affected URLs), and
  **opportunity count**.
- flipkart must complete without cancellation, reporting blocked URLs explicitly rather than
  appearing stalled.
- Zero **erroneous encoded-query tracking variants** in `site_urls` (legitimate `%3F`/`%26`/`%2F`
  path content must remain valid and unchanged).
- A cancelled-after-analysis crawl still produces opportunities, with coverage stated.

---

## Workstream 8 — Schema and image debt closure (final, mandatory)

Runs **after** all feature slices merge, so no partial migration or stale image survives.

> **Sequencing correction:** folding migrations and running clean-database verification happens
> **inside every schema-changing slice**, not here. WS8 is the **final audit** that proves
> nothing drifted — it must never be the first time migrations become complete.

1. **Confirm every schema change was folded into the single baseline.** Per invariant 16, all
   new tables/columns (query-evidence projection, link-graph snapshot, change observations,
   frozen issue descriptions, and action/verification events) live in
   `migrations/versions/0001_initial.py`. No `0002+`.
2. **Verify from an empty disposable database** (the full invariant-16 gate, not just
   `alembic check`):
   ```bash
   # from backend/
   uv run alembic upgrade head      # against a clean, empty DB
   uv run alembic check             # must report no pending diff
   ```
3. **Reset and recreate the development database** using the existing tool (it resolves the
   Docker env, drops, recreates, and migrates — dev/test envs only):
   ```bash
   uv run --project backend python reset-db.py
   ```
4. **Rebuild all container images from scratch** so no stale layer persists:
   ```bash
   env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
     POSTGRES_PASSWORD=<repo-.env-value> \
     docker compose -f infra/docker/docker-compose.yml build --no-cache
   env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
     POSTGRES_PASSWORD=<repo-.env-value> \
     docker compose -f infra/docker/docker-compose.yml up -d --force-recreate
   ```
   Do **not** run a blanket `docker image prune -f` — it affects unrelated images on the
   machine and is not required for correctness.
   (The `env -u …` form is mandatory — see the Compose gotcha in
   [`docker-compose.yml`](../../infra/docker/docker-compose.yml) and invariant 11 of
   `DEVELOPMENT.md`.)
5. **Repopulate and re-verify end to end** on the clean stack: onboard a project (confirm ICP)
   → crawl → connect GSC/GA4 → sync → recompute demand/opportunities → run an audit → confirm
   every station renders with real data and honest empty states.
6. **Confirm no orphaned artifacts:** no unused tables/columns left in the baseline, no removed
   route still referenced in `robots.ts`/sitemap/nav/page-titles, no dead component files.

**Documentation update:** reconcile `AGENTS.md`, `architecture.md`, all subsystem/runtime
authorities, `README.md`, and `documentation-index.md` against the clean shipped runtime; archive
superseded plans/screenshots; store a dated sanitized end-to-end evaluation artifact; audit every
completion note for final commit/PR and verification evidence; set this plan to `completed` only
when no row remains pending and `python docs/validate_documentation.py` is green.

---

## Validation methodology — "test before implement" as a hard gate

Every data-dependent feature's **first** implementation step is a validation spike, not the build:

**Two complementary layers, with distinct jobs — neither substitutes for the other:**

| Layer | Validates | Requirement |
|---|---|---|
| **Live runs** | Integration correctness and **honest abstention** on real evidence | Must run; the detector must not crash, double-count, or fabricate on live data |
| **Deterministic fixtures** | **Positive and boundary cases** | Must exist for every detector, including cases absent from the current sample |

1. Query the connected project's **live DB (read-only)** and confirm the detector integrates and
   abstains correctly (the method used to write this plan).
2. Run against **≥1 richer sample site** so nothing is tuned to one small corpus.
3. Write deterministic fixtures covering positive + boundary behaviour.

**A detector does NOT need to fire naturally on the current sample** — deterministic fixtures
are sufficient proof of positive behaviour. Requiring natural occurrence would quietly tune the
product to two or three sites.

---

## Verification

```bash
# Backend (from backend/)
uv run pytest tests/unit/test_demand*.py tests/unit/test_site_health*.py \
  tests/component/test_opportunities*.py tests/component/test_command_center*.py -q
uv run ruff check <changed paths>

# Frontend (from frontend/) — pnpm only
pnpm test -- <changed files>
pnpm lint && pnpm check:policy && pnpm build

# Docs + clean-database schema gate (invariant 16)
python docs/validate_documentation.py
(cd backend && uv run alembic upgrade head && uv run alembic check)   # empty disposable DB
```

Add deterministic fixtures per new detector/analyzer (invariant 5) and per honest-state case
(invariant 7).

**Site Health regression baseline (WS7B).** Record these live numbers before changing anything,
and re-measure after; every one must improve or hold:

| Metric | cube27 | flipkart | best&less |
|---|---|---|---|
| Wall time | 28s | 416s (cancelled) | ~194s |
| HTTP GET attempts / unique URL | 2.5× | 3.6× | 2.0× |
| `%3F` duplicate identities | 0 | 0 | **36** |
| Issue **types** (user-visible groups) | 16 | 22 | 14 |
| Issue occurrences (evidence rows) | 94 | 766 | 526 |
| Affected URLs | 22 | 114 | 150 |
| Opportunities produced | 254 | **0** | 65 |

Occurrence counts are expected to stay high (they are per-page evidence); what must improve is
**defect-class issue types**, false-positive criticals, wall time, and requests per URL.

**Store these as a dated, sanitized evaluation artifact** under `docs/evaluations/` rather than
treating a mutable local database as architecture. A detector does **not** need to occur
naturally on these three sites if deterministic fixtures prove it — otherwise the process
quietly tunes the product to one small sample.

---

## Sequencing

**Product decisions are closed for this plan:** measurable promise, explicit action/verification
events, route contract, provenance shape, grounding envelope, detector semantics, crawl
acquisition, issue-description history, and change comparability are selected above.
Implementation evidence may require a documented amendment; it does not authorize an implementer
to choose a different product contract silently.

The canonical implementation order is six fresh chats and six PRs:

```text
W1 Foundations       R00 → X01 → D01 → D02 → A01 → A02
W2 Site Health       S01 → S02 → S03 → S04 → S05 → S06
W3 Product loop      I01 → I02 → I03 → P01 → O01 → O02 → O03
W4 Demand + Content  G01 → Q01 → Q02 → Q03
W5 Site Intelligence L01 → L02 → E01
W6 Change + Final    C01 → C02 → Z01
```

One chat implements every internal row on one line, then `$ship-main` opens and merges that line's
single PR. The next fresh chat starts only from synchronized `main` and the next wave handoff.
Internal rows retain focused gates and completion evidence but never produce their own PR or
handoff. Rebalancing may move whole rows between the six waves to respect CodeRabbit's file limit;
it may not create a seventh PR or silently change the locked product contract.
