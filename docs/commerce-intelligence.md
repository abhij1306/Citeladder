# Commerce specialization

Commerce is a specialization over the shared Site Health, Content, Demand, and
Opportunity owners. It is not a separate crawler, page-analysis table,
knowledge store, or product architecture.

## Current boundary

- Site Health classifies product, category, pricing, comparison, FAQ, policy,
  and other structural page kinds.
- Product pages receive Product/Offer completeness and visible/schema parity
  rules in addition to the generic page-type schema contract.
- Catalog and product models remain specialized identity/evidence sources.
- Content and Demand workflows may reference product/catalog IDs through their
  existing typed contracts.

## Commerce Suite

`/products` ships one five-tab contract:

1. **Overview** — latest persisted product visibility KPIs, largest product
   gaps, and links to Commerce opportunities.
2. **Catalog** — product add, import, edit, delete, completeness, and feed
   health.
3. **AI Visibility** — per-SKU visibility rate, top-three rate, average
   position, engine coverage, and prior-audit change.
4. **Competitors** — a typed, read-only side-by-side projection created during
   audit finalization by deterministic matching.
5. **Opportunities** — the shared Opportunity API filtered to
   `opportunity_type=commerce`; review confirmation is browser-only and does
   not mutate a provider or create a second recommendation store.

Product detail retains persisted evidence and shows the latest three product
visibility snapshots. Overview is the default tab. All reads use durable
catalog, audit, metric, comparison, and opportunity rows; the UI has no mock or
seed-data fallback.

The removed Commerce discovery queue, candidates, review workflow, manual
comparison mutation, AI Conversations view, and generic Market Intelligence
view are not active architecture and must not be recreated.

The removed commerce industry pack and industry-role classifier are historical.
Do not recreate them beside the generic page-kind pipeline.

## Product schema rules

Product analysis retains bounded identity, offer, variant, rating, shipping,
and return-policy properties from recognized JSON-LD. Missing optional claims
remain absent rather than inferred. Visible/schema parity compares only claims
actually populated in markup.

Product-specific rules apply only when deterministic classification selected
`page_kind=product`; an unclassified page does not receive the product
checklist.
