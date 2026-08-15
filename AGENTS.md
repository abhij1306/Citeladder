# Agents.md — CiteLadder

> Mandatory session bootstrap for coding agents. Read this file first, then
> follow the documentation map below. Archived plans are historical context
> only and are never implementation authority.

## What CiteLadder is

CiteLadder is an evidence-grounded growth intelligence platform organized
around one measurable loop: Connect → Analyze → Act → Improve / Verify →
Track. Four durable capabilities sit behind those stations:

1. **Site Health** securely crawls the owned website, classifies each page by
   structural type, applies the correct deterministic checklist, and produces
   persisted scores, issues, snapshots, and opportunities.
2. **Content Intelligence** turns site and demand evidence into strategies,
   briefs, drafts, reviews, and post-publication verification.
3. **Demand Intelligence** connects GSC, GA4, journeys, prompts, and AI
   Visibility to show what audiences need and what should improve next.
4. **Growth Agent** orchestrates typed tools from those systems. It owns no
   second knowledge store and cannot publish or mutate external systems without
   an explicit user action.

The measured outcome is increased observed mention/citation share across a
versioned prompt portfolio under comparable audit conditions. AI Visibility is
the Track capability; crawl health, demand coverage, and AEO readiness are
leading indicators, never causal proof.

## Canonical documentation

Read only the documents required by the task.

| Task | Required source |
|---|---|
| Product loop, hierarchy, and architecture | `docs/architecture.md` |
| AEO rebuild delivery sequence | `docs/plans/citeladder-aeo-product-rebuild.md` |
| Complete active-document map | `docs/documentation-index.md` |
| Program sequence | `docs/plans/growth-intelligence-platform.md` |
| Site crawl, classification, rules, and runtime | `docs/site-health.md` |
| Content workflows | `docs/plans/content-intelligence.md` |
| Demand, prompts, and visibility | `docs/plans/demand-intelligence.md` |
| Agent, context, approvals, schedules | `docs/plans/growth-agent.md` |
| Backend ownership and shipped runtime | `docs/backend-architecture.md` |
| Frontend ownership and shipped runtime | `docs/frontend-architecture.md` |
| Hard invariants | `docs/invariants.md` |
| API errors | `docs/api-error-contract.md` |
| UI tokens and interaction rules | `docs/design.md` |
| Historical context | `docs/archive/` — only when explicitly reconciling old behavior |

Code plus current-runtime tests describe what is shipped. Active plans describe
approved future work. Archived plans have no authority.

## Site Health architecture

The shipped Site Health product has three pages: **Site Health**, **Issues**,
and **Opportunities**. Do not recreate the removed Site Intelligence workspace,
industry-pack catalog, knowledge tables, corrections, or comparison system.

Page analysis separates acquisition truth from structural classification:

```text
safe acquisition -> immutable artifact -> normalized facts
  -> deterministic page_kind + evidence
  -> page-kind-scoped rules and schema contract
  -> persisted evaluations, scores, issues, snapshot, opportunities
```

`page_kind` is the stable, cross-industry structural purpose. Structured data
is one classifier signal and one gap surface; it must never self-certify the
type whose schema is being validated. Path, headings, visible content, forms,
links, and delivery signals must still work when schema is absent.

Unclassified pages use `other`. That is an abstention, not a `WebPage` verdict:
page-kind-specific rules fail closed and remain out of scoring. A JS shell is
also distinct from missing content; content-reading rules stay not-applicable
while `aeo.server_rendered_content` owns the observable problem.

Every classifier, extractor, analyzer, rule, and scoring change carries a
version bump so append-only analyses are replayable.

## Repository invariants

- All IDs are UUIDs. Every project-owned query is workspace-authorized; never
  scope product data by `user_id` or trust an object ID alone.
- API routes use `/api/v1`. Browser calls remain same-origin through the
  frontend proxy.
- Configuration, catalogs, thresholds, limits, templates, page profiles, and
  schedules live in `backend/app/core/config/*` or frontend config owners—not
  service code.
- Raw evidence and provider attempts are immutable/append-only. Derived rows
  carry exact source IDs and relevant extractor, analyzer, classifier, rule,
  formula, template, or model versions.
- Read APIs render persisted projections. They never crawl, sync, call a
  model, or repair state.
- PostgreSQL remains durable state and the task queue. Claim with
  `FOR UPDATE SKIP LOCKED`, commit before network I/O, and use leases and
  idempotency. Do not add Redis without measured need.
- Extend existing subsystem owners before adding a table, queue, fetcher,
  parser, recommendation store, content store, or memory system.
- A model may explain, classify bounded ambiguity, plan, or generate. It never
  becomes raw truth or changes a deterministic metric.
- Unknown, unavailable, zero, historical, conflicting, not-applicable, and
  excluded are distinct states.
- No autonomous publishing, prompt activation, external mutation, or
  unbounded agent loop.

## Default implementation workflow

1. Identify the active owner and search before adding.
2. Inspect current code, tests, models, configuration, and API contracts.
3. Implement one gated slice completely.
4. Add deterministic fixtures plus workspace-isolation/provenance tests where
   persistence is touched.
5. Update active documentation when shipped authority changes.
6. Move superseded material to `docs/archive/`; never leave contradictory
   guidance beside active plans.
7. Run focused verification and report exactly what was and was not verified.

## Package and migration rules

- Frontend uses **pnpm only**, pinned by `frontend/package.json`. Never use npm
  or yarn and never create `package-lock.json`.
- CiteLadder is pre-launch and keeps one explicit
  `migrations/versions/0001_initial.py`. Fold schema changes into it, reset a
  disposable database, migrate from scratch, and check ORM drift. Do not add a
  `0002+` migration unless this policy changes explicitly.

## Focused verification

```bash
# Backend, from backend/
uv run pytest tests/unit/test_<area>.py tests/component/test_<area>.py -q
uv run ruff check <changed paths>
uv run alembic upgrade head
uv run alembic check

# Frontend, from frontend/
pnpm test -- <file>
pnpm lint
pnpm build

# Documentation, from repository root
python docs/validate_documentation.py
```

Preserve unrelated user-owned work. Do not use failures from another dirty
workstream as justification to rewrite or delete it.
