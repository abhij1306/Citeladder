# Site Health measurement reliability — PR4

> **Status:** implementation and local acceptance complete. Repository gates,
> disposable-database migration verification, deterministic calibration, and
> browser acceptance have been observed. Live Searchable and Flourist crawls
> remain an external release prerequisite because this repository contains no
> runnable live-crawl recipe or provider data for those sites.
>
> **Dependency:** implemented after the PR1–PR3 cutover in
> [`site-health-measurement-cutover.md`](site-health-measurement-cutover.md).
> PR4 is not live-calibrated or releasable until the two named live crawls are
> actually observed; offline labelled cases are not a substitute.
>
> **Delivery shape:** one atomic PR with four dependency-ordered internal slices.
> The slices are implementation checkpoints, not independently shippable
> contracts or partially enabled runtime modes.

[`../site-health.md`](../site-health.md) is the authority for the implemented
Site Health runtime. This plan records the PR4 reliability contract and its
remaining completion gates; it is not a second runtime scorer, projection, or
presentation authority.

The repository-wide rules in [`../../AGENTS.md`](../../AGENTS.md) and
[`../invariants.md`](../invariants.md) apply. Backend ownership remains the
single page-understanding seam described in
[`../backend-architecture.md`](../backend-architecture.md); frontend work follows
[`../frontend-architecture.md`](../frontend-architecture.md) and
[`../design.md`](../design.md).

## Decision

PR3 established the seven-dimension measurement and presentation contract. The
implemented PR4 cutover retains it rather than introducing Topical Authority,
Information Gain, or a new Site Health model. Its code addresses the trust
defects exposed by live post-PR3 crawls:

1. page-kind evidence produced false listings and excessive abstention;
2. overloaded or page-wide facts evaluated the wrong content;
3. rule count manufactured capability influence;
4. AEO measurement coverage did not disclose unresolved page purpose; and
5. `other` pages displayed a page-purpose AEO scalar despite classification
   abstention.

The seven dimensions remain **Answerability**, **Structure**, **Evidence**,
**Machine readability**, **Provenance & trust signals**, **Freshness**, and
**Crawlability**. Scores are never tuned toward a preferred brand or
distribution. A lower calibrated score is acceptable when its evidence and
coverage are more truthful.

Dimension identity and presentation use one config-owned mapping:

| Dimension ID | Display label |
|---|---|
| `answerability` | Answerability |
| `structure` | Structure |
| `evidence` | Evidence |
| `machine-readability` | Machine readability |
| `authority` | Provenance & trust signals |
| `freshness` | Freshness |
| `crawlability` | Crawlability |

`authority` is the stable internal identifier; **Provenance & trust signals** is
only its display label. No second `provenance` dimension or label map is
introduced.

## Grounded baseline

The 2026-08-30 read-only audit examined the current implementation, immutable
normalized facts, rule evaluations, snapshots, and two completed development
crawls.

| Site | Analyzed | Crawl coverage | Web Fundamentals | AEO Readiness |
|---|---:|---|---:|---:|
| Searchable | 183 | partial | 95.8 at 92.5% coverage | 88.9 at 99.1% coverage |
| Flourist | 200 | partial | 92.8 at 92.1% coverage | 78.9 at 96.7% coverage |

The persisted Searchable dimension results reproduce the stored 88.9 score
under the shipped formula. The arithmetic is not the primary defect.

Searchable exposed the reliability failures:

- 81 of 183 analyzed pages (44.3%) were `other`, so only 102 pages (55.7%)
  received a purpose-specific profile while AEO measurement coverage reported
  99.1%;
- `docs.searchable.com` contained 37 `other`, two `category`, and one `docs`
  page;
- the exact `/blog` archive was `article`;
- all 11 `category` assignments were inconsistent with the observed page
  purpose: six article details, two documentation pages, two feature pages, and
  one solutions page;
- editorial lead checks frequently read publication metadata instead of the
  first substantive page-owned paragraph;
- AEO heading evidence mixed page-owned headings with navigation, footer, and
  repeated-module headings;
- generic non-social external links could earn source-support credit without a
  deterministic source relationship; and
- `other` pages reported numeric AEO readiness even though the UI described
  their page-purpose measurement as unresolved.

These are calibration observations, not target score distributions.

## Scope lock

PR4 includes only the reliability cutover required to correct those findings:

- classifier evidence locality and bounded recall improvements;
- page-purpose fact separation;
- explicit checkpoint semantic accounting;
- fixed-budget AEO capability families;
- classification coverage in persisted crawl projections;
- non-scoring `other` page-purpose AEO results;
- synchronized persisted APIs and Site Health presentation; and
- direction-neutral calibration and regression evidence.

