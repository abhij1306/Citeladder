# Crawl, Onboarding and Prompt-Generation Repair

## Context

Five defects were reported, all reproducible and all long-standing. Each was traced to a
concrete code-level cause using the local Postgres (`citeladder-db-1`) before that database
was reset mid-investigation — the counts quoted below are from that snapshot of two
`lanhtropy.com` crawls and their generated prompts, and are the evidence this plan rests on.

Two of the five share a root: a crawl that the user cancels because it looks stuck leaves the
commerce catalog half-built, which is what starves commerce prompt generation of context.
They are therefore one plan, sliced so each slice ships independently.

### Evidence snapshot

Two crawls of `https://lanhtropy.com/`:

| | crawl A (04:50, cancelled) | crawl B (04:57, kept) |
|---|---|---|
| status | `cancelled` | `partially_completed` / `analysis_incomplete` |
| admitted / analyzed / failed | 500 / 3 / 0 | 500 / 499 / 1 |
| `discover` tasks | 500 (405 done in 7 min) | 1 |
| `analyze` tasks | 500 (3 done in 7 min) | 500 |
| elapsed | 7 min, cancelled | 4 min, complete |

The one failed task in crawl B:

```
requested_url  https://lanhtropy.com/customer_authentication/redirect?locale=en&region_country=IN
status         failed      error_code  ssrf_blocked
error_detail   URL rejected by admission policy: hard_excluded_host
```

One more task in crawl B recorded `crawl_task_lock_conflict` (an asyncpg
`DeadlockDetectedError`) and only succeeded on its second attempt.

Commerce catalog after crawl B: 466 products, 19 categories, and **every real category has
zero products** — all 466 rows sit under a synthetic `/` category. The 19 collection pages
*were* analyzed (`site_page_analyses.page_kind = 'category'`, 19 rows, all `completed`).

The five prompts generated for the `ACCESORIES` category of a linen-fashion brand:

```
best apple watch band for working out, sweat resistant
looking for a good laptop sleeve 14 inch macbook pro
screen protector for samsung s24 ultra with easy installation
cheap wireless earbuds under 30 that don't suck
phone case with magsafe for iphone 15 pro
```

all with `buyer_stage` and `prompt_intent` empty, versus the 20 prompts the visibility path
produced for the same brand, which were correctly about linen dresses, denim and knitwear
with the full buyer-stage taxonomy populated.

---

## Slice 1 — A crawl is always exactly one page short (499/500)

**Root cause.** `classify_url_admission` is applied twice with different inputs, and a URL can
pass the first and fail the second.

1. At discovery, `https://lanhtropy.com/customer_authentication/redirect?...` is admitted. Its
   host label is `lanhtropy` (not in `URL_HARD_EXCLUSION_HOST_LABELS`), its path matches none
   of `URL_HARD_EXCLUSION_PATH_PATTERNS` — `customer_authentication` is not `login`, `account`
   or `auth` — and `locale`/`region_country` are neither tracking nor hard-excluded query
   keys. It counts toward `admitted_url_count`, which is the **denominator** the UI shows
   ([lifecycle.py:265](../../backend/app/domain/site_health/service/lifecycle.py)).
2. At analyze time the fetcher follows the 302 to Shopify's customer-account host. `resolve_target`
   re-runs admission **on every redirect hop**
   ([url_policy.py:615-625](../../backend/app/connectors/web_evidence/url_policy.py)); the
   leftmost label is now `account`, which *is* in `URL_HARD_EXCLUSION_HOST_LABELS`
   ([site_health_crawl_policy.py:86-104](../../backend/app/core/config/site_health_crawl_policy.py)).
   The task fails `ssrf_blocked` — a policy decision, not a transient error, so no retry helps
   and no replacement URL is admitted.
3. `_terminalize_analysis_state` then sees `analyze_succeeded (499) != analyze_applicable (500)`
   and finalizes the crawl `partially_completed` / `analysis_incomplete`
   ([lifecycle.py:205-225](../../backend/app/workers/site_health/lifecycle.py)).

