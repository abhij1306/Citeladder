# CiteLadder frontend architecture

> **Status:** current frontend authority
> **Framework:** Next.js App Router, TypeScript, TanStack Query, Zod

The frontend projects workspace-scoped backend contracts. It owns navigation,
interaction, accessibility, validation, and local ephemeral state; it does not
own scoring, page classification, lifecycle truth, or authorization.

## Core rules

- Browser calls use relative `/api/*`; Next.js rewrites to server-only
  `BACKEND_ORIGIN`.
- Server data uses TanStack Query and shared Zod response schemas.
- IDs and active workspace/project context are explicit.
- No production screen falls back to mock data or computes a backend metric.
- Only live destinations render; future work is not shown as disabled UI.
- Long-running state comes from persisted backend projections. Polling may be
  accelerated by events but is never replaced by ephemeral client state.

## Site surfaces

The site area has exactly three destinations:

| Route | Purpose |
|---|---|
| `/site-health` | Crawl lifecycle, score summary, scores by page kind, URL inventory |
| `/issues` | Grouped issue catalog with severity, affected pages, and page-kind scope |
| `/opportunities` | Persisted prioritized actions |

The former multi-panel Site Intelligence workspace is removed. Do not nest a
second site workspace, knowledge panel, journey panel, correction workflow, or
comparison surface inside these routes.

The backend owns the current Site Health phase. The client renders the provided
phase and action availability instead of reconstructing a cross-product of
crawl, discovery, analysis, and phase-run states.

## Page-kind UX

The API-contract schema owns the page-kind vocabulary. Shared helpers in
`frontend/lib/site-health/page-kinds.ts` provide labels, stable ordering, and a
defensive parser for classifier evidence.

Pages and URL detail show the persisted structural kind. The detail disclosure
may explain the winning signal, schema suggestion, alternatives, conflicts,
confidence, and `other` reason. It never reclassifies in the browser.

Issue groups show affected page-kind badges so a product-schema issue is visibly
different from a universal title or delivery issue. Not-applicable evaluations
do not appear as passes or issues.

## Other route ownership

| Route family | Owner |
|---|---|
| `/content` | Content Intelligence |
| `/demand`, `/traffic`, `/analytics` | Demand Intelligence |
| `/prompt-research`, `/prompts`, `/visibility`, `/runs` | Demand/Visibility workflows |
| `/products` | Commerce specialization |
| `/agent` | Growth Agent conversations and bounded task progress |
| `/providers`, `/settings` | Shared workspace/project configuration |

## Data and query ownership

Each domain has one API module, one query-key owner, and shared schemas/types.
Queries are enabled only when their surface is visible where practical. A
shared artifact uses the same server ID and cache identity everywhere.

Unknown, unavailable, zero, historical, conflicting, excluded, and
not-applicable states retain distinct labels and are never communicated by
color alone.

## Verification

Use pnpm only:

```bash
pnpm test -- <file>
pnpm lint
pnpm build
```