PR4 does **not**:

- add a second page-family concept, page-analysis owner, crawler, evidence
  store, rule store, score store, or read-time derivation;
- add a model classifier or let structured data self-certify page kind;
- add weak evaluators merely to fill an unavailable family profile;
- add canonical/equivalence score entities or body-digest duplicate collapse;
- add cluster- or graph-scoped AEO families;
- add separate `unavailable` or `conflicting` checkpoint outcome states;
- infer claim support with an LLM or lexical claim detector;
- redesign Web Fundamentals or field Core Web Vitals;
- change Search eligibility critical checkpoints;
- add Topical Authority, Information Gain, or a replacement top-level Site
  Health score;
- retune the seven dimension weights to raise or lower observed scores;
- preserve pre-PR4 development history, add a `0002+` migration, increment an
  active semantic version above `1`, backfill, or retain compatibility scoring;
  or
- ship an internal slice independently.

## Shared contracts

### One page-understanding seam

`analysis/site_health/page_analysis.py` remains the external seam. Its
implementation may gain cohesive internal fact and scoring modules, but callers
continue to provide immutable normalized facts plus crawl context and receive
one page understanding with classification, traits, evaluations, and scores.
Workers do not reconstruct policy.

### Evidence before outcome

```text
immutable artifact
  -> bounded page-owned facts
  -> deterministic page_kind + independent traits
  -> frozen classified-kind × trait × family profile
  -> checkpoint outcomes
  -> fixed-budget capability families
  -> dimensions and overall AEO Readiness
  -> persisted page/crawl/snapshot projections
```

Context decides expectation; evidence decides outcome. Missing evidence never
turns itself into N/A. Structured data can corroborate classification and can be
validated after classification, but it cannot alone choose the type whose
schema contract is scored.

### Executable family profile

The canonical classified-kind profile is one serializable, snapshot-testable
config artifact. Each row has this exact semantic shape:

```text
page_kind
trait_condition
family_id
status: measured | measurement_gap | not_applicable
checkpoints:
  - checkpoint_id
    internal_weight
reason
```

Trait conditions are bounded config identifiers, not service callbacks. Every
classified kind enumerates every family in the fixed manifest; omission does
not imply N/A. `measured` rows name their checkpoint expressions and frozen
internal weights. `measurement_gap` and `not_applicable` rows name no
checkpoints and require a bounded reason.

Family ownership supplies the dimension; the profile does not repeat a
dimension field. Derive `expected_checkpoints()`, `expected_families()`,
`relevant_dimensions()`, and `measurement_gap_reasons()` only from this
artifact. A family is expected when its status is `measured` or
`measurement_gap`; a dimension is relevant when it owns at least one expected
family.

`other` is the explicit exception because it is classifier abstention, not a
page-purpose profile. It instantiates no AEO family rows and returns
`not_measured` with `page_purpose_unresolved`.

Catalog assembly validates the artifact against the fixed taxonomy and family
manifest below. A deterministic sorted serialization is snapshot-tested so
classifier/profile logic, evaluator applicability, scoring, API explanations,
and UI copy cannot acquire parallel maps.

### Outcome-state contract

Checkpoint outcomes use six states:

- `satisfied`: complete inspection proves the expectation;
- `partial`: complete inspection proves only the configured partial contract;
- `missing`: required evidence was inspectable but absent or deterministically
  defective;
- `unknown`: evidence is insufficient, unavailable, ambiguous, or conflicting;
- `not_applicable`: independent context proves semantic irrelevance; and
- `error`: evaluator execution failed before a semantic result.

The outcome controls scoring; a bounded `reason_code` preserves diagnostic
detail. Examples include `primary_content_unavailable`,
`conflicting_schema_entities`, and `ambiguous_source_attachment`. Those reasons
do not become additional first-class states in persistence, APIs, UI, exports,
or rollups.

A deterministically validated defect is `missing` or `partial`, never
`unknown`. Complete primary-content inspection with no candidate source is
`missing`; ambiguous source attachment is `unknown` with
`ambiguous_source_attachment`; failed extraction is `unknown` with
`primary_content_unavailable`.

Profile `measurement_gap` is not a checkpoint outcome. Crawl/inventory
exclusion is eligibility policy outside the AEO outcome taxonomy.

### Complete semantic accounting, not manufactured determinacy

Every classified `page_kind` × trait condition × capability-family row declares
exactly one profile status:

- `measured` with deterministic checkpoint expressions;
- `measurement_gap` with a bounded evaluator-gap reason; or
- `not_applicable` with a semantic irrelevance reason.