Every Shopify storefront exposes `/customer_authentication/redirect`, which is why this is
exactly one short, every time, forever.

**Changes.**

- Add the Shopify (and equivalent platform) auth-redirect paths to
  `URL_HARD_EXCLUSION_PATH_PATTERNS` in
  [site_health_crawl_policy.py:69-77](../../backend/app/core/config/site_health_crawl_policy.py),
  e.g. `r"(?:^|/)(?:customer_authentication|customer_identity|account_login)(?:/|$)"`. Follow
  the existing convention in that file: the patterns are anchored on path segments, and the
  comment block above the host-label set explains why each entry earns its place — add the
  same for these.
- Make a post-admission policy rejection an **exclusion, not a failure**. When an `analyze`
  task terminates with `ERROR_URL_ADMISSION_REJECTED`, it should leave the crawl's applicable
  set rather than counting as a failed page — so `analyze_applicable` becomes 499 and the crawl
  finalizes `completed`, not `partially_completed`. The natural seam is the analyze outcome
  path in [phases/analyze.py](../../backend/app/workers/site_health/phases/analyze.py) plus the
  `_TaskSummary` that feeds `_terminalize_analysis_state`; a URL rejected by policy is the same
  class of thing as a `page_kind_filtered` exclusion, which the corpus disposition vocabulary
  in `site_health_crawl_policy.py` already models.
- Record the exclusion on the URL so the dashboard can show *why* a page left the set, reusing
  the existing `URL_EXCLUSION_*` reason codes rather than inventing a new vocabulary.

**Also fix here (same file, same failure surface).** The `crawl_task_lock_conflict` deadlock is
already caught and requeued by
[db_conflicts.py](../../backend/app/workers/site_health/db_conflicts.py), so it self-heals — but it
consumes an attempt against `max_attempts`. Confirm a requeue after a transient DB conflict does
not increment `attempt_count`; in the snapshot the task showed `attempt_count 2` for what was
purely a lock collision.

---

## Slice 2 — A crawl almost never works on the first attempt

**Root cause.** Discovery and analysis are separate task kinds on one queue with one priority
scale, and an analyze task cannot run before the discover task for the *same* URL.

- `reusable_discover_artifact` returns `(None, pending=True)` when a `discover` task for the
  same `url_hash` is still active
  ([acquisition.py:52-64](../../backend/app/workers/site_health/acquisition.py)), and the
  analyze phase then **defers**
  ([analyze.py:118-128](../../backend/app/workers/site_health/phases/analyze.py)).
- Deferring sets `available_at = now + analysis_dependency_retry_seconds`
  ([postgres_task_queue.py:365](../../backend/app/orchestration/postgres_task_queue.py)), and the
  claim order is `priority DESC, available_at ASC, randomized_position ASC, id ASC`
  ([site_health_runtime.py:362-370](../../backend/app/core/config/site_health_runtime.py)).
- Discover and analyze for the same URL are created with the *same* `value_priority` and the
  discover row is inserted first, so it always wins the tie. Each deferral pushes the analyze
  row's `available_at` further back — a positive-feedback starvation loop.

That is the 405-vs-3 split in crawl A exactly. The user sees the analyzed counter stuck near
zero for minutes, concludes it is broken, and cancels. On the rerun the frontier resolves
differently (crawl B needed one discover task, not 500), analysis starts within 3 seconds, and
it "works".

The same structure also means **every page is fetched twice** — once by `discover` for its
links, once by `analyze` for its facts — on a single host bounded by
`per_host_concurrency = 6` and `per_host_delay_seconds = 0.15`
([site_health_runtime.py:97-103](../../backend/app/core/config/site_health_runtime.py)).

**Change: fold discover and analyze into a single fetch per URL.**

