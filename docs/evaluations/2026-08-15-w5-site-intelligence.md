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

## L02 Opportunity and browser fixture proof

- Complete graph fixture: one target carrying both approved signals and one
  deterministic suggested source produced exactly two distinct Opportunities,
  each with the graph snapshot/node and both source-analysis IDs.
- Boundary fixture: the identical observed topology marked incomplete produced
  zero link Opportunities; a complete graph's non-indexable weak target also
  produced none.
- Review boundaries: coverage uses the distinct crawl-scoped analyze-task
  population (not the broader monitored selection), so inventory-only URLs do
  not suppress complete HTML topology. Equivalent unresolved target variants
  canonicalize to one retained edge and occurrence count. Versioned graph tasks
  use versioned queue slots and scope both task and crawl selection by the exact
  workspace/crawl identity before reading graph evidence. A drained partial
  crawl with zero successful analyses produces no invented graph but emits a
  crawl-provenance Opportunity refresh so prior Site signals cannot remain live.
- Website fixture: the bounded followed-edge preview, page-authority table,
  collapsed-link table, cursor traversal for both evidence sets, page-detail
  source links, and descriptive partial-crawl disclosure render from persisted
  API rows. No client metric or alternate link store is used.

## E01 readiness spike

The same read-only inspection reconciled all seven dimensions across the latest
usable crawl for three sanitized corpora. Cells are `pass / fail /
not-applicable`; every row's total equals `analysis count × mapped rules`:

| Corpus (analyses) | Answerability | Structure | Evidence | Machine-readability | Authority | Freshness | Crawlability |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 (150) | 226/36/338 | 217/74/459 | 0/0/150 | 76/162/212 | 0/1/299 | 0/0/150 | 395/55/150 |
| 2 (114) | 217/15/224 | 315/98/157 | 0/0/114 | 83/111/148 | 2/1/225 | 0/0/114 | 319/23/114 |
| 3 (22) | 52/1/35 | 73/18/19 | 0/4/18 | 41/0/25 | 4/2/38 | 3/1/18 | 66/0/22 |

The query joined current successful HTML analyses to the exact crawl analyzer
and artifact extractor versions before mapping only the 20 declared rule IDs.
No project identity, URL, page content, score, provider call, or write is part
of this validation. Deterministic fixtures additionally trace a low-readiness
`case_study_review` page to failing `aeo.answer_first` and
`aeo.outbound_citations` evaluations and prove workspace isolation and bounded
fail-first evidence links.