There is no determinacy percentage gate. PR4 requires 100% profile accounting,
not 100% determinate evidence. The six checkpoint outcome counts and every
measurement-gap reason remain calibration outputs. `other` bypasses this matrix
and produces no page-purpose AEO score.

### Classification coverage

Classification coverage is a crawl/snapshot projection, not a second fact on
`SitePageAnalysis`. Analysis completion cannot shrink its denominator:

```text
classification_expected_page_count =
    selected, non-excluded, successfully acquired supported HTML pages
    assigned to page understanding

classified_page_count =
    classification-expected pages with a terminal page_kind != other

other_page_count =
    classification-expected pages with a terminal page_kind == other

classification_error_page_count =
    classification-expected pages without a terminal classification
    because page understanding failed

classification_expected_page_count =
    classified_page_count
    + other_page_count
    + classification_error_page_count

classification_coverage =
    null when classification_expected_page_count == 0
    else classified_page_count / classification_expected_page_count
```

Assignment to page understanding is recorded when successful acquisition makes
page-purpose analysis expected, before parsing, fact extraction, classification,
or analysis persistence begins. A JS shell is assigned and remains in the
denominator; it normally terminates as `other` with its rendering limitation.
Any post-acquisition failure before terminal classification increments
`classification_error_page_count`, including parser, fact, classifier, or
persistence failure. Crawl or analysis coverage does not make that page
disappear. Failed acquisition and supported non-HTML inventory remain outside
this denominator and are represented by Search eligibility and crawl coverage.

The immutable terminal snapshot freezes all four counts, ratio, bounded reason
groups from `page_kind_evidence` and classification errors, and exact source
artifact/execution/analysis IDs. The active `SiteCrawl.score_summary` mirrors
the same aggregation owner. Reads never derive or repair the projection.

### Fixed-budget AEO capability families

Rule count must not create score influence. Each readiness-scored checkpoint
belongs to exactly one family; each family has one dimension, one scope, and one
fixed budget. Family budgets within each dimension sum to `1`. Any family,
ownership, scope, budget, or internal-weight change is a scoring-contract change
and requires direction-neutral calibration evidence.

This is the complete PR4 family manifest:

| Dimension ID | Family ID | Budget | Scope | Checkpoints |
|---|---|---:|---|---|
| `answerability` | `answer_content` | `1` | page | `aeo.editorial_lead_present`, `aeo.answer_first`, `aeo.entity_value_proposition`, `aeo.product_answer_facts`, `aeo.listing_answer_set` |
| `structure` | `semantic_structure` | `1` | page | `aeo.heading_hierarchy`, `aeo.question_headings` |
| `evidence` | `source_support` | `1/2` | page | `aeo.source_support_present` |
| `evidence` | `commerce_facts` | `1/2` | page | `aeo.product_evidence_facts`, `aeo.listing_item_facts` |
| `machine-readability` | `structured_representation` | `1` | page | `aeo.schema_expected_for_type`, `aeo.schema_required_valid`, `aeo.schema_recommended_present`, `aeo.schema_matches_content` |
| `authority` | `visible_attribution` | `1/2` | page | `aeo.visible_attribution`, `aeo.product_brand_identity` |
| `authority` | `site_identity` | `1/2` | site | `aeo.organization_identity`, `aeo.trust_path_present` |
| `freshness` | `currency` | `1` | page | `aeo.content_date_present`, `aeo.offer_freshness_signal`, `aeo.assortment_freshness_signal` |
| `crawlability` | `indexability` | `1/3` | page | `technical.indexable` |
| `crawlability` | `snippet_access` | `1/3` | page | `search.snippet_access` |
| `crawlability` | `crawler_access` | `1/3` | site | `search.crawler_access` |

Equal shares are the direction-neutral baseline where a dimension has multiple
independent families. The profile selects which family checkpoints are expected
for a kind and trait context. Alternative kind-specific expressions receive
internal weight `1`. FAQ Structure selects both heading expressions at `1/2`
each. `site_identity` selects its two expressions at `1/2` each when both are
expected.

`structured_representation` is guarded. If expected schema is absent,
`aeo.schema_expected_for_type` resolves the family as determinate `missing`. If
present, the guard adds no separate credit and activates
`schema_required_valid=1/2`, `schema_matches_content=1/3`, and
`schema_recommended_present=1/6`.

The active source-support and visible-attribution checkpoint names are
clean-cutover contracts. Generic outbound-link and metadata-authorship proxies
do not survive as aliases, and a profile gap cannot add a placeholder
checkpoint to manufacture coverage.

#### Page-kind macro scoring

Page-scoped families aggregate directly:

```text
checkpoint outcomes
  -> family score and coverage per page
  -> mean within page kind
  -> equal macro mean across expected page kinds
  -> fixed family budgets within dimension
  -> existing dimension weights
  -> AEO Readiness
```

