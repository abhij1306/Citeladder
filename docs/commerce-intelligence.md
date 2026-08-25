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

`/products` ships one three-tab contract:

1. **Overview** — guided catalog → category prompt → Commerce audit workflow,
   followed by persisted product/category KPIs.
2. **Catalog** — product add, import, edit, delete, completeness, INR price,
   and variant-count facts. Integration origin, feed-health, and sync metadata
   are not presented as catalog insight.
3. **AI Visibility** — per-SKU visibility and average position alongside
   category-level brand presence, configured-competitor mentions, and cited
   source classification.
CSV categories are authoritative. Commerce reuses one prompt set, one topic per
category, and exactly two generated prompts per product: buyer destination and
alternatives comparison. Both deterministic questions name the persisted
product so the returned response can be measured for product, brand,
competitor, destination, and citation presence without assuming a merchant. The Commerce
generation action does not configure or call the application model. Commerce
audits are isolated by `audit_scope` and freeze uploaded product URL domains.
Category projections expose persisted tracked-brand response presence and
configured-competitor mentions. Cited alternatives/sources retain the
analyzer's brand, competitor, or third-party classification and matched
competitor name where available; they are never matched competitor SKUs. A
retrieval-enabled answer can truthfully have no citations.

The shared Opportunity owner may emit three deterministic Commerce action types: an uploaded product was
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
