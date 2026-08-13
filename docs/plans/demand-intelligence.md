# Demand Intelligence

> **Status:** shipped authority for deterministic first-party demand signals,
> Prompts, and AI Visibility.

Demand snapshots derive from immutable GSC and Traffic observations. The first
shipped detector identifies high-impression, low-CTR search demand and preserves
exact source IDs, freshness, time window, formula version, and unknown versus
zero/unavailable states. A previous compatible snapshot provides a descriptive
comparison. Signals route to the existing Opportunity owner.

```text
immutable GSC/Traffic artifacts -> DemandSnapshot -> DemandSignal -> Opportunity
```

The public Demand projection is the latest workspace-authorized snapshot plus
an explicit recompute action. Demand does not persist configured journeys,
duplicate Site inventory, provider capability panels, or copied Prompt and
Visibility summaries. Site completion does not enqueue Demand work when no Site
signal is consumed.

Prompts and AI Visibility retain their independent owners, immutable attempts,
evidence views, schedules, and provenance. Demand summary removal does not
remove either product. Acceptance covers workspace isolation, deterministic
signals/comparison, source freshness, missing/zero distinctions, recompute
idempotency, and Opportunity supersede-not-mutate behavior.
