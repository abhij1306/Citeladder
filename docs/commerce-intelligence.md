# Commerce Intelligence and AI Presence

Commerce is a workspace-scoped, evidence-first extension of CiteLadder. All IDs
are UUIDs, all reads and writes require workspace membership, and catalogue edits
never mutate the catalog identity frozen in an existing audit configuration.
Derived views project immutable crawl/import/answer-engine evidence; no dashboard
read calls an LLM, answer engine, crawler, or market source.

## Commerce workspace

`/products` has four user-facing views: **Discover** for domains, URLs, CSV and
candidate review; **Catalog** for owned and competitor product management and
completeness; **AI Conversations** for persisted prompts and answer-engine
discussion of products; and **Market Intelligence** for external offers, prices,
availability, and later comparison. The current frontend labels these views while
only calling live existing catalog/visibility APIs; staged endpoints activate only
when the backend ships their strict schemas.

Discovery creates versioned runs, Postgres queue tasks, immutable acquisition
artifacts, and reviewable candidates. Candidate identity is deterministic:
GTIN/SKU/model first, then configured brand/name/variant evidence. LLM output can
describe a candidate but can never establish identity. Accepted candidates carry
source artifact/candidate provenance and `discovered` origin; manual edits survive
later discovery. Raw/rendered ScraperAPI acquisition and supported structured or
Google Shopping sources remain visibly distinguished.

Product conversations extend persisted snapshots with frozen prompt text, theme,
intent, coverage, conversation themes, mentions/rank distribution, discussed
attributes, price claims/accuracy, buyer destinations, competitor co-mentions and
comparisons. Sentiment and attribute valence are not inferred deterministically.

Competitor catalog import/crawl accepts reviewed discovery candidates and bounded
CSV/JSON preview errors. Product matching is ordered: GTIN/UPC/EAN; manufacturer
part/model plus brand; normalized family and variant; configured title/attribute
similarity. Ambiguous matches require review and an accepted mapping is never
silently overwritten. Versioned comparisons preserve source artifact/catalog IDs,
matcher version, confidence, freshness, and truncation. Side-by-side results cover
catalog coverage, price/availability, variants/identifiers, completeness/schema
readiness, freshness, and AI-conversation metrics.

## AI Presence Index

Scores are per project/brand, not a workspace portfolio rollup. Non-commerce:
30% brand mention rate, 20% normalized share of voice, 20% owned citation rate,
and 30% Web Fundamentals. Commerce activates only for an accepted catalog with
sufficient `ProductMetricSnapshot` evidence: 25% Brand Visibility (60% mention
rate / 40% normalized share of voice), 30% Product Presence, 20% Web Fundamentals,
15% owned citation rate, and 10% Opportunity Execution.

Product Presence is 40% product share of voice, 25% product prompt/mention
coverage, 20% normalized rank performance, and 15% verifiable price accuracy.
Opportunity Execution is `resolved / (open + in_progress + resolved)` from the
latest comparable opportunity snapshot; dismissed rows are excluded and no
opportunities yields `null`, never a free 100.

Missing components renormalize the score. Responses expose component scores,
weights, coverage, source snapshot IDs, formula/analyzer/rule versions, and mark
incomplete scores provisional. Momentum is latest minus earliest comparable score
in the trailing 30 days, or `null` with fewer than two points. Comparable points
have the same commerce formula, component coverage, and compatible versions.
Resolved opportunities appear as trend annotations as well as the explicit
Commerce component.
