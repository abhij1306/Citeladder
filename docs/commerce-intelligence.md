# Commerce Intelligence

Commerce currently exposes four `/products` tabs: **Catalog**, **Competitors**, **Buyer Prompts**, and **AI Shelf**. This document describes the present runtime; it does not mark the staged PR or credentialed manual gates complete. Commerce reuses Site Health acquisition and the shared audit system; it does not own a crawler, response store, prompt store, or opportunity store.

## Catalog

Site Health extractor `sh-extractor-12`, analyzer `sh-analyzer-7`, and classifier `sh-classifier-7` emit generic category and PDP facts. The Commerce projector `commerce-projector-3` creates the persisted catalog from those analyses. Structured Product price is preferred; when it is absent, a validated visible PDP price is retained with its evidence path. A normalized canonical PDP URL is the primary product identity; GTIN, SKU, and MPN are secondary merge evidence.

CSV imports and explicit edits are append-only observations. Current product rows are read projections whose `field_sources` identify the exact observation and version controlling every field. CSV and edit authority is not silently overwritten by later crawl projection. Imports are content-hash idempotent and expose bounded, row-level outcomes.

Catalog surfaces persisted Site Health crawl and Commerce projection progress,
category hub/leaf roles and counts, product memberships, explicit product
correction/reassignment, and category rename/role correction. Category edits
also create append-only observations and retain field-level authority over later
projection refreshes. The Commerce rail renders products beneath every category
they belong to, keeps products without a projected category under
`Uncategorized`, and keeps catalog search pinned as an opaque first row while
the list scrolls. Categories are ordered by descending persisted product count,
then by name; they are collapsed initially, show that count, and expose a disclosure control only when projected child
products exist. Bulk checking a category includes that category and all of its
product targets; opening or expanding a category remains a separate navigation
action.

## Competitors

Discovery runs as a queued, versioned attempt whose status is exposed to the
workspace until it terminalizes. Tavily is optional; an unavailable provider
produces an explicit unavailable state. Product queries include bounded product
type, attribute, and price-band context; category queries retain their separate
merchant-intent form. Candidate URLs pass deterministic path/domain filters,
the shared safe fetcher, and target-aware deterministic classification before
persistence: product discovery requires a PDP and category discovery requires
a category/listing page. Candidates remain pending until approved or rejected
and cannot enter measurement before approval.

## Buyer Prompts

Every Commerce prompt has a typed category or product target. Structured
generation is bounded and rejects owned-name leakage. Generated and manual
prompts use the shared Prompt owner and remain disabled until explicit approval.
For one selected target, the Buyer Prompts workspace opens the shared audit
launcher over only its approved prompt IDs; provider selection, repetitions,
provider-free estimate, capacity admission, and execution stay with the audit
owner. Audit creation freezes approved prompts, current catalog identity,
approved competitors, and all relevant parser, matcher, formula, and template
versions. The shared schedule owner persists `audit_scope`; scheduled Commerce
runs therefore enter the same freeze, execution, observation, and snapshot path
as a manual Commerce launch.

## AI Shelf

Successful Commerce audit executions create append-only recommendation
observations linked to the raw response artifact and any persisted Citations.
Deterministic matching reads the catalog and approved competitors frozen into
that audit, so later catalog edits cannot reinterpret historical answers.
Unresolved bounded spans alone may use the configured structured-model resolver;
unavailable or malformed output preserves unresolved evidence. Product identity,
merchant URL/domain, and Citation associations stay separate, and an AI-observed
competitor is created only from an independently resolved product URL. Ordered
lists and provider card order carry a one-based rank; prose and bullets remain
unordered with a null rank.

The persisted `commerce-shelf-formulas-2` snapshot exposes:

- Product Visibility: successful target executions with an owned appearance divided by all successful target executions.
- Share of Shelf: owned recognized slots divided by all recognized slots.
- Average Shelf Position: mean owned rank across explicitly ordered observations; unavailable without ranked owned appearances.
- First-Position Win Rate: eligible ordered executions whose first slot is owned divided by eligible ordered executions.

AI Shelf requires an explicit product or category target. Its headline metrics,
latest evidence, and immutable snapshot history are all filtered to that target.
Zero and unavailable are distinct. Share of Shelf uses all recognized slots
while position metrics use only explicitly ordered recommendations.

## Deferred

Revenue attribution, order facts, feed remediation/publishing, autonomous publishing, JavaScript rendering, merchant dashboards, family aggregation UI, sentiment, and composite product scores are not part of the shipped replacement.
