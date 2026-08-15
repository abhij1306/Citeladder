# Growth Agent

> **Status:** shipped authority for bounded standalone evidence tasks.

The top-bar Agent cutover and rebuild sequencing are owned by
[`citeladder-aeo-product-rebuild.md`](citeladder-aeo-product-rebuild.md).

Growth Agent supports exactly two bounded tasks, labelled **Explain my latest
data** (`explain`) and **Prioritize next steps** (`build_roadmap`). Each request
is a standalone persisted run; the product does not claim conversational memory.
A lease-backed worker invokes only config-owned, workspace-authorized read tools
over persisted Site Health, Demand, Opportunity, and audit data.

```text
task objective -> queued AgentTaskRun -> append-only AgentToolAttempt
  -> bounded narration -> typed result + limitations + artifact references
```

Tool attempts are the canonical frozen evidence record. They contain authorized
inputs, exact artifact/source references, output hash, omissions, status, and
tool version. Runs contain a typed public result: `summary`, `observations`,
ranked `roadmap_items`, source availability for Site Health, Search Demand,
Opportunities, and AI Visibility, `limitations`, and retained artifact
references. Evidence is not copied into messages, context packages, steps, or
citation counters.

Roadmap items preserve the persisted Opportunity order, rank, title,
remediation, target URL, deterministic priority score, and severity. Narration
may summarize those items but cannot reorder them, invent metrics, or claim an
action occurred. If narration is unavailable, the worker writes a useful
deterministic result from the same typed evidence.

History list reads are compact run summaries. Only the selected run-detail read
returns the typed result and provenance. The normal UI presents a collapsed
**Data used** disclosure with human source labels, availability,
window/coverage, and plain-language missing-data reasons; it does not expose
raw tool names, identifiers, hashes, inputs, versions, or latency.

The Agent owns no conversations/messages, capability catalog, decision state,
child reconciliation, priority overrides, Content creation, prompt activation,
audit scheduling, arbitrary SQL/fetch/shell access, or external mutation.
Acceptance covers workspace isolation, fixed task validation, append-only tool
attempts, bounded omissions, leases, cancellation, and zero mutation paths.
