/**
 * Products (agentic commerce) display helpers — pure, framework-free.
 *
 * The tab model for the `/products` Commerce workspace plus the formatters the catalog and visibility tables
 * share. Every number rendered here
 * is derived from persisted backend values — never invented.
 */
import type {
  BuyerDestinationKind,
  BuyerDestinationMix,
  FeedHealthStatus,
  LogicalEngine,
  PriceRelationCounts,
  ProductCompleteness,
  ProductFeedHealth,
  ProductOrigin,
} from '@/lib/api/types';

/** The four `/products` workspace tabs, in display order; Overview is default. */
export type ProductsTab = 'overview' | 'catalog' | 'visibility' | 'opportunities';

/** Engine filter value for the products surfaces (`all` = cross-engine). */
export type ProductEngineFilter = LogicalEngine | 'all';

export const PRODUCTS_TABS: readonly { id: ProductsTab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'catalog', label: 'Catalog' },
  { id: 'visibility', label: 'AI Visibility' },
  { id: 'opportunities', label: 'Opportunities' },
] as const;

/**
 * Nested product drill-down evidence sub-tabs (local React state, NOT in the
 * URL): the unified evidence stream splits by `evidence_kind`.
 */
export type ProductEvidenceSubTab = 'mentions' | 'attributes' | 'destinations';

export const PRODUCT_EVIDENCE_SUB_TABS: readonly { id: ProductEvidenceSubTab; label: string }[] = [
  { id: 'mentions', label: 'Mentions' },
  { id: 'attributes', label: 'Attributes' },
  { id: 'destinations', label: 'Destinations' },
] as const;

const DEFAULT_TAB: ProductsTab = 'overview';

/** Narrow an arbitrary `?tab=` value to a known tab, else the default. */
export function normalizeProductsTab(value: string | null | undefined): ProductsTab {
  return PRODUCTS_TABS.some((tab) => tab.id === value) ? (value as ProductsTab) : DEFAULT_TAB;
}

/** Stable case-insensitive identity for uploaded catalog categories and topics. */
export function categoryIdentity(value: unknown): string {
  return typeof value === 'string' ? value.trim().toLowerCase() : '';
}

/** One display category per identity, preserving the first uploaded spelling. */
export function catalogCategories(products: readonly { attributes: Record<string, unknown> }[]) {
  const categories = new Map<string, string>();
  for (const product of products) {
    const rawCategory = product.attributes.category;
    if (typeof rawCategory !== 'string') continue;
    const category = rawCategory.trim();
    const identity = categoryIdentity(category);
    if (category && !categories.has(identity)) categories.set(identity, category);
  }
  return [...categories.values()].sort((left, right) => left.localeCompare(right));
}

/** ISO-4217 → common symbol (display only; the code stays the source). */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  AUD: 'A$',
  CAD: 'C$',
};

/** `$2,499.00` / `€2,499.00` / `2,499.00 CHF` / `—` when no price. */
export function formatPrice(price: number | null | undefined, currency: string): string {
  if (price === null || price === undefined) return '—';
  const amount = price.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const code = (currency ?? '').trim().toUpperCase();
  const symbol = code ? CURRENCY_SYMBOLS[code] : undefined;
  if (symbol) return `${symbol}${amount}`;
  return code ? `${amount} ${code}` : amount;
}

/** `0.482` → `48%`; null/undefined → `—`. */
export function formatPercent(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return '—';
  return `${Math.round(rate * 100)}%`;
}

/** `1.6`; `—` when the product was never rank-listed. */
export function formatAvgRank(avgRank: number | null | undefined): string {
  if (avgRank === null || avgRank === undefined) return '—';
  return avgRank.toFixed(1);
}

/** Rank-bucket display order + labels (backend `PRODUCT_RANK_BUCKETS`). */
export const RANK_BUCKET_ORDER = [
  'top_1',
  'top_2_3',
  'top_4_5',
  'rank_6_plus',
  'unranked',
] as const;

export const RANK_BUCKET_LABELS: Record<(typeof RANK_BUCKET_ORDER)[number], string> = {
  top_1: 'Top 1',
  top_2_3: 'Top 2–3',
  top_4_5: 'Top 4–5',
  rank_6_plus: '6+',
  unranked: 'Unranked',
};

// ---------------------------------------------------------------------------
// Commerce v2 (analyzer v2 columns and feed health)
// ---------------------------------------------------------------------------

