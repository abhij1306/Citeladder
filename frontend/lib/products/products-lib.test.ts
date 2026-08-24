import { describe, expect, it } from 'vitest';

import {
  aggregateAttributeFrequency,
  aggregateBuyerDestinationMix,
  catalogCategories,
  categoryIdentity,
  completenessHoverDetail,
  feedAttributeLabel,
  feedHealthDisplay,
  feedHealthLabel,
  formatAvgRank,
  formatPercent,
  formatPrice,
  hasDirectionUnavailableRows,
  isV1ProductAnalyzer,
  normalizeProductsTab,
  priceRelationDisplay,
} from './catalog';
import { parseProductCsv, validProductRows } from './csv';
import { emptyProductForm, formValuesToProductUpdate } from './forms';

describe('normalizeProductsTab', () => {
  it('defaults to Overview and passes through known tabs', () => {
    expect(normalizeProductsTab(null)).toBe('overview');
    expect(normalizeProductsTab('bogus')).toBe('overview');
    expect(normalizeProductsTab('overview')).toBe('overview');
    expect(normalizeProductsTab('visibility')).toBe('visibility');
    expect(normalizeProductsTab('competitors')).toBe('overview');
    expect(normalizeProductsTab('opportunities')).toBe('opportunities');
    expect(normalizeProductsTab('catalog')).toBe('catalog');
  });
});

describe('catalog category identity', () => {
  it('deduplicates category spellings that differ only by case', () => {
    const products = [
      { attributes: { category: 'Books' } },
      { attributes: { category: ' books ' } },
      { attributes: { category: 'Games' } },
    ];

    expect(catalogCategories(products)).toEqual(['Books', 'Games']);
    expect(categoryIdentity(' BOOKS ')).toBe(categoryIdentity('books'));
    expect(categoryIdentity({ category: 'Books' })).toBe('');
    expect(catalogCategories([{ attributes: { category: { name: 'Books' } } }])).toEqual([]);
  });
});

describe('formatters', () => {
  it('formats prices with currency symbols and placeholders', () => {
    expect(formatPrice(2499, 'USD')).toBe('$2,499.00');
    expect(formatPrice(2499.5, 'eur')).toBe('€2,499.50');
    expect(formatPrice(100, 'CHF')).toBe('100.00 CHF');
    expect(formatPrice(null, 'USD')).toBe('—');
  });

  it('formats percents and ranks with null placeholders', () => {
    expect(formatPercent(0.482)).toBe('48%');
    expect(formatPercent(null)).toBe('—');
    expect(formatAvgRank(1.6)).toBe('1.6');
    expect(formatAvgRank(null)).toBe('—');
  });
});

describe('priceRelationDisplay', () => {
  it('flags the analyzer-v1 lineage (never v2)', () => {
    expect(isV1ProductAnalyzer('product-analysis-1')).toBe(true);
    expect(isV1ProductAnalyzer('product-analysis-2')).toBe(false);
  });

  it('reads Direction unavailable for a v1 row with persisted mismatches', () => {
    const display = priceRelationDisplay({
      product_analyzer_version: 'product-analysis-1',
      price_relation_counts: { match: 4, mismatch: 3 },
    });
    expect(display).toEqual({ kind: 'unavailable', mismatch: 3 });
    expect(
      hasDirectionUnavailableRows([
        {
          product_analyzer_version: 'product-analysis-1',
          price_relation_counts: { match: 4, mismatch: 3 },
        },
      ]),
    ).toBe(true);
  });

  it('renders v2 Higher/Lower only from persisted counts', () => {
    expect(
      priceRelationDisplay({
        product_analyzer_version: 'product-analysis-2',
        price_relation_counts: { match: 2, higher: 1, lower: 3 },
      }),
    ).toEqual({ kind: 'counts', match: 2, higher: 1, lower: 3 });
    // A v1 row without mismatches is empty, never direction-inferred.
    expect(
      priceRelationDisplay({
        product_analyzer_version: 'product-analysis-1',
        price_relation_counts: { match: 2 },
      }),
    ).toEqual({ kind: 'counts', match: 2, higher: 0, lower: 0 });
    expect(
      priceRelationDisplay({
        product_analyzer_version: 'product-analysis-2',
        price_relation_counts: {},
      }),
    ).toEqual({ kind: 'empty' });
  });
});

describe('aggregateAttributeFrequency', () => {
  it('adds persisted counts across rows and sorts groups/dimensions', () => {
    const groups = aggregateAttributeFrequency([
      { attribute_dimension_frequency: { Facts: { Price: 2, Sizing: 1 }, Ratings: { Score: 1 } } },
      { attribute_dimension_frequency: { Facts: { Price: 3, Materials: 1 } } },
    ]);
    expect(groups.map((group) => [group.group, group.total])).toEqual([
      ['Facts', 7],
      ['Ratings', 1],
    ]);
    expect(groups[0]?.dimensions).toEqual([
      { dimension: 'Price', count: 5 },
      { dimension: 'Materials', count: 1 },
      { dimension: 'Sizing', count: 1 },
    ]);
  });
});

