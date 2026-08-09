# CiteLadder frontend architecture

> **Status:** current frontend authority
> **Framework:** Next.js App Router and TypeScript
> **Product hierarchy:** four layers — Site, Content, Demand Intelligence, and the Growth Agent
> **User decisions:** save content; run and schedule audits. No other blocking UI exists.

The frontend is a projection and workflow layer over workspace-scoped backend contracts. It owns
interaction, validation, accessibility, navigation, and local ephemeral state; it does not own
business truth, scoring, knowledge, authorization, or lifecycle decisions.

## Core rules

- The browser calls relative `/api/*`; Next.js rewrites to server-only `BACKEND_ORIGIN`.
- Server data uses TanStack Query; forms use typed inputs and Zod-backed validation.
- Responses are validated through the shared API-contract layer. Additive unknown response keys
  follow the existing tolerant policy; missing or invalid declared fields fail visibly.
- IDs are UUIDs and the active workspace/project context is always explicit.
- No production screen falls back to mock data or silently computes a backend metric.
- Only live navigation items render; future work is not represented by disabled placeholders.

## Target information architecture

Six destinations, flat. Sub-surfaces are tabs on the layer route, never sidebar children — two
levels of navigation is the limit. The screen geometry every route uses is owned by
[`design.md`](design.md).

```text
Overview   /projects   project state, ranked insights, what changed
Site       /site       corpus, pages, facts, schema, journeys, evidence
Content    /content    strategy, inventory, briefs, drafts, verification
Demand     /demand     search demand, journeys, prompts, visibility, coverage
Agent      /agent      conversation, tasks, roadmap
Reports    /reports    snapshots and exports
Settings   /settings   project, integrations, providers, billing
```

Existing `/site-health`, `/issues`, `/traffic`, `/analytics`, `/prompt-research`, `/prompts`,
`/visibility`, and `/runs` deep links stay usable through the migration. `/issues` and
`/opportunities` do not survive as destinations: findings are insights attached to the artifact
they concern.

The migration order lives in
[`plans/frontend-growth-intelligence.md`](plans/frontend-growth-intelligence.md).

The shipped `/demand` workspace has Overview, Search Demand, Journeys, Prompts, AI Visibility, and
Evidence panels. It reads immutable Demand projections, renders structured join/key-event
coverage, exposes persisted report-family capability state, and links to the existing owning
workflows.

## Current route ownership

| Route family | Current purpose | Target placement |
|---|---|---|
| `/projects`, `/knowledge-base` | Project state and curated profile | Project command centre and Business Knowledge |
| `/site-health`, `/issues` | Crawl, pages, rules, issues | Site Intelligence |
| `/content` | Basic generation | Content Intelligence |
| `/traffic`, `/analytics` | First-party projections | Demand Intelligence |
| `/prompt-research`, `/prompts` | Prompt creation/review | Demand Intelligence |
| `/visibility`, `/runs` | Answer-engine measurement/evidence | Demand Intelligence |
| `/products` | Catalog and product visibility | Commerce views backed by shared Site/Content/Demand contracts |
| `/providers`, `/settings` | Connections, billing, integrations | Shared project/workspace settings |

## Data and query ownership

Each domain has one API module, one query-key owner, and one set of shared schemas/types. Queries
are enabled only for the visible panel when possible. A shared artifact selected in one workspace
uses the same server ID and cache identity in contextual drawers and agent actions.

Polling remains the authoritative progress path for long-running tasks. SSE or streaming may
accelerate invalidation and presentation but never replaces persisted task state.

## Evidence and knowledge UX

- Every conclusion can open persisted evidence.
- Observed, derived, corrected, historical, conflicting, unknown, unavailable, and excluded states
  have distinct text labels and are never communicated by colour alone.
- Context drawers show included sources and important omissions.
- Derived facts are edited inline. A correction shows its author and timestamp, survives
  recomputation, and can be withdrawn to restore the derived value. There is no approval card and
  no review inbox.
- Industry role classification shows winning signals, alternatives, confidence, pack and version,
  and any correction.
- Composites render over the full denominator with coverage beside them; never renormalize over
  only the observed dimensions.

## Content workflow

```text
insight
  -> verified facts and limitations
  -> frozen brief
  -> generated draft
  -> automatic validation, with unsupported claims blocked
  -> user edits
  -> SAVE            <- the user decision in this layer
  -> export or publication claim
  -> later recrawl verification
```

Everything before `SAVE` is automatic. There is no `in_review` or `approved` state: the user who
generates is the user who edits and saves. Visible content and any mirroring structured data are
separate outputs, and markup cannot be saved when it does not match the visible content.

FAQ is one worked example of this flow, not a required first slice.

## Mobile and accessibility

Full workflows must remain possible on mobile. Tables become labelled records; filters and
evidence use accessible sheets; reorderable actions expose keyboard/touch controls. Tabs render
one panel at a time and mirror meaningful state to the URL. Focus, errors, loading, empty,
reduced-motion, forced-colour, and touch states are required.

## Design owner

[`design.md`](design.md) and `frontend/app/globals.css` own the shared light-only semantic system.
Components use existing primitives and semantic tokens. Product screens prioritize current state,
next actions, and evidence before secondary detail.

## Verification

Use focused Vitest/Testing Library tests, API contract drift checks, policy/design guards, TypeScript
checks, build, and targeted Playwright flows. A screen is not complete when it works only with
happy-path data; null, unavailable, conflict, partial coverage, authorization, retry, and mobile
states are part of the contract.
