# The AEO opportunity loop

Turning CiteLadder from a set of analyses that each report something true, into one loop that
answers a single question: **when AI recommends a brand in your category, why does it name them and
not you — and what do you do about it this week?**

**Status:** planned. Nothing here is implemented.

**Depends on:** the buyer-stage prompt taxonomy (`docs/visibility-prompt.md`), which is shipped.
Stage 1 below consumes `Prompt.buyer_stage` directly.

**Guiding constraint (inherited from `docs/invariants.md` and the Site Health model):** CiteLadder
reports **what it observed**. A citation sitting beside a gap is evidence of a pattern, never proof
of cause. Every claim below keeps that framing, including in user-facing copy.

---

## Context

The product currently looks random to a user, and the audit below shows why: the analyses are
individually sound but nothing sequences them. A user lands on a dashboard, sees a score, and has no
path from that score to an action. The reference model — the loop Searchable runs on its own brand —
is explicit about the sequence:

```
Find gap → Owned or earned → Prioritise → Act → Measure → Repeat
```

with one framing decision underneath it: **every citation is either owned (something you can build
or fix) or earned (somewhere a third party has to cite you)**. On their own account the split is
roughly 40% owned / 60% earned, and their earned mix is 76% editorial, 11% social, 7%
institutional, 4% forum, 2% review. Those exact numbers are theirs, not a universal constant, and
must never be hardcoded — but the *classification* is the thing that makes the loop actionable,
because it tells a user whether publishing more pages can possibly close their gap.

### The audit: what exists, and the one thing that does not

Most of the loop is already built. This is a sequencing and aggregation problem far more than a
new-capability problem.

| Loop stage | What exists today | Verdict |
|---|---|---|
| Find gap | `detect_brand_absent_high_value_prompt`, `detect_owned_page_not_cited`, `confirmed_prompt_decline` (`analysis/opportunities/detectors.py`) | Built |
| Classify source | `classify_source_domain` + 7 classes (`analysis/opportunities/source_patterns.py`) | Built, unused for routing |
| Prioritise | `priority_score = severity × value_factor(intent) × gap_factor` (`analysis/opportunities/scoring.py`) | Built, weak inputs |
| Act — owned/technical | Site Health crawler, 12 site rules, `SITE_ISSUE_TO_OPPORTUNITY_RULE_ID` | Built |
| Act — owned/content | `domain/content/` editor, `search_demand_content_gap`, `striking_distance_query` | Built |
| Act — earned | — | **Absent** |
| Measure | `OpportunityVerificationEvent`, `AiReferralsSnapshot`, `TrafficSnapshot`, visibility history | Built, not triangulated |
| Repeat | `audit_schedule` | Built |

**The finding.** `OPPORTUNITY_RULES` holds 25 rules. Every single one is owned or technical:

> brand_absent_high_value_prompt · owned_page_not_cited · confirmed_prompt_decline ·
> missing_structured_data · thin_content · schema_type_mismatch · schema_properties_incomplete ·
> schema_visible_content_conflict · content_structure_incomplete · citability_trust_incomplete ·
> product_not_mentioned · cited_alternatives_without_uploaded_presence · catalog_fields_missing ·
> search_demand_content_gap · striking_distance_query · query_cannibalization ·
> property_relative_ctr_gap · emerging_query · declining_query · site_link_near_orphan ·
> site_link_weak_authority · site_change_potential_regression · site_change_critical_regression ·
> low_share_of_voice_theme · high_traffic_low_visibility

**There is not one earned-side rule.** Whatever a user's actual gap is, CiteLadder can only ever tell
them to fix their own website. If the reference split is even directionally right, the product is
structurally blind to the majority of the opportunity — and worse, it will confidently recommend
publishing pages in exactly the cases where publishing cannot help.

Three supporting gaps, all verified:

- **No source-usage aggregate.** `Citation` rows carry `domain`, `is_owned`, `matched_competitor`
  and a source class, but nothing groups them by domain across a prompt set. The reference model's
  central prioritisation metric — *usage %*, how often an engine actually cites a source, as opposed
  to how authoritative it looks — cannot currently be computed. `grep` for `Citation.domain`
  aggregation returns one `order_by` and no `group_by`.
