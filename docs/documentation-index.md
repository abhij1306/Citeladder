# CiteLadder active documentation index

This is the authoritative map for current implementation work. A document not
listed here must prove a current operational purpose or move to the archive.

## Authority order

1. Runtime code, migrations, configuration, and tests describe shipped behavior.
2. [`../AGENTS.md`](../AGENTS.md) defines repository-wide implementation rules.
3. [`architecture.md`](architecture.md) defines the product hierarchy.
4. Active plans define approved future work.
5. Current-runtime references explain subsystem contracts.
6. Archived history, when present, is historical context only.

## Product and plans

| Document | Role |
|---|---|
| [`architecture.md`](architecture.md) | Canonical product architecture |
| [`plans/citeladder-aeo-product-rebuild.md`](plans/citeladder-aeo-product-rebuild.md) | Implementation-ready delivery plan for the AEO product rebuild (subordinate to `architecture.md`) |
| [`plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md`](plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md) | Demo-first Content Generation improvement proposal |
| [`plans/citeladder-onboarding-discovery-v7.md`](plans/citeladder-onboarding-discovery-v7.md) | Implemented evidence-first onboarding discovery. Its GMI Cloud cutover was later reverted to Mistral. |
| [`plans/commerce-suite-atomic-rebuild.md`](plans/commerce-suite-atomic-rebuild.md) | Active staged delivery plan and open gates for the Commerce Suite replacement |
| [`plans/commerce-ui-redesign.md`](plans/commerce-ui-redesign.md) | Proposed master-detail redesign of the Commerce workspace, replacing the four verb tabs and their repeated target selectors |
| [`plans/commerce-suite-retirement-manifest.md`](plans/commerce-suite-retirement-manifest.md) | Exact retired Commerce authorities and version lineage for the atomic cutover |
| [`plans/site-health-site-model.md`](plans/site-health-site-model.md) | Active four-PR plan for structurally scoped page facts, internal link metrics, and the observed site architecture model |

## Active implementation plans

No separate implementation plan is currently active beyond the product plans
listed above.

## Current-runtime references

| Document | Role |
|---|---|
| [`site-health.md`](site-health.md) | Crawl, page kinds, rules, scores, issues, graph, readiness, and crawl changes |
| [`backend-architecture.md`](backend-architecture.md) | Backend modules, queues, workers, and routes |
| [`visibility-prompt.md`](visibility-prompt.md) | Canonical topic discovery and AI Visibility prompt-generation contract |
| [`frontend-architecture.md`](frontend-architecture.md) | Frontend ownership, API contracts, and routes |
| [`invariants.md`](invariants.md) | Hard cross-cutting runtime invariants |
| [`api-error-contract.md`](api-error-contract.md) | Canonical API error envelope |
| [`security-fix.md`](security-fix.md) | 2026-08 security boundary and deployment compatibility reference |
| [`design.md`](design.md) | UI tokens, geometry, and interaction rules |
| [`integrations-traffic-analytics.md`](integrations-traffic-analytics.md) | Integration and traffic evidence contracts |
| [`commerce-intelligence.md`](commerce-intelligence.md) | Commerce specialization boundary |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Local development runbook |
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution workflow |
| [`release-checklist.md`](release-checklist.md) | Pre-release and clean-clone verification gates |
| [`../CHANGELOG.md`](../CHANGELOG.md) | Unreleased and published release notes |
| [`../Review.md`](../Review.md) | Review checklist |

Operational runbooks under `operations/`, evaluation fixtures under
`evaluations/`, and backend measurement references under `../backend/docs/`
remain active within their named scopes.

## Current Site Health boundary

The shipped product has three site surfaces: Site Health, Issues, and
Opportunities. The former Site Intelligence workspace, industry-pack runtime,
knowledge kernel, corrections, and its cross-industry comparison workspace were
removed during the 2026-08 simplification. The shipped deterministic
comparable-crawl Change Intelligence projection is a Site Health owner, not a
revival of that workspace. Historical context is non-authoritative; use
[`site-health.md`](site-health.md) for the current contract.

Site analysis is governed by the generic `page_kind` taxonomy and its
config-owned schema/property contracts. `other` means classification abstained;
it must not receive a guessed type-specific checklist.

## Documentation change rule

When authority changes, update this index in the same change and move the
superseded document to the archive. Do not leave broken pointers or competing
guidance in the active tree.
