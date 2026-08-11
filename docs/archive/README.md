# Documentation archive

Files in this directory are retained for history, forensic comparison, and migration context.
They are **not implementation authorities** and coding agents must not use them to decide current
product hierarchy, APIs, schemas, sequencing, or industry behavior unless a current document
explicitly requests a historical comparison.

## Why files are archived

A document belongs here when one or more of these conditions applies:

- it frames CiteLadder primarily as an AI-visibility tracker;
- a canonical Growth Intelligence plan supersedes it;
- it is a completed implementation plan or shipped roadmap record;
- its API, pricing, provider, deployment, or product assumptions no longer match the repository;
- it defines an earlier industry-pack shape replaced by the shared knowledge registry;
- it is a dated audit or operations assessment rather than a live runbook.

## Current authorities

Start from [`../README.md`](../README.md) and
[`../documentation-index.md`](../documentation-index.md). When useful historical
material is promoted back into the product, restate it in the current owner
with current contracts and tests; do not make runtime code depend on this
archive.

## Archive layout

- `architecture/` — visibility-era architecture and invariants.
- `plans/` — superseded or completed implementation plans.
- `roadmap/` — shipped or superseded feature design records.
- `subsystems/` — detailed runtime references replaced by concise current owners.
- `audits/` — dated repository audits.
- `operations/` — dated or deployment-specific operational records.

`plans/site-health-simplification/` preserves the removed Site Intelligence,
knowledge-kernel, industry-pack, and 2026-08 simplification handoff/audit plans.
The active replacement is [`../site-health.md`](../site-health.md).

The archive may contain broken links that reflect its historical repository layout. Active-doc
link validation intentionally excludes archive internals.
