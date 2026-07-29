# Refactoring Plan — Technical Debt & Site Health Stability

**Date:** July 29, 2026
**Source audit:** [static-analysis-audit-2026-07-29.md](../audits/static-analysis-audit-2026-07-29.md)
**Scope:** Backend (`backend/app`, `backend/tests`) + Frontend (`frontend/lib/site-health`, `frontend/components/site-health`)
**Primary goal:** Eliminate the Site Health flakiness. **Secondary goal:** pay down the complexity/duplication/dead-code debt the audit measured.

---

## 0. How this plan differs from the audit

The audit is a metrics snapshot. This plan is driven by a **root-cause trace of the Site Health flakiness**, done by reading the execution paths rather than the metrics. That trace found a compounding three-bug chain (§2) that explains "flaky at times" — load-dependent, non-deterministic stuck crawls. Complexity reduction is sequenced *behind* those fixes, because the correctness fixes are small and the decomposition is large.

Two audit findings were re-verified and **corrected**:

| Audit claim | Verified status |
| :--- | :--- |
| §4.B.5–7 — 5 config validators may be missing `@model_validator` decorators (Open Question 3) | **False positive.** All are correctly decorated (`site_health.py:1796,1815`, `analytics.py:335`, `suggestions.py:82,126`, `workspaces/schemas.py:41`). No work needed. |
| §5.4 / Open Question 5 — duplicated `normalize_citation_url` | **Misnamed.** No such function exists. The real duplication is a byte-identical `normalize_domain` in `app/analysis/normalization.py:53` and `app/connectors/answer_engines/normalization.py:54`. Still worth consolidating. |

A note on LOC figures, since two counts appear in this document: the audit reports **radon SLOC** (blank lines excluded), while `wc -l` counts every line. For `site_health_worker.py` that is 2,899 vs 3,099 — the same file, and 3,099 − 200 blanks = 2,899 exactly. Where this plan quotes `wc -l` it says so. The two are not comparable and neither indicates growth.

---

## 1. Priority summary

| Phase | Theme | Effort | Risk | Status |
| :--- | :--- | :---: | :---: | :--- |
| **P0** | Backend crawl-lifecycle correctness | S | Low | **Done** — stall bug fixed, regression-pinned |
| **P1** | Frontend polling & state-derivation | S–M | Low | **Done** — all of P1.1–P1.6 |
| **P2** | `site_health_worker.py` decomposition | L | Med | **Done** — 3,099 → 760 LOC across 10 modules |
| **P3** | `domain/site_health/service.py` dedup | M | Low | **Done** — shared keyset builder + the package split |
| **P4** | Dead code + duplication sweep | S | Low | **Done** — 2 of 5 findings were false positives (see §6) |
| **P5** | Test suite decomposition | M | Low | **Done except P5.3**, which is declined with reasons (§7) |

Nothing in this plan is open. The last two items to land were **P1.2/P1.6**
(single-subscription polling, the `'resolving'` phase that retired the `crawlStarting`
workaround) and **P3.2/P3.3** (the `service.py` package split + direct unit tests for the row
shapers) — both behaviour-neutral, and neither on the critical path of the flakiness fix.

**Ship P0 and P1 first and independently.** They are the user-visible fix.

---

## 2. Root cause: why Site Health is flaky

Three defects compound. Individually each is survivable; together they produce load-dependent stuck crawls.

### F1 — The lease sweeper terminalizes tasks without reconciling the crawl *(the stuck-crawl bug)*

