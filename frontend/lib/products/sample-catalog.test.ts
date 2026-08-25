import { readFileSync } from 'node:fs';
import path from 'node:path';

import { describe, expect, it } from 'vitest';

import { parseProductCsv } from './csv';

describe('commerce sample catalog', () => {
  it('contains one Flipkart catalog rather than competitor-owned destinations', () => {
    const raw = readFileSync(
      path.join(process.cwd(), 'public', 'samples', 'commerce-products.csv'),
      'utf8',
    );
    const parsed = parseProductCsv(raw);

    expect(parsed.errors).toEqual([]);
    expect(parsed.rows).toHaveLength(6);
    expect(parsed.rows.every((row) => row.errors.length === 0)).toBe(true);
    expect(new Set(parsed.rows.map((row) => new URL(row.input.url ?? '').hostname))).toEqual(
      new Set(['www.flipkart.com']),
    );
    expect(new Set(parsed.rows.map((row) => row.input.currency))).toEqual(new Set(['INR']));
    expect(parsed.rows.every((row) => Number(row.input.attributes?.variant_count) >= 1)).toBe(true);
  });
});