describe('aggregateBuyerDestinationMix', () => {
  it('adds persisted kind/domain counts across rows', () => {
    const mix = aggregateBuyerDestinationMix([
      {
        buyer_destination_mix: {
          total: 2,
          by_kind: [{ merchant_kind: 'brand_site', count: 2 }],
          by_domain: [
            {
              merchant_domain: 'acme.com',
              merchant_name: 'Acme',
              merchant_kind: 'brand_site',
              count: 2,
            },
          ],
        },
      },
      {
        buyer_destination_mix: {
          total: 3,
          by_kind: [
            { merchant_kind: 'brand_site', count: 1 },
            { merchant_kind: 'marketplace', count: 2 },
          ],
          by_domain: [
            {
              merchant_domain: 'acme.com',
              merchant_name: 'Acme',
              merchant_kind: 'brand_site',
              count: 1,
            },
            {
              merchant_domain: 'marketplace.example',
              merchant_name: 'Marketplace',
              merchant_kind: 'marketplace',
              count: 2,
            },
          ],
        },
      },
    ]);
    expect(mix.total).toBe(5);
    expect(mix.by_kind).toEqual([
      { merchant_kind: 'brand_site', count: 3 },
      { merchant_kind: 'marketplace', count: 2 },
    ]);
    expect(mix.by_domain.map((row) => [row.merchant_domain, row.count])).toEqual([
      ['acme.com', 3],
      ['marketplace.example', 2],
    ]);
  });
});

describe('feedHealthDisplay / feedHealthLabel', () => {
  const healthRow = {
    product_id: '33333333-3333-4333-8333-333333333333',
    connection_id: '44444444-4444-4444-8444-444444444444',
    external_item_ref: 'gid://shopify/Product/1',
    sync_run_id: '55555555-5555-4555-8555-555555555555',
    status: 'warning' as const,
    highest_severity: 'warning' as const,
    issue_count: 2,
    rule_ids: ['price_missing'],
    last_seen_in_feed: true,
  };

  it('distinguishes unbound, no-row, and status cells', () => {
    expect(feedHealthDisplay({ connection_id: null }, undefined)).toEqual({ kind: 'unbound' });
    expect(feedHealthDisplay({ connection_id: 'c1' }, undefined)).toEqual({ kind: 'no-row' });
    expect(feedHealthDisplay({ connection_id: 'c1' }, healthRow)).toEqual({
      kind: 'status',
      status: 'warning',
      issueCount: 2,
      ruleIds: ['price_missing'],
    });
  });

  it('labels every cell kind in text (never color-only)', () => {
    expect(feedHealthLabel({ kind: 'unbound' })).toBe('Not feed-bound');
    expect(feedHealthLabel({ kind: 'no-row' })).toBe('Feed health unavailable');
    expect(feedHealthLabel({ kind: 'status', status: 'healthy', issueCount: 0, ruleIds: [] })).toBe(
      'Healthy',
    );
    expect(feedHealthLabel({ kind: 'status', status: 'warning', issueCount: 2, ruleIds: [] })).toBe(
      '2 warnings',
    );
    expect(feedHealthLabel({ kind: 'status', status: 'error', issueCount: 1, ruleIds: [] })).toBe(
      '1 error',
    );
    expect(
      feedHealthLabel({ kind: 'status', status: 'unavailable', issueCount: 0, ruleIds: [] }),
    ).toBe('Unavailable');
  });
});