One fetch yields both outputs. `discover` already writes a `SiteFetchArtifact` with
`normalized_facts` that analyze is *designed* to reuse — `reusable_discover_artifact` is that
reuse path, and it is effectively dead because the ordering never lets it fire productively.
Rather than a second task kind that waits on the first, the discover phase should produce the
page analysis from the artifact it already holds.

- In
  [discover_stages.py:414-459](../../backend/app/workers/site_health/phases/discover_stages.py),
  `_persist_discover_success` already has the artifact, the normalized facts, and the admission
  result in one transaction. Run the analysis projection there, against the same artifact.
- Keep `TASK_KIND_ANALYZE` as the kind for URLs that enter the set *without* a discover pass —
  the monitored/re-seeded set, and `INPUT_MODE_EXACT_URLS` where
  `enqueue_children=False`. In auto mode it should no longer be created per discovered URL.
- `admit_candidates(..., enqueue_children=...)`
  ([frontier.py:141-158](../../backend/app/domain/site_health/frontier.py)) is the single
  place that decides whether a candidate gets a child task; the budget accounting
  (`progress.admitted`) already lives there and must keep counting one unit per admitted URL so
  `admitted_url_count` still means "pages this crawl will cover".
- `_terminalize_analysis_state` and `_partial_reason`
  ([lifecycle.py:175-225](../../backend/app/workers/site_health/lifecycle.py)) currently
  derive analysis state from analyze-task counts. They need to read the merged outcome instead.
  Preserve the discovery/analysis sub-state split in the API — the dashboard renders both — even
  though one task now advances both.
- `analysis_dependency_retry_seconds` and the deferral branch in `analyze.py` become dead for
  the auto path; remove rather than leave them, so the starvation loop cannot come back.

**Guard.** Whatever the final shape, add a regression test asserting that on a cold crawl of N
URLs the analyzed counter is strictly increasing from the first completed task — the property
that was violated, stated directly. The component tests under
`backend/tests/component/` already drive crawls end to end; extend those rather than adding a
new harness.

---

## Slice 3 — Commerce category prompts are for the wrong industry

**Root cause, two layers.**

*Layer 1 — the generator is given almost nothing.* `_target_context`
([prompts.py:45-78](../../backend/app/domain/commerce/prompts.py)) builds the brand, description,
attributes, price and currency keys **only inside `isinstance(row, CommerceProduct)`**. For a
category target the entire user message is:

```json
{"count": 5, "context": {"target_kind": "category", "name": "ACCESORIES", "locale": "en-IN"}}
```

No brand, no vertical, no business context, no member products, not even the category's
`canonical_url` — and `CommerceCategory` has no description column, so `name` really is all
there is. `COMMERCE_BUYER_PROMPT_EXEMPLARS`
([commerce_catalog.py:182-191](../../backend/app/core/config/commerce_catalog.py)) then sets
the register with thermometers, hygrometers, cookware and "works with an iPhone". Given the
bare word `ACCESORIES` and a gadget register, consumer electronics is the modal completion.
(The literal output strings appear nowhere in the repo or its history — this is invention from
an empty context, not example leakage.)

*Layer 2 — there is no product context to pass.* All 466 products sit under the synthetic `/`
category. The commerce projector (`commerce-projector-3`,
[projector.py](../../backend/app/domain/commerce/projector.py)) never populates
`commerce_product_categories` from the 19 analyzed category pages, so even a correct generator
would find zero products for `ACCESORIES`.

*And nothing catches it.* `buyer_prompt_validation.py` enforces survey framing, 4–24 words,
duplicates and repeated openings — all four bad prompts pass every one. `_leaks_owned_identity`
([prompts.py:114-119](../../backend/app/domain/commerce/prompts.py)) protects
`context["brand"]`, which is **always absent on the category path**, so it is a no-op there.
There is no topicality gate at all on the commerce path, while the visibility path has one
that is explicitly bypassed for commerce
([generation.py:703](../../backend/app/domain/prompts/generation.py)).