Coverage follows the same path. For any weighted set, `quality_mean` uses only
determinate `satisfied`, `partial`, and `missing` outcomes, while `coverage` is
determinate expected weight divided by total expected weight:

```text
credit(satisfied)=1
credit(partial)=0.5
credit(missing)=0

page_family_score =
    quality_mean(checkpoint credits, internal checkpoint weights)
page_family_coverage =
    determinate checkpoint weight / expected checkpoint weight

kind_family_score =
    quality_mean(page family scores, page family coverages)
kind_family_coverage =
    mean(page family coverage for expected pages)

family_score =
    quality_mean(kind family scores, equal kind weight * kind family coverage)
family_coverage =
    mean(kind family coverage for expected page kinds)

dimension_score =
    quality_mean(family scores, family budget * family coverage)
dimension_coverage =
    sum(family budget * family coverage)
    / sum(family budget for expected families)

overall_aeo_readiness =
    quality_mean(dimension scores, dimension weight * dimension coverage)
overall_aeo_measurement_coverage =
    sum(dimension weight * dimension coverage)
    / sum(dimension weight for expected dimensions)
```

A `measurement_gap` family has no quality score and coverage `0`. `unknown` and
`error` checkpoint outcomes reduce coverage and receive no quality credit or
penalty. `not_applicable` leaves the expected set. Missing remains determinate
with zero credit.

Every `quality_mean` is `null` when its determinate weight is zero. Coverage is
`null` when its expected weight is zero. No `null` becomes `0`, `100`, or N/A
during rollup.

The page-kind macro is fixed and equal: adding more pages of one kind can refine
that kind’s mean but cannot increase its cross-kind vote. Site-scoped families
are evaluated once and enter their owning dimension directly. PR4 introduces no
duplicate-page grouping layer.

Aggregate measurement state is:

```text
not_measured      expected weight > 0 and determinate weight == 0
limited_evidence  0 < determinate weight < expected weight
measured          determinate weight == expected weight > 0
```

For `other`, score and coverage are `null`, state is `not_measured`, and reason
is `page_purpose_unresolved`.

### Atomic merge, reviewable commits

PR4 is one atomic **merge contract**, not one atomic implementation diff. Build
it as four dependency-ordered, reviewable commit groups matching the internal
slices:

1. page-owned facts and classifier calibration;
2. executable family profile and checkpoint semantics;
3. family scorer, page-kind macro rollup, persistence, and backend contract; and
4. frontend projection, calibration evidence, and superseded-path removal.

Each commit group must pass its focused owner tests, preserve provenance, and
contain no stub, dual-write, compatibility scorer, or dead alternate path. The
repository is not releasable and no slice ships independently before commit
group 4 completes the clean cutover and the full repository gates pass.

## Internal slice 1 — evidence and classifier reliability

### Goal

Repair known false classifications and introduce calibrated facts before any
checkpoint or scoring formula changes.

### Classifier calibration manifest

Add a test-owned labelled manifest using bounded sanitized fixtures. It records:

- source label and observation date;
- expected `page_kind` or deliberate `other`;
- expected traits;
- allowed deciding evidence tier;
- competing kinds that must be rejected; and
- the structural reason for the expected result.

Include Searchable and Flourist patterns plus healthy, broken, ambiguous,
conflicting, JS-shell, and non-HTML cases across the fixed taxonomy. Tests never
fetch public pages. No product table stores calibration labels.

Calibration reports per-kind precision, recall, and observed abstention, plus
correct abstention on deliberately ambiguous fixtures. Exact labelled fixture
outcomes are the gate; PR4 does not tune a global probability threshold.

### Collection-bound listing facts

Update the existing region/entity fact implementation so a collection signal
requires its evidence to belong to the same page-owned collection:

- bind result count, sorting, filtering, facets, pagination, and empty state to
  the candidate card/list container;
- require controls to name, target, contain, or be structurally adjacent to that
  collection under a bounded deterministic relation;
- exclude ordinary editorial phrases such as “13 products” from result-count
  evidence;
- exclude navigation, footer, aside, recommendation, and unrelated form
  controls;
- retain collection size and distinct crawlable targets as observations rather
  than independent category verdicts; and
- persist bounded evidence naming the matched container and affordance class,
  never a raw selector or unbounded DOM fragment.

A blog detail with a large related-card module, a numeric product/result phrase,
or an unrelated sort-like control must remain an article when its page-owned
article evidence is stronger.

### Page-owned editorial and heading facts

Replace the overloaded shared lead/answer fact with separate facts:

- `editorial_lead`: first substantive page-owned paragraph after identity and
  publication metadata, excluding byline, date, breadcrumb, badge, card, and CTA
  text;
