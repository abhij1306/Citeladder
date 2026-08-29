# Site Health measurement cutover

> **Status:** active approved implementation plan.
>
> **Scope:** three sequential pull requests. Start each PR only after the prior
> PR merges, using a fresh implementation chat.

**Next implementation slice:** PR2 after PR1 merges. PR3 remains blocked on the
preceding merge by design.

[../site-health.md](../site-health.md) is the canonical authority for Site
Health runtime behavior, measurement meaning, checkpoint applicability, score
and coverage formulas, and product boundaries. This plan owns only delivery
sequence, temporary cutover behavior, PR-specific manifests, and acceptance
criteria. If this plan and the canonical logic disagree, the canonical logic
wins and this plan must be corrected before implementation.

The repository-wide invariants in [../../AGENTS.md](../../AGENTS.md) and
[../invariants.md](../invariants.md) also apply. UI implementation follows
[../design.md](../design.md). No archived plan is implementation authority.

## Delivery policy

CiteLadder is pre-launch and does not preserve development database history.
PR1, PR2, and PR3 fold every schema change into
`migrations/versions/0001_initial.py`, reset the disposable development
database, and rebuild observations with the current code. Every active
development semantic identifier remains `1`; do not add a `0002+`, preserve
prior-score compatibility, backfill old analyses, or build dual read/write
paths.

Each PR must:

1. finish its complete gated slice before repository validation;
2. update [../site-health.md](../site-health.md) from target to shipped truth for
   behavior that merged;
3. remove superseded code, serializers, tests, flags, and active documentation;
4. preserve same-origin `/api/v1`, workspace authorization, immutable source
   evidence, and persisted read projections; and
5. leave deferred PR2/PR3 behavior explicitly unshipped rather than partially
   enabled.

## Grounded baseline for the cutover

The 2026-08-29 audit reviewed the current deterministic owners, a read-only
snapshot of the development database, and five live pages already represented
in that data. It found an inflation problem rather than persistence corruption:

- 353 of 565 measured pages (62.5%) had AEO 100; the median was 100;
- 203 perfect pages had only one applicable positive-weight AEO defect, and
  345 of the 353 perfect pages had no more than three;
- all 126 classified articles scored 100 and 70 of 73 categories scored 100;
- all five persisted crawl snapshots had partial acquisition coverage; and
- Evidence and Freshness could report 100% projection coverage while no page
  had a determinate check, because row presence—including N/A—was called
  coverage.

