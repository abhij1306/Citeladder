# Site Health v2 — E2E harness (P1/P2)

Test-only harness for running a REAL site-health crawl end-to-end locally.
Nothing here ships; it supports the v2 phases (see
`docs/roadmap/site-health-v2-handoff.md`).

## Contents

- `fixture/` — 9-page static site engineered so every classifier page type is
  exercised (`/` homepage, `/blog/post-1/` article, `/pricing/` pricing with a
  deliberately outranked Product schema, `/docs/intro/` docs, `/faq/` faq,
  `/product/widget/` product, `/category/shoes/` category, `/about/`
  about_contact, `/misc/plain/` zero-signal → other) plus P2 additions:
  `robots.txt` (allows the crawler UA, blocks GPTBot, Sitemap directive),
  `llms.txt`, `sitemap.xml` (10 URLs incl. a link-less orphan page).
- `sh-seed.sh` — registers/logs in a test user, creates a project pointing at
  the fixture tunnel. Idempotent.
- `sh-p2-dryrun.py` — dry-run: `extract_page_facts` + `classify` +
  `evaluate_all` over every fixture page through the tunnel; regenerates
  `sh-p2-expectations.json`. **Re-run after any parser/rules change** —
  expectations must be re-baselined (two P2 review fixes changed outcomes).
- `sh-p2-e2e-free.py` — Free-sample crawl e2e: seed → crawl → API assertions
  (9/9 analyzed, page types, version stamps, `site_facts` stance, site_root
  weight-0 scoring neutrality, finalize rows, issues, exports, by_page_type).
- `sh-p2-e2e-negative.py` + `sh-p2-run-negative.sh` — robots denies the
  crawler UA: crawl fails, no page rows, site_root evaluations never
  fabricated, `site_facts` still persisted. Wrapper restores robots via trap.
- `sh-p2-e2e-starter.py` + `sh-p2-run-starter.sh` — Starter mode: sitemap
  ingestion → orphan in inventory; monitored set → `sitemap_orphan` FAIL on
  root, `broken_internal_link` FAIL on the orphan page. Wrapper restores the
  entitlement via trap.

## How to run

Prereqs: Postgres (`searchify` DB, greenfield-recreated after any model
change), backend on :8000, site-health worker running — see
`docs/DEVELOPMENT.md` and the memory recipes referenced in the handoff doc.

```bash
# 1. Serve the fixture and expose it (SSRF: the crawler rejects loopback)
python3 -m http.server 9900 --directory testing/site-health-v2-e2e/fixture &
# expose :9900 through your tunnel of choice; set FIXTURE_URL for the seed
# (the scripts default to the tunnel URL recorded in sh-seed.sh — edit it)

# 2. Dry-run / re-baseline expectations (recommended after any rule change)
cd backend && uv run python ../testing/site-health-v2-e2e/sh-p2-dryrun.py

# 3. Seed + Free e2e
bash testing/site-health-v2-e2e/sh-seed.sh
cd backend && uv run python ../testing/site-health-v2-e2e/sh-p2-e2e-free.py

# 4. Negative + Starter flows (each wrapper restores state via trap)
bash testing/site-health-v2-e2e/sh-p2-run-negative.sh
bash testing/site-health-v2-e2e/sh-p2-run-starter.sh
```

Gotchas: the Free sample allowance (10) is workspace-wide — deactivate stale
`free_sample` monitored rows before re-crawling (`UPDATE monitored_site_urls
SET active=false ... WHERE selection_source='free_sample' AND active=true;`).
The fixture's robots.txt must keep allowing the crawler's own UA
(`SearchifySiteHealthBot`) or every crawl is `robots_denied` by design.
