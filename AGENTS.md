# Agents.md — CiteLadder

> Mandatory session bootstrap for coding agents. Read this file first, then follow the
> documentation map below. Archived plans are historical context only and are never an
> implementation authority.

## What CiteLadder is

CiteLadder is an **evidence-grounded growth intelligence platform** for legacy businesses and
startups that need one governed system for their website, knowledge, content, demand, and
marketing decisions.

The product has three intelligence systems and one orchestrator:

1. **Site Intelligence** acquires the owned corpus, understands pages and documents, builds the
   project knowledge model, detects industry-specific gaps, and verifies changes after recrawl.
2. **Content Intelligence** turns verified knowledge and prioritized gaps into strategies,
   briefs, FAQs, drafts, reviews, and post-publication verification.
3. **Demand Intelligence** connects GSC, GA4, business journeys, paid/organic evidence, prompts,
   and AI Visibility to show what audiences need and what should improve next.
4. **Growth Agent** is the bounded orchestrator over typed tools from those systems. It does not
   own a second knowledge store and cannot promote model output into durable memory without an
   explicit user action.

**AI Visibility is a measurement capability inside Demand Intelligence, not the product's
organizing principle.** Existing visibility functionality remains valuable and must be preserved,
but new architecture and navigation follow the three-system hierarchy.

## Product loop

```text
acquire evidence
  -> understand the business and its owned corpus
  -> detect role-, journey-, and demand-specific gaps
  -> prioritize actions
  -> create or improve content
  -> measure and recrawl
  -> explain what changed and choose the next action
```

The first narrow end-to-end implementation is **FAQ Intelligence**:

```text
industry role classification
  -> required-question coverage
  -> evidence-backed FAQ brief
  -> constrained FAQ generation
  -> human approval
  -> visible FAQ and optional matching FAQPage JSON-LD
  -> recrawl verification
```

## Canonical documentation

Read only the documents required by the task.

| Task | Required source |
|---|---|
| Product hierarchy and architecture | `docs/architecture.md` |
| Complete active-document map | `docs/documentation-index.md` |
| Program architecture and sequence | `docs/plans/growth-intelligence-platform.md` |
| Site/crawler/knowledge implementation | `docs/plans/site-intelligence-primary-product.md` |
| Knowledge kernel persistence and migration | `docs/plans/knowledge-kernel-and-industry-pack-spec.md` |
| Canonical industry catalog, audit, validation, and extension rules | `backend/app/core/config/industry_packs/README.md` |
| Industry-role production wiring | `docs/plans/codex-site-intelligence-wiring-handoff.md` |
| FAQ-first implementation | `docs/plans/faq-intelligence-first-slice.md` |
| Content workflows | `docs/plans/content-intelligence.md` |
| GSC/GA4/demand/prompts/visibility | `docs/plans/demand-intelligence.md` |
| Agent, context, approvals, schedules | `docs/plans/growth-agent.md` |
| Backend ownership and shipped runtime | `docs/backend-architecture.md` |
| Frontend ownership and shipped runtime | `docs/frontend-architecture.md` |
| Hard invariants | `docs/invariants.md` |
| API errors | `docs/api-error-contract.md` |
| UI tokens and interaction rules | `docs/design.md` |
| Historical context | `docs/archive/` — read only when explicitly reconciling old behavior |

When a current-runtime reference and a target plan differ:

- code plus current-runtime tests describe what is shipped now;
- the canonical Growth Intelligence plans describe the intended migration;
- an archived plan has no authority;
- do not silently change runtime behavior merely because a target document exists.

## Knowledge architecture

The word **knowledge base** means a governed system, not a vector store or model-written summary:

```text
immutable evidence
  + versioned working intelligence
  + explicitly approved project memory
```

The shared core is industry-neutral. A versioned `IndustryPack` supplies page roles, entities,
assertions, journeys, required questions, trust expectations, schema expectations, rules, briefs,
prompts, and evaluation fixtures for one industry. Customer evidence and approved facts remain
project-scoped and never mutate a shared pack automatically.

Page analysis always separates:

