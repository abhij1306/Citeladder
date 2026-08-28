# The AEO opportunity loop

Turn CiteLadder's existing evidence into one weekly operating loop:

> **When AI recommends another brand and not yours, what did CiteLadder observe, which path can
> you act on, and what should you do first?**

**Status:** planned. The foundations listed below are shipped; the five stages in this plan are not.

**Decision update (2026-08-28):** the first complete-loop release includes comparable
verification, not only opportunity discovery. Product measurement uses approved first-party,
citation-capable frontier-engine routes; Content uses an independently approved frontier
generation route. Tavily, MiniMax, GLM, and other synthetic or externally scaffolded simulations
may support isolated evaluations, but they never populate product visibility measurements or
masquerade as another logical engine.

**Depends on:** the shipped buyer-stage prompt taxonomy (`docs/visibility-prompt.md`) and the
shipped Opportunity implementation/verification lifecycle in the active AEO rebuild.

**Measured outcome:** increased **observed** mention/citation share across a versioned prompt
portfolio under comparable audit conditions. A citation beside a gap is evidence of a pattern,
not proof that the citation caused the recommendation.

---

## What is already shipped

This is an extension of the existing Opportunities owner, not a new work-management system.

| Capability | Shipped foundation | Missing here |
|---|---|---|
| Find gaps | Visibility, Site Health, Demand, traffic, and change detectors feed one Opportunity store | Earned-source opportunity |
| Describe sources | Deterministic `classify_source_domain()` and per-gap source-pattern evidence | Portfolio routing, social/institutional classes, and coverage |
| Prioritize | Deterministic severity × value × gap score with formula provenance | Buyer-stage and source-usage factors |
| Act | Opportunity status/order plus immutable `OpportunityImplementationEvent` declarations | Typed Owned/Earned Content handoff, earned action copy, target handling, and generation linkage |
| Verify | Append-only `OpportunityVerificationEvent` observations | Comparable three-signal result |
| Repeat | Scheduled audits and Opportunity recompute | Clear no-longer-observed, persistent, and new gap presentation |

The implementation-event owner already closes the structural gap between a recommendation and a
later observation. Do **not** add another `Action` table or a parallel lifecycle. For the demo:

- `open`, `in_progress`, `dismissed`, and `resolved` remain the human workflow states;
- **I implemented this** remains the explicit declaration that a public change actually happened;
- a pitch sent but not published stays `in_progress`, not implemented; and
- later evidence never changes the human status automatically.

## Product evidence and provider boundary

1. Visibility audits use the existing config-owned logical-engine policy. Every enabled engine
   resolves to an approved citation-capable frontier route before provider I/O; the exact logical
   engine, provider, transport model, native retrieval state, locale, repetition policy, and
   request configuration are frozen on the audit.
2. No external search surrogate or synthetic model trace is accepted as a ChatGPT, Claude, Gemini,
   or other first-party engine observation. Unsupported retrieval is `unavailable`; it never falls
   back silently to Tavily, MiniMax, GLM, or model-invented URLs.
3. Opportunity analysis remains deterministic over immutable answers and citations already
   persisted by those audits. Opportunity read APIs never invoke a provider or retrieve the web.
4. Content generation has separate provenance and a config-owned allowlist of approved frontier
   generation routes. Its provider/model identity never changes the measurement identity of the
   audit that produced the opportunity.
5. Generated content is an inspectable, untrusted draft grounded only in the frozen Content
   context. It cannot create or repair citation evidence, provider observations, or visibility
   metrics.

## Delivery scope decisions

1. Route sources into **Owned**, **Competitive evidence**, or **Earned**. A competitor-owned page
   is evidence for an owned-content response, never an outreach target.
2. Build the first earned worklist only from citations already persisted by an audit. The demo adds
   no open-web crawl, outreach automation, domain-authority score, CRM, or assignment system.
3. Make only page-level claims supported by the observed citations. "The brand was not observed on
   these cited pages" is valid when page evidence exists; "the brand has no presence on this
   domain" requires a separate bounded observation and is deferred.
4. Group earned findings by a reliable source identity. Do not invent a template identity to group
   Site Health issues; the current rule/target identities and grouped Issues surface remain their
   owners.
