# W4 Demand + Content live validation — 2026-08-15

This artifact records sanitized, read-only validation against the existing
local evidence database. No provider was called and no live row was changed.
Deterministic fixtures, not these site-specific results, own threshold proof.

## Content grounding

- A BrandProfile existed, but none of its four content fields had confirmed or
  edited review provenance. The envelope correctly included zero profile facts
  and recorded `profile_field_unconfirmed` omissions.
- The bounded crawl selector chose 8 pages / 15,571 characters. The resulting
  envelope was `included` with 8 exact source references, 8 selected sources,
  and all 7 restricted claim classes prohibited unless confirmed evidence is
  supplied.
- Envelope validation passed with zero provider calls. This proves truthful
  crawl-only grounding rather than silently promoting unreviewed profile text.

## Query evidence and detectors

- Raw immutable `gsc_query_page_daily` evidence: 1,296 rows over 26 days.
- Latest-row selection produced 324 bounded observations: 255 exact owned-page
  resolutions and 69 ambiguous resolutions.
- Automatic brand classification produced 150 branded and 174 non-branded
  observations. The live database predates the append-only override table, so
  this spike intentionally evaluated automatic classification only; migrated
  schema and override precedence are covered by component tests.
- Striking distance: `available`, 28 signals.
- Cannibalization: `partial`, 1 signal; unresolved/ambiguous query groups
  abstained as designed.
- Property-relative CTR gap: `unavailable`, 0 signals because no cohort met
  the locked 20-row / 500-impression coverage gate.
- Trends: `insufficient_history`, 0 signals because 26 days is below the
  required adjacent 14 + 14 day coverage.

The thin-data result therefore emitted fewer signals with explicit states and
did not fabricate a CTR baseline, trend, or intended-page mismatch.
