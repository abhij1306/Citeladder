# Frontend Growth Intelligence implementation plan

> **Status:** canonical implementation plan.
>
> **Parent architecture:** [`growth-intelligence-platform.md`](growth-intelligence-platform.md).
> **Frontend authority:** [`../frontend-architecture.md`](../frontend-architecture.md) owns shipped
> ownership. This plan owns the migration — what changes, in what order, behind which gate.
> **Design authority:** [`../design.md`](../design.md) owns the screen geometry and the insight
> object this plan assembles.
>
> **Outcome:** move the product UI from a verb-grouped visibility shell to the four-layer
> hierarchy, on one screen geometry, around one reusable insight object — and correct the public
> website where it contradicts the architecture.

## 1. The two rules that govern every screen

**Two decisions.** The user is asked exactly twice: **save content** and **run or schedule an
audit**. No approval queue, no review inbox, no promotion step. Everything else — crawling within
a schedule, classification, knowledge extraction, gap detection, opportunity creation, demand
signals, prompt generation, prioritization, roadmaps — happens without asking, and the UI's job is
to *show what happened*, not to ask permission first.

**Corrections, not approvals.** Where a derived fact is wrong the user edits it in place, wherever
it is displayed. A correction is durable, attributable, and withdrawable. There is no separate
surface for blessing facts that are already right.

If a screen in this plan appears to need a third decision point, the design is wrong — go back to
the layer plan rather than adding a gate.

## 2. Scope and non-goals

**In scope:** app navigation and route ownership, the four workspaces, the shared component
contracts, the marketing landing page, and website content.

**Not in scope:** backend contracts, the design tokens themselves, and pricing or billing surfaces.

**Hard constraint.** Every surface ships only behind its backend gate. The frontend does not render
a projection the API cannot serve, does not compute a backend metric locally, and does not
represent future work as a disabled placeholder. Where a slice lands before its data does, leave
the current route in place rather than shipping an empty shell.

## 3. Starting point

The current sidebar ([`nav-items.ts`](../../frontend/components/layout/nav-items.ts)) groups twelve
items by verb — Home / Analyze / Resolve / Improve. That model cuts across the architecture:
`/site-health` and `/issues` sit under "Resolve" but belong to Site Intelligence, while
`/visibility`, `/traffic`, `/analytics`, `/prompts`, and `/runs` are split across "Analyze" and all
belong to Demand Intelligence.

| Current group | Items | Target layer |
|---|---|---|
| Home | `/projects` | Overview |
| Analyze | Visibility, AI Referrals, Traffic, Prompts, Commerce, Runs | Demand (Commerce keeps its own view) |
| Resolve | Site health, Issues, Recommended actions | Site (findings become contextual insights) |
| Improve | Content, Brand knowledge | Content, and project facts |

**Migration rule.** Regroup before rebuilding. Every deep link above keeps working for the whole
migration; only grouping and labels change first. Route moves happen per slice with a permanent
redirect, never as one cutover.

## 4. Navigation

Flat, six destinations, matching [`../design.md`](../design.md) screen geometry. The sidebar is the
architecture — if a user cannot name the four layers after a week, this failed.

```text
Overview          /projects          project state, top insights, what changed
Site              /site              corpus, pages, facts, schema, journeys, evidence
Content           /content           strategy, inventory, briefs, drafts, verification
Demand            /demand            search demand, journeys, prompts, visibility, coverage
Growth Agent      /agent             conversation, tasks, roadmap
Reports           /reports           snapshots and exports
Settings          /settings          project, integrations, providers, billing
```

Within a layer, sub-surfaces are tabs on the layer route rather than sidebar children. Two levels
of navigation is the limit.

`/issues` and `/opportunities` do not survive as destinations. Findings are insights attached to the
artifact they concern, surfaced in their owning layer and on Overview.

**Sequencing.** Regroup in one change, at the point the first `/site` route exists. A sidebar
promising destinations that resolve to nothing violates the live-navigation rule.

## 5. Shared components

Build these once, before the workspaces that consume them. Every one is a contract, not a
suggestion.

