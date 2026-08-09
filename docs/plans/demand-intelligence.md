# Demand Intelligence, Prompt Strategy, and Visibility

> **Status:** shipped through D0-D5 on `feature/demand-intelligence`; branch-close verification is
> recorded in the [delivery tracker](growth-intelligence-delivery-tracker.md).
>
> **Approval gate in this layer:** running or scheduling an audit is the only approval gate.
> Users may also generate or edit prompts, archive or restore them, and confirm journey/key-event
> mappings; those operations do not approve an external measurement run.
>
> **Parent architecture:** [`growth-intelligence-platform.md`](growth-intelligence-platform.md).
>
> **Outcome:** connect observable search demand, site content, user behavior, configured business
> journeys, and manual or scheduled answer-engine visibility into traceable Demand Signals,
> prioritized content/site actions, and valid editable prompt portfolios.

## 1. Product boundary

Demand Intelligence answers:

- what audiences are asking or searching for;
- which pages/entities/journeys currently serve that demand;
- where demand, engagement, conversion actions, content, and AI visibility disagree;
- which prompts should be generated, prioritized, measured, and scheduled;
- whether later evidence changed after site/content work or recurring measurement.

It does not claim causal conversion diagnosis from aggregate data, scrape search results, replace
Visibility measurement, or give the Growth Agent direct access to provider APIs. It consumes
immutable imports and persisted projections.

Initial channels are owned-site evidence, Google Search Console, Google Analytics 4, and existing
answer-engine Visibility. Paid media, CRM, email, and social sources are future connectors that
must map into the same signal contracts.

## 2. Shipped foundation

Reuse:

- Google OAuth/property mapping and queued GSC/GA4 sync;
- immutable `IntegrationImportArtifact` and versioned `IntegrationMetricRow` derivation;
- `TrafficSnapshot`, `TrafficPageStat`, and `TrafficQueryStat`;
- deterministic AI-referral classification and `AnalyticsSnapshot` projections;
- first-class `Topic`, `PromptSet`, and `Prompt` with active/archived states;
- consent-gated prompt generation, validation, deduplication, cohorts, and editable active output;
- persisted Visibility audits, evidence, metrics, and trends;
- recurring `AuditSchedule` slots that delegate to the same planner and create new immutable audits;
- Opportunities v2 and traffic source-id fields.

Do not create new prompt or visibility tables merely to serve Demand Intelligence. Extend their
evidence and generation contracts.

## 3. Cube27 factual baseline

The connected Cube27 project in the active Docker database provides a real integration fixture:

- successful GSC and GA4 on-demand runs for the requested 2026-07-08 through 2026-08-04 window;
- 282 derived metric rows across eight artifact pages;
- GSC page data: 93 rows, 18 pages, 27 observed days, 639 impressions, 37 clicks;
- GSC query data: 100 rows, 30 normalized queries, 24 observed days;
- GA4 channel/source/landing/referrer/e-commerce rows over seven observed days;
- GA4 session-grain projections observe 32 sessions and 20 engaged sessions with zero recorded
  conversions; this is insufficient to characterize a broader conversion rate;
- no item-commerce rows, AI referral sources, linked Visibility snapshots, or correlation sample;
- only one of 18 GSC page rows joins the current seven-URL Site crawl.

The baseline also exposes a correctness defect: GSC and GA4 enqueue the same Traffic refresh
idempotency identity for a project/window/revision. The earlier GSC refresh wins, the GA4 refresh
deduplicates, and stored snapshots contain GSC provenance while sessions/conversions remain null
despite imported GA4 rows. Fix this before building Demand Signals.

Use sanitized Cube27 artifacts or stable derived fixtures in CI. Live connected data is an
opt-in acceptance source and must never be committed with credentials or unnecessary raw query
values.

## 4. Correct integration contracts first

### 4.1 GSC report families

Add versioned report templates for:

- property/date totals where needed for coverage checks;
- page × date;
- query × date;
- query × page × date for demand-to-content attribution;
- optional country and device segment variants;
- a two-pass Search Appearance workflow: enumerate appearance values, then filter individual
  query/page requests.

GSC detail rows are not guaranteed to equal property totals because of privacy omission and row
limits. Persist coverage and truncation metadata and never fabricate missing queries.

Primary references:

