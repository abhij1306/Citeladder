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
