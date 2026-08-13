# Growth Agent

> **Status:** shipped authority for bounded standalone evidence tasks.

Growth Agent supports exactly two tasks: `explain` and `build_roadmap`. Each
request is a standalone persisted run; the product does not claim conversational
memory. A lease-backed worker invokes only config-owned, workspace-authorized
read tools over persisted Site Health, Demand, Opportunity, and audit data.

```text
task objective -> queued AgentTaskRun -> append-only AgentToolAttempt
  -> bounded narration -> answer + limitations + artifact references
```

Tool attempts are the canonical frozen evidence record. They contain authorized
inputs, exact artifact/source references, output hash, omissions, status, and
tool version. Runs contain only the public result and references; evidence is
not copied into messages, context packages, steps, or citation counters.

The Agent owns no conversations/messages, capability catalog, decision state,
child reconciliation, priority overrides, Content creation, prompt activation,
audit scheduling, arbitrary SQL/fetch/shell access, or external mutation.
Acceptance covers workspace isolation, fixed task validation, append-only tool
attempts, bounded omissions, leases, cancellation, and zero mutation paths.
