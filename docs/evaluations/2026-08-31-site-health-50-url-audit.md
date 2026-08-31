# Site Health 50-URL HTTP Audit (2026-08-31)

Run: `20260831T001500Z`

## Contract

Frozen responses were acquired once via `SecureFetcher` with no JavaScript. `verified` means the reported defect is observable in the bounded HTTP response; `wrong` means it is not observable. Cocofloss was excluded.

## Selection

Exactly **50** URLs: a 12-URL base from each of goodee, lootcrate, potgang, united by blue, plus two global lowest-score URLs. Raw bodies and redacted headers are gitignored under `artifacts/site-health-audit/20260831T001500Z`.

## Results

Reported occurrences: 240; verified: 193; wrong: 47; frozen-fact replay-only candidates classified `not_comparable`: 95.

## Corrected frozen-corpus replay

The audit-demonstrated corrected rules were re-run over the same frozen responses, including corrected page classification and applicability. Against their independently reviewed occurrences, it retained 67 verified findings, lost 0 verified findings, removed 45 wrong findings, and retained 0 wrong findings.

The two baseline-wrong crawl-graph broken-link aggregates are not raw-page replayable. Their corrected persistence owner now creates source-page occurrences with bounded target URL and HTTP status evidence; verification requires a future explicitly authorized crawl.

| Rule | Verified (TP) | Wrong (FP) | Comparable FN | Replay-only candidates | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|
| `aeo.answer_first` | 1 | 1 | 0 | 0 | 50.0% | n/a |
| `aeo.assortment_freshness_signal` | 6 | 0 | 0 | 1 | 100.0% | n/a |
| `aeo.editorial_lead_present` | 7 | 4 | 0 | 0 | 63.6% | n/a |
| `aeo.entity_value_proposition` | 4 | 3 | 0 | 0 | 57.1% | n/a |
| `aeo.heading_hierarchy` | 20 | 11 | 0 | 0 | 64.5% | n/a |
| `aeo.listing_answer_set` | 1 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.listing_item_facts` | 1 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.offer_freshness_signal` | 11 | 0 | 0 | 1 | 100.0% | n/a |
| `aeo.organization_identity` | 2 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.product_answer_facts` | 4 | 1 | 0 | 0 | 80.0% | n/a |
| `aeo.product_brand_identity` | 1 | 4 | 0 | 0 | 20.0% | n/a |
| `aeo.product_evidence_facts` | 4 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.question_headings` | 1 | 1 | 0 | 0 | 50.0% | n/a |
| `aeo.schema_expected_for_type` | 20 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.schema_recommended_present` | 13 | 0 | 0 | 1 | 100.0% | n/a |
| `aeo.schema_required_valid` | 6 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.source_support_present` | 1 | 0 | 0 | 0 | 100.0% | n/a |
| `aeo.visible_attribution` | 7 | 5 | 0 | 0 | 58.3% | n/a |
| `technical.broken_internal_link` | 0 | 2 | 0 | 0 | 0.0% | n/a |
| `technical.canonical_conflict` | 3 | 0 | 0 | 0 | 100.0% | n/a |
| `technical.indexable` | 4 | 0 | 0 | 0 | 100.0% | n/a |
| `web.accessibility_form_names` | 20 | 15 | 0 | 0 | 57.1% | n/a |
| `web.accessibility_heading_order` | 31 | 0 | 0 | 0 | 100.0% | n/a |
| `web.accessibility_image_alt` | 25 | 0 | 0 | 0 | 100.0% | n/a |

No comparable false negatives were established. The replay-only candidates are retained as a bounded triage appendix, but classification or applicability drift means they cannot truthfully enter recall.

## Reproduction

The committed CSVs contain bounded observations and SHA-256 hashes. Raw response fixtures are local-only and can be replayed by the audit helper before and after detector changes; no replacement product crawl was persisted.