**Changes.**

1. **Projector — populate category membership.** Make the commerce projector derive
   product↔category edges from the analyzed category pages, so `commerce_product_categories`
   reflects the 19 real collections instead of one `/` bucket. The page analyses carry the
   collection page and its outbound product links; `site_page_link_metrics` already models
   intra-site links per crawl. Bump `COMMERCE_PROJECTOR_VERSION` past `commerce-projector-3`
   ([commerce_catalog.py:10](../../backend/app/core/config/commerce_catalog.py)) so existing rows
   reproject. While here, `role` is `'unknown'` for all 19 categories although
   `COMMERCE_CATEGORY_ROLES` models `hub`/`leaf` — set it, since hub-vs-leaf changes what a
   sensible buyer prompt for that shelf looks like.
2. **Generator — pass real context.** Rewrite `_target_context` so a category target carries
   brand, business context (business model, category, category terms) and the names of its member
   products. `_generation_brand_context`
   ([generation.py:403-431](../../backend/app/domain/prompts/generation.py)) already assembles
   exactly this on the visibility path — reuse it rather than writing a second assembler.
3. **Exemplars — stop anchoring every vertical to gadgets.** Select the exemplar bank per
   business model, mirroring `PROMPT_EXEMPLARS` in
   [visibility_prompts.py:511-551](../../backend/app/core/config/visibility_prompts.py).
4. **Add a topicality gate.** `_topic_is_bound` / `_singular` / `_tokens` in
   [query_patterns.py:255-276](../../backend/app/domain/prompts/query_patterns.py) is the
   existing implementation; call it from `buyer_prompt_validation.py` so a prompt unrelated to
   the target's own vocabulary is rejected. `admitted_buyer_prompts` already returns
   `(texts, rejected)`, so the reason plumbs through unchanged.
5. **Fix `_leaks_owned_identity` for categories** — populate `context["brand"]` on both target
   kinds so the gate actually runs.
6. **Stamp the taxonomy.** Commerce prompts are written with `intent="comparison"` hardcoded and
   `buyer_stage` / `prompt_intent` left empty
   ([prompts.py:172-189](../../backend/app/domain/commerce/prompts.py)), so they sit outside
   the buyer-stage taxonomy this branch just built. Populate them, and set `theme` to something
   readable rather than the raw category name.
7. Bump `COMMERCE_PROMPT_TEMPLATE_VERSION` past `commerce-buyer-prompts-3`.

**Note on the current branch.** `feat/prompt-generation-repair` rebuilt the *visibility*
generator (`buyer-query-patterns` → archetypes, new `portfolio_validation.py`, `GENERATOR_VERSION`
v18 → v19). Its only touch to commerce is a docstring line in `buyer_prompt_validation.py`;
`commerce_catalog.py` and `domain/commerce/prompts.py` are not in the diff. The commerce path
received no functional repair, which is why it still fails while visibility now works.

---

## Slice 4 — "We couldn't finish this setup step just now" on every first project create

**Root cause.** A multi-minute synchronous LLM job behind a 30-second client timeout.

- Every API request is wrapped in `AbortSignal.timeout(getApiRequestTimeoutMs())`
  ([client.ts:104-113](../../frontend/lib/api/client.ts)) and
  `DEFAULT_API_REQUEST_TIMEOUT_MS = 30_000`
  ([operational.ts:19](../../frontend/lib/config/operational.ts)).
- `POST /brand-discoveries/{id}/complete` runs `_generate_confirmed_portfolio` — the entire
  multi-topic prompt portfolio, one LLM call *per topic* (`VISIBILITY_TOPIC_BATCH_SIZE = 1`)
  plus retries plus two named cohorts — **inline in the request**, before the project row is
  written ([service.py:587-625](../../backend/app/domain/projects/onboarding/service.py)).
  The lanhtropy portfolio was 20 prompts across 8 themes; that does not fit in 30 seconds.