5. Reuse `OpportunitySnapshot`, `Opportunity`, `OpportunityImplementationEvent`, and
   `OpportunityVerificationEvent`. A JSON projection may start bounded and versioned inside the
   existing snapshot; a separate source-usage table is justified only when measured scale or query
   needs demand one.

The demo loop is therefore:

```text
Audited prompt gap
  -> observed source route + coverage
  -> grouped, usage-aware Opportunity
  -> human starts or dismisses it
  -> Content receives a frozen Owned/Earned evidence handoff
  -> approved frontier model generates a reviewable draft
  -> human publishes, submits, or contributes outside CiteLadder
  -> human declares the published change
  -> later comparable evidence verifies, contradicts, or remains limited
  -> Opportunity recompute shows no-longer-observed, persistent, and new gaps
```

---

## Stage 1 — Buyer-stage-aware priority

**Goal:** make commercial relevance improve the ordering of every prompt-backed Opportunity without
changing whether a detector fires.

1. Freeze `buyer_stage` and `prompt_intent` into `AuditPromptSnapshot` beside its existing legacy
   `intent` when the audit is created. Historical scoring must never join back to a mutable or
   deleted `Prompt`.
2. Add config-owned stage weights and a pure
   `value_factor_for_prompt(buyer_stage, prompt_intent, legacy_intent)`. It uses buyer stage when
   present, then the newer prompt intent, then the existing legacy intent factor; no known-empty
   input becomes zero.
3. Persist the selected stage, intent, weights, and resulting factor in Opportunity evidence and
   `priority_factors`.
4. Bump the Opportunity analyzer version and `FORMULA_VERSION`. Fold the snapshot columns into
   `0001_initial.py`; the immutable frozen values and their prompt-generation provenance remain the
   audit input authority.

**Done when:** for otherwise identical evidence, a configured higher-value buyer stage ranks above
a lower-value stage; a manual prompt with no stage keeps the legacy result; and a prompt edited or
deleted after an audit cannot change that audit's Opportunity score.

## Stage 2 — Source routing and honest coverage

**Goal:** show which observed sources are controllable, competitive evidence, or plausible earned
paths.

### Source class to pathway

| Source class | Pathway | Product meaning |
|---|---|---|
| `brand_owned` | Owned | Improve or create an owned answer |
| `competitor_owned` | Competitive evidence | Study the cited content pattern; route to Owned/Content |
| `review_marketplace`, `editorial_third_party`, `community`, `social`, `institutional`, `video` | Earned | A human may be able to improve presence or earn inclusion |
| `other_third_party` | Earned / unclassified | Count as non-owned observation, but do not create a class-specific task |

Add config-owned `social` and `institutional` classes and bump
`SOURCE_TAXONOMY_VERSION`. Domain/suffix rules remain deterministic and deliberately conservative;
unknown sources stay `other_third_party`.

### Persisted source-mix projection

Extend the existing `OpportunitySnapshot` with one versioned, bounded `source_mix` projection. Do
not create a second snapshot owner for the demo.

- **Unit:** one canonical domain per analyzed answer. Repeated citations to the same domain in one
  answer count once; observations in separate answers each count once.
- **Population:** the exact analyzed answers for prompt targets in the visibility-gap set produced
  by the same Opportunity recompute, all bound to one audited prompt cohort.
- **Mix denominator:** all valid domain observations routed as Owned, Competitive evidence, or
  Earned. Answers with no usable citations add no domain observations.
- **Usage denominator:** analyzed answers eligible for the selected audit/cohort. Failed or
  not-run answers are reported separately, not treated as uncited answers.
- **No gap:** no qualifying visibility gap is `not_applicable`. A qualifying gap with no valid
  domain observations is `unavailable`, never `0% earned`.
- **Provenance:** exact audit, prompt snapshots, response analyses, artifacts, taxonomy version,
  projection version, truncation state, and limitations.

The Opportunities headline is three-way and always carries coverage, for example:

> **54% Earned · 31% Competitive evidence · 15% Owned**
> Based on 68 source observations across 41 of 75 eligible analyzed gap answers.

Copy must say "source observations," not "54% of your gap" or "what caused the answer."