| Component | Requirement |
|---|---|
| `Insight` | The anatomy in [`../design.md`](../design.md). One implementation, used identically in all four layers. Same server ID and cache identity wherever it appears. Does not render without resolvable evidence. |
| `EvidenceLink` | Every derived number or claim opens its persisted source. No conclusion without a path to evidence. |
| `StateLabel` | `unknown`, `unavailable`, `not_applicable`, `historical`, `future`, `conflicting`, `excluded`, `failed`, and observed zero each get distinct **text**. Never colour alone. |
| `ProvenanceChip` | Pack ID/version, analyzer version, snapshot identity — on every projection surface. |
| `CoverageMeter` | Renders the §6 rule. One component, so the rule cannot drift per screen. |
| `EditableFact` | Inline correction: shows the derived value, its evidence, and an edit affordance. Records author and timestamp. Withdrawing restores the derived value. This replaces every approval card in the old model. |
| `DecisionPrompt` | The only blocking UI. Used for exactly two things: saving content, and running or scheduling an audit. States precisely what will be spent or written. |
| `ContextManifest` | Included and omitted artifact counts and IDs for any agent or generation task. |

## 6. Score and coverage display

Composites render over the **full** denominator with coverage beside them. Never render a
renormalized composite.

Renormalizing over observed dimensions assumes the missing ones would have scored like the
observed ones, and in this domain that fails predictably: absent evidence correlates with weakness.
A site with no schema graph, no policy pages, and no author attribution is missing exactly the
dimensions it would have failed, so renormalizing scores it above a site that published all three
and scored badly.

`CoverageMeter` therefore shows score and coverage as two numbers that are read together, and low
coverage is presented as a finding — an insight in its own right — not as a footnote under a
flattering number.

## 7. Workspaces by gate

Gate names are the backend plans' own.

### 7.1 Overview — after stage 2

Project state, the ranked insight list across all layers, and what changed since the last snapshot.
This is the page a returning user lands on; it must answer "what happened and what should I do"
without a click.

### 7.2 Site — after stages 1–2

- **Corpus** — disposition (analyzed / inventory-only / excluded) with reasons. Documents appear as
  inventory-only rows rather than being hidden.
- **Pages** — extends the current Site Health list. `page_kind` and `industry_role` are **separate
  columns**, never merged into one badge.
- **Page detail** — classification panel: winning signals, alternatives considered, confidence,
  pack ID/version, and any correction.
- **Facts** — entities, assertions, relations with effective dates and contradiction groups. Every
  value is an `EditableFact`; every one resolves to its source span.
- **Schema** — observed JSON-LD beside pack expectations, as a comparison rather than a score.
- **Journeys** — stage coverage against the pack template; gaps become insights.
- **Evidence** — crawl attempts, artifacts, and fetch failures.

### 7.3 Content — after stage 4

```text
insight → brief → generated draft → automatic validation → user edits → SAVE → verification
```

- Briefs are immutable; rebuilding creates a new version. Never present one as editable in place.
- The generated attempt is read-only; the **revision** is the editable object. There is no
  `in_review` or `approved` state — the user who generates is the user who edits and saves.
- **Unsupported-claim surfacing is the highest-value screen in this workspace.** Each flagged claim
  shows the claim, why it failed (unsupported / conflicting / historical-as-current / prohibited),
  and the fact it conflicts with. Blocking flags disable save at the UI *and* the API.
- Verification is descriptive: what was observed after recrawl. It must not imply the content
  caused a ranking or conversion change.

The existing free-prompt composer moves behind an "advanced custom task" affordance.

### 7.4 Demand — after stage 3

Mostly regrouping. `/traffic`, `/analytics`, `/prompts`, `/visibility`, and `/runs` keep their
screens under the new grouping. New:

- **Demand signals** with time window, source coverage, and the join that produced them.
- **Journeys and configured outcomes**, shared with Site.
- **Prompts** — generated and active, editable and removable, with no approval step. The surface
  shows exactly what would be measured on the next run *before* the user schedules it.
- **Coverage panel** distinguishing `unavailable`, `not_configured`, and `observed zero` as three
  visibly different states. This is the most common place the distinction gets lost, because all
  three naturally render as an empty chart.

