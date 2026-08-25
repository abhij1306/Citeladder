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

`/products` ships one four-tab contract:

1. **Overview** — guided catalog → category prompt → Commerce audit workflow,
   followed by persisted product/category KPIs and actions.
2. **Catalog** — product add, import, edit, delete, completeness, and feed
   health.
3. **AI Visibility** — per-SKU visibility rate, top-three rate, average
   position, engine coverage, and prior-audit change.
4. **Opportunities** — the shared Opportunity API filtered to
   `opportunity_type=commerce`; review confirmation is browser-only and does
   not mutate a provider or create a second recommendation store.

CSV categories are authoritative. Commerce reuses one prompt set, one topic per
category, and exactly two generated prompts per category: generic discovery and
uploaded-product comparison. That fixed prompt pair is derived deterministically
from the category and uploaded product names; the Commerce generation action
does not configure or call the application model. Commerce audits are isolated
by `audit_scope` and freeze uploaded product URL domains. Category citation
projections label third-party results as cited alternatives/sources, never
matched competitor SKUs. A retrieval-enabled answer can truthfully have no
citations.

Commerce emits only three deterministic action types: an uploaded product was
absent, third-party category citations appeared while uploaded products and
destinations were absent, or catalog fields were missing.

The removed product-level competitor catalog, matching/comparison projection,
discovery queue, candidates, review workflow, manual comparison mutation, AI
Conversations view, and generic Market Intelligence view are not active
architecture and must not be recreated. Brand competitors remain unchanged.

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