Persist a separately labelled two-way **action-path projection** for worklist filtering and the
Owned-versus-Earned operating view:

- **Owned action path:** `brand_owned` plus `competitor_owned`, because competitor pages are
  evidence for content the brand controls rather than outreach targets.
- **Earned action path:** actionable earned classes. `other_third_party` contributes to measured
  non-owned source observations but cannot create a class-specific earned task.

The two-way action view must not replace or be presented as the three-way observational mix. It
uses the same frozen population, coverage, source IDs, versions, and unavailable/not-applicable
rules.

### Backend/frontend contract

The Opportunity owner exposes `source_mix`, `action_path_mix`, and bounded domain rollups through
the existing summary/detail routes. Backend schemas and strict frontend schemas change in the same
slice. The frontend does not reclassify domains, infer pathways, or calculate denominators.

Both contracts support `social` and `institutional` before those values can be persisted. The
frontend renders the server-provided three-way headline, two-way filters, coverage, limitations,
and explicit `unavailable`/`not_applicable` states.

**Done when:** a citation-bearing audit renders its measured three-way mix from persisted data; a
no-gap audit renders `not_applicable`; a gap with no usable citations renders `unavailable`; and
competitor-owned domains never appear as earned outreach tasks.

## Stage 3 — A small earned worklist that a person can act on

**Goal:** make the first demo useful without claiming to know a brand's entire off-site presence.

### Source usage affects earned priority

Within the Stage 2 snapshot, persist a deterministic, config-bounded domain rollup:

- canonical domain and source class/pathway;
- answers and distinct prompts citing it;
- themes and competitors observed in the same answers;
- usage numerator, denominator, percentage, coverage, and exact source-analysis IDs; and
- whether the bounded projection was truncated.

For earned Opportunities only, evolve the formula to:

```text
priority = existing base score
           x bounded source-usage factor
           x bounded competitor-co-occurrence factor
```

The multipliers and bounds live in config. Owned/technical rules keep their existing factor path.
Stage 3 bumps `FORMULA_VERSION`, and the API continues to expose every applied factor. Stage 4 may
later replace simple competitor co-occurrence with recommendation strength under another explicit
formula bump.

### First earned detector

Ship one detector for the demo:

`earned_source_recurs_beside_gap`

It fires when an actionable earned source class recurs above configured usage/coverage thresholds
in answers for persisted visibility gaps. It says only that the source recurred beside those gaps.
Its evidence includes representative cited URLs, prompts/themes, source class, usage calculation,
competitor co-occurrence, coverage, limitations, and all relevant versions.

The suggested action is class-specific but human-led: inspect the cited pages, decide whether the
brand belongs there, then update a profile, contribute useful material, or pursue editorial
inclusion. The detector does not claim the brand is absent from the whole domain and does not
guarantee inclusion will change an engine answer.

### Grouping and action lifecycle

- Emit one live row per `(rule_id, source_class, canonical_domain)` using a stable target key such
  as `earned-source:{source_class}:{canonical_domain}`.
- Aggregate affected prompts, themes, and citations into that row, with deterministic caps and
  explicit truncation. Twelve prompt hits on the same source become one work item.
- Show a suggested role such as Marketing, PR, or Founder as guidance only. Do not add assignment,
  notifications, due dates, or a new action owner.
- Reuse status/order for triage and the existing implementation declaration for **I implemented
  this**. An earned declaration may have no owned-page target and can carry a visibility expected
  check; it remains an explicit user claim.

### Opportunity to Content handoff

The Opportunity owner projects one typed, bounded `content_handoff` on the existing detail
contract. It is not a second brief or action store. It contains:

- action pathway (`owned` or `earned`), source class, canonical domain, and suggested role;
- a config-owned suggested Content skill/output kind;
- editable task seed and target URL/theme when one exists;
- representative cited page URLs/titles, affected prompts/themes, observed competitors, coverage,
  limitations, truncation state, and exact source-analysis IDs; and
- Opportunity snapshot, detector, formula, taxonomy, and handoff-template versions.

