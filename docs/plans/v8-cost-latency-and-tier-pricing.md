# Cost, latency, and four-tier pricing implementation plan

> **Status: DRAFT FOR OWNER APPROVAL.** Prepared 2026-07-30. Supersedes
> [`v5-free-tier-cost-and-latency.md`](v5-free-tier-cost-and-latency.md) in full: there is no Free
> tier, no card-verified funded audit, and no Paid→Base migration. Greenfield — no migration
> compatibility is owed to any current schema or tier vocabulary.
>
> Companion contracts: [`../invariants.md`](../invariants.md),
> [`../backend-architecture.md`](../backend-architecture.md),
> [`../frontend-architecture.md`](../frontend-architecture.md).

## 1. What this plan builds

Two requirements, in dependency order.

**Slice 1 — cost and latency.** Ships first, before any billing work, because tier prices cannot be
set until per-execution cost is measured, and funded execution is priced from that cost.

**Slice 2 onward — four-tier pricing.** No Free tier. A one-week trial of tier 1 replaces it. Four
tiers whose capabilities are composed from grants, so anything expensive becomes an activatable
add-on or top-up rather than a hardcoded tier column.

| | Tier 1 | Tier 2 | Tier 3 | Enterprise |
|---|---:|---:|---:|---|
| List price (placeholder, BYOK baseline) | `$99` | `$199` | `$299` | Contact us |
| Grounded benchmark cadence | weekly | daily | daily | override grants |
| Additional providers (BYOK key) | add-on | included | included | override grants |
| Funded execution | top-up credits | top-up credits | top-up credits | override grants |
| Trial | 7 days free, card required, pulse mode | — | — | — |