- The timeout surfaces as `ApiError { code: 'request_timeout' }` with **no HTTP status**, so
  `onboardingErrorMessage` falls past its 403 and 422 branches to the generic string
  ([forms.ts:94-103](../../frontend/lib/onboarding/forms.ts)).
- The server keeps working after the client aborts. `_completion_replay` matches on
  `input_data["completion_idempotency_key"]`, which is written in the same transaction as the
  project ([service.py:620-625](../../backend/app/domain/projects/onboarding/service.py)) —
  so if attempt 1 did commit, the second click replays instantly and "works"; if it did not,
  the second click re-runs and lands under the wire on a warm provider. Either way the user is
  told it failed when it may well have succeeded.

**Change: make completion asynchronous.** Return immediately with a job identity, generate the
portfolio on a worker, and have the review screen poll — the pattern brand discovery itself
already uses (`brand_discovery_tasks`, `brand_discovery_worker.py`), so reuse that shape rather
than inventing a second one.

- `complete_discovery` splits: a short transaction that validates, claims the idempotency key
  and enqueues; a worker that generates and persists the project.
- The client's `complete` mutation ([onboarding-flow.ts:157-182](../../frontend/components/onboarding/onboarding-flow.ts))
  polls to completion instead of awaiting one long request, reusing `ActivityProgress` — the
  discovery stage already renders exactly this.
- Write the idempotency record when the job is **claimed**, not when it commits, so a retry
  during generation replays instead of starting a second portfolio.

**If the async move is deferred**, the minimum safe stopgap is: claim the idempotency key up
front, and map `code: 'request_timeout'` in `onboardingErrorMessage` to an honest "still
working — checking…" that polls the projects list, since the client already marks that error
`retryable: true` and the generic message is actively misleading.

---

## Slice 5 — One brand's portfolio is almost entirely brand prompts

**Root cause.** The branded cohorts are a fixed count while the organic cohort is not, so when
the organic cohort collapses the fixed prompts become the whole portfolio — and whether it
collapses depends on the brand's own name.

- `_generate_named` always requests `VISIBILITY_BRAND_PROMPT_COUNT = 2` plus, when competitors
  exist, `VISIBILITY_COMPARISON_PROMPT_COUNT = 1`
  ([portfolio_generation.py:333-337](../../backend/app/domain/projects/onboarding/portfolio_generation.py),
  [visibility_prompts.py:213-214](../../backend/app/core/config/visibility_prompts.py)) —
  independent of how many organic prompts survived.
- `brand_terms` bans every distinctive token of the brand name — length ≥ 4, not a generic
  provider word, not in the confirmed category vocabulary
  ([portfolio_validation.py:93-109](../../backend/app/domain/prompts/portfolio_validation.py))
  — and `_name_error` rejects any **core** prompt containing one as `tracked_name`
  ([portfolio_validation.py:198-205](../../backend/app/domain/prompts/portfolio_validation.py)).
- For a brand whose name is ordinary shopping language, that bans ordinary shopping language.
  `TOPICAL_BINDING_STOPWORDS`
  ([prompts.py:89](../../backend/app/core/config/prompts.py)) holds only function words and
  auxiliaries — no "love", "shop", "beauty", "home". For **ilovedooney** the token `love` is
  ≥ 4 chars, is not generic, and is not category vocabulary, so every organic prompt containing
  "love" is rejected. The organic cohort collapses; the fixed 2 + 1 remain.

This is per-brand by construction, which is exactly why only this brand shows it. The failure
mode is already documented in the `brand_terms` docstring — the "Red Dress" case at
[portfolio_validation.py:84-91](../../backend/app/domain/prompts/portfolio_validation.py)
describes it verbatim: *"rejected every organic dress query, emptied the core cohort, and left a
portfolio of nothing but the two mandatory brand-diagnostic prompts."* The `category_vocabulary`
escape hatch added for it does not cover a brand token that is generic English rather than
category language.

