# CiteLadder Active Documentation Index

**Purpose:** one small, authoritative map for humans and coding agents. A document not listed here
must prove a current operational purpose before it is used for implementation.

## Authority order

1. Runtime code, migrations, configuration, and tests describe shipped behavior.
2. `Agents.md` defines repository-wide implementation rules.
3. `docs/architecture.md` defines the target product hierarchy.
4. The canonical Growth Intelligence plans define the migration and gated implementation slices.
5. Current-runtime references explain subsystem ownership and existing contracts.
6. `docs/archive/` is historical context only.

A stale plan never overrides code. Existing code does not invalidate an approved target plan; it
states the migration starting point.

## Product and program architecture

| Document | Role |
|---|---|
| [`../Agents.md`](../Agents.md) | Mandatory agent bootstrap, invariants, and read-on-demand map |
| [`README.md`](README.md) | Documentation read order and active-plan overview |
| [`architecture.md`](architecture.md) | Canonical product architecture and long-term vision |
| [`plans/growth-intelligence-platform.md`](plans/growth-intelligence-platform.md) | Master program architecture, boundaries, and dependency graph |
| [`plans/site-intelligence-primary-product.md`](plans/site-intelligence-primary-product.md) | Crawler, corpus, page understanding, knowledge, reports, Education and Commerce |
| [`plans/content-intelligence.md`](plans/content-intelligence.md) | Strategy, briefs, generation, automatic validation, save, and verification |
| [`plans/demand-intelligence.md`](plans/demand-intelligence.md) | GSC/GA4, journeys, demand signals, prompts, and Visibility |
| [`plans/growth-agent.md`](plans/growth-agent.md) | Typed tools, selective context, corrections, orchestration, and schedules |
| [`plans/frontend-growth-intelligence.md`](plans/frontend-growth-intelligence.md) | App IA migration, shared insight/evidence components, landing page, website content, and UI debt |

## Knowledge and industry packs

| Document | Role |
|---|---|
| [`plans/knowledge-kernel-and-industry-pack-spec.md`](plans/knowledge-kernel-and-industry-pack-spec.md) | Stable knowledge contracts, persistence, pack lifecycle, and migration mapping |
| [`../backend/app/core/config/industry_packs/README.md`](../backend/app/core/config/industry_packs/README.md) | Canonical executable catalog authority, layout, maturity, source snapshot, and validation |
| [`../backend/app/core/config/industry_packs/schema/industry-pack.schema.json`](../backend/app/core/config/industry_packs/schema/industry-pack.schema.json) | Normative machine-readable pack schema |
| [`../backend/app/core/config/industry_packs/PAGE_ANALYSIS_AUDIT.md`](../backend/app/core/config/industry_packs/PAGE_ANALYSIS_AUDIT.md) | Audit of the shipped generic classifier and exact migration boundary |
| [`../backend/app/core/config/industry_packs/PERFORMANCE_CONTRACT.md`](../backend/app/core/config/industry_packs/PERFORMANCE_CONTRACT.md) | Classifier hot-loop, crawler, persistence, scale, and benchmark contract |
| [`../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md`](../backend/app/core/config/industry_packs/EXTENSION_CONTRACT.md) | Shared releases, capability composition, project overlays, and maturity promotion |
| [`../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md`](../backend/app/core/config/industry_packs/EVALUATION_CONTRACT.md) | Deterministic fixtures, safety gates, field evaluation, and regression policy |
| [`plans/industry-packs/README.md`](plans/industry-packs/README.md) | Compatibility pointer only; contains no competing pack definitions |
| [`evaluations/README.md`](evaluations/README.md) | Evaluation-corpus provenance, labels, activation, and CI policy |
| [`evaluations/education/the-asian-school/screaming-frog-growth-diagnostic.md`](evaluations/education/the-asian-school/screaming-frog-growth-diagnostic.md) | First-customer diagnostic and Education/crawler acceptance requirements |

## Implementation handoff

| Document | Role |
|---|---|
| [`plans/growth-intelligence-delivery-tracker.md`](plans/growth-intelligence-delivery-tracker.md) | Active three-branch delivery status, verification record, gotchas, and fresh-chat handoffs |
| [`plans/codex-site-intelligence-wiring-handoff.md`](plans/codex-site-intelligence-wiring-handoff.md) | Next gated slice: freeze pack manifests and shadow-wire industry roles beside generic page types |

The handoff is subordinate to the architecture and companion plans. Update it when gates or
canonical dependencies change.

## Current-runtime references

These documents retain their place because they describe shipped ownership, invariants, APIs,
operations, or design constraints. They are not alternate product roadmaps.

| Document | Role |
|---|---|
| [`../COMMANDS.md`](../COMMANDS.md) | Local setup, database, worker, test, and verification command reference |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution workflow and repository ownership rules |
| [`../Review.md`](../Review.md) | Code-review checklist and recurring security/correctness anti-patterns |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Local stack, test, migration, entitlement, and environment runbook |
| [`backend-architecture.md`](backend-architecture.md) | Shipped backend modules, models, queues, workers, and routes |
| [`frontend-architecture.md`](frontend-architecture.md) | Shipped frontend ownership, API-contract layer, and route behavior |
| [`invariants.md`](invariants.md) | Hard cross-cutting runtime invariants |
| [`api-error-contract.md`](api-error-contract.md) | Canonical error envelope and coded failures |
| [`design.md`](design.md) | Design tokens, screen geometry, the insight object, and interaction rules |
| [`site-health.md`](site-health.md) | Shipped generic Site Health behavior until Site Intelligence slices replace it |
| [`commerce-intelligence.md`](commerce-intelligence.md) | Current Commerce specialization boundary within the shared intelligence architecture |
| [`integrations-traffic-analytics.md`](integrations-traffic-analytics.md) | Current persisted integration/traffic evidence and Demand migration boundary |
| [`validate_documentation.py`](validate_documentation.py) | Enforces the active-document allowlist and validates local links |
| [`../backend/docs/`](../backend/docs/) | Backend evaluation/measurement references used by current code and tests |

A current-runtime reference that contains future-roadmap prose must be corrected when its owning
slice changes; future direction belongs only in the canonical plans.

## Industry pack maturity

- **Canonical catalog:** 16 exact versioned JSON packs under `backend/app/core/config/industry_packs/`, with immutable loading, hash verification, reference classification, fixtures, validation, tests, and benchmarks.
- **Validated candidates:** Education and Commerce; they are ready for controlled shadow evaluation, not automatically authoritative production findings.
- **Foundation packs:** General Business plus 13 additional industry families; complete definitions and fixtures do not substitute for representative domain calibration.
- **Runtime readiness:** the catalog library exists, but current Site Health still persists and scores the generic `page_type`; production pack selection and `industry_role` persistence are the next gated slice.
- **Project extensions:** versioned overlays remain project-scoped and never alter shared packs or another customer’s knowledge.

## Archive

[`archive/README.md`](archive/README.md) records why superseded files are retained and how the
archive is organized. Archived documents are intentionally excluded from
normal agent discovery.

## Documentation change rule

A change that introduces, supersedes, or renames an architectural authority must update this
index in the same pull request. Superseded documents move to the archive; the canonical executable catalog remains under
`backend/app/core/config/industry_packs/`.
