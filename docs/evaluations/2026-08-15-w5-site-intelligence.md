# W5 Site Intelligence live validation — 2026-08-15

## L01 crawl-scoped graph spike

Read-only PostgreSQL inspection found three crawl-scoped corpora with current
successful HTML analysis/link evidence:

| Current analyses | Internal anchor observations | Nofollow observations | Target-artifact resolutions |
|---:|---:|---:|---:|
| 114 | 6,587 | 0 | 0 |
| 150 | 309 | 0 | 0 |
| 22 | 250 | 0 | 0 |

The zero target-artifact result fixed the live boundary for L01: targets must
resolve against in-crawl analyzed `SiteUrl` identities using artifact final URLs
when available, while unresolved observations remain evidence rather than
silently disappearing. No URL, workspace, project, credential, or page content
is stored in this artifact.

Deterministic fixtures prove stable PageRank across input order, dangling-mass
redistribution, BFS unknown for unreachable nodes, repeated-anchor collapse,
retained nofollow observations, the 20-node weak-authority gate, bounded source
suggestions, partial-coverage limitations, snapshot idempotency, exact source
analysis provenance, workspace isolation, and snapshot-bound pagination.

The schema gate migrated a disposable empty `citeladder_w5_migration` database
from the singular `0001_initial.py`, reported no ORM drift, and then dropped the
disposable database.

## E01 readiness spike

The same read-only inspection confirmed that current persisted evaluations
contain pass, fail, and not-applicable states across the locked readiness rule
set. Exact dimension reconciliation is recorded after E01; no score or provider
call is part of this validation.