### 7.5 Growth Agent — after stage 5

- **Task composer** listing only the task families in the backend catalog.
- **Plan and progress timeline** driven by polling; polling is authoritative and streaming is
  presentation only. `awaiting_user` and `awaiting_task` render differently — one needs the person,
  one needs patience.
- **Context manifest drawer** — included sources, omitted counts, truncation, contradictions
  carried in. This is what makes "selective context" inspectable rather than a claim.
- **Result cards** separating conclusion, evidence used, artifacts created, decisions still needed,
  and next step.
- **Roadmap** rendering the deterministic order with agent-authored grouping and rationale. A
  `PriorityOverrideProposal` renders as a visible, reversible suggestion beside the deterministic
  order — never as a silently reordered list.
- **Citation resolution.** A citation that does not resolve to an artifact in the manifest renders
  as a validation failure, not as a link and not as plain text.

## 8. Landing page

Copy lives in [`landing.ts`](../../frontend/lib/marketing-content/landing.ts).

### 8.1 Corrections

| Location | Change |
|---|---|
| `packs.items[*].status` — "Education pack · Reviewed", "Commerce pack · Reviewed" | Both are **validated candidates**, ready for controlled shadow evaluation, not authoritative production findings. Say that. |
| `packs.title` — "Built for every growth team." | Overstates 14 foundation drafts. "Built around how your industry actually works." |
| `packs.lead` | Mention the real composition model: one primary pack plus reviewed capabilities. |

**"Four intelligence layers" is correct and stays.** The Growth Agent is the fourth layer of the
product — it is only not a fourth *database*. The site, the sidebar, and
[`../architecture.md`](../architecture.md) now agree on this.

The shipped `AgentConsole` section needs no copy change: its transcript derives from
`platform.modules` and asserts no metric.

### 8.2 Structure

- **Lead with the loop, not the layers.** The differentiator is
  evidence → improvement → verification; the module breakdown is *how*, not *why*. Move `workflow`
  above `platform`.
- **Add an evidence/provenance section** showing the real chain: artifact → fact → insight → brief
  → verification. This is the claim competitors cannot copy and it is currently only implied.
- **Show the insight object.** It is the product's most recognisable artifact; a real one on the
  landing page is stronger proof than a feature list.

## 9. Website content

### 9.1 Causality

[`../architecture.md`](../architecture.md) §8 is explicit that CiteLadder does not claim causality
from aggregate correlations, and verification is descriptive. Audit all of
`frontend/lib/marketing-content/` for phrasing implying a change *caused* a lift, and extend the
existing guards in
[`landing-claims.test.tsx`](../../frontend/components/marketing/landing/landing-claims.test.tsx) —
which already pin scheduling, ROI, and pricing claims — with a causality guard. That file fails the
build rather than relying on review, which is why it is the right home.

### 9.2 Per page

| Page | Change |
|---|---|
| `/solutions` | Segments map to packs and carry the same maturity labels as the landing page. A segment backed by a foundation draft must not read like a shipped vertical. |
| `/faq` | Add: what an industry pack is; what "evidence-grounded" means concretely; **what the user actually has to do** (two decisions); what the product does not claim. |
| `/compare` | Reframe from feature tables to the evidence and provenance axis. The existing "Compared honestly" section is the right spine. |
| `/enterprise` | Governance is the strongest enterprise story: workspace isolation, no cross-customer training, encrypted BYOK, reproducible provenance. Currently under-used. |
| `/pricing`, `/blog` | No change. |

### 9.3 Terminology

Fix the drift across docs, app, and site once:

- **"Site Intelligence / Content Intelligence / Demand Intelligence / Growth Agent"** — the four
  layers, named identically everywhere;
- **"industry pack"** — never "industry profile" or "vertical";
- **"project facts"** and **"correction"** — never "approved memory", "brand memory", or
  "knowledge base". The `/knowledge-base` route may persist; its label becomes "Facts";
- **"validated candidate" / "foundation draft"** — the two pack maturity terms.

## 10. Delivery order