describe('parseProductCsv', () => {
  it('parses header + rows with attributes and a variant', () => {
    const parsed = parseProductCsv(
      'name,sku,variant,category,price,currency,url,gtin\n' +
        'VoltCity Commuter 500,VC-EB500-GR,Graphite / Standard,E-Bikes,"$2,499.00",usd,https://x.example/p,0123\n',
    );
    expect(parsed.errors).toEqual([]);
    expect(parsed.rows).toHaveLength(1);
    const row = parsed.rows[0]!;
    expect(row.errors).toEqual([]);
    expect(row.input).toEqual({
      sku: 'VC-EB500-GR',
      name: 'VoltCity Commuter 500',
      aliases: [],
      variants: [{ name: 'Graphite / Standard' }],
      price: 2499.0,
      currency: 'USD',
      url: 'https://x.example/p',
      attributes: { category: 'E-Bikes', gtin: '0123' },
    });
    expect(validProductRows(parsed)).toHaveLength(1);
  });

  it('rejects headerless files (matching the backend)', () => {
    const parsed = parseProductCsv('VoltCity Commuter 500,2499.00\n');
    expect(parsed.rows).toEqual([]);
    expect(parsed.errors[0]).toMatch(/header row is required/i);
  });

  it('flags rows without a sku as not importable and clears bad prices', () => {
    const parsed = parseProductCsv('name,sku,price\nNoSku,,10\nBadPrice,SKU-2,not-a-price\n');
    expect(parsed.rows[0]!.errors[0]).toMatch(/SKU is required/);
    expect(parsed.rows[1]!.warnings[0]).toMatch(/Unparseable price/);
    expect(parsed.rows[1]!.input.price).toBeNull();
    // Only the row with a sku is importable.
    expect(validProductRows(parsed).map((row) => row.sku)).toEqual(['SKU-2']);
  });

  it('falls back to the sku as name and splits aliases', () => {
    const parsed = parseProductCsv('sku,aliases\nSKU-1,Volt 500 | VC500\n');
    expect(parsed.rows[0]!.input.name).toBe('SKU-1');
    expect(parsed.rows[0]!.input.aliases).toEqual(['Volt 500', 'VC500']);
  });

  it('folds spaced headers to underscores like the backend import', () => {
    // `Product SKU` / `Currency Code` are accepted by the server
    // (csv_import folds spaces to underscores); the browser preview must too.
    const parsed = parseProductCsv(
      'Product SKU,Product Name,Price Amount,Currency Code\nSKU-9,Volt,10,usd\n',
    );
    expect(parsed.errors).toEqual([]);
    expect(parsed.rows[0]!.input).toMatchObject({
      sku: 'SKU-9',
      name: 'Volt',
      price: 10,
      currency: 'USD',
    });
  });

  it('strips letter-prefixed currency symbols from prices (backend parity)', () => {
    for (const raw of ['US$100', 'A$100', 'C$100', 'AU$100', 'CA$100', '€100', '£100']) {
      const parsed = parseProductCsv(`sku,price\nSKU-1,"${raw}"\n`);
      expect(parsed.rows[0]!.input.price).toBe(100);
    }
  });
});

describe('completenessHoverDetail (D4)', () => {
  it('names every present attribute count for a complete row', () => {
    expect(completenessHoverDetail({ score: 1, present: 12, total: 12, missing: [] })).toBe(
      'Feed completeness 100% — all 12 required attributes present',
    );
  });

  it('labels the missing feed attributes for an incomplete row', () => {
    expect(
      completenessHoverDetail({ score: 0.75, present: 9, total: 12, missing: ['gtin', 'mpn'] }),
    ).toBe('Feed completeness 75% — missing 2 of 12: GTIN, MPN');
  });

  it('falls back to the raw key for an unknown attribute', () => {
    expect(feedAttributeLabel('seller_rating')).toBe('seller_rating');
    expect(
      completenessHoverDetail({ score: 0.5, present: 1, total: 2, missing: ['seller_rating'] }),
    ).toBe('Feed completeness 50% — missing 1 of 2: seller_rating');
  });
});

describe('formValuesToProductUpdate', () => {
  const existing = {
    id: 'p1',
    project_id: 'proj',
    sku: 'SKU-1',
    name: 'Volt',
    aliases: ['V'],
    variants: [
      { name: 'Graphite', sku: 'SKU-1-G', price: 2499 },
      { name: 'Silver', sku: 'SKU-1-S', price: 2599 },
    ],
    price: 2499,
    currency: 'USD',
    url: 'https://x.example/p',
    attributes: { brand: 'Acme', mpn: 'MPN-1', condition: 'new' },
    origin: 'imported',
    completeness: { score: 1, present: 12, total: 12, missing: [] },
    created_at: '2026-07-01T00:00:00Z',
    updated_at: '2026-07-01T00:00:00Z',
  } as const;

  it('preserves form-unmanaged attribute keys and variants on edit', () => {
    const update = formValuesToProductUpdate(existing as never, {
      ...emptyProductForm,
      name: 'Volt Renamed',
      sku: 'SKU-1',
      brand: 'Acme 2',
    });
    // Form-owned keys overwritten; unmanaged keys (mpn/condition) survive.
    expect(update.attributes).toEqual({ brand: 'Acme 2', mpn: 'MPN-1', condition: 'new' });
    // variants[0].name overwritten in place; every other variant preserved.
    expect(update.variants).toEqual([
      { name: 'Graphite', sku: 'SKU-1-G', price: 2499 },
      { name: 'Silver', sku: 'SKU-1-S', price: 2599 },
    ]);
    expect(update.name).toBe('Volt Renamed');
  });

  it('writes the single form variant for a product without variants', () => {
    const update = formValuesToProductUpdate({ ...existing, variants: [] } as never, {
      ...emptyProductForm,
      sku: 'SKU-1',
      variant: 'Graphite',
    });
    expect(update.variants).toEqual([{ name: 'Graphite' }]);
  });
});
