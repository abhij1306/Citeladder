# Content Intelligence

> **Status:** shipped authority for website-grounded content generation.

Content owns one bounded generation workflow. A user supplies an instruction
and may link an Opportunity. The service selects a usable persisted Site Health
snapshot, freezes a bounded website-context snapshot with exact source IDs,
hashes, versions, excerpts, and omissions, and queues provider-neutral work.

```text
user instruction + optional Opportunity + persisted Site Health evidence
  -> immutable bounded website context
  -> queued ContentGeneration
  -> append-only provider attempts
  -> result, history, feedback, retry, or regeneration
```

Generation is rejected with `website_context_unavailable` when usable website
evidence cannot be assembled. Website text is untrusted provider input. Read
APIs never crawl or repair state; retries create new attempts; no provider can
change Site Health metrics.

Content does not own strategy snapshots, inventory copies, briefs, context
packages, validation state machines, revisions, publication claims, or later
verification. Those PR #59 compatibility paths were removed because they were
unreachable after Site Intelligence deletion and carried empty evidence.

No autonomous publishing is permitted. Retained acceptance covers workspace
isolation, source provenance, bounded omissions, queue leases, idempotency,
cancellation, retry/regeneration, provider attempts, and feedback.
