# CiteLadder documentation

Start with [`../AGENTS.md`](../AGENTS.md), then use the
[`documentation-index.md`](documentation-index.md) to find the one current
owner for the task.

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

The former Site Intelligence and industry-pack plans were superseded by the
three-page Site Health simplification and live under
[`archive/plans/site-health-simplification/`](archive/plans/site-health-simplification/).
They are historical context, not implementation authority.

## Documentation policy

- Active docs describe shipped behavior or an explicitly approved plan.
- Code and current tests decide what is shipped.
- Superseded material moves to `archive/`; it is not silently reused.
- Run `python docs/validate_documentation.py` after documentation changes.
