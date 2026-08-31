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
| [`plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md`](plans/CITELADDER_CONTENT_GENERATION_SIMPLIFIED_PLAN.md) | Frontier-model Content Generation plan with crawl, demand, and typed Opportunity grounding |
| [`plans/citeladder-onboarding-discovery-v7.md`](plans/citeladder-onboarding-discovery-v7.md) | Implemented evidence-first onboarding discovery. Its GMI Cloud cutover was later reverted to Mistral. |
| [`plans/commerce-suite-atomic-rebuild.md`](plans/commerce-suite-atomic-rebuild.md) | Active staged delivery plan and open gates for the Commerce Suite replacement |
| [`plans/commerce-ui-redesign.md`](plans/commerce-ui-redesign.md) | Proposed master-detail redesign of the Commerce workspace, replacing the four verb tabs and their repeated target selectors |
| [`plans/commerce-suite-retirement-manifest.md`](plans/commerce-suite-retirement-manifest.md) | Exact retired Commerce authorities and version lineage for the atomic cutover |
| [`plans/site-health-measurement-cutover.md`](plans/site-health-measurement-cutover.md) | Active three-PR Site Health stabilization, measurement-contract, Overview/AEO UI, and checkpoint-coverage cutover |
| [`plans/site-health-measurement-reliability-pr4.md`](plans/site-health-measurement-reliability-pr4.md) | Approved post-PR3 Site Health reliability cutover for classifier evidence, checkpoint semantics, capability-family scoring, classification coverage, and calibrated presentation |
| [`plans/site-health-correctness-and-debt-reduction.md`](plans/site-health-correctness-and-debt-reduction.md) | Approved frozen-corpus Site Health correctness audit, occurrence evidence, master-detail issues workspace, and immediate onboarding shell |
| [`plans/aeo-opportunity-loop.md`](plans/aeo-opportunity-loop.md) | Implemented buyer-stage priority, owned/competitive/earned routing, Content handoff, implementation linkage, and comparable verification contract |

## Active implementation plans

[`plans/site-health-measurement-cutover.md`](plans/site-health-measurement-cutover.md)
owns the active PR1 → PR2 → PR3 implementation sequence. The approved
post-cutover reliability follow-up is
[`plans/site-health-measurement-reliability-pr4.md`](plans/site-health-measurement-reliability-pr4.md).
Both are subordinate to the canonical runtime and measurement logic in
[`site-health.md`](site-health.md); PR4 begins only after PR3 merges.

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
| [`design-system/audit.md`](design-system/audit.md) | Design system inventory, surface breakdown, and debt analysis |
| [`design-system/heroui-reference-map.md`](design-system/heroui-reference-map.md) | HeroUI v3 reference mapping, slot anatomy, and token adaptations |
| [`design-system/component-map.md`](design-system/component-map.md) | Authoritative component action matrix and consolidation targets |
| [`design-system/component-map.json`](design-system/component-map.json) | Machine-readable component action matrix for validation and execution tooling |
| [`design-system/visual-improvement-map.md`](design-system/visual-improvement-map.md) | Visual improvement map across all 30 CiteLadder UI primitives |
| [`design-system/visual-improvement-map.json`](design-system/visual-improvement-map.json) | Machine-readable visual improvement mapping for Codex execution |
| [`design-system/surface-improvement-map.md`](design-system/surface-improvement-map.md) | Surface-level visual and layout gap analysis across 10 application surfaces |
| [`design-system/migration-map.md`](design-system/migration-map.md) | Phased implementation sequence and verification criteria |
| [`design-system/review-required.md`](design-system/review-required.md) | Architectural decisions and trade-off review log |
| [`ui-component-system.md`](ui-component-system.md) | Authenticated component, state, motion, and enforcement map |
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
revival of that workspace. The persisted observed-architecture projection is
also a Site Health owner. Its broad archetype expects common structures, does
not classify a site, cannot emit a defect, and is suppressed for absence claims
without complete crawl coverage. Historical context is non-authoritative; use
[`site-health.md`](site-health.md) for the current contract.
Use
[`plans/site-health-measurement-cutover.md`](plans/site-health-measurement-cutover.md)
for the approved PR1 → PR2 → PR3 delivery sequence. Use
[`plans/site-health-measurement-reliability-pr4.md`](plans/site-health-measurement-reliability-pr4.md)
only for the dependent post-PR3 reliability cutover.

Site analysis is governed by the generic `page_kind` taxonomy and its
config-owned schema/property contracts. `other` means classification abstained;
it must not receive a guessed type-specific checklist.

## Documentation change rule

When authority changes, update this index in the same change and move the
superseded document to the archive. Do not leave broken pointers or competing
guidance in the active tree.