/** Catalog origin badge labels (backend `Product.origin` vocabulary). */
export const PRODUCT_ORIGIN_LABELS: Record<ProductOrigin, string> = {
  manual: 'Manual',
  imported: 'CSV import',
  synced: 'Synced feed',
};

/** Buyer-destination kind badge labels (backend `MERCHANT_KINDS`). */
export const BUYER_DESTINATION_KIND_LABELS: Record<BuyerDestinationKind, string> = {
  marketplace: 'Marketplace',
  retailer: 'Retailer',
  brand_site: 'Brand site',
  other: 'Other',
};

/**
 * The analyzer-v1 version lineage (mirrors the backend config-owned
 * `PRODUCT_ANALYZER_VERSION` history: v1 = `product-analysis-1`). v1 rows
 * recorded price mismatches without a direction, so direction is NEVER
 * inferred for them.
 */
const PRODUCT_ANALYZER_V1_VERSION = 'product-analysis-1';

export function isV1ProductAnalyzer(version: string): boolean {
  return version === PRODUCT_ANALYZER_V1_VERSION;
}

/**
 * Display model for the Price relation column. A v1 entry with persisted
 * mismatches renders `Direction unavailable` (never Higher/Lower); otherwise
 * the persisted match/higher/lower counts render as badges, and an entry
 * with no verifiable relation renders the null placeholder.
 */
export type PriceRelationDisplay =
  | { kind: 'unavailable'; mismatch: number }
  | { kind: 'counts'; match: number; higher: number; lower: number }
  | { kind: 'empty' };

export function priceRelationDisplay(entry: {
  product_analyzer_version: string;
  price_relation_counts: PriceRelationCounts;
}): PriceRelationDisplay {
  const counts = entry.price_relation_counts;
  const mismatch = counts.mismatch ?? 0;
  if (isV1ProductAnalyzer(entry.product_analyzer_version) && mismatch > 0) {
    return { kind: 'unavailable', mismatch };
  }
  const match = counts.match ?? 0;
  const higher = counts.higher ?? 0;
  const lower = counts.lower ?? 0;
  if (match + higher + lower === 0) return { kind: 'empty' };
  return { kind: 'counts', match, higher, lower };
}

/** True when any entry renders `Direction unavailable` (drives the v1 alert). */
export function hasDirectionUnavailableRows(
  entries: readonly {
    product_analyzer_version: string;
    price_relation_counts: PriceRelationCounts;
  }[],
): boolean {
  return entries.some((entry) => priceRelationDisplay(entry).kind === 'unavailable');
}

/** One attribute group row: integer frequency per dimension + group total. */
export type AttributeFrequencyGroup = {
  group: string;
  dimensions: { dimension: string; count: number }[];
  total: number;
};

/**
 * Aggregate the selected projection's row-level `attribute_dimension_frequency`
 * for display only — persisted counts are added, evidence is never re-scored.
 * Groups sort by total descending, dimensions by count descending.
 */
export function aggregateAttributeFrequency(
  entries: readonly { attribute_dimension_frequency: Record<string, Record<string, number>> }[],
): AttributeFrequencyGroup[] {
  const groups = new Map<string, Map<string, number>>();
  for (const entry of entries) {
    for (const [group, dimensions] of Object.entries(entry.attribute_dimension_frequency)) {
      let bucket = groups.get(group);
      if (!bucket) {
        bucket = new Map();
        groups.set(group, bucket);
      }
      for (const [dimension, count] of Object.entries(dimensions)) {
        bucket.set(dimension, (bucket.get(dimension) ?? 0) + count);
      }
    }
  }
  return [...groups.entries()]
    .map(([group, dimensions]) => {
      const rows = [...dimensions.entries()]
        .map(([dimension, count]) => ({ dimension, count }))
        .sort((a, b) => b.count - a.count || a.dimension.localeCompare(b.dimension));
      const total = rows.reduce((sum, row) => sum + row.count, 0);
      return { group, dimensions: rows, total };
    })
    .sort((a, b) => b.total - a.total || a.group.localeCompare(b.group));
}

/**
 * Aggregate row-level `buyer_destination_mix` for display only (persisted
 * counts added; kinds and domains sorted by count descending).
 */