`PostgresTaskQueue.release_expired` ([postgres_task_queue.py:327-374](../../backend/app/orchestration/postgres_task_queue.py#L327-L374)) can set a task to `TASK_STATUS_FAILED` when its lease expires with attempts exhausted:

```python
if task.attempt_count >= task.max_attempts:
    task.status = TASK_STATUS_FAILED  # terminal
    task.completed_at = now
```

But `_reconcile_crawl_status` — the *only* thing that terminalizes a crawl — has exactly **two callers, both inside `_execute_task`** ([site_health_worker.py:632](../../backend/app/workers/site_health_worker.py#L632), [:663](../../backend/app/workers/site_health_worker.py#L663)). There is no watchdog, no reaper, no periodic reconcile (verified by repo-wide grep).

**Consequence:** if the sweeper terminalizes the *last* non-terminal task of a crawl, `run_once` then claims nothing, returns 0, and **nobody ever reconciles**. The crawl stays `status='running'` / `analysis_status='running'` forever. No snapshot is persisted, no `crawl.completed` event fires. The frontend — whose `shouldPollCrawl` only stops on a terminal status (§F7) — polls that crawl every 4s indefinitely.

This is the headline bug and the direct cause of "sometimes a crawl just never finishes."

### F2 — Reconcile holds the crawl row lock across the entire finalize pass

`_reconcile_crawl_status` ([:2603](../../backend/app/workers/site_health_worker.py#L2603), CC=26) opens `session.get(SiteCrawl, crawl_id, with_for_update=True)` and, on the terminalizing call, performs **inside that lock**: 6 count queries (`_task_counts`), the full `_run_crawl_finalize_pass` (cross-page broken-link / orphan / hreflang evaluation over every analysis in the crawl), and `_persist_snapshot`.

It runs in the `finally:` of **every** task, of every kind. With `worker_concurrency: 8` ([site_health.py:1773](../../backend/app/core/config/site_health.py#L1773)), 8 concurrently-finishing tasks serialize on one row, and the tail of a crawl serializes behind a finalize pass that scales with crawl size.

### F3 — The persist phase runs with no heartbeat

Heartbeats are started per fetch and **cancelled when the fetch returns** ([:1816-1826](../../backend/app/workers/site_health_worker.py#L1816-L1826)). Everything after — `_persist_analyze`, `_write_page_analysis` (CC=24), artifact write, link-check enqueue, event record, `_finalize_queue_row` — runs **unheartbeated** against a `lease_ttl_seconds: 120.0` budget. That phase includes `_lock_guarded_analyze_task`, which contends for the same crawl row that F2 is holding.

### The compounding chain

> **F2** (long lock hold, ×8 concurrency) → **F3** (unheartbeated persist blocked on that lock exceeds the 120s lease) → sweeper reclaims → attempts exhaust → **F1** (terminal task, no reconcile) → **crawl stuck forever** → frontend polls forever.

Every link is load-dependent, which is exactly why it presents as intermittent: small crawls finish fine, larger or slower ones intermittently hang.

### P0 fixes

| ID | Fix | File |
| :--- | :--- | :--- |
| **P0.1** | Make reconcile reachable outside task execution. Call `_reconcile_crawl_status` for every distinct `crawl_id` the sweeper touched — have `release_expired` return the affected task rows (not just a count), and reconcile those crawls in `run_once` after the sweep. | `postgres_task_queue.py`, `site_health_worker.py:459-469` |
| **P0.2** | Add a **stuck-crawl watchdog**: in `run_once`, reconcile any crawl that is non-terminal, has zero non-terminal tasks, and whose `updated_at` is older than a threshold. This is the belt-and-braces guarantee that no crawl can hang regardless of which path terminalized the last task. Idempotent by construction (reconcile already short-circuits on terminal crawls). | `site_health_worker.py` |
| **P0.3** | ~~Move `_run_crawl_finalize_pass` + `_persist_snapshot` out of the crawl `FOR UPDATE` window.~~ **Dropped during implementation — see note below.** | — |
| **P0.4** | Keep the heartbeat alive through the persist phase. Extend heartbeat coverage from "fetch only" to "fetch + persist", ending at `_finalize_queue_row`. Removes the lease-expiry window entirely. | `site_health_worker.py:1816-1826`, `:717-731`, `:2390-2397` |
| **P0.5** | Log loudly when the sweeper terminalizes a task at max attempts (currently a single aggregate `info` with only a count — a stuck crawl leaves no attributable trace). Include `crawl_id` + `task_kind`. | `postgres_task_queue.py:369-373` |

> **Implementation note — why P0.3 was dropped.** Splitting the finalize pass and
> snapshot out of the terminalizing transaction trades a fixed bug for a worse
> one. Today, "crawl went terminal" and "snapshot + finalize issues exist" commit
> atomically under one lock; that atomicity *is* the exactly-once guarantee.
> Moving them to a follow-up transaction opens a crash window that leaves a
> terminal crawl with no snapshot and no finalize-scoped issues — a permanently
> wrong dashboard, unreachable by retry because the crawl is already terminal
> (`persist_crawl_snapshot` is `ON CONFLICT DO NOTHING`, so it cannot self-heal
> a missed write, and reconcile short-circuits on terminal crawls).
>
> Crucially, P0.3 was never the correctness fix — **P0.4 is**. Lock contention
> only caused failures *because* the persist phase was unheartbeated; with the
> heartbeat spanning fetch + persist, contention costs waiting, not lease loss.
> Reducing the lock hold is a latency optimization and belongs in P2, where
> `lifecycle.py` can be restructured with the exactly-once invariant made
> explicit and tested rather than preserved by accident.

**Tests to add** (component, against the real queue):
- Sweeper fails the last analyze task of a crawl → crawl reaches a terminal status and persists a snapshot.
- Watchdog terminalizes a crawl whose tasks were all terminalized out-of-band.
- Concurrent finalize of N tasks on one crawl terminalizes exactly once (regression guard for P0.3).
- A persist phase artificially slowed beyond `lease_ttl_seconds` does not lose its lease (P0.4).

---

## 3. P1 — Frontend polling and state derivation

### F4 — Five independent 4s polls, plus SSE invalidating all of them

Active-crawl polling at `POLL_INTERVAL_MS = 4_000` runs in **five** places:

- [use-site-health-screen.ts:47](../../frontend/lib/site-health/use-site-health-screen.ts#L47) — dashboard
- [use-site-health-screen.ts:69](../../frontend/lib/site-health/use-site-health-screen.ts#L69) — pages
- [inventory-section.tsx:149](../../frontend/components/site-health/inventory-section.tsx#L149) and [:283](../../frontend/components/site-health/inventory-section.tsx#L283)
- [url-detail.tsx:93](../../frontend/components/site-health/url-detail.tsx#L93)

On top of that, `useCrawlEvents` invalidates **5 query keys on every single SSE frame** ([use-crawl-events.ts](../../frontend/lib/site-health/use-crawl-events.ts)) — and the backend emits an `analysis.progress` event *per analyzed URL* ([site_health_worker.py:2135-2142](../../backend/app/workers/site_health_worker.py#L2135-L2142)). A 500-URL crawl therefore triggers ~2,500 invalidations, each racing the 4s timers.

**Consequence:** overlapping in-flight requests land out of order, so different panels render state from different moments — counts that tick backwards, a phase that flips, a score that appears then vanishes. This is the visible "flakiness" even when the backend is healthy.

**P1.1** — Debounce/coalesce SSE invalidation (trailing edge, ~500ms). One burst of events → one invalidation round.
**P1.2 — DONE.** The dashboard query owns the ONE timer. Every other crawl-derived view refreshes
when `crawlProgressVersion(crawl)` changes — a fingerprint of the crawl's status/sub-states/counters/
`updated_at` — so a poll that returns an unchanged crawl now costs nothing downstream. The screen's
pages query and both `inventory-section` timers are gone. Poll and stream share ONE definition of
what a crawl change refreshes ([invalidate.ts](../../frontend/lib/site-health/invalidate.ts)), which
also narrowed the SSE path: only the FIRST page of each list is invalidated, so deeper cursor pages
no longer shift under a reader mid-crawl. (`url-detail.tsx`'s timer is NOT part of this: it is the
per-page rerun poll, a different subject with its own ceiling.)
**P1.3** — Back off the poll interval as the crawl ages (4s → 10s → 30s) instead of a flat 4s for the crawl's entire lifetime.

### F5 — SSE never reconnects

The stream is opened once per `useEffect`. The server closes it at `sse_max_duration_seconds: 300.0` ([site_health.py:1794](../../backend/app/core/config/site_health.py#L1794)). When the reader hits `done`, the loop simply exits — **no reconnect**.

**Consequence:** crawls under 5 minutes feel instant and responsive; crawls over 5 minutes silently degrade to 4s polling partway through. Identical code, two different behaviours — a classic "it's flaky" report.

**P1.4** — Reconnect with capped exponential backoff on clean stream end while the crawl is still active, passing `last_event_id` (the endpoint already supports it, [site_health.py:689](../../backend/app/api/site_health.py#L689)).

### F6 — No poll ceiling

`shouldPollCrawl` ([status.ts:69-71](../../frontend/lib/site-health/status.ts#L69-L71)) returns `!TERMINAL_OVERALL.has(crawl.status)` — unbounded. Paired with F1, a stuck crawl polls forever, in every open tab, until the browser closes.

**P1.5** — Add a poll ceiling and a stalled-crawl UI state ("This crawl hasn't progressed in N minutes"), following the existing `BILLING_CONFIRM_MAX_POLLS` precedent in [lib/api/billing.ts:18](../../frontend/lib/api/billing.ts#L18). This is a **safety net, not a substitute for P0** — with P0 shipped it should never trigger.

### F7 — Phase derived from three independently-resolving queries

`resolveSiteHealthPhase(crawl, plan, hasMonitoredSelection)` combines `dashboardQuery`, `entitlementQuery`, and `monitoredQuery`. As those settle in varying orders the phase transiently mis-resolves. The `crawlStarting` flag and the `createMutation.reset()` effect ([use-site-health-screen.ts:126-155](../../frontend/lib/site-health/use-site-health-screen.ts#L126-L155)) are patches for this — the code comment says so outright: *"which is what used to bounce the UI back to the selection list after 'Start analysis'"*.

**P1.6 — DONE.** `resolveSiteHealthPhase` is now total over loading state: `crawl === undefined`,
`plan === null`, or `hasMonitoredSelection === null` means "not settled" and resolves to
`'resolving'`, which the screen renders as its skeleton. `null` still means a settled "no crawl", so
the empty state is unchanged. A FAILED query counts as settled (it has an answer; waiting forever
would be worse).

Both workarounds are deleted — but note that `'resolving'` alone was NOT sufficient, and finding
that out was the useful part. It closes the FIRST-LOAD window (the monitored query settling last),
while `crawlStarting` was mostly covering a second window: after a create succeeded, the dashboard
still returned the PREVIOUS crawl, so the phase re-resolved against a stale (often terminal) crawl.
The fix for that is to stop the stale input existing at all — `createCrawl`'s `onSuccess` writes the
new crawl straight into the dashboard cache (the same shape the cancel mutation already used). With
the input correct there is no gap to freeze, so the compound flag and the `reset()` effect both go,
and what remains is an ordinary `startPending` for the in-flight request. The canonical-flow
regression test (`walks discover → cancel → select → start analysis → finish`) is what pins it.

---

## 4. P2 — `site_health_worker.py` decomposition (3,099 LOC, MI 0.0)

**Answering the audit's Open Question 4:** do **not** split into `DiscoverWorker` / `AnalyzeWorker` / `LinkCheckWorker` / `FinalizeWorker` process classes. The single claim loop is what makes cross-kind reconcile correct and the per-host politeness gate (`_host_semaphores`, `_host_start_locks`, `_host_last_started`) coherent; four workers would need four gates over the same hosts and a distributed terminalization protocol. **Split by collaborator, not by process.**

Extract from `SiteHealthWorker`, keeping one worker class as the queue-loop shell:

| New module | Moved from | Rationale |
| :--- | :--- | :--- |
| `workers/site_health/host_gate.py` | `_execute_claimed`, `_release_host_gate`, `_evict_idle_hosts`, `_evict_host`, `_host_*` dicts | Self-contained politeness state machine; independently unit-testable without a DB. |
| `workers/site_health/lifecycle.py` | `_reconcile_crawl_status`, `_task_counts`, `_ensure_running` | The exactly-once terminalization invariant — currently the most-commented, least-isolated logic. This is where P0.1–P0.3 land. |
| `workers/site_health/phases/discover.py` | `_run_discover` + `_fetch_discover`, `_ensure_robots_policy`, `_fetch_well_known`, `_site_setup` (CC=18), `_ingest_sitemaps` (CC=18), `_persist_discover` | |
| `workers/site_health/phases/analyze.py` | `_run_analyze`, `_evaluate_analyze_guard`, `_fetch_analyze`, `_persist_analyze`, `_write_page_analysis` (CC=24) | |
| `workers/site_health/phases/link_check.py` | `_run_link_check`, `_load_link_check_source`, `_link_check_targets`, `_probe_link`, `_write_link_reference` | |
| `workers/site_health/persistence.py` | `_write_artifact`, `_write_attempt` (CC=16), `_finalize_queue_row`, `_record_crash` | Shared write helpers; removes the inline-AsyncSession sprawl driving MI to 0.0. |

**Sequencing:** pure moves first (host gate, persistence), then phases, then lifecycle last — lifecycle carries the P0 changes and deserves an isolated diff.

**Targets:** no function above CC 15; `site_health_worker.py` under 400 LOC; MI back into Rank A. Each extraction is behaviour-preserving and verified by the existing component suite before the next begins.

---

## 5. P3 — `domain/site_health/service.py` decomposition (2,005 LOC, MI 0.0)

Highest-value split in the read path. `get_inventory` (CC=35) and `get_pages` (CC=34) share the 37-line 100%-identical keyset-pagination block the audit flagged ([§5.1](../audits/static-analysis-audit-2026-07-29.md)).

- **P3.1** — Extract a shared keyset paginator (`_decode_url_keyset` / `_decode_created_id_keyset` + filter construction) used by `get_inventory`, `get_pages`, and `get_issues`. Kills the top duplication block and a large share of both CC scores.
- **P3.2 — DONE.** `service.py` is now a package whose `__init__.py` is a pure façade, so every
  existing `from app.domain.site_health.service import x` still resolves (including the two private
  names the router and the unit tests import). Five modules, not the three planned: `presentation.py`
  (363) and `lifecycle.py` (241) as specified, plus `common.py` (115) for the plumbing every read
  path shares (the two error types, the limit clamp, the workspace-scoped loaders, the cursor
  decoders) and a split of the "queries" bucket into `queries.py` (815 — entitlement/crawls/
  inventory/pages/page detail) and `issues.py` (647 — the grouped catalog, detail, history). One
  1,460-line `queries.py` would have been worse than the file it replaced; grouping is its own
  algorithm rather than another row projection, which is the seam. Every moved function is
  byte-identical to what it replaced (the split was done by slicing the original), so the component
  suite verifies it as a pure move.
- **P3.3 — DONE.** [test_site_health_presentation.py](../../backend/tests/unit/test_site_health_presentation.py)
  tests the row shapers directly: the `project_crawl` aliases, the Free redaction (including the
  frozen-capability fallback), `total_url_count` withheld until the inventory closes, the derived
  `_page_facts` counts, `_delivery_facts` distinguishing unknown from zero, current-catalog titles on
  persisted evidence, and the two shared filter predicates.

**Baseline note.** The split moved five functions that are still above the ratchet's CC-15 ceiling
(`get_inventory` 30, `get_pages` 29, `_page_facts` 24, `get_page_detail` 19, `get_issues` 16 by the
checker's count). New modules get no grandfathering, so the ratchet failed until the baseline was
rewritten. It was — and because the baseline is now per-FUNCTION (see §7), those five carry their own
budgets instead of hiding under one module-wide max of 30, which is strictly tighter than what they
had before the move. Their CC is unchanged by this work; reducing it is separate work on the
functions themselves.

---

## 6. P4 — Dead code and duplication sweep

### Confirmed removable (re-verified against current HEAD)

| Symbol | Location | Evidence |
| :--- | :--- | :--- |
| `transports_for_engine` | [provider_catalog.py:53](../../backend/app/core/config/provider_catalog.py#L53) | 1 repo-wide hit. Sibling helpers (`is_route_approved`, `is_active_transport`) cover routing. **Removed.** |
| ~~`url_count` property~~ | [web_evidence/sitemaps.py:142](../../backend/app/connectors/web_evidence/sitemaps.py#L142) | **KEPT.** Removing it broke `test_collector_accumulates_urls`, which asserts on `collector.url_count`. My verification grep filtered out `*_url_count` to skip the ~140 unrelated `discovered_url_count` hits and discarded this real caller with them — the audit's "needs verification" label was right. |

**`enqueue_order_retention_sweep` — KEPT (audit §4.A.1 / Open Question 1 answered "no").** The
audit's call-count evidence was right but the conclusion was wrong. Its task kind
`ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP` is registered in the analytics worker's live
`_executors` table ([analytics_worker.py:98](../../backend/app/workers/analytics_worker.py#L98)) against
a real implementation (`run_order_retention_sweep`), and it is the exact structural twin of
`enqueue_referral_retention_sweep`, which has no production caller either — both are
scheduler-facing entry points for a queue whose consumer side is fully wired. Deleting one
half of a live queue contract because no *caller* exists yet would break the sweep the moment
a cron is attached. Not dead code; an un-scheduled feature.

### Tested-but-unused (decide: promote or delete)

`normalize_prompt_rows` ([projects/normalization.py:40](../../backend/app/domain/projects/normalization.py#L40)) and `can_transition` ([orchestration/audit_state.py:76](../../backend/app/orchestration/audit_state.py#L76)) are exercised only by their own unit tests. Each is a test asserting nothing about production behaviour. Delete both unless a caller is planned.

`fetch_subscription` ([billing/base.py:43](../../backend/app/connectors/billing/base.py#L43), [razorpay.py:162](../../backend/app/connectors/billing/razorpay.py#L162)) is an abstract-interface method — **keep**; removing it would make the connector interface asymmetric for a webhook-outage fallback that is genuinely wanted.

### Duplication

- **P4.1** — Consolidate the identical `normalize_domain` into one shared module and re-export (corrects audit §5.4).
- **P4.2** — Extract the shared snapshot-provenance column mixin (`models/analytics.py:271-297` ≡ `models/site_health.py:973-999`) and the score-aggregation mixin repeated 3× in `models/analysis.py`.
- **P4.3** — Extract the OAuth refresh-retry loop shared by [ga4.py:41-62](../../backend/app/connectors/integrations/ga4.py#L41-L62) and [gsc.py:23-44](../../backend/app/connectors/integrations/gsc.py#L23-L44).
- **P4.4** — Hoist the duplicated `run_until_idle` drain loop into a shared worker mixin (content/integration/site-health/analytics all reimplement it).

---

## 7. P5 — Test suite and a structural brake

`test_site_health_worker.py` is 3,327 LOC at MI 0.0, with single tests at CC=40 and CC=28. A 40-branch test is not a specification — it is a second system to debug, and it is likely a contributor to *test* flakiness alongside the product flakiness.

- **P5.1 — DONE.** Split into `test_site_health_{discover,analyze,link_check,terminalization,loop}.py`, mirroring the P2 module layout. (`terminalization`, not `lifecycle`: that filename already holds the P0 stall regressions.)
- **P5.2 — DONE.** All shared setup — fake resolver, stub transports, HTML fixtures, crawl seeders — moved to `site_health_worker_helpers.py`, imported explicitly (no star imports) by each phase file.
- **P5.3 — NOT DONE, deliberately.** The CC=79 / CC=72 tests in `test_product_analysis_worker.py` (169 lines) and `test_integration_ga4.py` (205 lines) are single end-to-end scenarios whose assertions run against one accumulated state. The suite empties every table between tests ([conftest.py](../../backend/tests/conftest.py#L45-L66)), so a shared seeded fixture **cannot** span split tests — each fragment would re-run the full seed plus a worker pass. Splitting one such test five ways multiplies its setup cost fivefold and gains no coverage; high CC is the honest shape of an e2e test that asserts a whole pipeline. Revisit only if these tests become a debugging problem in practice, and then by extracting assertion helpers rather than splitting the scenario.

**Structural brake — DONE.** Nothing in CI measured module size or function complexity, so the two
MI-0.0 monoliths reached that state without any build ever objecting.
[check_complexity.py](../../backend/scripts/check_complexity.py) is that watcher: stdlib-`ast` only
(CI installs from a frozen lock, so needing radon would mean lockfile churn on every touch), it runs
in the backend job, and it fails only on regression against a checked-in baseline.

The baseline is per-FUNCTION, not per-module-max. A single module max let one function's improvement
pay for another's regression — dropping a CC-34 hotspot to 20 silently bought every other function in
that module 20 points of headroom. Now each function carries its own budget, a function the baseline
does not know (new, or renamed) has no budget to inherit and must meet the CC-15 ceiling, and a
module's LOC still cannot grow. Baselines without the per-function map are read compatibly (module
max only) so the file can be regenerated on its own schedule.

---

## 8. Suggested sequencing

1. **P0.1 + P0.2** (stuck-crawl fix + watchdog) — ship alone, with the component regression tests. This is the fix.
2. **P0.3 + P0.4 + P0.5** (lock window, heartbeat, logging) — removes the conditions that trigger F1 at all.
3. **P1.1 + P1.4 + P1.5** (invalidation debounce, SSE reconnect, poll ceiling) — user-visible stability.
4. **P1.2 + P1.3 + P1.6** — polling consolidation and phase-resolution cleanup; success criterion is deleting the `crawlStarting` workaround.
5. **P4** — cleanup, parallelizable with anything above.
6. **P2** then **P3** — decomposition, one extraction per PR, green suite between each.
7. **P5** — after the code it tests has settled.

**Do not start P2 before P0 lands.** Restructuring the worker while a live correctness bug is open makes the bug harder to attribute, and the P0 diffs are small enough to review carefully on today's code.

---

## 9. Open questions for the owner

1. **P0.2 watchdog threshold** — what is the maximum acceptable time for a crawl to sit non-terminal before the watchdog force-reconciles? Suggest 2× `lease_ttl_seconds` (240s).
2. **Retention sweep & provider catalog** (audit OQ 1–2) — delete, or are they staged for an unreleased feature?
3. **P1.5 stalled-crawl UX** — with P0 shipped this should be unreachable. Show a stalled state with a retry, or just stop polling silently?
4. **P1.3 poll backoff** — acceptable to trade worst-case 30s latency on long crawls for the reduced request load?