- `direct_answer`: answer/definition text structurally associated with the
  relevant question or definition heading;
- `entity_proposition`: entity identity plus page-owned audience, capability, or
  outcome copy; and
- `primary_heading_outline`: ordered headings inside primary content, excluding
  chrome and repeated-card modules.

Do not silently change the document-wide Web Fundamentals heading rule in this
slice. AEO consumes `primary_heading_outline`; the separate objective
accessibility contract remains unchanged unless independently re-specified.

### Ordered classifier repair

Implement in this order:

1. remove false structural category/listing evidence;
2. recognize exact archive roots such as `/blog`, `/blogs`, and `/news` only
   when page-owned collection evidence exists;
3. add documentation host context as corroboration, never as a verdict; and
4. add a service/capability expression only after the known false-positive
   corpus is green.

Documentation context may combine a docs/developer host with independently
observed hierarchy, documentation navigation, breadcrumb/isPartOf structure,
reference/task semantics, or page-owned technical content. A documentation host
can contain hubs, details, changelogs, and other purposes; every labelled
fixture must receive its own expected kind.

Service/capability evidence remains industry-neutral: named capability or
service, provider/entity, audience or outcome, and an acquisition/next-action
path. Feature, platform, workflow, solution, and use-case route vocabulary is
route evidence only.

### Slice 1 acceptance

- Every labelled fixture produces its exact expected kind, traits, deciding
  signal, and permitted confidence label.
- Searchable’s six misclassified blog details are not categories.
- The exact Searchable blog archive is a category only because its observed
  collection corroborates the archive route.
- Searchable documentation fixtures receive their individually labelled kinds;
  host alone classifies none.
- Incidental result copy, recommendation cards, and unrelated controls cannot
  produce a listing verdict.
- Remaining `other` fixtures retain bounded `no_signals`, `schema_only`, or
  conflict evidence rather than a forced guess.
- No checkpoint, scoring formula, API field, or UI behavior changes in this
  slice.

## Internal slice 2 — checkpoint semantic repair

### Goal

Make every scored checkpoint state exactly what it measures, then account for
all classified-kind family profiles without inventing weak evaluators.

### One config-owned family profile

Implement the executable family profile defined in the shared contract. Derive
checkpoint expectation and dimension relevance from family ownership and row
status; do not retain parallel kind × dimension or applicability maps.

Catalog/profile assembly fails when:

- a classified taxonomy kind omits a family;
- a `measured` row names no implemented checkpoint;
- a `measurement_gap` row lacks a bounded evaluator-gap reason;
- a `not_applicable` reason describes uncertainty rather than irrelevance;
- a triggered quality check has no same-family absence/root sibling; or
- a rule’s finding class, score role, family, dimension, and applicability
  contract disagree.

The profile is complete without implementing every gap. `measurement_gap` is
permitted only when no deterministic evaluator exists and must carry a specific
reason; no weak evaluator is added merely to improve coverage.

### Deterministic source support

The generic outbound-link scored proxy is retired. A supporting source
is observed only when an external reference appears inside primary content and
at least one bounded deterministic relationship holds:

- the reference is inside a References or Sources section;
- the reference is inside a Methodology section;
- a local citation/reference marker is structurally adjacent; or
- nearby visible text explicitly attributes the named source.

All markers, section vocabularies, adjacency bounds, and evidence caps are
config-owned. A generic external link, social profile, navigation link, partner
logo, or footer link never qualifies. PR4 does not identify arbitrary factual
claims or infer whether a source proves one.

Applicability comes from independent research-sensitive context such as a
comparison, observed methodology/references section, case-study/review trait,
or explicitly time-bound report purpose. When that context requires support,
complete primary-content inspection with no candidate source yields `missing`.
A candidate source whose deterministic attachment is ambiguous yields `unknown`
with `ambiguous_source_attachment`; unavailable primary-content extraction
yields `unknown` with `primary_content_unavailable`. Deterministically invalid
or contradictory support markup is a quality defect with a bounded `missing`
reason. If no trustworthy evaluator exists, the family profile declares
`measurement_gap`.

### Independent freshness applicability

Freshness applicability is decided before reading the date being scored. Valid
independent contexts include:

- product offer or assortment state;
- pricing/billing state;
- version-specific documentation;
- changelog/release purpose;
- news/current-event purpose;
- time-bound report; or
- explicit year/version semantics in page identity or structural context.

Date presence cannot make freshness applicable by itself, and date absence
cannot make freshness irrelevant. Once expected, persisted publication,
modification, effective, offer-validity, or version evidence determines the
outcome.

### Attribution, schema, and extractability

