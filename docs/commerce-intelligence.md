# Commerce Intelligence

Commerce is the shipped four-tab `/products` workspace: **Catalog**, **Competitors**, **Buyer Prompts**, and **AI Shelf**. It reuses Site Health acquisition and the shared audit system; it does not own a crawler, response store, prompt store, or opportunity store.

## Catalog

Site Health extractor `sh-extractor-9`, analyzer `sh-analyzer-5`, and classifier `sh-classifier-4` emit generic category and PDP facts. The Commerce projector `commerce-projector-1` creates the persisted catalog from those analyses. A normalized canonical PDP URL is the primary product identity; GTIN, SKU, and MPN are secondary merge evidence.

CSV imports and explicit edits are append-only observations. Current product rows are read projections whose `field_sources` identify the exact observation and version controlling every field. CSV and edit authority is not silently overwritten by later crawl projection. Imports are content-hash idempotent and expose bounded, row-level outcomes.

## Competitors

Discovery runs as a queued, versioned attempt. Tavily is optional; an unavailable provider produces an explicit unavailable state. Candidate URLs pass deterministic path/domain filters and the shared safe fetcher before persistence. Candidates remain pending until approved or rejected and cannot enter measurement before approval.

## Buyer Prompts

Every Commerce prompt has a typed category or product target. Structured generation is bounded and rejects owned-name leakage. Generated and manual prompts use the shared Prompt owner and remain disabled until explicit approval. Audit creation freezes approved prompts, current catalog identity, approved competitors, and all relevant parser, matcher, formula, and template versions.

## AI Shelf

Successful Commerce audit executions create append-only recommendation observations linked to the raw response artifact and any persisted Citations. Ordered lists and provider card order carry a one-based rank; prose and bullets remain unordered with a null rank. Unknown recommendations are retained as unresolved evidence.

The persisted `commerce-shelf-formula-1` snapshot exposes:

- Product Visibility: successful target executions with an owned appearance divided by all successful target executions.
- Share of Shelf: owned recognized slots divided by all recognized slots.
- Average Shelf Position: mean owned rank across explicitly ordered observations; unavailable without ranked owned appearances.
- First-Position Win Rate: eligible ordered executions whose first slot is owned divided by eligible ordered executions.

Zero and unavailable are distinct. Share of Shelf uses all recognized slots while position metrics use only explicitly ordered recommendations.

## Deferred

Revenue attribution, order facts, feed remediation/publishing, autonomous publishing, JavaScript rendering, merchant dashboards, family aggregation UI, sentiment, and composite product scores are not part of the shipped replacement.
