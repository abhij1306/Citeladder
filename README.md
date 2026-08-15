<div align="center">

# CiteLadder

<strong>Connect evidence, improve what answer engines can understand, and track observed citation share.</strong>

[Architecture](docs/architecture.md) · [Backend](docs/backend-architecture.md) · [Frontend](docs/frontend-architecture.md) · [Invariants](docs/invariants.md) · [Plans](docs/plans/) · [Development](docs/DEVELOPMENT.md)

<p align="center">
  CiteLadder is an evidence-grounded growth intelligence platform for making a brand more likely to be recommended and cited by answer engines—without pretending leading indicators prove causality.
</p>

<p align="center">
  <a href="https://github.com/abhij1306/Citeladder/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/abhij1306/Citeladder?style=flat-square" /></a>
  <a href="https://github.com/abhij1306/Citeladder/issues"><img alt="GitHub issues" src="https://img.shields.io/github/issues/abhij1306/Citeladder?style=flat-square" /></a>
  <a href="https://github.com/abhij1306/Citeladder/blob/main/LICENSE"><img alt="MIT License" src="https://img.shields.io/github/license/abhij1306/Citeladder?style=flat-square" /></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&amp;logoColor=white&amp;style=flat-square" />
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-modular%20monolith-009688?logo=fastapi&amp;logoColor=white&amp;style=flat-square" />
  <img alt="Next.js 16" src="https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&amp;logoColor=white&amp;style=flat-square" />
  <img alt="TypeScript" src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&amp;logoColor=white&amp;style=flat-square" />
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?logo=postgresql&amp;logoColor=white&amp;style=flat-square" />
</p>

<p align="center">
  <code>Connect</code> · <code>Analyze</code> · <code>Act</code> · <code>Improve / Verify</code> · <code>Track</code> · <code>AEO</code> · <code>AI Visibility</code> · <code>Evidence-Grounded</code> · <code>Open Source</code>
</p>

</div>

---

<a id="what-citeladder-does"></a>
## What CiteLadder does

Most growth tooling answers one question and leaves the evidence behind. CiteLadder answers four
connected questions over one governed evidence system:

1. **What does this business currently say and prove?**
2. **What is missing, weak, contradictory, stale, or hard to discover?**
3. **What are customers demonstrably asking and doing?**
4. **What should the business improve, create, and measure next?**

The durable differentiator is not the crawler, the dashboard, or the chat box. It is a
project-specific evidence trail that compounds through every crawl, import,
generation, audit, and later measurement.

<a id="product-architecture"></a>
## Product architecture

Five user-facing stations sit over four durable capability owners.

| Layer | Owns |
|---|---|
| **Site Health** | Crawls the owned site, classifies pages structurally, applies page-type-correct checks, and persists comparable-crawl changes |
| **Content Intelligence** | Turns verified gaps into strategies, briefs, drafts, and post-publication verification |
| **Demand Intelligence** | Connects GSC, GA4, journeys, prompts, AI Visibility, and later paid marketing evidence to decide what improves next |
| **Growth Agent** | Explains and orchestrates bounded tasks through typed tools, selective context, and reproducible provenance |

AI Visibility is the Track station. The primary measured outcome is increased
**observed** mention/citation share under comparable portfolio and engine
conditions; Site Health and demand metrics remain leading indicators.

> The Growth Agent is a real layer — the one you spend the most time in — but it owns no data. It
> is deliberately **not** a fourth database, an unrestricted chat interface, or an autonomous
> publisher.

## What you actually have to do

The system runs itself. You are asked exactly twice:

| Decision | Why you are here |
|---|---|
| **Generate and save content** | Content is the only durable outward-facing output. You choose what to generate, edit it, and decide what to keep. |
| **Run and schedule audits** | Crawls, syncs, and answer-engine audits cost money and hit external systems. You choose when they run. |

Everything else — bounded crawling, structural page classification, deterministic
analysis, demand signals, prompt generation, prioritization, and roadmaps — may
run automatically within configured limits. Every output records its source and
version so stale analysis can be recomputed rather than silently reinterpreted.

<a id="durable-differentiator"></a>
## The evidence system

```text
immutable evidence
  + versioned page-kind analysis
  + persisted demand and content projections
  + explicit user decisions
```

Persistence means **observed**, never automatically true. Site Health keeps
immutable acquisition evidence and versioned analysis. Generated content never
becomes a fact on its own. The former industry-pack and knowledge-kernel runtime
was removed during simplification; page analysis now uses a small generic
structural taxonomy with page-type-specific schema and content rules.