The Content owner accepts `opportunity_id`, authorizes it in the active workspace/project, freezes
that exact handoff into the generation context manifest, and records omissions and budgets before
provider I/O. Observed third-party page metadata remains untrusted evidence; Content does not fetch
the domain or use a second search provider.

The Opportunities drawer offers **Create owned content** or **Prepare earned content** and routes to
the existing Content screen with `opportunity_id`. Content displays the pathway, cited domain/page
evidence, coverage, and limitations; preselects the server-suggested skill; seeds an editable
instruction once; and never overwrites user edits on refetch.

Initial earned outputs are transparent human-led assets such as an editorial inclusion brief,
expert-contribution outline, review/profile evidence pack, or outreach draft. They must not
impersonate independent users, fabricate experience, or automate posting, sending, or publishing.

### Generation to implementation linkage

After a successful generation, Content offers **Return to opportunity** and the Opportunity detail
shows linked generations. Drafting or sending a pitch keeps the item `in_progress`. Only the user
can declare that the external change is public or otherwise implemented.

An implementation declaration created from this flow includes `generation_id`. The backend rejects
a generation unless it belongs to the same workspace, project, and opportunity and is in an
eligible successful state. Expected checks are config-owned server projections for the rule and
pathway; the browser never invents a visibility threshold. The immutable event freezes the exact
Opportunity snapshot and accepted expected checks.

Evidence-gated follow-ons—not demo requirements—may add `EarnedProfileEvidence` for bounded
review/marketplace profile checks and cited-page brand-presence extraction. Those detectors must
abstain on `unavailable`; missing citations alone can never establish domain-wide absence.

**Done when:** the first three rows are grouped actions a person could reasonably take this week;
a source used in many eligible answers outranks an otherwise equal source used once; one recurring
domain does not produce a row per prompt; both pathways reach Content with inspectable frozen
evidence; unrelated/failed generations are rejected; and an earned item can enter the shipped
start → generate → human implement → observed lifecycle without a second action model.

### Actionable milestone

Stages 1–3 are the first actionable milestone, but not a complete-loop release. They change the
answer from "your score is 37" to:

> "These are the sources engines repeatedly used beside your gaps. This one is yours to improve,
> this one is competitor evidence, and this one is a realistic earned path. Here is the first
> action and why it ranks first."

---

## Stage 4 — Recommendation strength by entity

**Goal:** distinguish recommendation from mention before using that distinction in priority.

At `ResponseAnalysis` creation, persist an entity-level assessment for the tracked brand and each
competitor in the exact entity roster supplied to that audit:

`recommended | hedged | mentioned | recommended_against | absent | not_assessed | unavailable`

Each item carries stable entity identity, confidence, evidence spans, method, analyzer version, and
any model/template version. `absent` is valid only when entity matching ran successfully over a
usable answer. Parser failure or bounded ambiguity is `unavailable`; a deliberately skipped step
is `not_assessed`.

Freeze that entity roster or its exact manifest in the audit configuration before provider I/O.
Historical assessment must not read the project's current competitor list.

Start with deterministic explicit cases. No LLM fallback is required for this plan. If a later
model adjudicates ambiguity, it must create versioned derived evidence from the exact artifact; it
must not mutate an old assessment or become raw truth.

Once the entity projection and consumer land together, use recommendation strength in the
visibility-gap factor and bump the response analyzer/scoring versions plus `FORMULA_VERSION`.
`recommended_against` is a distinct urgent observation, not a negative number hidden inside an
average position.

**Done when:** one answer can recommend a competitor, merely mention the brand, and leave another
entity unavailable without collapsing those states; evidence spans explain each assessed state;
and unavailable never scores as absent.

## Stage 5 — Comparable three-signal verification and repeat

**Goal:** report what changed after an implementation declaration without attributing causality.

Extend the existing verification projection; do not replace it. Show these independent legs:

| Signal | Question | Existing evidence owner |
|---|---|---|
| Citation/mention | Did comparable engine observations use or recommend the brand differently? | Audits, response analyses, citations |
| AI referral traffic | Did observed visits from AI sources change? | `AiReferralsSnapshot` |
| Branded search demand | Did observed branded demand change? | GSC/Traffic snapshots and branded-query classification |