**Changes.**

1. **Cap the branded share, not just the count.** Make the named cohorts proportional to what
   the organic cohort actually produced, with the current 2 + 1 as a ceiling — so a portfolio of
   5 organic prompts does not ship 3 branded ones. `_generate_named` receives the validator and
   can read `validator.accepted`; compute the named budget after the core cohort resolves.
2. **Stop banning generic English as a brand token.** Extend the exclusion in `brand_terms`
   beyond `PROVIDER_DESCRIPTION_PHRASES | TOPICAL_BINDING_STOPWORDS` to a common-word list
   (`love`, `shop`, `home`, `best`, `good`, `style`, `beauty`, `world`, `plus`, `care`, `life`…),
   kept in `core/config/` next to the existing vocabularies. The full brand name and its aliases
   stay banned unconditionally, so "I Love Dooney" itself still cannot appear in an organic
   prompt — only the bare word "love" becomes usable again. This is the same "safe direction to
   fail in" the existing docstring argues for.
3. **Pass the aliases.** `_generate_confirmed_portfolio` calls `brand_terms(brand_name, [], …)`
   with an empty alias list
   ([service.py:744-748](../../backend/app/domain/projects/onboarding/service.py)) although
   a `brand_aliases` table exists. Populate it, so short forms are caught by the alias list
   rather than by over-eager token banning.
4. **Surface the collapse.** `core_prompts_empty` and `topic_without_prompts:<name>` warnings
   are already produced
   ([portfolio_generation.py:311-320](../../backend/app/domain/projects/onboarding/portfolio_generation.py))
   and carried on the discovery row. Add a warning when the branded share exceeds a threshold,
   and render these warnings in the review UI — the user should not have to notice this by
   reading the prompt list.

---

## Implementation status

All five slices are implemented on `feat/prompt-generation-repair`. Where the
build departed from the plan, it is noted below.

| Slice | Status | Departure from plan |
|---|---|---|
| 1 — 499/500 | Done | Also split `UrlAdmissionRejected` out of `UrlPolicyError`, so a policy rejection stops being reported as `ssrf_blocked`. `admitted_url_count` stays monotonic (the frontier budget depends on it); the dashboard projection nets exclusions out of both sides instead. |
| 4 — setup step | Done | As planned: completion is queued and the worker generates. Added an advisory occupancy precheck so a full workspace still fails fast with a 403. |
| 5 — brand prompts | Done | As planned, plus the domain label as a brand alias, since freeing "love" would otherwise let "ilovedooney" through. |
| 2 — crawl starvation | Done, **narrower than planned** | See below. |
| 3 — commerce prompts | Done | As planned. |

### Slice 2: what was built instead of a full phase merge

The plan called for folding discover and analyze into one fetch. On reading
the code, `reusable_discover_artifact`
([acquisition.py](../../backend/app/workers/site_health/acquisition.py)) already
implements exactly that reuse — an analyze task reuses the discover artifact
for the same URL and does not re-fetch. The double fetch in the plan's
diagnosis was therefore overstated: the real and only defect was **ordering**.

Two changes fix it without restructuring the phases:

1. **Analyze tasks are created by the fetch, not by admission.** Admission used
   to queue an analyze task for a URL it was simultaneously queuing for
   discovery, so that task woke while its own page was still unfetched,
   deferred, and pushed its `available_at` back — every time. It is now queued
   from the discover task's own persistence transaction
   (`enqueue_analysis_for_discovered_url`), where the artifact is already
   committed.
2. **`ANALYZE_PRIORITY_BOOST`** puts analysis of a page already in hand
   categorically ahead of fetching another one.

Merging the phases outright was left alone deliberately: `_persist_analyze`
owns the membership guard, the page-analysis rows, rule evaluation, issues and
the queue finalize, and the crawl's terminalization counts analyze tasks. The
ordering fix removes the whole starvation class without touching any of that.