- Visible named creator/responsible publisher and schema/metadata attribution
  are separate atoms. Metadata-only attribution cannot earn full visible
  provenance credit; explicit deterministic partial credit is permitted.
- Associate structured-data validation with primary schema entities and their
  declared relationships. A page-wide union of types does not activate a
  purpose-specific validator.
- `BreadcrumbList`, generic `Article`, or generic `WebPage` cannot alone satisfy
  collection, comparison, case-study/review, guide, or policy representation.
- Keep schema absence a modest advisory. Present malformed or contradictory
  markup remains a defect.
- Remove the expand-gating proxy from the catalog: server-present collapsed text
  is extractable and the old signal did not prove interaction-only content.
- Keep server-rendered-content evidence diagnostic and remove every score role.
  Do not rename it into a scored extractability capability. A future evaluator
  requires deterministic healthy and failed evidence.
- Correct editorial lead, entity proposition, and AEO heading hierarchy to
  consume the page-owned facts.

### Page-purpose profile depth

Implement only deterministic expressions justified by the new facts. The family
profile must account for homepage, article, product, category, pricing, docs,
FAQ, about/contact traits, service, local, procedural and non-procedural guides,
comparison, case-study/review traits, and trust/policy. `other` remains the
terminal abstention outside this profile.

Purpose-specific requirements remain those in the canonical measurement matrix:
pricing option/billing association is not replaced by generic schema,
comparison evidence is not replaced by external-link count, and docs do not
receive blanket date/source obligations without independent context.
Unimplemented expressions remain explicit family gaps.

### Slice 2 acceptance

- Every classified kind × trait × family row has one status; `other` has no AEO
  family profile.
- Family ownership is the only dimension mapping.
- Missing input never becomes N/A; evaluator absence is a profile gap.
- Unavailable, ambiguous, and conflicting evidence use `unknown` with distinct
  bounded reason codes.
- A generic external link earns no Evidence credit.
- Freshness remains expected when independent context requires it but the date
  is missing.
- Metadata-only authorship cannot manufacture full visible-attribution credit.
- Unrelated schema nodes cannot activate or satisfy a primary-entity contract.
- Diagnostics have no score roles, and removed proxy rule IDs have no remaining
  evaluator, issue, handoff, API, UI, fixture, or documentation caller.
- Expected profiles are frozen before outcomes and retain exact source evidence
  and version provenance.
- Scoring formulas and public projections remain unchanged until slice 3.

## Internal slice 3 — family-normalized scoring and classification coverage

### Goal

Replace rule-count influence with fixed capability budgets and make unresolved
purpose visible without suppressing valid scores for classified pages.

### Family normalization cutover

Extend the existing scoring owner; do not add a second scorer. Consume the
single family manifest and executable profile. Resolve checkpoint outcomes into
one family result per page, average page families within page kind, and apply
the existing fixed equal page-kind macro before family budgets, dimension
weights, and overall AEO Readiness.

The `structured_representation` family receives one fixed budget whether it has
one absence result or several present-artifact validators. Apply the same rule
to every family. Subcheck count can improve resolution but never manufactures
family or dimension influence.

Web Fundamentals remains objective-defect scoring and does not consume the AEO
family formula.

### `other` and aggregate cohort

- A page with `page_kind=other` persists universal technical/diagnostic evidence
  but has `aeo_readiness_score=null`, `aeo_measurement_state=not_measured`, and
  reason `page_purpose_unresolved`.
- Page-purpose AEO family, dimension, and overall calculations consume
  classified pages only.
- Unclassified pages are not silently excluded: classification counts, ratio,
  and reason groups are frozen beside measurement and crawl coverage.
- Measurement coverage continues to describe expected evidence for the
  classified scored cohort. Classification coverage describes how much of the
  analyzable cohort received a purpose profile. Crawl coverage describes how
  much of the selected acquisition/analysis cohort was observed.
- Classification coverage does not enter the quality numerator, act as a zero,
  or reuse the AEO measurement-coverage field.

No arbitrary classification or determinacy threshold suppresses the numeric
score. The persisted measurement state and classification state remain separate;
presentation qualifies any partial-classification aggregate as readiness for
**classified audited pages**.

### Persistence and contract

Freeze `classified_page_count`, `other_page_count`,
`classification_error_page_count`, expected count, coverage, state, reason
groups, formula version, exact source artifact/execution/analysis IDs,
`scored_page_kind_set`, and `scored_page_count_by_kind` on
`SiteHealthSnapshot`. Mirror them in `SiteCrawl.score_summary` through the same
aggregation owner. Do not add page-level classification coverage.