export function aggregateBuyerDestinationMix(
  entries: readonly { buyer_destination_mix: BuyerDestinationMix }[],
): BuyerDestinationMix {
  const byKind = new Map<BuyerDestinationKind, number>();
  const byDomain = new Map<
    string,
    {
      merchant_domain: string;
      merchant_name: string;
      merchant_kind: BuyerDestinationKind;
      count: number;
    }
  >();
  let total = 0;
  for (const entry of entries) {
    total += entry.buyer_destination_mix.total;
    for (const row of entry.buyer_destination_mix.by_kind) {
      byKind.set(row.merchant_kind, (byKind.get(row.merchant_kind) ?? 0) + row.count);
    }
    for (const row of entry.buyer_destination_mix.by_domain) {
      const existing = byDomain.get(row.merchant_domain);
      if (existing) existing.count += row.count;
      else byDomain.set(row.merchant_domain, { ...row });
    }
  }
  return {
    total,
    by_kind: [...byKind.entries()]
      .map(([merchant_kind, count]) => ({ merchant_kind, count }))
      .sort((a, b) => b.count - a.count || a.merchant_kind.localeCompare(b.merchant_kind)),
    by_domain: [...byDomain.values()].sort(
      (a, b) => b.count - a.count || a.merchant_domain.localeCompare(b.merchant_domain),
    ),
  };
}

// ---------------------------------------------------------------------------
// Catalog feed health + sync display model (null-safe commerce formatters)
// ---------------------------------------------------------------------------

/**
 * Human labels for the per-SKU completeness matrix keys (backend
 * `config/products.py`: `PRODUCT_REQUIRED_ATTRIBUTES` +
 * `PRODUCT_COMPLETENESS_ATTRIBUTE_KEYS`). Drives the completeness hover
 * detail (D4) so raw keys like `gtin` never render verbatim.
 */
export const FEED_ATTRIBUTE_LABELS: Record<string, string> = {
  name: 'Name',
  sku: 'SKU',
  price: 'Price',
  currency: 'Currency',
  url: 'URL',
  brand: 'Brand',
  category: 'Category',
  gtin: 'GTIN',
  mpn: 'MPN',
  availability: 'Availability',
  condition: 'Condition',
  description: 'Description',
};

/** Label one completeness matrix key (unknown keys pass through). */
export function feedAttributeLabel(key: string): string {
  return FEED_ATTRIBUTE_LABELS[key] ?? key;
}

/**
 * The per-SKU completeness hover detail (D4): the score plus, for an
 * incomplete row, exactly which feed attributes are missing — everything is
 * already in the `completeness` payload, so the hover works for every row
 * (complete ones included), not just the ones with a warning badge.
 */
export function completenessHoverDetail(completeness: ProductCompleteness): string {
  const score = formatPercent(completeness.score);
  if (completeness.missing.length === 0) {
    return `Feed completeness ${score} — all ${completeness.total} required attributes present`;
  }
  const missing = completeness.missing.map(feedAttributeLabel).join(', ');
  return `Feed completeness ${score} — missing ${completeness.missing.length} of ${completeness.total}: ${missing}`;
}

/**
 * Feed-health cell model: an unbound product (null `connection_id`) is
 * `Not feed-bound`; a bound product with no projected health row is
 * `Feed health unavailable`; otherwise the persisted status renders.
 */
export type FeedHealthDisplay =
  | { kind: 'unbound' }
  | { kind: 'no-row' }
  | { kind: 'status'; status: FeedHealthStatus; issueCount: number; ruleIds: string[] };

export function feedHealthDisplay(
  product: { connection_id: string | null },
  healthRow: ProductFeedHealth | undefined,
): FeedHealthDisplay {
  if (!product.connection_id) return { kind: 'unbound' };
  if (!healthRow) return { kind: 'no-row' };
  return {
    kind: 'status',
    status: healthRow.status,
    issueCount: healthRow.issue_count,
    ruleIds: healthRow.rule_ids,
  };
}

/** The badge text for a feed-health cell (meaning is never color-only). */
export function feedHealthLabel(display: FeedHealthDisplay): string {
  if (display.kind === 'unbound') return 'Not feed-bound';
  if (display.kind === 'no-row') return 'Feed health unavailable';
  if (display.status === 'healthy') return 'Healthy';
  if (display.status === 'unavailable') return 'Unavailable';
  if (display.status === 'warning') {
    return `${display.issueCount} warning${display.issueCount === 1 ? '' : 's'}`;
  }
  return `${display.issueCount} error${display.issueCount === 1 ? '' : 's'}`;
}