**One bug this surfaced:** `_automatic_remaining` spent the frozen page budget
by counting analyze *tasks*. With those created later, the budget read as
untouched and a second admission batch went straight past the limit. It now
counts the membership admission writes, which is what the limit actually caps.

The root keeps its own analyze task rather than waiting for a handover — it is
one page, so it cannot starve anything, and an independent task means a root
whose *discover* fails is still analyzed.

---

## Sequencing

| Order | Slice | Why here |
|---|---|---|
| 1 | Slice 1 (499/500) | Smallest, self-contained, unblocks "crawl completed" as a truthful state |
| 2 | Slice 4 (setup step) | Highest user-visible frequency; independent of the crawl work |
| 3 | Slice 5 (brand-heavy portfolio) | Independent; small config + validator change |
| 4 | Slice 2 (crawl starvation) | Largest blast radius in the crawl worker |
| 5 | Slice 3 (commerce prompts) | Projector fix needs a crawl that actually finishes, so it lands after slice 2 |

---

## Verification

**Slice 1.** Unit-test `classify_url_admission` against
`https://<host>/customer_authentication/redirect?locale=en&region_country=IN` — extend the
existing table at
[test_web_url_policy.py:190-200](../../backend/tests/unit/test_web_url_policy.py), which
already covers the `account.<domain>` hard-host cases. Then crawl a Shopify storefront end to
end and assert the crawl finalizes `completed` with `partial_reason` empty, and that
the dashboard's disclosed `discovered == analyzed` after policy exclusions are
netted out. The raw monotonic `admitted_url_count` still includes the reserved
URL because it remains the frontier's budget ledger.

**Slice 2.** Crawl `https://lanhtropy.com/` cold, from an empty `site_urls`, and watch:

```sql
select event_type, count(*), min(created_at), max(created_at)
from site_crawl_events where crawl_id = '<id>' group by 1 order by 3;
```

The pass condition is `analysis.progress` events beginning within seconds of `crawl.queued` and
rising steadily — not the 405-discovery / 3-analysis split above. Confirm total wall time drops
and that every auto-mode `analyze` task is created only after its matching discover artifact,
then reuses that artifact without another page fetch.

**Slice 3.** After a completed crawl:

```sql
select c.name, count(pc.*) from commerce_categories c
left join commerce_product_categories pc on pc.category_id = c.id group by 1 order by 2 desc;
```

Every real collection must be non-zero. Then click **Generate 5** on `ACCESORIES` and confirm
the prompts are about linen accessories, carry non-empty `buyer_stage` / `prompt_intent`, and
that a deliberately off-vertical prompt is rejected by the new topicality gate. Add a unit test
asserting `_target_context` for a category includes brand and member product names.

**Slice 4.** Create a project through onboarding and confirm the UI never shows the generic
error, that a slow portfolio renders progress rather than failing, and that double-clicking
Create produces exactly one project. Check the discovery row holds
`completion_idempotency_key` and the frozen completion payload before generation finishes, with
exactly one `brand_completion` task for that discovery.

**Slice 5.** Run onboarding for `ilovedooney.com` and inspect:

```sql
select cohort, count(*) from prompts p
join prompt_sets s on s.id = p.prompt_set_id where s.project_id = '<id>' group by 1;
```

`brand_diagnostic` + `comparison` must be a small minority. Add a unit test for `brand_terms`
asserting "I Love Dooney" does not ban the bare token `love`, alongside the existing
"Apollo Hospitals" and "Red Dress" cases the docstring describes.

**Whole-repo.** `backend/tests/unit` and `backend/tests/component` for the crawl, onboarding and
prompt suites; `frontend` tests for `lib/onboarding/forms.test.ts` and the onboarding screen.
`docs/validate_documentation.py` is already in the working diff — run it, since
`docs/backend-architecture.md` describes the crawl phases this plan changes.