Update the existing same-origin `/api/v1` schemas atomically across backend and
frontend. Overview, Pages, page detail, page-kind summaries, AEO Readiness,
exports, and trend/change comparability consume persisted values only. A
comparison lacking the new classification or scored-cohort projection is
non-comparable.

When the scored kind set or page counts by kind change, the mathematical
comparison remains available with bounded reason `cohort_composition_changed`,
added/removed kinds, and prior/current counts. PR4 does not invent a
quality-versus-cohort decomposition.

### Slice 3 acceptance

- Rule duplication and subcheck additions cannot change a family budget.
- Repeating an entire page-kind cohort leaves that kind’s mean and fixed
  cross-kind vote unchanged.
- Adding distinct pages may change their kind’s mean but not its macro weight.
- A valid complete structured representation cannot score worse merely because
  its triggered validators became expected; invalid evidence may lower it.
- Missing versus unknown changes quality and coverage exactly as declared.
- A page assigned to understanding that later fails increments
  `classification_error_page_count`.
- `other` produces no page-purpose AEO scalar and cannot manufacture AEO 100.
- Adding an unresolved page cannot increase classification coverage.
- Snapshots persist the scored kind set and page counts by kind; composition
  changes carry `cohort_composition_changed`.
- Page, page-kind, crawl summary, snapshot, and diagnostics reproduce the same
  family, dimension, score, and coverage points.
- Search eligibility, Web Fundamentals, seven dimension weights, and the
  Content handoff remain stable.

## Internal slice 4 — projection, calibration, and cutover

### Goal

Make the three coverage concepts and remaining limitations comprehensible,
then prove the new contract against fixtures and live calibration crawls.

### Presentation

Overview presents distinct persisted facts:

```text
AEO Readiness                 quality for classified audited pages
AEO Measurement Coverage      determinate expected evidence for that cohort
Classification Coverage       classified / classification-expected HTML pages
Crawl Coverage                selected/discovered/analyzed evidence boundary
```

Keep the seven-dimension ledger. Do not introduce Topical Authority,
Information Gain, or a replacement headline architecture.

The headline card intrinsically qualifies the score; classification and
measurement coverage are adjacent, above the fold, and never hidden behind a
tooltip or secondary navigation. When classification is incomplete, the layout
contract is:

```text
94
Readiness of classified audited pages

55.7% of audited pages classified
96.4% AEO measurement coverage
```

The values above illustrate hierarchy only; persisted values and states supply
the rendered copy. At complete classification the title may be **AEO
Readiness**, but the classification and measurement coverage lines remain
visible. Incomplete crawl coverage adds an equally visible **audited pages**
qualifier and crawl-coverage line.

- `other` rows render **Not measured** rather than a numeric AEO score, generic
  `WebPage` readiness, or appended internal classification reason.
- Any present score renders its measurement state and coverage together; a
  limited-evidence number is never visually unqualified.
- Overview, AEO, exports, and summaries use **readiness of classified audited
  pages** whenever classification is incomplete.
- Evidence drawers name the capability family, checkpoint, observed evidence,
  expectation, reason, and remediation without exposing internal rule IDs as
  primary copy.
- Retired rule filters and Content handoffs are removed or migrated atomically;
  no alias remains.

### Calibration output

After the implementation is complete:

1. reset the disposable database from `0001_initial.py`;
2. verify zero ORM drift;
3. rerun Searchable and Flourist under the final PR4 code;
4. run the labelled fixture corpus without network access; and
5. append one direction-neutral calibration record to this plan.

The acceptance record reports:

**Page classification**

- fixture counts by expected kind;
- per-kind precision and recall;
- abstention and correct-abstention counts;
- confusion matrix;
- deciding signal/tier distribution; and
- top abstention/conflict reasons.

**Measurement semantics**

- satisfied, partial, missing, unknown, `not_applicable`, and error counts by
  kind × dimension;
- unknown reason-code counts, validated-defect reasons, and explicit
  measurement-gap reasons; and
- retired versus introduced checkpoint/family IDs.

**Coverage**

- crawl coverage;
- classification coverage; and
- AEO measurement coverage, each with numerator, denominator, and state.

**Score**

- Web Fundamentals;
- overall AEO Readiness;
- seven dimensions;
- fixed-budget capability-family contributions; and
- scored page-kind set and scored page count by kind.

**Regression**

- top reason-code changes;
- classification and score invariants;
- scored-cohort composition changes and bounded comparison reasons;
- Search eligibility outcomes;
- issue and Content-handoff changes; and
- visible before/after screenshots of Overview, Pages, page-kind summaries, AEO
  Readiness, and one `other` page detail.

There is no required score direction or preferred distribution.

#### Observed local calibration — 2026-08-30

- The offline classifier corpus contains 35 labelled pages: 27 classified
  cases and 8 deliberate abstentions. All 8 abstentions remained `other`.