The public-page spot check confirmed both denominator and classification
problems. [tentree About](https://www.tentree.com/pages/about) and
[tentree Accessories](https://www.tentree.com/collections/accessories) each
received AEO 100 from one scored check despite many unmeasured capabilities.
[Allbirds News](https://www.allbirds.com/blogs/news) and the
[Asian School education archive](https://www.theasianschool.net/blog/category/education/)
were listings classified as articles. The
[Adored Vintage homepage](https://www.adoredvintage.com/) had materially richer
evidence but showed the same unqualified 100 presentation.

The persisted workspace/project/crawl/artifact/evaluation provenance was
internally consistent. The delivery sequence therefore reduces churn by
stabilizing current inputs and screens first, cutting over the new measurement
contract once, and expanding checkpoint breadth only after that contract is
visible in-product.

| Pull request | Owns | Deliberately defers |
|---|---|---|
| PR1 | Existing classifier/trait/rule bugs, sparse AEO-100 suppression, true current readiness coverage, Pages/AEO readability, supplied Architecture redesign | Overview, new persistence/scoring contract, Combined retirement, Content handoff, checkpoint-family registry |
| PR2 | One atomic measurement/API/persistence cutover, Overview, final Pages metrics, improved AEO UI, readiness-to-Content handoff | Broad new pillar/page-kind checkpoint coverage |
| PR3 | Robust seven-pillar evidence and applicability across all page kinds/traits, Web Fundamentals expansion, full calibration matrix | Formula or major UI redesign unless calibration proves a separate product-policy defect |

## PR1 — stabilize existing Site Health logic and screens

**Implementation status:** complete in the PR1 change set; repository validation
must pass before merge.

**Scope lock.** PR1 does not add the Overview tab, the new persisted AEO scoring
model, checkpoint-family registry, or the Content handoff. It improves
the shipped Pages, Architecture, AEO Readiness, and Changes surfaces and fixes
known bugs in the evidence, classification, applicability, coverage, and current
score presentation they already consume. Existing backend/frontend contracts
remain intact so PR2 has one deliberate cutover rather than two migrations.

### PR1 backend stabilization

- Normalize active identifiers to `sh-extractor-1`, `sh-classifier-1`,
  `sh-traits-1`, `sh-analyzer-1`, `sh-rules-1`, `sh-scoring-1`,
  `sh-coverage-1`, `sh-link-metrics-1`, `sh-architecture-1`, and
  `sh-archetypes-1`. These are resets of existing owners, not new subsystems.
  PR2 separately introduces the new expected-profile, schema-contract, and
  presentation-policy identifiers. Later PRs retain every value at `1`.

Freeze both meaning and score ownership for the unreliable proxies rather than
merely setting their weight to zero:

| Rule | PR1 `finding_class` | PR1 `score_roles` |
|---|---|---|
| `technical.single_h1` | `advisory` | `none` |
| `technical.thin_content` | `advisory` | `none` |
| `aeo.server_rendered_content` | `diagnostic` | `none` |
| `aeo.outbound_citations` | `advisory` | `none` |
| `aeo.date_present` | `advisory` | `none` |
| `aeo.no_expand_gating` | `advisory` | `none` |
| `technical.ai_crawler_access` | `diagnostic` | `none` |
| `aeo.answer_first` | `advisory` | `none` in PR1; PR2 may assign AEO under its strong gate |

These rows cannot feed defect counts, defect severity, defect Issues, or
defect-derived Opportunities while their finding class is advisory/diagnostic.
- Correct archive/listing classification so repeated linked-card collections
  such as `/blogs/news` and `/blog/category/...` do not become individual
  articles without article-owned body evidence.
- Separate page-owned `contact_intent` from site-wide footer/navigation contact
  affordances. A footer phone or email cannot activate a contact-page profile.
- Tighten current expectation applicability: page-kind-derived failures require
  page-owned structural evidence; route/title-only classifications may show
  conditional advisories but cannot fail or score an expectation.
- Remove Technical score weight from word-count-based thin content and
  exact-one-H1. They remain visible guidance, not objective integrity defects.
- Remove `aeo.outbound_citations` from guide-wide scoring/failure semantics,
  keep `aeo.date_present` non-scoring unless current evidence proves freshness
  is material, and constrain `aeo.answer_first` to proven FAQ/answer-task
  purpose. Evidence and Freshness may honestly remain not measured.
- Keep `aeo.no_expand_gating` advisory-only and correct any copy that claims
  server-present accordion text is inaccessible. Treat
  `aeo.server_rendered_content` as a non-scoring compatibility diagnostic in
  PR1; PR3 owns a real rendered-content-availability checkpoint.
- Keep training-crawler preferences out of Search eligibility and AEO scoring;
  unresolved `technical.ai_crawler_access` evidence is displayed as unknown.
- Fix the current AEO Readiness projection so coverage means determinate checks
  over expected checks. N/A row presence cannot produce 100% coverage.
- Preserve PR1's current stored outcome vocabulary, but treat N/A rows
  whose reason means uncertainty—including `coverage_not_complete`,
  `insufficient_evidence`, and `no_checkable_alternates`—as expected but
  non-determinate in coverage and presentation. They lower coverage and must
  not be labelled structurally not applicable. PR2 owns their persisted outcome
  replacement.
- Add a config-owned sufficiency guard in the current scorer and finalizer. PR1
  deliberately uses determinate checkpoint IDs and readiness dimensions only;
  checkpoint families do not exist until PR2. The temporary policy owns
  `PR1_AEO_MIN_DETERMINATE_CHECKPOINTS=4` and
  `PR1_AEO_MIN_DETERMINATE_DIMENSIONS=3`; a result below either minimum is
  internally treated as limited evidence. PR1 preserves the current
  API shapes: page, detail,
  page-kind, and crawl-summary `aeo_score` fields serialize `null`; the existing
  AEO route reports `state=incomplete` with a bounded limitation; and the UI
  renders **Not measured** rather than a numeric ratio. PR2 introduces the
  explicit `limited_evidence` measurement state. In particular, one passing
  server-rendering check cannot show AEO 100.
- Keep current persistence shapes and route contracts. PR1 may correct derived
  rows by resetting and recrawling the disposable development database; it does
  not add compatibility, backfill, or dual scoring paths.

### PR1 frontend improvements to existing screens

- **Pages:** preserve the current layout, filters, pagination, and row/detail
  interaction. Improve legibility and render corrected page kinds plus explicit
  `Not measured` and unavailable states instead of a misleading AEO 100. In
  PR1, a sparse current AEO result is represented by the existing nullable score
  contract rather than a new per-page state field. Do not perform the PR2
  metric-contract rename yet.
- **Architecture:** group URLs by the persisted `page_kind`; page family is not
  a second term. Show Page kinds, Pages, Median depth, Duplicate metadata, and
  Orphaned pages above page kind, pages, median depth, indexable, duplicate
  metadata, and orphaned columns. Remove URL-pattern and type-mix presentation.
  Only assigned URLs collapse. Render the persisted observed hierarchy and its
  parent evidence beneath the ledger without inferring relationships in the
  browser. Persisted Internal linking and Structure depth summaries use the
  supplied card layout, with detailed reports deferred to PR3.
- **AEO Readiness:** retain the existing dimension ledger and evidence drawer,
  improve typography/spacing and show determinate, expected, N/A, error,
  coverage, and limitations accurately. PR1 does not introduce the final AEO
  scalar, readiness-gap taxonomy, or Content action.
- **Changes:** preserve the existing design and correct only labels or states
  affected by the backend bug fixes.

### PR1 acceptance

- The fixture outcomes are exact: Allbirds News and the Asian School education
  archive each produce `page_kind=category` with `listing` in `page_traits`;
  tentree About produces `page_kind=about_contact` with `about_intent` and
  without `contact_intent` from footer chrome.
- A one-check or otherwise sparse AEO result cannot present 100 on Pages, page
  detail, AEO Readiness, or crawl summaries.
- Evidence and Freshness no longer claim full coverage when zero determinate
  checks ran.
- Uncertainty-coded N/A outcomes lower readiness coverage in PR1; the
  API shape remains unchanged, sparse AEO score fields are `null`, and the AEO
  projection reports `incomplete` with a limitation.
- The Architecture screen groups every observed URL under exactly one persisted
  page kind (including `other`) and no primary page-kind fact requires opening a
  dropdown. It renders the persisted observed parent hierarchy, and contains no
  URL-pattern family or type-mix terminology.
- Existing routes remain stable; the pre-launch Architecture projection contract
  cuts over atomically and the disposable database is rebuilt. The Overview
  route/tab and Content handoff remain absent.
- The database is rebuilt from `0001_initial.py`; all active versions are `1`.
- The PR atomically updates
  [the canonical Site Health runtime](../site-health.md) for the new version-`1`
  identifiers, exact classifier/applicability behavior, and current AEO
  coverage/sufficiency guard. Obsolete pre-PR1 runtime statements do not remain
  as active truth.

## PR2 — Overview, improved AEO foundation, and Content handoff

PR2 is the single atomic measurement-contract cutover. It implements the score,
coverage, applicability, persistence, aggregate, Overview, Pages-metric, AEO UI,
and Content-handoff contracts defined in
[the canonical Site Health logic](../site-health.md#approved-measurement-contract-target-not-shipped).
It deletes the Combined score and superseded serializers/tests in the
same PR; no compatibility scoring facade survives.

### PR2 initial readiness scoring manifest

PR2 reuses the evaluators stabilized in PR1 but scores only the following
defensible capabilities. `readiness_weight` is independent of Technical defect
weight and is used within the seven fixed dimension weights.

| Dimension | Family | Current rule | PR2 score-applicability gate | Within-dimension weight |
|---|---|---|---|---:|
| Answerability | `answer_content` | `aeo.answer_first` | structurally proven FAQ/answer-task purpose | 1.0 |
| Structure | `semantic_structure` | `aeo.question_headings` | structurally proven FAQ with determinately observed sections | 1.0 |
| Machine readability | `structured_representation` | `aeo.schema_expected_for_type` | page kind established by page-owned structure | 1.0 |
| Machine readability | `structured_representation` | `aeo.schema_required_valid` | relevant schema artifact triggers validation | 1.0 |
| Machine readability | `structured_representation` | `aeo.schema_recommended_present` | relevant schema artifact triggers completeness guidance | 0.5 |
| Machine readability | `structured_representation` | `aeo.schema_matches_content` | schema and visible page-owned content are determinate | 1.0 |
| Provenance & trust signals | `provenance` | `aeo.author_present` | structurally proven authored editorial purpose | 1.0 |
| Provenance & trust signals | `provenance` | `aeo.organization_identity` | structurally proven homepage/entity context | 1.0 |
| Crawlability | `indexability` | `technical.indexable` | known intended-public/indexable state | 1.0 |

The family IDs and meanings are owned by the canonical checkpoint-family
registry. All schema checks count as one family; duplicated checks cannot
manufacture breadth.

The following remain visible but no-score in PR2: word-count thin-content,
exact-one-H1, generic outbound citations, generic date presence, expand-gating,
duplicated structured-data presence, Open Graph, `llms.txt`, conflated AI-bot
access, initial-server-HTML compatibility, and HTTPS duplicated from Technical
Integrity/Web Fundamentals. Evidence and Freshness remain `not_measured` until
PR3 provides trustworthy evaluators. In PR2 they freeze `unresolved` for every
non-excluded page: PR2 has no evaluator capable of proving either dimension
irrelevant. Each therefore has null readiness, zero coverage, and remains in
the overall coverage denominator. PR3 may emit `not_applicable` only after a
dedicated applicability contract can freeze a deterministic irrelevance reason.

For every other dimension, an empty expected-checkpoint set follows the
canonical three-way rule. Proven irrelevance is `not_applicable`; proven
relevance without a score-applicable PR2 checkpoint is `applicable` and
`not_measured` with `no_expected_checkpoint_evaluator`; undecidable relevance
is `unresolved` and `not_measured` with `dimension_relevance_unresolved`.
An empty set cannot silently leave the coverage denominator.

### PR2 expected measurement distribution

PR2 is expected to render **Limited evidence**, not a numeric AEO headline, for
most pages and for most mixed-page sites. This is an intentional foundation
state rather than a regression:

- Evidence (15%) and Freshness (5%) have no trustworthy PR2 evaluator, are
  always unresolved for non-excluded pages, and contribute zero coverage.
- Non-FAQ pages have no PR2 evaluator for Answerability (20%) or Structure
  (15%). If those dimensions are applicable or unresolved, the best possible
  page coverage is 45%. If both are determinately not applicable, the best
  possible coverage is `45 / 65 = 69.23%`. Either ceiling is below
  `AEO_MEASURED_MIN_COVERAGE`.
- A qualifying page with determinate Answerability, Structure, Machine
  readability, Provenance, and Crawlability can meet
  `AEO_MEASURED_MIN_COVERAGE`. An ordinary FAQ with no independent provenance
  applicability evidence cannot: its empty Provenance expected set is
  unresolved, not silently N/A. The canonical breadth gates still apply.
- The site aggregate will normally remain limited when most selected pages have
  unresolved Answerability or Structure coverage. PR3 owns the missing
  page-purpose evaluators that make a broadly measured headline possible.

In this state, Overview's AEO card shows **Limited evidence**, AEO Measurement
Coverage, audited-page count, and a plain limitation explaining that PR3
expands page-purpose coverage. The calculated readiness ratio may remain in
persisted diagnostics but is not rendered as a headline. The seven-dimension
ledger still shows measured, not-measured, and unresolved evidence so PR2 is
useful without pretending the sparse manifest is complete.

PR2 Search eligibility uses only `acquisition.public_representation` and
`search.indexability` as critical checkpoints because they have determinate
healthy and blocker outcomes. `search.crawler_access` and
`search.snippet_access` remain persisted non-critical observations with
`unknown` reasons; they do not force the aggregate gate to `unknown`. PR3 ships
their dedicated evaluators and promotes them into the complete canonical
critical set. The Overview banner can therefore render `eligible`, `blocked`,
or `unknown` honestly in PR2.

### PR2 backend and persistence cutover

- Retain every existing active semantic identifier at `1`. PR2 introduces
  `sh-profiles-1` for the expected-checkpoint profile registry, `sh-schema-1`
  for the independently versioned schema/structured-representation contract,
  and `sh-presentation-1` for the new persisted measurement presentation
  policy. These are new config-owned authorities required by the new contract,
  not renames of existing PR1 owners or a second analyzer.
- `SitePageAnalysis` exposes `technical_integrity_score`,
  `technical_integrity_coverage`, `technical_integrity_state`,
  `aeo_readiness_score`, `aeo_measurement_coverage`, `aeo_measurement_state`,
  the frozen expected-checkpoint profile, and per-dimension summary.
  `overall_score` is removed, not renamed.
- Each readiness dimension persists `dimension_applicability`,
  `dimension_measurement_state`, nullable score, coverage, expected/determinate
  points, and a bounded reason. `not_measured` is never serialized as N/A.
- Audit every current N/A reason code during the atomic cutover. Only a bounded
  reason proving structural irrelevance remains `not_applicable`.
  `coverage_not_complete` and `no_checkable_alternates` become `unavailable`;
  `insufficient_evidence` becomes `unknown`. The audit is registry-wide rather
  than limited to Architecture rules, and each retained or changed reason is
  pinned by a deterministic fixture.
- `SiteRuleEvaluation` freezes display applicability, score applicability,
  expected-profile membership, bounded reason code, and distinct determinate,
  unknown, unavailable, conflicting, error, N/A, and excluded outcomes.
- `SiteHealthSnapshot` stores pooled crawl measurements, eligibility totals,
  crawl coverage, source manifests, and the four Pages status counts. It pools
  readiness points rather than averaging page scores. It first normalizes
  measurement coverage within each dimension and then applies each configured
  dimension weight once. Aggregate states are derived from pooled evidence and
  breadth uses unique checkpoint IDs, families, and readiness dimensions—not
  page-rule occurrence counts.
- Search eligibility is intentionally not a `SitePageAnalysis`-only field.
  `SiteHealthSnapshot` freezes the aggregate gate, per-state page totals,
  per-critical-checkpoint reasons, and exact acquisition task/attempt, artifact,
  analysis, and evaluation source IDs. PR2 configures
  `SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1` with
  `acquisition.public_representation` and `search.indexability` only. This
  covers blocked URLs that never produced a successful analysis while keeping
  `eligible` reachable. Deferred crawler/snippet observations persist outside
  the critical set until PR3. Overview only renders the persisted projection;
  it does not derive the gate at read time.
- Persist and serialize `authority` as the stable dimension key while rendering
  **Provenance & trust signals** as its label. PR2 changes the label and
  measurement contract, not the machine identity.
- `SiteCrawl.score_summary`, if still required for lifecycle polling, is only a
  serializer projection of the snapshot and is equivalence-pinned; it owns no
  formula.
- Reads remain persisted projections. No Overview, Pages, Architecture, AEO,
  Changes, or handoff read crawls, repairs, or recalculates measurement.

The cohesive Overview projection is:

```text
search_eligibility
technical_integrity
aeo_readiness
aeo_measurement_coverage
crawl_coverage
aeo_dimensions[]
top_issues[]
web_fundamentals
trend
change_summary
```

`aeo_measurement_coverage` qualifies AEO Readiness. Technical Integrity carries
its own coverage/state. Crawl Coverage is separate and includes denominator
kind/evidence. Partial or unknown acquisition permanently labels the aggregate
**AEO Readiness — audited pages** with analyzed-page count; it never implies
whole-site readiness.

Top issues use the stable ordering `(eligibility_blocker desc, impact_band
desc, finding_class defect-before-gap, affected_pages desc, rule_id asc)`.
Defects use config-owned severity; readiness gaps use config-owned checkpoint
impact. Trend/change summaries compare only rows created inside the same reset
database and version-`1` contract.

### PR2 frontend cutover

The tab order becomes **Overview**, **Pages**, **Architecture**, **AEO
Readiness**, and **Changes**, with Overview as the default after a usable crawl.

- **Overview:** implement the supplied hierarchy: Search eligibility banner;
  peer cards for Technical Integrity, AEO Readiness, AEO Measurement Coverage,
  and Crawl Coverage; seven-row readiness ledger beside Top issues; Web
  Fundamentals, trend, and change summary below. Technical and AEO cards show
  their coverage/state. There is no Combined score.
- **Pages:** preserve the PR1 design and interactions; change only metrics to
  Technical Integrity, AEO Readiness, AEO Measurement Coverage, Issues, Inbound
  links, and Main-content indexable. Remove Combined from table, detail, sorts,
  exports, and page-kind rollups.
- **AEO Readiness:** lead with AEO score, coverage/state, affected-page count,
  and limitations. Follow with the seven-dimension ledger and readiness-gap
  list. Every row distinguishes dimension applicability from measurement state,
  so `Not measured` never renders as N/A. Selecting a dimension/gap opens
  bounded persisted page evidence with observed evidence, expected capability,
  and remediation.
- **Architecture and Changes:** preserve the PR1 designs and consume the final
  names/states without another redesign.

### PR2 AEO Readiness → Content handoff

Content-addressable readiness gaps expose **Improve in Content** in the AEO
evidence drawer. Technical, crawler-policy, schema-implementation, security, and
other non-content gaps do not show that action.

The action navigates to the existing Content workflow with a typed reference to
persisted Site Health evidence:

```text
project_id, crawl_id, site_url_id, source_analysis_id,
dimension, checkpoint_ids[]
```

The route carries stable IDs, not an untrusted evidence blob. An authorized
read-only handoff projection resolves those immutable rows and returns the
bounded frozen context: finding class, observed evidence, expected capability,
remediation, page kind, page traits, and scoring policy version `1`. Content
consumes that context when the user explicitly starts the workflow; it does not
recrawl, reinterpret the score, create another finding owner, or publish
autonomously. Site Health remains the evidence owner, Content remains the
creation owner, and Opportunities remains the cross-product prioritization
owner. Crawl observations remain untrusted observations rather than confirmed
brand facts; the existing Content grounding and claim-validation rules still
apply.

### PR2 calibration and acceptance

- Conditional display guidance cannot alter a score unless its independent
  score-applicability gate passes.
- Expected checkpoints are frozen before evaluation; unknown cannot become N/A
  without a deterministic structural reason.
- Unknown changes coverage, never readiness credit; missing advisories can
  lower AEO Readiness without becoming Technical defects.
- Applicable/unresolved but unsupported dimensions remain `not_measured` with
  zero coverage; they cannot disappear as N/A or raise AEO coverage.
- Every current N/A reason is classified during cutover: uncertainty becomes
  `unknown` or `unavailable`, while only proven structural irrelevance remains
  `not_applicable`. Coverage-incomplete Architecture and sitemap-orphan absence
  claims are `unavailable`, not N/A; a sitemap-orphan check on a site with no
  sitemap remains structurally not applicable to that specific rule.
- Technical Integrity cannot present a headline ratio unless its own state is
  `measured`, every critical expected Technical checkpoint is determinate, and
  Technical coverage meets the canonical
  `TECHNICAL_MEASURED_MIN_COVERAGE`. Fixtures directly below and at the
  configured boundary pin the decision.
- No sparse page presents a measured 100. Page and pooled crawl breadth obey
  `AEO_MEASURED_MIN_CHECKPOINTS`, `AEO_MEASURED_MIN_FAMILIES`, and
  `AEO_MEASURED_MIN_DIMENSIONS`; page and crawl totals reproduce persisted
  points.
- Aggregate measurement coverage first combines selected pages within each
  dimension and then applies the seven dimension weights once. A fixture with
  materially different per-dimension page counts proves that page frequency
  cannot change the configured 20/15/15/20/10/5/15 influence.
- Evidence and Freshness are unresolved—not N/A—for every non-excluded PR2
  page. A homepage fixture that would otherwise remove those dimensions proves
  they remain in the denominator and cannot inflate coverage.
- An FAQ with no independent Provenance applicability evidence freezes
  Provenance as unresolved with `dimension_relevance_unresolved`; its empty
  expected set cannot become N/A. A separate fixture whose independent
  Provenance gate passes may meet `AEO_MEASURED_MIN_COVERAGE` only when all
  canonical critical and breadth gates also pass.
- A healthy non-FAQ page and a mixed site dominated by non-FAQ pages both
  produce `limited_evidence`, expose their coverage and limitations, and show no
  numeric AEO headline.
- A healthy intended-public URL with determinate acquisition and indexability
  is `eligible` in PR2 even while crawler/snippet observations are unknown. A
  contradiction in either PR2 critical checkpoint is `blocked`; missing or
  indeterminate evidence in either makes the gate `unknown`.
- A robots-denied intended-public URL with no `SitePageAnalysis` still makes the
  persisted Search eligibility projection `blocked` with exact acquisition
  provenance; the Overview read performs no derivation.
- The Overview and AEO screens match the supplied hierarchy and expose limited,
  unavailable, partial-crawl, and not-measured states honestly.
- **Improve in Content** appears only for content-addressable persisted gaps and
  arrives in the existing Content workflow with workspace-authorized context.
- The disposable database rebuilds from `0001_initial.py`; every active version
  is `1`; no Combined or compatibility scoring path remains.
- The PR atomically updates
  [the canonical Site Health runtime](../site-health.md): Technical alone remains
  defect-only; declared applicable defects/advisories may score AEO; the AEO
  route exposes score/coverage/state; the tab list includes Overview; and the
  Content boundary records the typed Site Health handoff. Superseded pre-PR2
  runtime statements are removed or rewritten.

## PR3 — robust AEO pillars and page-kind coverage

PR3 keeps the PR2 formula, persistence interface, Overview hierarchy, AEO UI,
and Content-handoff interface stable. It improves the facts and applicability
behind them so coverage is robust across all 15 page kinds and relevant traits.

- **Answerability:** add purpose-essential facts, direct answers/definitions,
  useful summaries, and task outcomes only for page purposes that warrant them.
- **Structure:** add semantic heading sequence, meaningful lists/tables,
  question-answer relationships, listing organization, and content hierarchy
  without exact-one-H1 or stylistic length proxies.
- **Evidence:** add claim/research sensitivity, source attribution, comparison
  basis, case-study methodology/results, and concrete support. Generic outbound
  links never substitute for evidence quality.
- **Machine readability:** distinguish rendered primary content from initial
  server HTML, validate entity clarity and schema/content parity, and use
  publisher/feature-specific schema contracts rather than generic presence.
- **Provenance & trust signals:** deepen creator/organization identity,
  credentials/profile paths, responsible publisher, and policy ownership only
  where the page purpose makes them applicable.
- **Freshness:** measure accurate publication/update/version signals only when
  freshness is material; generic date presence is not sufficient.
- **Crawlability:** split search/citation crawlers from training bots and add
  response/soft-error, snippet-control, crawlable-link/target, pagination,
  facet, canonical-cluster, hreflang, sitemap, and coverage-qualified orphan
  evidence. Once `search.crawler_access` and `search.snippet_access` can each
  produce determinate healthy and blocker states, add them to
  `SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1` and rebuild the disposable
  database; the active identifier remains `1` under the reset policy.
- Deepen all page-kind/trait profiles, including listing completeness,
  product/offer consistency, about/contact separation, local/service intent,
  procedural guides, comparisons, reviews/case studies, docs, FAQs, pricing,
  and trust/policy pages. `other` remains abstention.
- Add deterministic Accessibility, Mobile, Security, and lab diagnostics while
  field Core Web Vitals remain unknown until a real persisted provider exists.
- Add healthy, broken, weak-classification, JS-shell, non-HTML, and conflicting
  fixtures for every kind and applicable pillar, plus public calibration pages
  for kinds absent from the current corpus.
- Extend the PR2 Content handoff only to newly content-addressable gaps; the
  typed interface and ownership do not change.
- Keep every active version at `1`, fold schema changes into
  `0001_initial.py`, reset the disposable database, and rerun the calibration
  crawls. PR1/PR2 rows are not preserved or backfilled.

PR3 is complete when every page kind has an explicit expected profile,
healthy/broken fixtures, deterministic score/display applicability, and honest
N/A/unknown behavior for every potentially relevant pillar. Coverage expansion
must improve explainability and monotonicity; it is never tuned to manufacture
a preferred score distribution. The PR also removes or rewrites each shipped
known-analyzer-gap statement in
[the canonical Site Health runtime](../site-health.md) that its new capability
supersedes. The canonical document must describe the post-PR3 runtime rather
than retain resolved limitations as active truth.