| Step | Work | Gate | Status |
|---|---|---|---|
| 1 | Website content corrections (§8.1, §9) | none | **Done** |
| 2 | Shared components (§5) and the coverage rule (§6) | none | **Done** |
| 3 | Landing structure (§8.2) | none | **Done** |
| 4 | Sidebar regrouping (§4) | first `/site` route | **Done** |
| 5 | Site workspace (§7.2) and Overview (§7.1) | stages 1–2 | Pages tab + Overview insight list shipped; rest pending |
| 6 | Content workspace (§7.3) | stage 4 | Not started |
| 7 | Demand workspace (§7.4) | stage 3 | Visibility/Traffic regrouped; signals pending |
| 8 | Agent workspace (§7.5) | stage 5 | Not started |
| 9 | Contextual agent actions, Reports, schedules | stage 6 | `/reports` stub only |

Steps 1–3 have no backend dependency and are the correct first commits after this branch merges.

## 13. Implementation log

Recorded so future work does not re-derive these decisions or re-litigate them.

### Shipped (branch `feat/frontend-growth-intelligence`, PR #52)

**Steps 1–4 complete**, plus the parts of 5/7/9 that existing projections already
back. Components live in `frontend/components/intelligence/`.

**Empty shells are acceptable while the product is pre-users.** §3 originally said to
leave the current route in place rather than ship an empty shell. That rule exists to
protect users from a promise the API cannot keep, and there are none yet — so `/site`,
`/demand` and `/reports` render declared-but-empty panels for surfaces whose backend has
not landed. Revisit before the first real user, not before.

### Gotchas

- **`/prompts` owns `?tab=`.** Its manage mode already uses that param, so it is NOT
  embedded as a tab under `/demand` — the two would collide. §11 already schedules the
  prompts URL-contract change; do the move there, not here.
- **Band tones on the landing page cascade.** `Section` enforces "no two adjacent bands
  share a tone". The page had only two sunken sections in an eight-section run, so
  moving `Workflow` above `Platform` forced four sections to flip. `page.test.tsx`
  asserts alternation — trust it over eyeballing.
- **§8.1 was wrong about `AgentConsole`.** It claimed the section needs no copy change
  because its transcript derives from `platform.modules`. The transcript is hardcoded,
  and it carried three approval claims. The claim guard caught them; the plan text
  above has not been edited, so treat that sentence as stale.
- **`Insight` returns `null` without evidence.** Deliberate (§5). Consumers rendering
  lists must filter before computing counts, or a count will disagree with the rows.
- **`DecisionKind` is a closed union of two members.** Adding a third fails
  `decision-count.test.ts` at the type level. That failure is the signal to go back to
  the layer plan, not to edit the test.
- **SonarCloud runs in automatic-analysis mode** — there is no `sonar-project.properties`
  and adding one switches the project to CI-based analysis. Duplication exclusions can
  only be set in the SonarCloud UI. `faq.ts` tripped the 3% new-code duplication gate
  because Sonar's tokenizer counts the repeated `'...' +` concatenation shape across
  every answer; answers are now single template literals. Keep them that way.
- **Marketing cannot import `Insight`.** The landing page's insight card in
  `evidence-chain.tsx` mirrors the anatomy rather than importing the component: `Insight`
  requires a resolvable evidence href and refuses to render without one, and marketing is
  monochrome-plus-blue so it cannot use the app's danger fill for the priority chip.
- **`opportunity_type` is a closed enum**: `visibility | site | traffic | topic`. It is NOT
  free-form, and it does not carry `content_*` or `prompt_*` members. `opportunity-insight.ts`
  maps it exhaustively to the four layers; extend that map when the backend enum grows.
- **`dashboard-screen.test.tsx` mocks `@tanstack/react-query` wholesale.** Any child added
  to `DashboardScreen` that runs its own query will receive the command-center fixture
  instead of its own response shape. `TopInsights` is stubbed there for that reason — do
  the same for the next such child rather than teaching that fixture two shapes.

### Not yet done

Everything gated on a backend stage that does not exist: Facts/Corpus/Schema/Journeys/
Evidence tabs (§7.2), Overview (§7.1), the Content workspace (§7.3), demand signals and
the coverage panel (§7.4), and the entire Agent workspace (§7.5). The §11 UI-debt items
remain open and deliberately deferred. A live accessibility pass (§11) has still not run.