```text
page_kind      = generic structural purpose
industry_role  = active-pack business purpose
```

Structured data is one classifier signal and one gap surface; it is not the sole way to identify
a page. Deterministic path, title, heading, content, form, link, media, and visible-fact signals
must work when schema is absent.

**Status:** the Site Intelligence layer is built through slice S5 — inventory, acquisition ladder,
typed knowledge, 16 registered industry packs, snapshots, durable corrections, inline
contradiction decisions, immutable compatible-recrawl comparison, evidence-only action
resolution, and the six-panel workspace. There is deliberately no approved-memory store or
review inbox: every assertion stays `observed`, while a typed correction overlays it, survives
recomputation, records append-only transitions, and can be withdrawn to restore the derived value.

Only `education` and `commerce` are calibrated against a real corpus; the other fourteen packs
are structurally valid but unproven. See
[`docs/plans/site-intelligence-primary-product.md` §15](docs/plans/site-intelligence-primary-product.md#15-delivery-status-and-open-work).

## First acceptance corpora

- **Education:** The Asian School Screaming Frog export is an external crawler baseline and a
  sanitized Education evaluation corpus. Technical observations may be compared directly;
  semantic roles and expected gaps require reviewed labels.
- **Commerce:** synthetic and opt-in merchant fixtures cover category, PDP, variant, offer,
  policy, comparison, FAQ, shipping, and returns behavior.

Every future industry pack requires versioned fixtures with expected classifications, entities,
assertions, gaps, briefs, and verification outcomes.

## Repository invariants

- All IDs are UUIDs. Every project-owned query is workspace-authorized; never scope product data
  by `user_id` or trust an object ID alone.
- API routes use `/api/v1`. Browser calls remain same-origin through the frontend proxy.
- Configuration, catalogs, thresholds, model capabilities, limits, templates, pack definitions,
  and schedules live in `backend/app/core/config/*` or frontend config owners—not service code.
- Raw evidence and provider attempts are immutable/append-only. Every derived row carries exact
  source IDs and analyzer, rule, formula, pack, template, or model versions as applicable.
- Read APIs render persisted projections. They never crawl, sync, call a model, or repair state.
- PostgreSQL remains durable state and the task queue. Claim with `FOR UPDATE SKIP LOCKED`, commit
  before network I/O, use leases/idempotency, and do not add Redis without measured need.
- Extend existing subsystem owners before adding a table, queue, fetcher, parser, recommendation
  store, content store, or memory system.
- A model may classify ambiguity, extract bounded candidates, explain, plan, generate prompts,
  FAQs, content, or creatives. It never becomes raw truth, changes a deterministic metric, or
  writes Approved Brand Memory without an audited approval transition.
- Unknown, unavailable, zero, historical, conflicting, not-applicable, and excluded are distinct
  states. Never collapse them for convenience.
- No autonomous publishing, prompt activation, external mutation, or unbounded agent loop.

## Default implementation workflow

1. Identify the canonical plan and owning subsystem.
2. Search before adding; duplication is a review failure.
3. Inspect the current code, tests, models, configuration, and API contracts.
4. Implement one gated slice completely rather than partially implementing several plans.
5. Add deterministic fixtures and workspace-isolation/provenance tests.
6. Update the active documentation and `docs/documentation-index.md` when authority changes.
7. Move superseded material to `docs/archive/`; do not leave contradictory guidance beside active
   plans.
8. Run focused verification and report exactly what was and was not verified.

## Package and migration rules

- Frontend uses **pnpm only**, pinned by `frontend/package.json`. Never use npm or yarn and never
  create `package-lock.json`.
- CiteLadder is pre-launch and keeps one explicit `migrations/versions/0001_initial.py`. Fold
  schema changes into it, reset a disposable database, run the migration from scratch, and check
  ORM drift. Do not add a `0002+` migration unless this policy is explicitly changed.

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

# Canonical industry catalog, from backend/
uv run python -m app.core.config.industry_packs.validate
```

Do not use unrelated failures from another dirty workstream as justification to rewrite or delete
its work. Preserve user-owned changes, state focused limitations, and keep archived history intact.