- **No recommendation strength.** `ResponseAnalysis` records `brand_mentioned`, `owned_domain_cited`,
  `avg_position`, `sentiment`. It cannot distinguish *recommended* from *mentioned in passing* from
  *recommended against*. A competitor being recommended while you are named in a footnote is a far
  larger gap than any position number expresses.
- **Two missing source classes.** `SOURCE_CLASS_ORDER` has brand_owned, competitor_owned,
  review_marketplace, editorial_third_party, community, video, other_third_party. There is no
  **social** (LinkedIn, X) and no **institutional** (.gov, .edu, standards bodies) class — together
  ~18% of the reference earned mix, currently collapsed into `other_third_party`.

The IA is already loop-shaped (`components/layout/nav-items.ts`: Overview → Analyze → Act → Track),
so this plan changes what those stations *contain*, not the nav.

---

## Stage 1 — Buyer stage into the priority score

**Why first:** it is the smallest change with the widest effect, and it is the join to the prompt
work already shipped. `value_factor_for_intent` (`analysis/opportunities/scoring.py:26`) already
multiplies prompt intent into every opportunity's priority. Swapping the input upgrades the ranking
of all 25 existing rules for free.

- Add `STAGE_VALUE_WEIGHTS` to `core/config/opportunities.py`, weighting decision > consideration >
  awareness > implementation — the same commercial shape the prompt archetypes already use.
- `value_factor_for_intent` becomes `value_factor_for_prompt(buyer_stage, intent)`, falling back to
  the legacy intent weight when `buyer_stage` is empty (manual and imported prompts).
- Bump `FORMULA_VERSION`. Priority scores are provenance-stamped, so a formula change must be
  legible as one rather than appearing as drift.

**Done when:** a decision-stage gap outranks an awareness-stage gap of identical severity, and the
factor breakdown is visible on the opportunity so a user can see *why* it ranks where it does.

## Stage 2 — Owned vs Earned, as a first-class split

**Why second:** it is the conclusion a user can actually make a decision from, and it is an
aggregation over data already persisted.

- Add `SOURCE_CLASS_SOCIAL` and `SOURCE_CLASS_INSTITUTIONAL` to `core/config/source_patterns.py`
  with their domain tables; bump `SOURCE_TAXONOMY_VERSION`.
- Add a pure `owned_earned_split()` projection over `Citation` rows for a prompt set: for every
  prompt where the brand is absent or under-cited, classify each cited source, and roll up to a
  portfolio-level share. Its unit is one canonical domain per analyzed engine answer: repeated
  citations to the same normalized domain in one answer count once, while the same domain observed
  in separate engine answers or repetitions contributes once per answer. The denominator is all
  owned plus earned domain observations across the project's exact audited prompt set, and the
  earned numerator is the subset classified as earned. Answers with no citations contribute to
  neither value; a portfolio with no domain observations is unavailable, never zero. Persist the
  exact project, prompt-set, audit, answer, and taxonomy-version inputs so aggregation order cannot
  change the result.
- Surface it as the headline on the Opportunities screen: *"73% of citation-source observations
  across this project's measured visibility gaps came from sources you do not own."* Never publish
  a fixed 40/60 expectation — it is measured per project or it is not stated.
- Frame it as observed, per the guiding constraint: this is where answers were sourced, not proof of
  what caused a recommendation.

**Done when:** a project with a measured audit shows its own owned/earned split, and each
opportunity is tagged Owned/Technical, Owned/Content, or Earned/<class>.

## Stage 3 — Source usage, and the earned worklist

**Why third:** this is the missing half of the product. It depends on Stage 2's classification.

- Add a `SourceUsage` projection: per third-party domain across a prompt set, how many answers cited
  it, on how many prompts, for which competitors, and whether the brand appears there at all. Usage
  % is `answers citing this domain / answers analysed` — a behavioural measure, deliberately not a
  domain-authority proxy.
- Add the first earned detectors, mirroring the reference worklist shape
  (`Source | Pathway | Usage | Gap | Owner | Action`):
  - `earned_source_competitor_cited` — a high-usage third-party source cites a competitor and never
    the brand.
  - `earned_profile_incomplete` — a review/marketplace source is a category source for this topic
    and the brand's presence there is absent or thin.
  - `earned_community_absent` — a community source recurs in answers for a topic with no brand
    presence.