For every leg, persist its own state (`available`, `observed_zero`, `unavailable`, `not_run`, or
`non_comparable`), exact source IDs, baseline and post-action windows, values/delta, versions, and
limitations. Visibility comparison additionally requires the same frozen prompt-snapshot cohort or
exact cohort hash, logical engine set and resolved model/retrieval identity, locale, repetition
policy, and relevant analyzer/taxonomy versions. A mismatch produces `non_comparable`, never a
trend delta.

Anchor the baseline to the implementation event's frozen Opportunity snapshot and declared time.
If another implementation event overlaps a comparison window, list it as an overlapping action and
do not attribute movement to either action. Three aligned signals are stronger evidence; one moving
alone is a lead; disagreement is displayed, not averaged away.

On recompute, present gaps as **no longer observed**, **persistent**, or **new** under the comparable
snapshot pair. This projection does not silently set the human Opportunity status to `resolved`.

**Done when:** a user can move from one implementation declaration to a comparable before/after
view; missing GA4 leaves only that leg unavailable; a changed prompt/provider cohort suppresses the
visibility delta; overlapping actions are explicit; and the UI offers the next comparable audit or
schedule action without implying that CiteLadder caused the observed change.

---

## Sequencing and non-goals

```text
Actionable slice:      Stage 1 Priority -> Stage 2 Route -> Stage 3 Act and Generate
Complete-loop release: Stage 1 -> Stage 2 -> Stage 3 -> Stage 5 Measure and Repeat
Independent follow-on: Stage 4 Understand recommendation strength
```

Do not combine all stages into one PR. Each stage is one gated slice and leaves the repository
runnable. Stage 5 is nevertheless required before the product is described as a complete
opportunity loop. Stage 4 may ship before or after Stage 5 but is not a verification prerequisite.
Schema-changing slices fold changes into `0001_initial.py` and prove a clean database before
completion.

Explicitly out of scope for this plan:

- automated outreach, publishing, profile mutation, or prompt activation;
- web-wide claims about brand absence;
- domain authority, paid keyword/SERP data, or causal lift claims;
- a second Opportunity, action, verification, queue, or source-usage owner;
- template-level Site Health grouping without a deterministic template identity owner; and
- a model dependency for Opportunity detection, classification, routing, scoring, or verification.

## Verification and demo acceptance

Every stage must pass the repository gates once, in order:

```powershell
.\scripts\check.ps1
.\scripts\test.ps1
```

Also require:

1. Positive and boundary fixtures for every new projection/factor/detector, including citation
   deduplication within one answer, repeat observations across answers, failed answers, no
   citations, unknown source class, competitor-owned routing, and bounded truncation.
2. Workspace-isolation, idempotency, exact provenance, historical-stability, and clean-baseline
   migration coverage for every persistence change.
3. API/UI contract coverage for `unavailable`, observed zero, `not_run`, and `non_comparable` where
   applicable; none may collapse into another state.
4. One sanitized development project with a completed citation-bearing audit. Read Opportunities
   top to bottom and confirm:
   - the source-mix headline includes coverage;
   - competitor-owned evidence routes to Owned/Content;
   - the same earned domain is grouped into one work item;
   - priority factors explain why the first item ranks first; and
   - Owned and Earned filters use the backend action-path projection;
   - the item reaches Content with the same persisted evidence and suggested skill;
   - a successful generation links back to the same Opportunity;
   - a sent-but-not-published earned draft remains `in_progress`; and
   - an explicit implementation reaches the comparable later-observation flow.
5. A dated sanitized evaluation artifact under `docs/evaluations/` recording inputs, versions,
   coverage, the top three actions, and any abstentions. A detector need not occur naturally in the
   sample if deterministic fixtures prove its positive behavior.
6. One mapped end-to-end test covering frontier audit fixture -> persisted source/action mix ->
   grouped earned Opportunity -> Content handoff -> successful generation -> explicit implementation
   with `generation_id` -> comparable verification -> no-longer-observed/persistent/new display.
7. Negative contract tests proving that foreign or unrelated generations are rejected, unsupported
   retrieval is unavailable rather than substituted, provider/model cohort mismatches are
   non-comparable, and no Tavily/MiniMax/GLM provenance can appear as a first-party product engine.
