# Contributing to CiteLadder

Thanks for contributing. Read [`AGENTS.md`](AGENTS.md),
[`docs/README.md`](docs/README.md), and [`docs/invariants.md`](docs/invariants.md) before making a
change. `docs/archive/` is historical and is not an implementation authority.

## Before starting

1. Search for the current owner of the model, route, schema, config, industry entry, queue,
   component, test, and documentation. One concept has one owner.
2. Read only the current subsystem authority and the relevant gated plan slice.
3. Confirm whether the requested behavior is shipped, planned, or an evaluation requirement.
4. Preserve workspace authorization, evidence immutability, provenance/versioning, unknown-state
   semantics, and approval boundaries in the design—not as cleanup after implementation.

## Development workflow

1. Create a scoped branch such as `feat/<description>`, `fix/<description>`,
   `docs/<description>`, or `refactor/<description>`.
2. Put code in the owning layer:
   - backend: `api / core / models / schemas / domain / connectors / orchestration / analysis /
     workers`;
   - frontend: app shell/auth, API-contract layer, domain workspaces, shared primitives/tokens.
3. Make the smallest complete gated change. Do not add parallel stores or hidden partial
   architecture.
4. Add deterministic/unit, component/workspace-isolation, API/UI contract, and evaluation fixture
   tests as applicable.
5. Update the current owner documentation. Move superseded plans or design records into
   `docs/archive/` instead of maintaining two authorities.
6. Open a pull request with a clear summary and exact `## Testing` evidence.

## Configuration and industry knowledge

Operational settings and product policy do not live in service code. Models, transports, limits,
timeouts, retries, thresholds, page roles, classifier signals, entity/predicate registries,
journeys, FAQ expectations, claim policies, context budgets, prompt archetypes, and creative brief
constraints belong under `backend/app/core/config/*` or a documented frontend config owner.

The shared industry registry is reviewed product data. Project/customer evidence never mutates it.
A generalized change requires a registry version, migration note where needed, validation, and
labelled evaluation coverage. Do not create industry-specific tables or service branches when the
shared core and profile can represent the concept.

## Evidence, knowledge, and generation

- Source artifacts are immutable and are not automatically true.
- Every derived row records exact source IDs and relevant versions.
- Reports and reads use persisted projections only.
- Model output remains proposed/derived until deterministic validation and explicit user approval.
- Approved memory requires an audited transition; raw chat and generated bodies are not memory.
- FAQ or other generated content must use a frozen brief/context package and cannot invent unknown,
  historical-as-current, conflicting, numeric, regulated, safety, price, fee, date, policy, or
  availability claims.
- `FAQPage` JSON-LD must match visible reviewed content.

## Database migrations

CiteLadder currently maintains one hand-written greenfield baseline at
`migrations/versions/0001_initial.py`. Fold schema changes into it while this policy remains
active and verify only against a disposable database:

```bash
cd backend
uv run alembic upgrade head
uv run alembic check
```

Never downgrade or reset a shared, staging, or production database.

## API and frontend contracts

The backend is the wire-contract source of truth. Update matching Zod schemas, API functions,
query keys, MSW fixtures, null/coverage states, and UI tests with a DTO change. The browser uses
relative `/api/*` through same-origin Next.js rewrites; do not expose a browser-visible backend
origin.

## Verification

Run focused checks while working and the full relevant suite before review:

```bash
# Backend, from backend/
uv run pytest tests/unit/test_<area>.py tests/component/test_<area>.py -q
uv run ruff check <changed paths>
uv run alembic upgrade head
uv run alembic check

# Frontend, from frontend/
pnpm test -- <file>
pnpm check:contract
pnpm check:policy
pnpm exec tsc --noEmit
pnpm build
```

Industry-profile work also runs the registry validator, onboarding fallback tests, labelled
classification/gap fixtures, FAQ validation fixtures, and a before/after verification case.
Live sites, provider APIs, and connected analytics are opt-in acceptance sources, not CI
requirements.

## Release preparation

Releases are maintainer-owned and occur only after the change has merged. Do not create a tag,
GitHub release, or package publication from a feature branch. Follow the clean-clone Compose and
repository gates in [`docs/release-checklist.md`](docs/release-checklist.md), update
[`CHANGELOG.md`](CHANGELOG.md), and obtain release-owner approval for the exact candidate commit
before creating release artifacts.

## Commits and review

Use conventional, scoped commit messages. When other work exists in the tree, stage explicit
pathspecs rather than `git add -A`. A change fails review when it violates any current invariant,
even if its happy path appears to work.

Report bugs with reproduction, expected/actual behavior, versions, and safe logs or screenshots.
Disclose secret-handling or other security issues privately.

Contributions are licensed under the [MIT License](LICENSE).
