# CiteLadder documentation

Start with [`../AGENTS.md`](../AGENTS.md), whose task map points to the current
owner for each subsystem.

## Product authorities

1. [`architecture.md`](architecture.md) — product and system architecture.
2. [`invariants.md`](invariants.md) — review-blocking technical rules.
3. The owning runtime reference:
   - [`site-health.md`](site-health.md)
   - [`backend-architecture.md`](backend-architecture.md)
   - [`frontend-architecture.md`](frontend-architecture.md)
   - [`integrations-traffic-analytics.md`](integrations-traffic-analytics.md)
   - [`commerce-intelligence.md`](commerce-intelligence.md)
   - [`api-error-contract.md`](api-error-contract.md)
   - [`design.md`](design.md)
4. The one active plan that owns approved future work.

The former Site Intelligence and industry-pack plans are historical context, not
implementation authority. The current authoritative replacement is
[`site-health.md`](site-health.md).

## Delivery references

- [`DEVELOPMENT.md`](DEVELOPMENT.md) documents the local and clean-clone Compose workflows.
- [`release-checklist.md`](release-checklist.md) defines pre-release verification; it does not
  authorize tagging or publishing.
- [`../CHANGELOG.md`](../CHANGELOG.md) records unreleased and published release notes.

## Documentation policy

- Active docs describe shipped behavior or an explicitly approved plan.
- Code and current tests decide what is shipped.
- Superseded material moves to `archive/`; it is not silently reused.