- Sanitized labelled coverage includes 14 Searchable cases and 3 Flourist
  cases. These are offline fixtures, not live crawl results.
- Per-kind precision and recall were `1.0` for every represented kind; the
  confusion matrix was an identity matrix. Fixture support was:
  `about_contact=1`, `article=8`, `case_study_review=1`, `category=3`,
  `comparison=1`, `docs=1`, `faq=1`, `guide=1`, `homepage=2`, `local=1`,
  `other=8`, `pricing=1`, `product=2`, `service=3`, and `trust_policy=1`.
- The 25 mutation-invariant scoring tests passed. A fresh disposable database
  upgraded from `0001_initial` and `alembic check` reported no drift.
- Repository static gates, selected backend/frontend/E2E tests, and browser
  checks of Overview plus AEO Readiness passed. The browser observed the
  qualified partial-classification headline, adjacent classification coverage,
  no standalone classification-completeness box in the Website tabs, and all
  seven named dimensions.
- No live Searchable or Flourist crawl coverage, score, checkpoint
  distribution, or reason-code distribution was observed. None is inferred or
  recorded here.

The deterministic scorer suite includes these mutation invariants:

```text
RULE DUPLICATION
duplicate an existing checkpoint observation or semantic checkpoint identity
=> catalog/idempotency rejects or collapses the duplicate
=> family budget, family score, dimension score, and final score are unchanged

PAGE-MIX MUTATION
replicate an entire page-kind cohort N times
=> the within-kind mean is unchanged
=> the page kind receives no additional cross-kind family influence

UNCERTAINTY MUTATION
change the same expected checkpoint from missing to unknown
=> raw quality credit remains zero
=> the determinate quality denominator loses that checkpoint
=> coverage decreases exactly by its expected weight
=> no aggregate null is coerced to a numeric score
```

### Slice 4 acceptance

- Searchable no longer reports 99.1% measurement coverage as though it were
  99.1% classification coverage.
- Searchable `other` rows no longer expose AEO 99.6 or any page-purpose scalar.
- The prior UI contradiction between “not measured” copy and a numeric `other`
  row is absent on every affected surface.
- Both calibration crawls disclose partial crawl coverage without making
  whole-site claims.
- The calibration record contains all outputs above and names every remaining
  measurement gap; it does not convert gaps into weak heuristics.
- Browser verification exercises the actual persisted terminal surfaces.

## Deferred reliability backlog

PR4 records but does not implement:

- canonical/equivalence entity scoring;
- body-digest duplicate collapse;
- advanced page-equivalence handling;
- cluster- and graph-scoped AEO families;
- additional evaluators for profile rows that remain measurement gaps.

These require separate observed evidence and an explicit successor decision.
They are not prerequisites for repairing the Searchable and Flourist defects.

## Atomic cutover and removal manifest

PR4 is one clean merge cutover delivered through the four reviewable commit
groups above. Before implementation, inventory all affected:

- normalized fact fields and extractors;
- classifier signals/config/tests;
- trait and expected-profile owners;
- rule IDs, evaluators, issues, Opportunities, and Content handoffs;
- scorer and summary/snapshot writers;
- ORM/migration columns and JSON projections;
- backend/frontend schemas and clients;
- Pages, Overview, AEO, page-kind, detail, export, trend, and change callers;
- filters, query parameters, fixtures, E2E tests, and active docs.

At cutover:

- delete replaced facts and their callers;
- delete the generic outbound-link, metadata-authorship, and expand-gating
  proxies rather than retain aliases;
- keep server-rendered-content evidence diagnostic and remove its AEO score role
  everywhere;
- delete rule-level scoring paths superseded by family normalization;
- remove read-time or UI-derived classification ratios;
- remove old DTO fields rather than dual-write compatibility shapes; and
- update every active authority in the same change.

The final search for retired names must find no active evaluator, issue,
handoff, API, UI, fixture, or documentation caller.

## Implementation verification

During implementation, use focused deterministic tests for the owning seam. At
completion run the repository gates once, in order, from the repository root:

```powershell
.\scripts\check.ps1
.\scripts\test.ps1
```

The PR is complete only when:

- all four internal slices and their acceptance criteria are complete;
- the disposable database upgrades from the single baseline and `alembic check`
  reports no drift;
- Searchable and Flourist calibration plus browser verification are recorded;
- every active semantic identifier remains `1`;
- current runtime docs describe the shipped PR4 contract;
- the PR1–PR3 cutover plan remains an intact implementation record linked to
  this successor; and
- no compatibility scorer, duplicate profile map, second projection owner, or
  superseded rule/fact/UI path remains.