**Prices are catalog configuration and deliberately not a focus of this plan** — they change without
code. What has to be right is the architecture that decides what an account may do, and the shape is:
BYOK is the baseline product, and anything that costs CiteLadder money is an activatable add-on or a
metered top-up rather than a tier column
([§4](#4-slice-2--entitlement-architecture), [§5.1](#51-byok-is-the-baseline-funded-execution-is-a-metered-grant)).
Enterprise is a contact form backed by `override` grants, not a separate code path.

## 2. Corrections to the stated approach

Two of the assumptions behind requirement 2 are worth testing before the slice is built around
them, because building on them as stated would under-deliver.

### 2.1 Output length is a real lever but not the biggest one

Your instinct that output drives cost is directionally right and there is a genuine problem to fix
— `max_output_tokens` is currently **4096** ([provider_catalog.py:154](backend/app/core/config/provider_catalog.py#L154)),
far above what any answer needs. But two things make the saving smaller than it looks.

**A cap is a ceiling, not a reduction.** Lowering `max_output_tokens` from 4096 to 600 does not cut
output cost by 85%. It only removes tokens from responses that *would have exceeded 600*. If the
median grounded answer is ~500 tokens, the cap saves close to nothing while truncating the longest
and most citation-rich answers — the ones carrying the most product value. The lever that actually
shortens output is a **concise-answer instruction**, which changes the length *distribution* so the
model writes shorter, with the cap left as a safety ceiling rather than the mechanism. The harness
must measure the current output-length distribution before any cap is chosen.

**This is now measured, not estimated.** A harness ran 11 executions on the repo's pinned Anthropic
route (`claude → anthropic → claude-sonnet-4-6`) across three brand-neutral visibility prompts and
four conditions, recording token classes, wall time, `finish_reason`, search count, citations, and
deterministic brand-mention counts. Medians:

| Condition | Output tok | Input tok | Wall time | Cost/exec | Brands found | Hit the cap |
|---|---:|---:|---:|---:|---:|---:|
| **A** no search, no instruction, `max_tokens=4096` (today's config) | 439 | 19 | 10.5 s | `$0.0066` | 7 | 0/3 |
| **B** no search, **concise instruction**, `max_tokens=4096` | 183 | 48 | 5.3 s | `$0.0029` | 7 | 0/3 |
| **C** no search, no instruction, **`max_tokens=600`** | 386 | 19 | 8.7 s | `$0.0059` | 5 | 0/3 |
| **D** **search on**, no instruction, `max_tokens=4096` | 2,334 | 37,200 | 61.5 s | `$0.1466` | 6 | 0/2 |

Four findings, each of which changes a decision:

1. **The concise instruction is the single best lever, and it is free.** Condition B cut output
   tokens 58%, cost 56%, and latency 49% against the same route — while brand-mention counts held
   or improved (per prompt: 7/4/7 → 7/5/8). A shorter answer is *denser* in named products, because
   the words removed are prose, not brands. This is the rare lever that improves cost, latency, and
   the extraction signal at once.
2. **The hard cap is nearly useless as a cost lever, exactly as predicted.** Condition C saved 12%
   against baseline, and **0 of 3 executions ever reached the 600-token ceiling** — median natural
   output is 439 tokens, so the cap almost never binds. Confirmed: lower `max_tokens` from 4096 as a
   safety ceiling, but do not expect it to save money.
3. **Search is ~95% of the cost of a grounded execution — 51× a concise no-search one.** Grounded
   input context is 37,200 tokens against 19 without search, so input alone is 75% of grounded token
   cost and output only 25%. Per-search fees are on top and not included in these figures. Retrieval,
   not output length and not model tier, is the dominant cost variable.
4. **Reasoning tokens are zero on this route — I was wrong to assume otherwise.** All 11 executions
   returned no thinking blocks: on `claude-sonnet-4-6`, omitting the `thinking` parameter runs
   thinking *off*, so nothing is silently spent. The reasoning risk is therefore **provider-specific,
   not universal** — OpenAI's reasoning models and Gemini's thinking budgets do default on. Verify
   and pin per provider; do not carry a blanket assumption into the config.

Revised lever ranking, measured where marked:

1. **Retrieval on/off** *(measured: 51×)* — the largest single variable by an order of magnitude.
2. **Cadence** *(derived)* — how often a grounded run happens. See
   [§2.3](#23-cadence-is-the-binding-cost-constraint-on-paid-tiers).
3. **Concise-answer instruction** *(measured: −56% cost, −49% latency, mentions preserved)*.
4. **Repetitions** — direct linear multiplier; see [§3.6](#36-repetitions-are-a-cost-quality-dial-not-just-a-cost-dial).
5. **Model tier** — still a real multiplier on every token line, but subordinate to retrieval; and it
   carries the validity cost in [§2.2](#22-cheapest-model-from-every-provider-collides-with-measurement-validity).
6. **Batch API for scheduled runs** — roughly 50% off token components, no user-visible latency cost.
7. **Search depth / call count** — 2–3 searches per grounded execution were observed; fewer means
   less grounded context as well as fewer fees.
8. **Prompt caching** — the concise instruction is identical across every prompt and provider, but at
   48 input tokens it is far below the cacheable minimum. **Not worth doing** — a measurement that
   removed work from the plan.
9. **Output ceiling** *(measured: 12%)* — a safety rail, not a saving.

Requirement 2 led with lever 9 and filed lever 5 under latency. The measured answer is that lever 1
dominates and lever 3 is the cheapest real win.

### 2.2 "Cheapest model from every provider" collides with measurement validity

This is the one place I'd push back hardest, because it is a product-integrity question rather than
a tuning question.

CiteLadder's claim is that it measures what answer engines say about a brand. That claim holds only
if the model measured resembles the model real users are served. Measuring with a cheap API model
and reporting the result as "what ChatGPT says about you" is not a cost trade-off — it invalidates
the number the customer is buying. It also collides with invariant 10, which pins one approved
route per engine specifically so results are comparable and provenance is unambiguous.

There is, however, a version of your instinct that is not just defensible but *more* accurate: most
consumer answer-engine traffic is served by the default or free-tier model, not the flagship. If a
provider's cheap API model is the same model that provider serves to typical users, then measuring
with it is closer to reality than measuring with the flagship — and it is cheaper and faster.

So resolve it by verification rather than by assumption. For each provider, Slice 1 determines which
API model best represents what a typical user is served, and that becomes the measurement route
regardless of whether it is the cheapest or the most expensive. Where the representative model is
expensive, use a two-mode design:

| Mode | Model | Frequency | Purpose |
|---|---|---|---|
| `pulse` | Cheap, fast route | Daily | Trend direction, change detection |
| `benchmark` | Representative route | Weekly / monthly by tier | The number quoted as the customer's visibility |

Never mix modes inside one trend series; partition trends by mode, model identity, and retrieval
setting. Benchmark frequency then becomes a natural tier axis, and the UI must label which mode
produced any given figure. What is not acceptable is quietly measuring with a cheap model and
presenting it as the engine's answer.

### 2.3 Cadence is the binding cost constraint on paid tiers

This is the most consequential number the harness produced, and it lands directly on the pricing in
requirement 1. At the measured `$0.1466` per grounded execution, provider cost per project per month
for 10 prompts across 3 providers is:

| Shape | Executions/month | Provider cost/month |
|---|---:|---:|
| **Daily grounded** (search on, every day) | 900 | **`$131.95`** |
| Weekly grounded | 120 | `$17.59` |
| Daily concise no-search | 900 | `$2.60` |
| **Daily pulse + weekly benchmark** | 1,020 | **`$20.20`** |

**Daily search-grounded monitoring costs more in provider spend than the entire proposed `$99` list
price.** Three consequences:

- **A funded (non-BYOK) tier cannot offer daily grounded runs at any of `$99`/`$199`/`$299`.** It
  would sell a dollar for eighty cents. Either the funded tiers run the pulse/benchmark split, or
  funded execution is not offered at these prices at all.
- **The two-mode design from [§2.2](#22-cheapest-model-from-every-provider-collides-with-measurement-validity)
  is now a cost necessity, not just a validity one.** Daily pulse plus weekly benchmark costs
  `$20.20`/month — roughly 80% gross margin on a funded `$99` tier, with room for the add-on
  providers. Two independent arguments now converge on the same architecture, which is the strongest
  signal in this document.
- **Cadence, not prompt count, is the number to tier on.** Doubling prompts doubles cost linearly;
  moving one project from weekly to daily benchmark multiplies it by seven. Price the cadence.

These figures are the Anthropic leg only. Confirm OpenAI and Google before finalising, and add
per-search fees — but the ratio between shapes will hold, because it is driven by retrieval volume
rather than by any one provider's rate card.

## 3. Slice 1 — cost and latency

### 3.1 The harness ships before any optimisation

Nothing in this slice can be chosen without measurement: not the model per provider, not the output
cap, not the concise instruction wording, not the concurrency limits, and not the tier prices that
depend on all of them. Build the measurement harness first.

The harness runs a fixed, non-sensitive prompt set (10–20 prompts) across the full matrix of
candidate routes × search on/off × reasoning effort × output treatment × repetition count, and
records per execution:

- uncached input, cached input, output, and **reasoning tokens as a separate field**;
- search/tool call count and per-call fees;
- wall time, time to first token, and queue wait;
- `finish_reason` — the **canonical** termination reason, normalised across providers, and the only
  field any gate or report reads (specifically the share terminating on a length limit). The raw
  provider value is preserved separately as untyped metadata on the artifact — Anthropic calls it
  `stop_reason`, other providers name it differently, and none of those names may leak into a gate;
- resulting mention count, citation count, and extracted queries;
- provider-reported cost where available.

Two outputs gate everything downstream: a per-route cost table, and the **output-length
distribution** that determines whether a cap is worth anything.

### 3.2 Cost work

- Add a config-owned pricing catalogue: uncached input, cached input, output, **reasoning**, and
  per-search rates per route, with currency, effective date, and a pricing version. Missing usage
  yields `unknown`, never zero.
- Extend the existing artifact-derived `ExecutionCostProjection` to carry reasoning tokens and
  search charges as separate lines, referencing its `RawResponseArtifact`, attempt count, pricing
  version, and formula version. Repricing creates a new projection row rather than mutating one
  (invariant 3).
- Add a **separate** config-owned expected-cost-per-execution figure per route, used only for
  budget admission control and pricing decisions. The artifact-derived projection is post-hoc by
  design and therefore structurally cannot gate anything before execution. Keep the two numbers in
  different places so an estimate can never be mistaken for a measurement.
- Add `reasoning_effort` to the route config and pin it to minimum on all routes. Disqualify any
  route where effort cannot be pinned from cost-sensitive use.
- Replace the blanket 4096 ceiling with a per-mode output policy: concise-answer instruction plus a
  ceiling chosen from the measured distribution.
- **Do not implement prompt caching.** The shared concise instruction measures ~48 input tokens,
  far below every provider's minimum cacheable prefix, so a breakpoint would never produce a hit.
  Revisit only if the instruction grows past the smallest supported minimum — this is a measurement
  that removed work rather than added it, and it matches `Prompt caching — do not implement` in
  [§11](#11-config-keys-and-proposed-defaults).
- Implement batch submission for scheduled runs, behind a flag, only where the batch payload
  preserves search events, citations, usage, and per-item error reporting identically to the
  synchronous path. If it does not, keep the route synchronous — a cheaper number is not worth
  losing citation fidelity.

### 3.3 Latency work

Ranked by expected effect on wall-clock time for one audit:

1. **Concurrency within an audit.** This dominates everything else. Thirty executions run serially at
   the measured 5.3 s each is 159 s; at six in flight it is ~27 s. Workers must hold N tasks in
   flight with asyncio, bounded by per-transport and per-connection semaphores.
2. **Retrieval on/off** — measured at 61.5 s grounded against 5.3 s concise no-search on the same
   route. Retrieval is the dominant latency variable as well as the dominant cost one, which is why
   the trial must be a no-search mode to hit any sub-minute target.
3. **The concise-answer instruction** — measured at −49% wall time (10.5 s → 5.3 s), on top of its
   −56% cost effect. The same single change serves both goals.
4. **Reasoning effort pinned low, where the provider defaults it on** — worth 10–30 s on a reasoning
   route, but measured at **zero** on Anthropic (thinking is off unless requested). Verify per
   provider rather than assuming.
5. **Tail control — and retries are billable executions.** Measured spread was 5.3 s median against
   10.8 s max on pulse, and 61.5 s median against 74.3 s max on grounded. A bounded timeout with a
   retry beats waiting on the tail, but a retry is a *second provider call*, so it cannot be added
   without settling the accounting first:
   - **Config-owned attempt limit** per route (`max_attempts`, already an audit-config field), so the
     worst case is bounded and knowable rather than emergent.
   - **Reserve funded credits for the maximum attempts, not the first one.** Reserving one credit and
     retrying twice oversells the budget; reserve `max_attempts`, then release the unused reservation
     when the execution terminates. Admission control must gate on the worst case
     ([§8.1](#81-the-audit-is-an-llm-proxy-unless-it-is-constrained)).
   - **Every attempt gets its own `ConsumableLedger` row**, keyed by `(task_id, attempt)`, so the
     ledger explains a multi-attempt execution instead of hiding it behind one debit.
   - **Decide per provider whether a timed-out attempt is charged.** A client-side timeout does not
     cancel server-side generation: the provider may bill tokens CiteLadder never received. Until that
     is confirmed per provider, treat a timed-out attempt as **billable** — the conservative
     assumption — and record it as such.
   - Set per-route timeouts from measured p95, not from a guess.
6. **Search depth** — 2–3 searches per grounded execution were observed; fewer means fewer round
   trips and less context to process.
7. **Perceived latency.** Stream per-provider results into the run view as they land so a 40-second
   audit feels responsive. This is frontend work with a large subjective payoff and no backend cost.

### 3.4 Two credential pools with different limits

This distinction must exist in the design from the start. Funded execution runs on CiteLadder's own
keys, so the rate limit is **global and shared across every concurrent customer**. BYOK execution
runs on the customer's key, so the limit is per tenant and does not contend.

Treating them as one pool fails at exactly the wrong moment — a launch spike or a trial rush — and
produces 429s rather than slow responses. The design needs:

- a global concurrency and rate budget for the funded pool, separate from BYOK;
- a per-account fair share inside the funded pool so one audit cannot monopolise it;
- pacing sized to CiteLadder's own documented provider limits, not the customer's;
- 429 backoff applied to the pool rather than to the individual audit; and
- an honest queued state surfaced to the user when the funded pool is saturated, rather than an
  audit that appears hung.

BYOK also means the latency SLO cannot be guaranteed on BYOK accounts, since their key's limits are
theirs. Disclose that in the BYOK settings copy.

### 3.5 Worker architecture

Keep the Postgres queue with `FOR UPDATE SKIP LOCKED`, leases, heartbeats, and the sweeper — it
satisfies invariant 8 and needs no replacement. Changes required:

- **In-flight concurrency.** Claim and execute up to N tasks concurrently per worker, with the claim
  committed before any network I/O (invariant 8) and a semaphore per `(transport, connection)`.
- **Rate limiting without Redis.** Hold token-bucket state in a Postgres table with row locking.
  Adequate at this scale and it keeps the no-Redis constraint intact.
- **Horizontal scaling.** Currently blocked on cross-process capacity coordination. The Postgres
  token bucket removes that blocker, so multiple worker replicas become safe. Until it lands, keep
  a single replica.
- **DB pool guard.** Concurrency multiplied by queries per task must not exhaust the connection
  pool. Size the pool from the concurrency ceiling and assert the relationship at startup.
- **Cooperative cancellation** stays as-is (invariant 9): stop at the execution boundary, no
  mid-call kills.

### 3.6 Repetitions are a cost-quality dial, not just a cost dial

Answer-engine responses are non-deterministic, and the harness measured it directly: on the same
prompt under the same condition, brand-mention counts moved between 4 and 7 across runs. That is the
noise floor of a single repetition, and it is large relative to any real week-over-week movement a
customer would care about. One repetition per day is the cheapest option and also the noisiest — a
customer's daily score will move for no reason, which reads as a broken product and generates support
load and churn. Higher repetitions cost linearly more and are the only way to reduce that variance.

**Decided: daily cadence, with smoothing mandatory.** Daily grounded benchmarks are viable because
BYOK is the baseline — the customer's key pays for execution, so CiteLadder's marginal cost is
infrastructure only. It is only *funded* daily benchmarking that does not clear
([§2.3](#23-cadence-is-the-binding-cost-constraint-on-paid-tiers)), and funded accounts buy
top-up credits at real cost, which prices itself correctly without a special case.

The measured noise floor makes smoothing non-optional rather than a nice-to-have: at one repetition,
mention counts moved between 4 and 7 on the same prompt under identical conditions. Publishing a raw
daily figure would show customers a 40% swing that means nothing. So:

- report a rolling trend (7-day) as the headline, not the single most recent day;
- de-emphasise single-day figures in the UI and label them as one sample;
- keep repetitions as an add-on axis for customers who want a tighter confidence interval on the
  headline number.

Daily cadence itself is an add-on grant
([§4.4](#44-included-versus-add-on)), so the frequency a customer gets is a
commercial choice rather than a hardcoded product constant.

### 3.7 Slice 1 exit gates

The Anthropic leg of the first three gates is **done** — see
[§2.1](#21-output-length-is-a-real-lever-but-not-the-biggest-one). The remaining work is repeating it
on OpenAI and Google, adding per-search fees, and the concurrency and pool gates.

- Per-route cost table published, with reasoning and search as separate lines. *(Anthropic done.)*
- Measured output-length distribution published, and the cap chosen from it rather than assumed.
  *(Anthropic done: median 183 concise / 439 unconstrained / 2,334 grounded.)*
- Mention and citation extraction statistically equivalent to the uncapped baseline — the cap must
  not silently degrade the product. Measure against **uncapped** output as ground truth; comparing
  two capped runs is circular.
- Representative model per provider determined and documented, with the evidence for why it
  represents what users are served.
- Cost per execution and cost per audit known for every mode, funded and BYOK.
- Audit wall-time p95 measured per mode at target concurrency.
- No provider calls from any read path (invariant 7) — a regression gate.

Only after these gates is funded execution priced.

## 4. Slice 2 — entitlement architecture

This is the core of the build. Prices are configuration and will change; the architecture that
decides *what an account may do* is what has to be right, because every other slice reads from it.

### 4.1 Entitlements are composed from grants, not looked up by tier

The wrong shape — and the shape the previous revision had — is a table of per-tier limits that
service code consults by `tier_key`. Every new add-on, promotion, enterprise exception, or
grandfathered account then needs a new column or a special case, and the commercial vocabulary
leaks into domain code.

The right shape is a **grant algebra**. An account holds a set of immutable grants; the effective
entitlement is a deterministic fold over the active ones. A tier is just the grant bundle a
subscription happens to issue.

```text
effective_entitlement(account, at) = fold(active_grants(account, at))

grant sources, in ascending precedence:
  plan     — issued by the subscription tier, resets each period
  addon    — issued by an active recurring add-on, resets each period
  topup    — issued by a one-time purchase, does not reset, expires at
             min(purchased_at + topup_credit_valid_days, subscription_end) — see §4.3
  trial    — issued once, expires on a deadline or on exhaustion
  override — enterprise or support action, audited, arbitrary
```

`AccountGrant` is append-only: UUID, billing account, `source_kind`, `source_ref` (the subscription,
add-on subscription, or payment that created it), `key`, `value`, period bounds, `valid_from`,
`valid_until`, catalog revision, idempotency key, timestamps. **Capability never changes except by
writing a row — never by updating one.**

That rule has to hold for revocation too, which is where an append-only design usually breaks.
Cancelling an add-on or clawing back a grant **must not update the original row's `valid_until`**:
doing so rewrites history and makes past-instant replay wrong. Instead write a **`GrantRevocation`**
row referencing the target grant with its own `effective_from`, reason, and actor. The resolver treats
a grant as active at `at` only when no revocation for it is effective at `at`. The original grant is
never touched, so replaying any past instant still yields exactly what the account could do then —
which is the entire point of the model, and what makes a billing dispute answerable.

### 4.2 The capability registry — every key declares its own composition rule

The one design decision that keeps this flexible instead of turning into a mess: composition is not
one global rule. Each key declares its own type and resolution strategy in a config-owned registry
(invariant 1), and the resolver is generic over that registry.

| Type | Resolution | Enforcement | Examples |
|---|---|---|---|
| `flag` | **OR** — any grant enabling it wins | presence check | `fanout`, `provider.grok`, `exports` |
| `counter.occupancy` | **SUM** | `COUNT(*)` against current rows at mutation time | `project_slots`, `prompt_slots`, `monitored_urls` |
| `counter.consumable` | **SUM** | reservation ledger, decremented on spend | `benchmark_credits`, `pulse_credits` |
| `counter.rate` | **SUM** | count of actions inside a declared rolling window | `manual_runs_per_day` |
| `level` | **MAX** by declared ordering — never summed | comparison | `history_window`, `benchmark_cadence`, `support_tier` |

Three consequences worth being explicit about, because getting any of them wrong produces a subtly
broken product:

- **Levels must not sum.** Two grants of "90-day history" are not 180 days. `history_window` and
  `benchmark_cadence` are ordered enums resolved by maximum; only counters add.
- **Occupancy is not metering.** Project slots, prompt slots, and monitored URLs are answered by
  counting existing rows at the moment of a mutation. They need no ledger, no reservations, and no
  period accounting — which removes most of the machinery the previous revision proposed.
- **Only consumables need a ledger**, and only where CiteLadder funds the spend. At the measured
  `$0.1466` per grounded execution, benchmark credits are the one thing genuinely worth metering
  atomically.
- **A rate limit is its own type, not a consumable.** `manual_runs_per_day` resets on a rolling window
  and is never purchased, reserved, or carried forward, so it fits neither occupancy (which counts
  live rows and never resets) nor consumable (which needs a ledger and a spend order). `counter.rate`
  declares its window in the registry — `manual_runs_per_day` uses a rolling 24 hours, counted from
  audit-creation timestamps, with no ledger.

Adding a product capability is then: one registry entry, one catalog entry, zero domain-code
changes. That is the flexibility requirement 2 is asking for.

### 4.3 Credit lifetime and spend order

**Top-up credits expire.** Validity is:

```text
valid_until = min(purchased_at + 1 month, subscription_valid_until)
```

Two consequences the implementation has to get right:

- **`subscription_valid_until` moves.** Cancellation shortens it, renewal extends it. So the grant
  cannot store a frozen timestamp and walk away — either recompute the effective expiry at resolve
  time as `min(fixed_one_month, current_subscription_end)`, or re-stamp affected grants on every
  subscription lifecycle event. Recomputing at resolve time is fewer moving parts and cannot drift;
  the resolver is already pure over `(grants, registry, at)`, so the subscription end is just another
  input to the fold.
- **Credits are forfeit on cancellation.** That is a chargeback surface if it is buried, so it belongs
  in the purchase confirmation copy, on the usage screen next to each credit balance, and in a warning
  before expiry — not only in terms of service.

**Spend order is earliest-expiring-first**, not source-ordered. The previous revision said "spend the
perishable plan allowance first, then top-ups, which never expire" — that rule is wrong now that
top-ups have a one-month life, because a credit pack bought on the 20th expires *before* a plan
allowance that resets on the 1st. Draining the plan allowance first would burn a paid credit for
nothing.

```text
sort active grants for the key by EFFECTIVE valid_until ascending
  → draw from the soonest-to-expire first
  → on exact ties only, order by source: trial → plan → addon → override → topup
  → final tie-break on grant id, so the order is total and reproducible
```

The tie-break ordering is deliberate and complete: trial credits are worthless once the trial ends,
plan and add-on allowance is free and perishable, `override` grants are goodwill rather than purchased,
and **`topup` is always last on a tie because it is the only kind the customer paid cash for.** Naming
every `source_kind` matters — an ordering that omits `trial` or `override` is non-deterministic in
exactly the cases a billing dispute will ask about.

Earliest-expiry-first generalises the old rule rather than replacing it: when top-ups genuinely never
expired, they sorted last automatically. The resolver returns the ordered grant IDs to draw from, and
the ledger records which grant each reservation drew against, so a usage screen or invoice can always
explain where a credit went and when the rest of them die.

### 4.4 Included versus add-on

The measurements decide this cleanly: **include what is cheap and defines the product; meter what
multiplies cost.** From [§2.1](#21-output-length-is-a-real-lever-but-not-the-biggest-one) and
[§2.3](#23-cadence-is-the-binding-cost-constraint-on-paid-tiers), grounded benchmark frequency is the
only thing that scales cost steeply — so it is the primary metered axis and nearly everything else can
be generous.

Placeholder shape at `$99` / `$199` / `$299`, all values configuration:

| Key | Type | Tier 1 | Tier 2 | Tier 3 | Available as add-on |
|---|---|---|---|---|---|
| `pulse_cadence` | level | daily | daily | daily | — (cheap, always included) |
| `benchmark_cadence` | level | weekly | daily | daily | **yes — the main add-on axis** |
| `benchmark_credits` | consumable | small | medium | large | **yes — one-time top-up packs** |
| `project_slots` | occupancy | 1 | 3 | 10 | yes |
| `prompt_slots` | occupancy | 10 | 30 | 60 | yes |
| `monitored_urls` | occupancy | 50 | 150 | 400 | yes |
| `history_window` | level | 90d | 12mo | 24mo | yes |
| `fanout` | flag | — | yes | yes | yes |
| `provider.{grok,perplexity}` | flag | — | yes | yes | **yes — BYOK, so near-zero cost** |
| `provider.copilot` | flag | — | — | — | **not issuable** — catalog-only, no adapter ([§6.1](#61-copilot-is-listed-but-ships-last)) |
| `manual_runs_per_day` | `counter.rate` (rolling 24h) | 3 | 6 | 12 | yes |
| `exports` | flag | yes | yes | yes | — |

Two notes on the economics rather than the prices. Extra providers are BYOK
([§6](#6-slice-4--additional-providers)), so their marginal cost to CiteLadder is infrastructure only —
they can be cheap unlocks and are a good low-friction upsell. Benchmark cadence is the opposite: one
project moving from weekly to daily multiplies grounded spend sevenfold, which is exactly why it
belongs behind a metered add-on rather than inside a tier.

### 4.5 Fail-closed resolution

Resolution must never fall back to a *funded* profile. If an account's grants cannot be resolved —
corrupt tier key, missing catalog revision, unreadable subscription — return an explicit
**no-capability** entitlement that grants nothing and funds nothing, surface
`entitlement_unresolved`, and alert operators. A lookup miss is data corruption, not a reason to
quietly hand out spend.

Resolution is deterministic and pure over `(grants, revocations, registry_revision,
subscription_end, at)` — and the cache key must cover **every one of those inputs**, or a cancelled
subscription keeps serving capability it no longer has.

```text
cache key = (account_id, registry_revision, subscription_lifecycle_version, validity_window)
```

- **`subscription_lifecycle_version`** is bumped on every subscription state change. It is in the key
  because effective credit expiry is `min(fixed, subscription_end)`
  ([§4.3](#43-credit-lifetime-and-spend-order)), so cancellation changes the answer without touching
  a single grant row — invalidating only on grant write would miss it entirely.
- **`validity_window`** is not the billing period. It is the interval to the next instant any input
  changes: the earliest upcoming `valid_from`, `valid_until`, revocation `effective_from`, or period
  boundary. Caching for a whole billing period is wrong because a grant can expire mid-period; the
  entry must not outlive the next boundary.
- Invalidate on: grant write, revocation write, registry revision change, and **any subscription
  lifecycle event** (cancel, renew, payment failure, reactivation).

No provider calls, and no clock reads inside the fold beyond the passed-in `at`.

### 4.6 Enterprise is a placeholder

Enterprise is a marketing tier that routes to a contact form. It has no operative capability profile,
no plan grants, and no checkout path. When enterprise deals close, they are served by
`override` grants against a real account — which the grant algebra already supports without new
machinery, and which is exactly why the algebra is worth building now.

### 4.7 Trial

The trial is a **platform overview**, not a rigorous measurement — so it runs pulse mode
([§2.2](#22-cheapest-model-from-every-provider-collides-with-measurement-validity)): no search,
concise answers, measured at `$0.087` for a 30-execution audit and roughly 27 seconds wall-clock at
six-way concurrency.

Mechanically it is just another grant: `source_kind = trial`, a small `pulse_credits` allowance, one
`project_slot`, `benchmark_cadence` unset, expiring on a deadline or on exhaustion. No separate trial
subsystem, no special-case code path — which is the payoff of the grant model.

- **Front-load the value.** Run the audit immediately on trial start rather than waiting for a
  schedule, so there is a real artifact within a minute.
- **Set expectations honestly.** The trial shows model-knowledge results with no citations. Label it
  as such, and state plainly that grounded benchmark numbers will differ — otherwise the first paid
  report reads as a regression.
- **Abuse controls** in [§8.2](#82-trial-abuse). At `$0.087` a farmed trial is cheap but not free;
  bound it.

**Card required, one free week.** The trial is a standard subscription trial on the payment
provider — a trial period on the subscription, not a zero-amount authorisation — which is why it
carries no exotic-payment-flow risk. It auto-converts on day 8 unless cancelled, with reminders on
days 5 and 6, and days-remaining always visible in-app.

A pre-generated sample report remains worth building for anonymous visitors: it costs nothing, needs
no grant, and serves the "just show me the platform" need without spending a trial.

## 5. Slice 3 — BYOK and funded execution

### 5.1 BYOK is the baseline; funded execution is a metered grant

The originally intended mechanic was "BYOK shaves `d`% off the list price." The measurements break
that formulation: at daily-grounded cadence provider cost is `$131.95` per project per month
([§2.3](#23-cadence-is-the-binding-cost-constraint-on-paid-tiers)), so a discount bounded by
`provider_cost / list_price` would exceed 100% — the arithmetic tells you to give the plan away and
pay the customer. That is a signal the model is upside down, not a number to round down.

In the grant architecture this resolves itself. **BYOK is the baseline product; funded execution is a
consumable grant you sell on top.** Two prices, kept deliberately separate in the catalog so neither
can be derived from the other by accident:

```text
credit_price(cadence)      = measured_provider_cost(cadence) × (1 + margin)   # the funded add-on
total_funded_price(tier)   = base_price(tier) + credit_price(cadence)          # what a buyer pays
```

`base_price` is the subscription: platform, storage, scheduling, evidence, everything that costs
CiteLadder money regardless of whose key runs the execution. `credit_price` covers provider spend and
nothing else. A BYOK customer pays `base_price`; a funded customer pays `total_funded_price`.

**Both the BYOK toggle and checkout must derive from these two catalog values**, never from a
provider-cost-only figure — quoting `credit_price` alone as "the funded price" would omit the
subscription and undercharge every funded account
([§7.1](#71-pricing-page-and-the-byok-toggle)).

Otherwise it is one execution path differing only in which `credential_source` the planner resolves —
no separate funded product, and no discount arithmetic that can invert.

### 5.2 Credential resolution

- `ProviderConnection` gains `credential_source = byok | platform`. Platform keys are ordinary
  Fernet-encrypted connection rows in a reserved system workspace, seeded from deployment secrets in
  a provisioning path — never read from env inside the connector. One resolution path, existing
  redaction coverage, and a funded audit freezes a real `connection_id` like any other.
- The planner picks BYOK when a valid key exists for the logical source, otherwise draws a funded
  credit if the account holds one, otherwise fails with `execution_credentials_unavailable`. That
  precedence is config-owned, not hardcoded.
- **Key failure must not silently become funded spend.** If a BYOK key fails, pause that provider and
  notify; do not transparently fall back to platform credentials. Silent fallback is the one path
  that loses money invisibly.
- Provider Settings shows per-provider `connected | missing | failed | unavailable` with the safe
  reason and last probe time. Keys are Fernet-encrypted, resolved at execution time only, and never
  in a DTO, log line, request snapshot, or artifact (invariant 6).
- BYOK accounts get a clear notice that the latency target is not guaranteed on their own keys, since
  their key's rate limits are theirs.

### 5.3 Top-up API

Uniform surface over the catalog, so the frontend needs no per-add-on code:

```text
GET    /api/v1/billing/catalog          plans, add-ons, top-up packs, with resolved prices
GET    /api/v1/billing/entitlement      effective entitlement + per-key grant provenance
GET    /api/v1/billing/usage            per-key allowance / consumed / remaining / reset
POST   /api/v1/billing/addons           activate a recurring add-on
DELETE /api/v1/billing/addons/{key}     schedule deactivation at period end
POST   /api/v1/billing/topups           purchase a one-time pack
```

Rules that make this safe:

- **Idempotency is mandatory** on both mutating endpoints — client-supplied `Idempotency-Key`, stored
  with the response, replay returns the original result. Payment retries and double-clicks are the
  normal case, not the edge case.
- **The browser submits only a catalog key and quantity.** The server resolves region, currency,
  amount, provider, and external plan ID. Never trust a client-supplied price.
- **Grants are created from verified provider webhooks**, not from the checkout response — the
  webhook is the only authority that money moved. Webhook handling is idempotent on event ID.
- **There is an explicit `pending` state, because the webhook is not instantaneous.** Checkout writes
  a `PendingActivation` row (catalog key, quantity, idempotency key, `status`, expiry) and returns it.
  The state machine is narrow on purpose:

  ```text
  pending --(verified webhook: paid)------> activated   [writes the AccountGrant]
  pending --(verified webhook: failed)----> failed
  pending --(expiry with no webhook)------> abandoned   [reconciliation]
  ```

  **A pending row grants nothing.** It exists for status visibility — the UI shows "payment
  processing" instead of a silent nothing — and so reconciliation has something to find. Entitlement
  begins only when a verified payment writes the grant.
- **Reconciliation covers the missed-webhook case**, which will happen. A periodic job polls the
  provider for pending intents older than a config-owned threshold and settles them from the provider's
  own record, writing the grant if payment in fact succeeded. Reconciliation is idempotent against the
  same `IdempotencyRecord` as the webhook path, so a late webhook and a reconciliation sweep racing on
  the same intent produce exactly one grant.
- **Activation is immediate on payment confirmation; deactivation is at period end.** Mid-cycle
  activation prorates through the payment provider, and entitlement takes effect on grant write —
  which is when the money is confirmed, not when the browser returns from checkout.
- Billing-owner authorization on every mutation; workspace membership for reads of project data.

## 6. Slice 4 — additional providers

**Grok and Perplexity** ship as **BYOK key-addition unlocks**: the customer pastes an API key, a
`provider.grok` or `provider.perplexity` flag grant enables the source, and the catalog exposes it.
Because the customer's key pays for execution, CiteLadder's marginal cost is infrastructure only —
cheap unlocks and a low-friction upsell.

**Copilot is catalog-only and explicitly unavailable.** It is listed because the market names it, but
it has no adapter, accepts no API key, and **no `provider.copilot` grant is issuable** until a real
API exists ([§6.1](#61-copilot-is-listed-but-ships-last)). Attempting to activate it returns
`provider_unavailable`.

Each shippable provider still needs a real adapter before it can be sold, and ships independently only
after contract tests prove exact model and endpoint, customer-key support, search/citation/query
semantics including the empty-search case, usage reporting, truncation, authentication, timeouts, 429
and partial-failure behaviour, rate limits, and a safe key probe.

**Cost and latency scale linearly with provider count.** Ten prompts across six providers is 60
executions per run, not 30. At the measured grounded figure that is `$8.80` per run rather than
`$4.40`, and the concurrency budget in
[§3.4](#34-two-credential-pools-with-different-limits) must account for the higher ceiling. On BYOK
the money is the customer's, but the queue time is yours.

### 6.1 Copilot is listed but ships last

**Decided: Copilot is named in the catalog because the market names it — competitors list it, so its
absence reads as a gap — but it ships after Grok and Perplexity.** The naming is right: customers
recognise "Copilot", not "Microsoft", and the capability key is `provider.copilot`.

What it cannot be is silently backed by the wrong thing. Grok/xAI and Perplexity both expose real
APIs with live search, so "paste an API key" works exactly as described. Copilot does not:

- **Azure OpenAI** takes an API key, but it serves *GPT models* — it is not Copilot. Measuring Azure
  OpenAI and reporting the result as Copilot would tell a customer what Copilot says about them when
  it does not, and it is largely redundant besides: the same GPT family the ChatGPT route already
  covers.
- **Consumer Copilot** has no official customer-authenticated API that reproduces the answer a real
  user sees, with its citations.

So Copilot stays in the catalog as an **unavailable** source with a truthful state until an API exists
that reproduces Copilot answers. The provider catalog already carries `availability` and a safe reason
per source, and Provider Settings already renders `connected | missing | failed | unavailable` — so
listing it costs nothing and needs no placeholder adapter. When the API lands, it is one registry
entry and one adapter.

Two rules while it is unavailable, both because this is a measurement product and the number is the
product:

- **Never route Copilot to an Azure OpenAI deployment as a stand-in.** If that ever becomes desirable,
  it ships as its own source labelled "Azure OpenAI", never under the Copilot name.
- **Public pricing and marketing may name Copilot only with an explicit coming-soon state.** An
  unqualified Copilot logo beside three working engines is a claim of support.

**Marketing gate.** `frontend/public/brand/grok.webp` and
`frontend/components/marketing/landing/rotating-engine-logos.tsx` are already present and untracked
on this branch. A provider logo on the landing page is a claim of support. Gate the logo behind a
shipped adapter, or label it explicitly as coming soon.


## 7. Slice 5 — frontend and landing

All pricing and plan content stays centralised in
[frontend/lib/marketing-content/pricing.ts](frontend/lib/marketing-content/pricing.ts) and is
consumed from there by every surface, with the backend catalogue as the source of truth for anything
enforceable. No hardcoded prices or limits in components (invariant 1).

### 7.1 Pricing page and the BYOK toggle

The BYOK toggle is a first-class element of the pricing page, not a settings-screen detail. It is a
real differentiator — most competitors do not offer BYOK at all — and it self-selects technical
buyers who convert well and cost nothing to serve.

**Toggle direction: default to the funded price, and let BYOK bring it down.** This matters, because
the measured economics
([§5.1](#51-byok-is-the-baseline-funded-execution-is-a-metered-grant)) fix the two prices relative to
each other — BYOK shows `base_price(tier)` and funded shows
`base_price(tier) + credit_price(cadence)`, both read from the catalog — so only the presentation is a
choice. Showing the base price first and having the toggle *raise* it reads as a
penalty; showing the funded price first and having BYOK *lower* it reads as a saving, animates
downward, and matches how a buyer thinks about bringing their own keys. Same numbers, better framing.

| Toggle | Headline price | What the buyer is told |
|---|---|---|
| Off (default) | funded = base + uplift | "We supply the answer-engine keys. Nothing to set up." |
| On | base | "You supply your own keys and pay providers directly." |

Implementation requirements:

- **All four tiers animate together** from one state change — the toggle is page-level, not per-card,
  so a buyer comparing tiers never sees a mixed view.
- **Tween the number, not the opacity.** Interpolate the displayed integer over ~250–300 ms so the
  price visibly counts down; cross-fading two static numbers loses the causal link between the toggle
  and the change, which is the entire point of animating it.
- **Respect `prefers-reduced-motion`** — snap to the new value with no tween. The branch already has
  a marketing motion layer (`marketing-motion.css`, the motion provider); reuse it rather than adding
  a second animation primitive (invariant 2).
- **It is a switch, not a button.** `role="switch"` with `aria-checked`, keyboard operable, and an
  accessible label naming what changes ("Use your own API keys"). Announce the resulting price to
  assistive tech via a polite live region, since a silent number tween is invisible to a screen
  reader.
- **Mirror state in the URL** (`?byok=1`) so a BYOK price is linkable and survives reload — the same
  pattern as the existing `?tab=` mirroring on Visibility.
- **Prices come from the catalog, never the component.** Both the funded and BYOK figures resolve from
  `GET /api/v1/billing/catalog` through
  [pricing.ts](frontend/lib/marketing-content/pricing.ts) (invariant 1). The displayed BYOK price and
  what checkout actually charges must be the same value from the same source — a mismatch here is a
  consumer-protection problem, not a UI bug.
- **State the trade-off honestly next to the toggle**, not buried in a tooltip: with your own keys you
  pay providers directly, and the report-ready latency target is not guaranteed because your key's
  rate limits are yours ([§5.2](#52-credential-resolution)).

The rest of the page:

- Four tiers with the [§4.4](#44-included-versus-add-on) axes as a comparison table, rendered from
  the same catalog the backend enforces.
- **Add-on and top-up activation inline**, driven entirely by `GET /api/v1/billing/catalog` — no
  per-add-on frontend code, so a new add-on appears without a deploy.
- Add-on price deltas shown against whichever headline the toggle is currently showing.
- Trial CTA stating plainly: **7 days free, card required, then `$X`/month, cancel anytime.**
- Top-up packs must state the expiry rule at the point of purchase: valid for one month, or until the
  subscription ends, whichever comes first
  ([§4.3](#43-credit-lifetime-and-spend-order)).
- The page must not imply any capability that is not shipped.

### 7.2 Landing page

Building on the redesign already in flight (`hero.tsx`, `proof.tsx`, `see-it.tsx`,
`product-window.tsx`, `evidence-panel.tsx`, `hero-atmosphere.tsx`):

- Hero shows the real artifact — an actual evidence panel with citations — rather than an abstract
  claim. The `see-it` and `product-window` work already points this way.
- A short **"what we measure"** section is now required rather than optional, because the two-mode
  design in [§2.2](#22-cheapest-model-from-every-provider-collides-with-measurement-validity) means
  the honest answer is nuanced: which model, whether retrieval was on, how often the benchmark runs.
  Explaining this is a trust advantage over competitors who are vague about it.
- Engine logos limited to providers with shipped adapters; anything else is explicitly labelled.
- No comparative cost claims. A "3× cheaper" style claim measured against CiteLadder's own prior
  estimate is unverifiable by any customer and should not appear.

### 7.3 In-app

- Trial banner with days remaining and a one-click upgrade path.
- Usage meters for prompts, projects, manual runs, and funded allowance where applicable.
- BYOK settings with per-provider status, probe results, and the latency-guarantee notice.
- Run view **streams per-provider results as they land**, with a queued state when the funded pool
  is saturated — the single largest perceived-latency win available.
- Every figure labels its mode (`pulse` or `benchmark`) and the model that produced it. Runs,
  Visibility, evidence, and exports all carry it.
- Strict response schemas, all four Visibility tabs with `?tab=` mirroring and WAI-ARIA behaviour
  preserved, same-origin API access via the existing rewrite proxy (invariant 12).

## 8. Security and misuse prevention

### 8.1 The audit is an LLM proxy unless it is constrained

This is the misuse vector most likely to be missed. A trial or funded account submits arbitrary
prompt text that CiteLadder executes on CiteLadder's keys and returns results for. That is a free LLM
API unless it is bounded — and people will find it. Controls:

- **Topical binding.** Prompts must relate to the project's brand, domain, or category. The existing
  prompt-generation flow should be the default path, with free-text entry validated against the
  project's category rather than accepted unconditionally.
- Config-owned maximum prompt length and prompt count per audit.
- Manual-run rate limits per account per day, resolved from the `manual_runs_per_day` counter in
  [§4.4](#44-included-versus-add-on).
- **Funded-execution budget with a monthly ceiling and complete-cost admission control.** The
  admission estimate must be `expected_token_cost + expected_search_fee × expected_searches`, summed
  over the worst-case attempt count ([§3.3](#33-latency-work)), before comparing against
  `funded_monthly_budget_minor`. The measured `$0.1466` per grounded execution **excludes per-search
  fees** and 2–3 searches per grounded execution were observed, so gating on the token figure alone
  understates real spend on exactly the most expensive path.
  **Until a per-search fee is configured for a route, that route fails closed on the funded path** —
  admitting work against a knowingly incomplete cost figure is how a budget ceiling silently stops
  being a ceiling. BYOK is unaffected: no CiteLadder spend, nothing to admit.
  Plus a graceful exhaustion state and operator alerting — without them an acquisition spike is an
  uncapped bill.
- Retain the invariant-6 rule that the brand and competitor list is never sent to a provider.

### 8.2 Trial abuse

- One trial per billing account, **and** one per payment-instrument fingerprint across all accounts,
  ever. Account-only uniqueness is farmable: accounts are one-to-one with users, so the same card
  across fifty signups yields fifty trials.
- Block disposable email domains; require a verified email before the trial starts.
- Velocity limits per IP and ASN on trial creation, with a review queue rather than a hard block for
  borderline cases.
- Store only safe verification state and an opaque provider reference. Never store card data.

### 8.3 Standard controls

- Workspace membership authorisation on every project-scoped read and write, filtered by
  `workspace_id`, no admin shortcut (invariant 5).
- Billing-owner authorisation for checkout, trial, and subscription mutations.
- Payment webhook signature verification, replay protection, and body size limits.
- Secrets never in DTOs, logs, snapshots, or artifacts; credentials and authorization headers
  redacted (invariant 6).
- Telemetry excludes prompts, answers, brand and competitor data, keys, and raw provider bodies.
- Export and download paths authorised identically to the API and bounded in size.

## 9. Data model

Additive to the existing schema; greenfield means the shape can be designed correctly rather than
migrated toward.

- `ProviderConnection` gains `credential_source = byok | platform`. Platform keys are ordinary
  Fernet-encrypted connection rows owned by a **reserved system workspace**, seeded from deployment
  secrets in a provisioning path — never read from env inside the connector. This keeps one
  credential resolution path, reuses existing redaction, and lets a funded audit freeze a real
  `connection_id` like any other audit, so the planner, worker, and provenance paths need no
  special case. Tenant-facing queries filter to `byok`; the system workspace is unlistable.
- `Audit.configuration` freezes measurement mode (`pulse` | `benchmark`), route and exact model,
  reasoning effort, retrieval setting, output policy and cap, repetitions, `credential_source` and
  `connection_id`, pricing and policy versions, trigger, and funded-reservation state.
- `ExecutionCostProjection` gains cached input, reasoning tokens, and search charges as separate
  fields, plus the pricing version. Immutable; repricing appends.
- `AuditSchedule`: one per eligible project, timezone-aware, with IANA timezone, local report-ready
  time, selected prompts and sources, mode, state and pause reasons, next local date, and dispatch
  policy version. Unique on `(schedule_id, local_date)`.
**The entitlement core is three tables, and only three.** This is what replaces a per-tier limits
table, and it is the whole reason a new add-on needs no schema change:

- **`AccountGrant`** — append-only, the single source of capability. UUID, billing account,
  `source_kind` (`plan | addon | topup | trial | override`), `source_ref`, `key`, `value` (integer;
  flags store 0/1, levels store the ordinal), period bounds, `valid_from`, `valid_until`, catalog
  revision, idempotency key, timestamps. Indexed on `(billing_account_id, key, valid_from)` for the
  resolver's hot read. **Never updated in place** — see `GrantRevocation` below.
- **`ConsumableLedger`** — immutable rows for `counter.consumable` keys only. References the grant it
  drew against, the audit or task that spent it, units, and an idempotency key. This is the *only*
  place needing atomic reservation under `FOR UPDATE`, and only on the funded path — occupancy limits
  are `COUNT(*)` checks with no ledger
  ([§4.2](#42-the-capability-registry--every-key-declares-its-own-composition-rule)).
- **`GrantRevocation`** — append-only. References the target grant, with `effective_from`, reason, and
  actor. The only way to end a grant early; the target row is never mutated, so past-instant replay
  stays accurate ([§4.1](#41-entitlements-are-composed-from-grants-not-looked-up-by-tier)).
- **`IdempotencyRecord`** — key, account, request fingerprint, stored response, expiry. Shared by the
  top-up endpoints and the payment webhook handler, because both are replayed as a matter of course.
- **`PendingActivation`** — checkout intent awaiting a webhook: catalog key, quantity, idempotency key,
  status, and expiry. Grants **no** entitlement; exists so the UI can show "payment processing" and so
  reconciliation can find intents whose webhook never arrived
  ([§5.3](#53-top-up-api)).

Notably **absent**: any `AccountEntitlement` projection table. The effective entitlement is derived
and cached in memory under the full key in
[§4.5](#45-fail-closed-resolution) — including subscription lifecycle version and validity window,
not just account and registry revision — so there is no second source of truth to drift, and no
migration when a capability key is added.

Everything else stays as above: keep commercial vocabulary in config rather than a DB CHECK
constraint, since plan names, add-ons, and capability keys will all keep changing.

## 10. Task graph

Slice 1 gates every cost, cap, and cadence value. The entitlement core (T7–T8) gates everything
commercial, because every later task reads its resolver rather than a tier table.

| Task | Depends on | Delivers |
|---|---|---|
| **T1** Measurement harness | — | Route × mode × cap × reasoning matrix; token, timing, `finish_reason`, mention/citation capture. *Anthropic leg done — see [§2.1](#21-output-length-is-a-real-lever-but-not-the-biggest-one).* |
| **T2** Cost config and projection | T1 | Pricing catalogue, reasoning/search/cached lines, expected-cost figures, `unknown` handling |
| **T3** Route and output policy | T1 | Representative model per provider, per-provider reasoning pin, concise instruction, ceilings from measured distribution |
| **T4** Worker concurrency and pacing | T1 | In-flight concurrency, Postgres token bucket, dual credential pools, tail timeouts, DB pool guard |
| **T5** Batch path for scheduled runs | T2, T4 | Flagged batch submission, fidelity-verified, sync fallback |
| **T6** Slice 1 gate review | T1–T5 | Published cost/latency numbers per provider; cadence economics confirmed |
| **T7** Capability registry + grant model | — | `AccountGrant`, per-key type/resolution registry, pure resolver, fail-closed profile, cache + invalidation. **No dependency on T6 — buildable in parallel with Slice 1.** |
| **T8** Catalog + top-up API | T7 | Plans/add-ons/top-up packs in config, the six `/billing` endpoints, idempotency store, webhook-to-grant issuance |
| **T9** Enforcement | T7 | Occupancy checks at mutation points, consumable ledger with spend order, manual-run limits |
| **T10** Trial as a grant | T7, T8 | Trial grant issuance, front-loaded pulse audit, expiry, abuse controls |
| **T11** BYOK + funded credentials | T6, T7 | `credential_source`, platform connections in the system workspace, resolution precedence, key-failure pause (never silent funded fallback), probes |
| **T12** Schedules and modes | T9, T11 | Dispatcher, pulse/benchmark cadence from the resolver, lead time from measured p95, DST policy, partial-report policy |
| **T13** Frontend: pricing and landing | T8 | Catalog-driven pricing page, **BYOK toggle with animated price change**, add-on and top-up activation (no per-add-on code), landing rework, "what we measure" |
| **T14** Frontend: in-app | T9, T10, T12 | Trial banner, usage meters from `/billing/usage`, provider key settings, streaming run view, mode labels |
| **T15** Additional providers | T11, T13 | Grok and Perplexity adapters shipped independently; `provider.*` flag grants; logo gating. Copilot per [§6.1](#61-copilot-is-listed-but-ships-last) |
| **T16** Enterprise | T7 | Contact-us routing only; deals served by `override` grants, which T7 already supports |

The ordering change worth noting: **T7 has no dependency on Slice 1.** The grant model is independent
of what anything costs, so the entitlement core and the cost/latency work can proceed in parallel
rather than in series — which is the practical payoff of separating "what may this account do" from
"what does an execution cost".

## 11. Config keys and proposed defaults

Every value below lives in `backend/app/core/config/*` per invariant 1. Values marked **(m)** are
measured on the Anthropic leg ([§2.1](#21-output-length-is-a-real-lever-but-not-the-biggest-one)) —
confirm against OpenAI and Google before freezing. Values marked *(T1)* still need measurement.

| Concern | Key | Proposed | Basis |
|---|---|---:|---|
| Concise-answer instruction | `pulse_answer_instruction` | config-owned text | **(m)** −56% cost, −49% latency, mentions preserved |
| Output ceiling, pulse | `pulse_max_output_tokens` | 600 | **(m)** median output 183; never binds — safety rail only |
| Output ceiling, benchmark | `benchmark_max_output_tokens` | **4096** | **(m)** grounded median output 2,334 — a 1200 ceiling would truncate real answers |
| Reasoning effort | `route_reasoning_effort` | per provider, pinned low | **(m)** zero thinking tokens on Anthropic; verify OpenAI/Google separately |
| Repetitions, pulse | `pulse_repetitions` | 1 | |
| Repetitions, benchmark | `benchmark_repetitions` | 3 | |
| Prompt caching | — | **do not implement** | **(m)** instruction is ~48 tokens, far below the cacheable minimum |
| Route timeout, pulse | `pulse_timeout_seconds` | 30 | **(m)** median 5.3 s, max 10.8 s |
| Route timeout, benchmark | `benchmark_timeout_seconds` | 150 | **(m)** median 61.5 s, max 74.3 s |
| Worker in-flight tasks | `worker_max_inflight` | 10 *(T1)* | |
| Funded pool concurrency | `funded_pool_max_concurrency` | 12 *(T1)* | |
| Funded per-account share | `funded_pool_per_account` | 6 *(T1)* | |
| Per-transport concurrency | `per_transport_concurrency` | 4 *(T1)* | |
| Expected cost, pulse exec | `expected_pulse_cost_microusd` | 2_890 | **(m)** `$0.00289` |
| Expected cost, benchmark exec | `expected_benchmark_cost_microusd` | 146_600 | **(m)** `$0.1466` tokens only — search fee added separately |
| Per-search fee | `expected_search_fee_microusd` | *(T1)* — **unset fails closed** | required for funded admission ([§8.1](#81-the-audit-is-an-llm-proxy-unless-it-is-constrained)) |
| Expected searches per benchmark | `expected_searches_per_benchmark` | 3 | **(m)** 2–3 observed |
| Trial length | `trial_days` | 7 | card required, subscription trial |
| Top-up credit lifetime | `topup_credit_valid_days` | 30 | capped by subscription end, whichever is earlier |
| Benchmark cadence, default | `default_benchmark_cadence` | weekly / daily / daily | per tier; add-on can raise |
| Trend smoothing window | `trend_smoothing_days` | 7 | **(m)** required by the 4–7 mention noise floor |
| Pricing page toggle default | `pricing_byok_default_on` | false | show funded price first; BYOK lowers it |
| Trial execution ceiling | `trial_max_executions` | 30 | **(m)** one 10×3 pulse audit ≈ `$0.087` |
| Monthly funded budget | `funded_monthly_budget_minor` | 50_000 (`$500`) | **(m)** ≈5,700 trials/month at `$0.087` |
| Funded uplift per cadence | `funded_uplift_pct` | derived, see [§5.1](#51-byok-is-the-baseline-funded-execution-is-a-metered-grant) | **(m)** provider cost can exceed list price |
| BYOK key-failure grace | `byok_key_grace_days` | 7 | |
| Manual runs per day | `manual_runs_per_day` | 3 / 6 / 12 | |
| Max prompt length | `max_prompt_chars` | 300 | |
| Schedule lead-time floor | `schedule_lead_time_floor_seconds` | 1800 | |
| Schedule lead-time factor | `schedule_lead_time_p95_factor` | 1.5 | |

## 12. Verification gates

Slice 1, all required before prices are set:

- per-route cost table with reasoning and search itemised;
- output-length distribution published and the cap derived from it;
- mention and citation extraction statistically equivalent to uncapped output;
- representative model per provider documented with evidence;
- audit wall-time p95 per mode at target concurrency;
- funded pool holds its rate limit under simulated concurrent load without 429 cascades;
- DB pool never exhausted at maximum configured concurrency;
- cost `unknown` rather than zero when usage is missing;
- zero provider calls from any read path.

Slices 2–5:

- tier resolution failure grants nothing and funds nothing;
- trial uniqueness holds per account and per card under concurrency;
- funded spend cannot exceed the monthly budget;
- funded execution is priced above measured provider cost at every cadence;
- top-up credits expire at `min(purchase + 30d, subscription_end)`, and cancelling a subscription
  forfeits them — asserted against a moving subscription end, not a frozen timestamp;
- consumables draw earliest-effective-expiry-first, with free allowance before purchased top-ups
  **only on an exact expiry tie**, and a total ordering across every `source_kind`
  ([§4.3](#43-credit-lifetime-and-spend-order));
- every retry attempt of a funded execution appears as its own ledger row, and credits are reserved
  for `max_attempts` rather than for one attempt;
- the BYOK price shown on the pricing page equals what checkout charges, from one catalog source;
- the pricing toggle is a `role="switch"`, keyboard operable, announces the new price to assistive
  tech, and snaps instead of tweening under `prefers-reduced-motion`;
- Copilot resolves to no adapter and is never routed to an Azure OpenAI deployment;
- level-typed keys resolve by maximum and never sum (two 90-day grants are not 180 days);
- add-on activation and top-up purchase are idempotent under replay, and grants are written only
  from verified webhooks;
- BYOK key failure pauses the provider and never silently funds a discounted account;
- prompt topical binding rejects off-domain free text;
- secrets absent from every DTO, log, snapshot, artifact, and export;
- workspace isolation on every project-scoped path;
- schedules correct across timezones, DST gap (dispatch at first existing instant after the missing
  time) and fold (dispatch once), delayed ticks, and concurrent dispatchers;
- report-ready SLO measured **per customer per month**, not globally — a global average hides the
  one customer who churns;
- pricing page, backend catalogue, and enforced limits agree;
- no provider logo or capability claim without a shipped adapter.

## 13. Open decisions

**Settled.** Prices are `$99`/`$199`/`$299` placeholders and explicitly not a focus — catalog config,
changeable without code. Enterprise routes to a contact form, served by `override` grants. The trial
is a card-required subscription with one free week, running pulse mode. Cadence is daily, with
smoothing mandatory. Additional providers are BYOK key-addition unlocks; Copilot is listed but
unavailable until a real API exists. Top-up credits are valid for one month or until the subscription
ends, whichever is earlier, and are forfeit on cancellation.

**Still open — each needs a number, not a decision:**

1. **The funded margin multiplier.** `funded_price = provider_cost × (1 + margin)` needs its `margin`,
   and it sets how the BYOK toggle's two numbers relate
   ([§5.1](#51-byok-is-the-baseline-funded-execution-is-a-metered-grant)).
2. **Top-up pack sizes**, in benchmark credits. At `$0.1466` per grounded execution, a pack that covers
   one month of daily benchmarking on one project is ~900 credits — size the packs against how
   customers actually run, once there is usage data.
3. **Included benchmark credits per tier**, which is the same question as how much funded execution
   each tier absorbs before a top-up is needed.
4. **Repetitions per benchmark**, now that daily is settled. One repetition carries the measured 4–7
   mention-count noise floor; the smoothing window partly compensates, but the trade-off between
   repetitions and pack burn is a product judgement
   ([§3.6](#36-repetitions-are-a-cost-quality-dial-not-just-a-cost-dial)).

**One risk to track rather than decide.** Daily grounded benchmarking on BYOK costs CiteLadder nothing
in provider spend, but it is 30 grounded executions per project per day against a measured 61.5 s each
— so it is the dominant driver of queue capacity, worker concurrency, and DB pool sizing. The money
question is answered; the capacity question moves to T4 and T12.

## 14. Non-goals

- Any Free tier, funded standalone audit, or card-verified no-subscription grant.
- Migration or naming compatibility with `free`/`paid`/`bundle` vocabulary.
- Sentiment and average position — still not computed, still `—`, per invariant 9.
- Scraping consumer answer-engine interfaces.
- Relabeling a generic Azure or OpenAI model as Copilot.
- Marketing any provider before its adapter ships.
- Redis, or multi-replica workers before the Postgres token bucket lands.
- Any cost, latency, price, or margin claim that Slice 1 has not measured.
