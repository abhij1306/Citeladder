# Growth Agent

> **Status:** active owner and plan for bounded conversational orchestration.

## Role

The Growth Agent helps a user inspect persisted Site Health, Content, and
Demand evidence and run config-owned tasks through typed domain tools. It owns
conversations, task runs, context manifests, progress, and results. It owns no
copy of domain truth and no independent memory or correction store.

## Execution flow

```text
authorized conversation message
  -> resolve task policy from catalog
  -> assemble bounded persisted context
  -> freeze context manifest
  -> call authorized typed tools
  -> persist progress and terminal result
  -> render one assistant response
```

Read tools never crawl, sync, classify, call a provider, or repair state. Work
that requires acquisition or generation enters the owning persisted queue.

## Tool boundary

Tools are registered, typed, workspace-authorized, versioned, and bounded. The
agent has no arbitrary SQL, unrestricted URL fetch, shell, provider credential
access, autonomous recursion, or generic external-mutation tool.

The Site Intelligence comparison, knowledge, and correction tools were removed
with their owning runtime. Do not return them as wrappers around missing data.

## Context

Context assembly selects only evidence relevant to the resolved task and
records eligible, included, omitted, unavailable, and stale sources. It applies
per-section and total budgets, redacts secrets, and freezes a manifest before
provider I/O.

An empty Content fact/source envelope is a limitation to surface, not a reason
for the agent to infer business truth.

## Decisions and safety

The agent may explain, compare persisted projections, prioritize using the
owning deterministic formula, build a brief, or start an authorized bounded
workflow. Explicit user decisions are required for content save/publish claims,
external mutations, prompt activation, billing changes, and future durable
memory promotion.

The agent presents priority; it does not silently set it. A proposed reorder or
plan is a visible artifact and never overwrites the owning Opportunity record.

## Scheduling

Schedules are durable project-scoped rows owned by the workflow they trigger.
They store cadence, timezone, active state, next run, last run, and bounded
configuration. A schedule creates ordinary queue work and follows the same
authorization, entitlement, lease, and audit rules as a manual run.

## Verification

Acceptance tests cover:

- workspace isolation for conversation, run, and tool access;
- context budgets, omissions, redaction, and manifest stability;
- idempotent child-task reconciliation and cancellation;
- unavailable source behavior;
- zero arbitrary tool or external mutation paths;
- one durable assistant response per completed user message.