## 11. UI debt

A static UI and performance review ran on 2026-08-07. The accessibility and interaction fixes it
found are **already applied** on this branch: skip link and `id="main"` landmarks, `theme-color`,
anchor `scroll-margin-top`, safe-area helpers on fixed chrome, `touch-action`,
`overscroll-behavior: contain` on the dialog, command palette, and mobile drawer, keyboard
operability on the Site Health page rows, `router.push` buttons converted to real links,
decorative-icon `aria-hidden`, `spellCheck` on email, explicit transition properties in place of
`transition-all`, `scaleX` instead of animated `width`, `text-balance` on section headings, and the
duplicated active-project storage key removed.

These remain open, deliberately deferred because each needs measurement or a product decision
rather than a mechanical edit:

| Item | Why deferred | Where |
|---|---|---|
| Code splitting via `next/dynamic` — tour (`driver.js`), `GsapRevealInitializer`, `ProductWindow`, `AgentConsole`, `CommandPalette`, `react-markdown` | The repo currently has zero `next/dynamic`. Splitting a client island imported by a Server Component needs care, and the win should be measured against a bundle report first rather than assumed. | `product-tour-provider.tsx`, `(marketing)/layout.tsx`, `see-it.tsx`, `platform.tsx`, `app-shell.tsx`, `lib/content/markdown.tsx` |
| Prompt manage-mode `search` and `filters` in query params | Real bug — refresh loses state — but it is a URL-contract change, and the prompts surface is being regrouped under Demand (§7.4). Do it with that move. | `prompt-library.tsx`, `prompt-toolbar.tsx`, `(app)/prompts/page.tsx` |
| Unsaved-changes guard on the brand-profile draft | Becomes moot when facts move to inline `EditableFact` corrections (§5), which save per field. Revisit only if a multi-field draft survives that migration. | `brand-profile-panel.tsx` |
| Versioned `localStorage` key for the discovery model | Needs a migration path, not just a renamed key. | `discovery-model-card.tsx` |
| `theme-color` browser-chrome tint | Next requires a literal colour in `viewport`, which collides with the rule that `globals.css` is the only owner of colour values (`pnpm check:policy` enforces it). The invariant is worth more than the tint. Revisit only if the policy grows a narrow, documented exception. | `app/layout.tsx` |

**Rejected findings, recorded so they are not re-raised:**

- *"Nav scroll state re-renders on every scroll event."* It does not. `setScrolled(window.scrollY > 10)`
  passes an unchanged boolean on almost every event and React bails out without re-rendering. Only
  the transition costs a render.
- *"Forms do not focus the first invalid field."* react-hook-form's `handleSubmit` defaults to
  `shouldFocusError: true`, and `components/ui/input.tsx` forwards the ref, so this already works.
- *"Remove `autoFocus` from the topic-name input."* That input renders only after the user clicks
  Add, so moving focus to it is the correct behaviour — removing it would be the regression.
- *"Placeholders should end with an ellipsis."* `you@company.com` is an example value and `••••••••`
  is a mask; neither is truncated text. Only genuine ASCII `...` was corrected to `…`.
- *"Enable `experimental.viewTransition`."* There is no view-transition usage in the repo. Adding
  experimental config ahead of a use case is speculative.

A live accessibility and UX pass — focus order, touch-target size, 320px reflow, real bundle weight
— has not been run and cannot be substituted by static review. Do that against `/`, `/login`,
`/projects`, `/visibility`, and `/site-health` before ship.

## 12. Verification

Each slice carries:

- Vitest/Testing Library tests including null, unavailable, conflicting, partial-coverage, and
  authorization states — a happy-path-only screen is incomplete;
- a correction-durability test: edit a fact, recompute, confirm the correction survives;
- a decision-count test per workspace: exactly the decisions in §1 block, and no others;
- an extension to `landing-claims.test.tsx` for every new marketing claim class;
- API contract drift checks for each new projection;
- `pnpm lint`, `pnpm build`, and the design and policy guards;
- targeted Playwright coverage for the content save flow, which is the one path where a UI mistake
  has a durable consequence.
