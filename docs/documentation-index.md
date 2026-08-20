# CiteLadder active documentation index

This is the authoritative map for current implementation work. A document not
listed here must prove a current operational purpose or move to the archive.

## Authority order

1. Runtime code, migrations, configuration, and tests describe shipped behavior.
2. [`../AGENTS.md`](../AGENTS.md) defines repository-wide implementation rules.
3. [`architecture.md`](architecture.md) defines the product hierarchy.
4. Active plans define approved future work.
5. Current-runtime references explain subsystem contracts.
6. [`archive/`](archive/README.md) is historical context only.

## Product and plans

| Document | Role |
|---|---|
| [`architecture.md`](architecture.md) | Canonical product architecture |
| [`plans/citeladder-aeo-product-rebuild.md`](plans/citeladder-aeo-product-rebuild.md) | Implementation-ready delivery plan for the AEO product rebuild (subordinate to `architecture.md`) |
| [`plans/growth-intelligence-platform.md`](plans/growth-intelligence-platform.md) | Program sequence and open cross-system work |
| [`plans/content-intelligence.md`](plans/content-intelligence.md) | Content strategy, briefs, generation, review, and verification |
| [`plans/demand-intelligence.md`](plans/demand-intelligence.md) | GSC/GA4, journeys, prompts, and AI Visibility |
| [`plans/growth-agent.md`](plans/growth-agent.md) | Typed tools, context, decisions, and schedules |

## Engineering decision inputs

These documents record bounded research or completed audit evidence. They are
not runtime or implementation authority; findings are implemented only when
they are reflected in code, tests, configuration, migrations, or an active
plan.

| Document | Role |
|---|---|
| [`plans/deep-research-report.md`](plans/deep-research-report.md) | Non-authoritative Feedonomics demo research input |

## Current-runtime references

| Document | Role |
|---|---|
| [`site-health.md`](site-health.md) | Crawl, page kinds, rules, scores, issues, graph, readiness, and crawl changes |
| [`backend-architecture.md`](backend-architecture.md) | Backend modules, queues, workers, and routes |
| [`frontend-architecture.md`](frontend-architecture.md) | Frontend ownership, API contracts, and routes |
| [`invariants.md`](invariants.md) | Hard cross-cutting runtime invariants |
| [`api-error-contract.md`](api-error-contract.md) | Canonical API error envelope |
| [`security-fix.md`](security-fix.md) | 2026-08 security boundary and deployment compatibility reference |
| [`design.md`](design.md) | UI tokens, geometry, and interaction rules |
| [`integrations-traffic-analytics.md`](integrations-traffic-analytics.md) | Integration and traffic evidence contracts |
| [`commerce-intelligence.md`](commerce-intelligence.md) | Commerce specialization boundary |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | Local development runbook |
| [`../COMMANDS.md`](../COMMANDS.md) | Command reference |
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