<a id="first-complete-workflow"></a>
## The improvement loop

```text
owned domain, documents, and integrations
  -> immutable evidence
  -> page and document understanding
  -> project facts, gaps, and demand signals
  -> prioritized opportunities
  -> brief
  -> generated content you edit and save
  -> recrawl, resync, or visibility audit
  -> before/after observation
  -> next recommended action
```

Every stage is inspectable and versioned, and a later observation never rewrites earlier evidence.
Unknown fees, dates, prices, policies, and regulated claims are requested or omitted — never
invented. Structured data mirrors saved visible content; it is never a substitute for it.

<a id="what-citeladder-does-not-claim"></a>
## What CiteLadder does not claim

Stated as plainly as the features, because it is a design constraint rather than a disclaimer:

- no causal conversion diagnosis without adequate behavioural evidence;
- no autonomous publishing or external mutation;
- no model trained on private customer data;
- no automatic sharing of one customer's facts with another;
- no single universal score that hides coverage or industry differences.

`unavailable`, `not configured`, and `observed zero` stay three different things.

<a id="quick-start"></a>
## Quick start (Docker Compose)

> **Important:** exported `POSTGRES_*` and `DATABASE_URL` shell variables are resolved by Compose
> *before* `.env`. Use the `env -u …` form verbatim — see [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

```bash
# 1. Copy the env template
cp infra/docker/.env.example infra/docker/.env    # edit secrets for anything non-local

# 2. Start Postgres first
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=citeladder_dev_password \
  docker compose -f infra/docker/docker-compose.yml up -d --force-recreate db

# 3. Apply migrations from the repository root
(cd backend && uv run alembic upgrade head)

# 4. Bring up the application services
env -u POSTGRES_PASSWORD -u POSTGRES_USER -u POSTGRES_DB -u DATABASE_URL \
  POSTGRES_PASSWORD=citeladder_dev_password \
  docker compose -f infra/docker/docker-compose.yml up -d --build

# 5. Start the frontend
cd frontend
echo "BACKEND_ORIGIN=http://localhost:8000" > .env.local
pnpm install
pnpm dev            # http://localhost:3000
```

Register a user (a workspace is created automatically), create a project, then connect a BYOK
provider for Visibility audits or open Site Health to discover and analyze the site.

Full command reference: [`COMMANDS.md`](COMMANDS.md). Environment, entitlement, and migration
runbook: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

<a id="start-here"></a>
## Start here

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Mandatory implementation rules and the task-specific document map |
| [`docs/documentation-index.md`](docs/documentation-index.md) | Complete active documentation authority map |
| [`docs/architecture.md`](docs/architecture.md) | Canonical target product architecture |
| [`docs/invariants.md`](docs/invariants.md) | The review-blocking rules |
| [`docs/plans/growth-intelligence-platform.md`](docs/plans/growth-intelligence-platform.md) | Program architecture and delivery order |
| [`docs/site-health.md`](docs/site-health.md) | Site crawl, page kinds, rules, issues, link graph, readiness, and crawl changes |
| [`docs/design.md`](docs/design.md) | Design tokens, screen geometry, and the insight object |

Everything under [`docs/archive/`](docs/archive/) is historical and is **not** an implementation
authority.

<a id="repository-shape"></a>
## Repository shape

```text
frontend/                              Next.js application
backend/app/                           FastAPI modular monolith and workers
backend/app/core/config/site_health.py page-kind, crawl, rule, and scoring policy
migrations/versions/0001_initial.py    pre-launch canonical database baseline
docs/plans/                            active target implementation plans
docs/evaluations/                      evaluation corpora, provenance, and labels
docs/archive/                          historical plans and superseded context
```

<a id="focused-validation"></a>
## Focused validation

```bash
# Repository root
python docs/validate_documentation.py

# Backend, from backend/
uv run pytest tests/unit/test_<area>.py tests/component/test_<area>.py -q
uv run ruff check <changed paths>

# Frontend, from frontend/ — pnpm only
pnpm test -- <file>
pnpm lint
pnpm build
```

<a id="contributing"></a>
## Contributing

Read [`Agents.md`](Agents.md) and the owning architecture document before changing code.
[`CONTRIBUTING.md`](CONTRIBUTING.md) covers workflow and ownership; [`Review.md`](Review.md) covers
the review checklist and recurring anti-patterns.

CiteLadder is a dirty, active, multi-workstream repository. Preserve unrelated user-owned changes
and verify focused slices rather than rewriting other workstreams.

<a id="license"></a>
## License

[MIT](LICENSE)
