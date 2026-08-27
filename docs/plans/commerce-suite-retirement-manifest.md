# Commerce Suite atomic cutover manifests

> **Status:** implementation manifest for
> [`commerce-suite-atomic-rebuild.md`](commerce-suite-atomic-rebuild.md)

## Retirement manifest

The atomic cutover removes these exact legacy authorities. Generic uses of the
words product or commerce outside this list are not retirement evidence.

### Backend

- Routes: `/projects/{project_id}/products*`, `/products/{product_id}*`,
  `/projects/{project_id}/commerce/attribution*`, and
  `/projects/{project_id}/commerce/catalog-health`.
- Models/tables: `Product`, `ProductResponseAnalysis`, `ProductMention`,
  `MerchantMention`, `ProductMetricSnapshot`, `OrderFact`, `FeedIssue`,
  `AttributionSnapshot`, and `AttributionLink`.
- Task kinds: `attribution_snapshot`, `attribution_link`, and
  `order_retention_sweep`.
- Configuration namespaces: `core.config.products`, the legacy measurement and
  feed/order members of `core.config.commerce`, and `core.config.attribution`.
- Domains: `domain.products`, `domain.attribution`, and the feed/order/catalog
  implementation under `domain.commerce`.
- Audit hooks: `analysis.product_service`, `analysis.product_scoring`,
  `analysis.product_scoring_aggregation`, the legacy product analyzer pass,
  product catalog freezing, and product metric terminalization.
- Opportunity hooks: `product_not_mentioned`,
  `cited_alternatives_without_uploaded_presence`, and
  `catalog_fields_missing` when sourced from legacy product metric snapshots.
- Shopify integration capability: OAuth provider/transport support, per-shop
  endpoint handling, Admin GraphQL product/order datasets and connector,
  provider-specific mapping/finalization, secrets, infrastructure egress, and
  the order pseudonymization salt. Commerce catalog evidence now enters through
  Site Health discovery or explicit CSV import; Shopify synchronization can be
  reconsidered only as a complete future integration slice.

### Frontend and public assets

- API/schema/query owners: `lib/api/products.ts`, legacy `lib/api/commerce.ts`,
  `lib/api/schemas/products.ts`, `lib/api/schemas/commerce-health.ts`,
  `lib/api/schemas/attribution.ts`, and their product/commerce query keys.
- Product workspace exports and components implementing Overview, legacy
  Catalog, AI Visibility, and `/products/[productId]`.
- The `/samples/commerce-products.csv` demo asset.
- Legacy Commerce product, visibility, attribution, catalog-health, feed/order,
  prompt-shim, product-detail, and Commerce-local Opportunity tests/fixtures.
- [`../commerce-intelligence.md`](../commerce-intelligence.md) as the old shipped
  runtime contract after this cutover lands.

No compatibility bridge is retained: CiteLadder is pre-launch and the
inventory found no external caller.

## Version lineage manifest

| Concern | Before | After |
|---|---|---|
| Site Health acquisition | `sh-acquisition-2` | unchanged |
| Site Health extractor | `sh-extractor-8` | `sh-extractor-12` |
| Site Health analyzer | `sh-analyzer-4` | `sh-analyzer-7` |
| Page classifier | `sh-classifier-3` | `sh-classifier-7` |
| Site Health rules | `sh-rules-4` | `sh-rules-6` |
| Site Health scoring | `sh-scoring-2` | unchanged |
| Legacy Commerce importer | `commerce-importer-1` | retired |
| Legacy product analyzer | `product-analysis-3` | retired |
| Legacy product scoring | `product-scoring-v2` | retired |
| Catalog projector | absent | `commerce-projector-3` |
| Catalog importer/edit policy | absent | `commerce-catalog-importer-1` / `commerce-catalog-edit-2` / `commerce-category-edit-1` |
| Competitor provider/validator | absent | `tavily-commerce-1` / `commerce-competitor-validator-5` |
| Buyer prompt template | absent | `commerce-buyer-prompts-2` |
| Recommendation parser/matcher | absent | `commerce-recommendation-parser-3` / `commerce-recommendation-matcher-3` |
| AI Shelf formulas | absent | `commerce-shelf-formulas-2` |