- Add a versioned `EarnedProfileEvidence` projection for review and marketplace sources. For each
  project, brand entity, and canonical source domain, persist the observed profile URL and artifact
  IDs, `presence = present | absent | unavailable`, and
  `completeness = complete | incomplete | not_applicable | unavailable`, plus the field-level
  checklist, observation time, extractor version, and source-taxonomy version. A bounded profile
  lookup may establish absence; missing `Citation` rows may not. `earned_profile_incomplete` fires
  only from persisted `absent` evidence or `present + incomplete` evidence and abstains when the
  profile observation is unavailable.
- Each carries its source class as `pathway`, its usage %, and a suggested owner (PR, founder,
  marketing) so the output is a worklist rather than an observation.

**Explicitly out of scope:** automated outreach, and any claim that being cited on a source *causes*
a recommendation. CiteLadder names where answers are sourced and leaves the pitch to a human.

**Done when:** a project with competitor citations produces earned opportunities alongside owned
ones, ranked together by the Stage 1 score.

## Stage 4 — Recommendation strength

**Why fourth:** it sharpens the gap factor for every rule, owned and earned, once both sides exist.

- Add `recommendation_strength_by_entity` to `ResponseAnalysis`, keyed by the stable brand or
  competitor entity ID, with each value one of `recommended | hedged | mentioned |
  recommended_against | absent`. One answer can therefore recommend one competitor, merely mention
  the brand, and omit another competitor without collapsing those observations into one enum.
- Feed the brand's value and each relevant competitor's value into `gap_factor_visibility`: a
  competitor recommended while the brand is merely mentioned is a larger gap than the position
  delta shows, and a brand-specific `recommended_against` value is a distinct, urgent finding rather
  than a low score. Bump `SCORING_RULE_VERSION` only after the entity map and this consumer land
  together.
- This is the one stage needing a genuinely new analysis step rather than an aggregation. Scope it
  as a deterministic first pass over answer text, with an LLM stage only if that proves insufficient
  — the scorer is deterministic today and that property is worth keeping.

## Stage 5 — Triangulated measurement

**Why last:** it verifies the loop, so it needs the loop.

The reference model refuses to prove impact with a single metric, and combines three signals.
CiteLadder has all three and never reads them together:

| Signal | Question | Owner today |
|---|---|---|
| Crawl and citation | Are engines reaching and using us? | `Citation`, `ResponseAnalysis` |
| Human traffic | Are people arriving from AI? | `AiReferralsSnapshot` |
| Search demand | Is visibility showing up as branded demand? | `TrafficSnapshot`, GSC branded queries |

- Extend `OpportunityVerificationEvent` to record the before/after of all three around an
  implemented action, not just visibility.
- Report them side by side, and say plainly when they disagree. Three signals moving together is
  evidence; one moving alone is a lead.
- Honour `unavailable ≠ zero ≠ not-run` throughout — a project without GA4 has no traffic leg, and
  that must read as absent, not as failure.

---

## Sequencing

**1 → 2 → 3 → 4 → 5.** Stage 1 depends on shipped prompt work. Stage 3 depends on Stage 2's
classification. Stage 4 sharpens rules that Stages 1–3 must already produce. Stage 5 verifies what
Stage 3 makes actionable.

Stages 1 and 2 together already change the product's answer from "your score is 37" to "here is your
biggest gap, here is whether you can build your way out of it, and here is what to do first." That
is the point at which it stops looking random.

## Verification

Each stage lands with:

1. `.\scripts\check.ps1`.
2. `.\scripts\test.ps1`.
3. Unit tests for the pure projection or scoring change.
4. Contract tests for all three availability states — `unavailable`, observed zero, and `not_run` —
   asserting their distinct persisted values, API representations, and UI copy.
5. A component test proving the opportunity surfaces with correct provenance and version stamps.
6. `python reset-db.py`, re-onboard a real project, run an audit, and read the Opportunities screen
   top to bottom — the acceptance question is whether the first three rows are things a person would
   actually do this week.