- [Search Analytics query API](https://developers.google.com/webmaster-tools/v1/searchanalytics/query)
- [Search Analytics data extraction and completeness](https://developers.google.com/webmaster-tools/v1/how-tos/all-your-data)

### 4.2 GA4 report families

Do not create one giant cross-scope report. Define capability-tested templates:

- landing page plus session source/medium/channel/campaign with sessions, engaged sessions,
  engagement rate, active/total/new users where compatible, and key events;
- page/path/referrer content reports;
- event name with event count and key events for configured journeys;
- country and device segment reports where useful;
- existing commerce reports for transactions/revenue/items where the property supports them.

Use stable Core Data API `keyEvents` rather than treating deprecated `conversions` as the
long-term contract. Resolve relative landing paths against the validated project origin before
canonical matching. Call `getMetadata`/`checkCompatibility` per property before enabling a
template and persist its capability snapshot.

Primary references:

- [GA4 Data API schema](https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema)
- [GA4 compatibility check](https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/checkCompatibility)
- [Reporting-data expectations](https://developers.google.com/analytics/devguides/reporting/data/v1/reporting-data-expectations)

### 4.3 Projection correctness

- include provider/connection or source-artifact identity in analytics refresh idempotency;
- recompute a project/window projection when any contributing source revision changes;
- freeze the complete contributing artifact/row identity in every snapshot;
- resolve GA4 relative paths using project origin and the same canonical identity as Site/GSC;
- expose page/query/event join coverage and unmatched reason counts;
- project engaged sessions and stable key events rather than importing and discarding them;
- retain null when a measure is unavailable and zero only when a compatible report observed zero;
- prevent sums across GA4 datasets that are alternative dimensions of the same activity.

## 5. Business journeys and measurement configuration

Analytics rows cannot explain conversion without a business definition. Add optional,
low-friction `JourneyDefinition` configuration under Business Knowledge:

- name and primary outcome;
- audience and offering/entity;
- ordered conceptual stages;
- relevant site page roles/URLs;
- configured GA4 key events and optional supporting events;
- attribution/observation window policy;
- industry-pack origin or user-defined origin;
- version and effective dates.

Education v1 proposes an admissions journey, but the user confirms event mappings. Commerce v1
proposes product discovery, product consideration, checkout, and purchase journeys. Missing
events surface as measurement gaps, not zero performance.

## 6. Canonical Demand model

### 6.1 Normalized source observations

Keep raw provider-specific metric rows in Integrations. Demand Intelligence projects normalized
observations such as:

- search query demand and query-page performance;
- page search reach and engagement;
- landing and acquisition behavior;
- configured journey/key-event behavior;
- AI referral traffic;
- answer-engine prompt, mention, citation, rank, and fanout evidence;
- site content/topic/question/journey coverage.

Each observation retains source dataset, artifact, row identity, window, dimensions, coverage,
and importer version.

### 6.2 `DemandSignal`

A signal is a versioned interpretation of one coherent evidence pattern:

- signal type and state;
- audience, intent, journey stage, geography/device when supported;
- query/question/topic cluster;
- related knowledge entities, offering, pages, and content units;
- observed search demand and page performance;
- engagement and key-event evidence;
- site/content coverage and quality;
- AI visibility and owned/competitor citation evidence;
- confidence, magnitude, freshness, limitations, and coverage;
- exact source ids plus analyzer/rule/formula versions.

Initial signal families:

- high-impression/low-click question or page;
- valuable query with weak or mismatched owned page;
- demand cluster with no relevant page/answer;
- strong organic page with weak AI visibility;
- tracked prompt with no supporting owned knowledge;
- relevant page with engagement but missing configured outcome evidence;
- journey stage with missing content or measurement;
- emerging/stale query cluster;
- owned citation or AI-referral gain/loss after a comparable change.

Deterministic thresholds and metrics identify candidates. A schema-constrained semantic analyzer
may cluster queries, map intent/entities/journeys, or explain a signal using a frozen context
package. Model output retains provenance and does not overwrite raw metrics.

### 6.3 `DemandSnapshot`

Freeze one bounded view for a project, time window, integration revisions, Site snapshot,
Visibility audit selection, journey configuration, industry pack, and formula/analyzer versions.
It contains coverage, aggregates, signal ids, prompt-portfolio summary, priorities, and comparison
to a compatible prior snapshot.

## 7. Prompt strategy

### 7.1 Two states, not three

1. **Active:** generated automatically from project facts, Site knowledge, pack archetypes, and
   current content, then continuously rescored as GSC/GA4 evidence arrives. Active prompts are
   eligible for measurement.
2. **Archived:** removed by the user or superseded, and retained for historical audit
   comparability.

There is no proposed-then-approved gate. A prompt costs nothing until an audit runs, and **running
or scheduling the audit is the user decision** — so gating the prompt as well is friction that buys
no safety. The user edits or removes any prompt at any time, and the portfolio surface shows what
would be measured on the next run before that run is scheduled.

New evidence never silently rewrites active prompt text. It changes priority, or proposes a new
candidate alongside the existing one. Historical audits keep the exact text they measured
([`../invariants.md`](../invariants.md) §18).

### 7.2 `PromptCandidate` validity

`PromptCandidate` is a transient generation value, never a persisted resource, lifecycle state, or
user-edit staging record. Every candidate carries:

- exact natural-language text and language/market;
- audience/persona, intent, journey stage, and question/topic cluster;
- branded/unbranded/comparison cohort;
- related entity/offering/page and expected answer shape;
- supporting knowledge and Demand Signal ids;
- why it is measurable and valuable;
- generation context hash, provider/model, skill/template, and generator version;
- deterministic validation, relevance, policy, normalized-hash dedupe, and diversity results;
- priority and its formula inputs;
- the evidence and validation fields needed to decide whether it can be persisted.

Prompt generation is model-driven because natural, useful prompts cannot be produced by metrics
alone. The knowledge/demand layer determines eligible context and evidence; the provider-neutral
model proposes text; deterministic and semantic validators enforce grounding, topical relevance,
cohort rules, deduplication, and portfolio coverage.

Extend the existing `Prompt`/`Topic` workflow. Validated candidates become active `Prompt`
resources directly, candidate evidence maps to `Prompt.generation_evidence`, and only active and
archived are persisted statuses. User edits apply to the persisted `Prompt`, never the transient
candidate.

### 7.3 Portfolio design

Balance the portfolio across:

- awareness/discovery, evaluation/comparison, action/purchase/admission, service/local, and
  support intents;
- audiences, offerings, journeys, regions, and topics;
- branded, unbranded, and named-comparison cohorts;
- proven search demand, strategically important site knowledge, and measured visibility gaps.

Portfolio constraints are industry-pack/config policies with versioned evidence. Do not optimize
only for existing keywords; provisional prompts intentionally cover strategic questions not yet
visible in GSC.

## 8. Visibility and outcome loop

Reuse current audits and Visibility projections unchanged as measurement truth. Link active
prompts and audits back to candidate/source signals through generation evidence and frozen audit
snapshots.

Demand Intelligence can compare:

- prompt answer-engine mention/citation outcomes;
- linked page organic demand and engagement;
- relevant site/content changes and verification;
- AI referral changes where classification coverage exists.

These comparisons are descriptive. They display aligned windows, sample size, missing sources,
and version compatibility. No single correlation proves a content change caused conversion or
AI visibility.

## 9. Prioritization and opportunities

Extend existing Opportunity detectors rather than add a second action store. Enable traffic/topic
rules only after projection correctness and Demand Signals land.

Priority is a transparent versioned function of:

- business/journey importance;
- demand magnitude and trend;
- current position/click/engagement/key-event evidence;
- content/site gap severity;
- visibility/citation gap;
- evidence coverage, confidence, freshness, and estimated effort band.

A model may summarize or sequence a roadmap but cannot silently change formula inputs. New
snapshots supersede derived opportunities without rewriting accepted status/history.

## 10. Persistence

Add or extend:

- integration dataset/capability registry and import artifact metadata;
- Traffic/Analytics projections and provenance completeness;
- `JourneyDefinition` plus append-only transition/version history;
- `DemandSignal` and `DemandSnapshot`;
- prompt `generation_evidence`, frozen again on each immutable audit prompt snapshot;
- Opportunity source ids for Demand Signals;
- links from prompt/audit snapshots to originating candidate/signal ids.

Prefer normalized identity/link tables where relations need filtering and integrity; keep bounded
provider payload details in existing JSONB artifacts. All ids are UUIDs and workspace-scoped.

## 11. APIs and UI

### APIs

- integration capability/status and safe sync coverage;
- Demand snapshot list/detail/recompute;
- signal list/detail with filters for source, audience, intent, journey, entity, page, confidence,
  and status;
- journey definitions and versioning;
- prompt generate/list/detail/edit/archive/restore; restore is an idempotent archived-to-active
  transition, and restoring an already-active prompt leaves it active without creating a new row;
- portfolio coverage and recommendation projection;
- linked Site/Content/Visibility comparison;
- report/export endpoints from persisted snapshots.

All provider sync and analysis writes are queued and idempotent. Reads never call Google or an
LLM.

### Demand Intelligence workspace

1. **Overview** — coverage, important signals, journey outcomes, and changes.
2. **Search Demand** — query clusters, query-page fit, content gaps, and segments.
3. **Journeys** — landing, engagement, configured key events, and measurement gaps.
4. **Prompts** — evidence-prioritized active/archived resources and portfolio coverage.
5. **AI Visibility** — existing Overview/Trends/Evidence/Fanout views in the demand context.
6. **Evidence** — import revisions, source coverage, joins, limitations, and versions.

Existing `/traffic`, `/analytics`, `/prompt-research`, `/prompts`, and `/visibility` deep links
remain compatible while navigation and cross-links migrate.

## 12. Implementation slices and gates

All six slices are shipped. The notes below remain the acceptance contract; implementation uses
the existing integration, Traffic, Prompt, Opportunity, Audit Schedule, and Visibility owners.

### D0 — Data correctness and Cube27 fixture

- fix cross-connection Traffic refresh idempotency;
- include all contributing GSC/GA4 artifacts in refreshed snapshots;
- resolve relative GA4 landing paths and expose join coverage;
- project engaged sessions and stable key events;
- capture sanitized Cube27 fixtures and expected aggregates.

**Gate:** a combined Cube27 snapshot contains both GSC and GA4 provenance and correct null/zero
semantics.

### D1 — Rich Google report families

- add query×page GSC and optional segment/search-appearance workflows;
- add GA4 capability discovery, compatibility-tested landing/session/event/key-event templates;
- persist coverage, truncation, sampling/thresholding, and capability metadata.

**Gate:** fixture and opt-in sync tests prove each enabled dataset's grain and compatibility;
unsupported templates remain visibly unavailable.

### D2 — Identity joins and journeys

- canonicalize Site/GSC/GA4 page identity;
- link queries, pages, knowledge entities, content units, and journeys;
- add optional journey/key-event configuration and Education defaults.

**Gate:** join-rate metrics and unmatched reasons are stable; missing journey events are not
rendered as zero conversion.

### D3 — Demand Signals and priorities

- add signal catalog, deterministic candidate detectors, bounded semantic mapping, snapshots,
  comparison, and Opportunity integration;
- ship Education rules first and Commerce rules second.

**Gate:** each signal traces to exact metrics/site/visibility evidence and reports limitations.

### D4 — Prompt strategist

- build task context, prompt-generation skill, validators, portfolio coverage, and the existing
  Prompt links;
- generate prompts without integrations, and rescore them from Demand Signals once they exist.

**Gate:** generated prompts are grounded, non-duplicative, and editable, and no prompt is measured
until the user runs or schedules an audit.

### D5 — Visibility schedules, outcome loop, and product experience

- link active prompts, manual audits, scheduled slots, and resulting audits to source signals;
- add schedule create/update/pause/resume/history projections without duplicating the audit planner;
- add outcome comparisons and the Demand Intelligence workspace;
- surface contextual Growth Agent tools.

**Gate:** a user can trace demand → active prompt portfolio → manual or scheduled audit evidence
→ later demand/site evidence; every schedule slot is idempotent, creates a new frozen audit, and no
read path makes an external call or comparison asserts unsupported causality.

## 13. Acceptance

### Cube27

- import/snapshot fixtures reproduce expected GSC and GA4 aggregates;
- both providers contribute to one correct projection;
- query-page and landing-page joins expose coverage;
- zero key events over seven observed days is reported as limited evidence;
- absence of Visibility runs produces “unavailable,” not false low visibility;
- generate and review a small evidence-grounded prompt portfolio.

### The Asian School

- create education prompts from project facts and Site knowledge before Google
  integrations;
- after GSC/GA4 sync, create demand-to-page signals and reprioritize candidate prompts;
- configure the admissions journey and required key events;
- show measurement gaps until the relevant events/data exist;
- review the generated admissions prompt portfolio, schedule recurring Visibility measurement, and
  prove each due slot freezes the active prompts and provider configuration into a new audit;
- relate later Visibility and site/content snapshots descriptively.

## 14. Verification matrix

- connector/derivation tests for every dataset grain, compatibility result, truncation, sampling,
  thresholding, revision, and null/zero rule;
- projection tests for cross-provider idempotency, complete provenance, joins, aggregates, and
  windows;
- pure signal/prioritization tests and semantic-mapping fixtures;
- prompt context, grounding, validation, dedupe, portfolio, frozen-audit, and scheduled-slot
  idempotency/pause/resume tests;
- component tests for workspace isolation, coded errors, queues, snapshots, schedules, and exports;
- frontend tests for coverage, unavailable states, prompt editing, journey configuration, and
  evidence drilldowns;
- live Google sync remains opt-in; CI uses sanitized fixtures.
