import { describe, expect, it } from 'vitest';

import { evidenceStatements } from './issue-evidence';

describe('evidenceStatements', () => {
  it('states exact schema expectations, found types, missing paths, and limits', () => {
    expect(
      evidenceStatements({
        expected_types: ['Product'],
        found_types: ['Article'],
        schema_type: 'Product',
        missing: ['offers.priceCurrency'],
        checked_blocks: 1,
        extraction: 'microdata_shallow',
      }),
    ).toEqual([
      'Expected Product; found Article.',
      'Product is missing offers.priceCurrency.',
      'Checked 1 schema block.',
      'Property extraction was limited for shallow microdata.',
    ]);
  });

  it('distinguishes both persisted heading scopes', () => {
    expect(
      evidenceStatements({
        skips: [
          { from: 1, to: 3, scope: 'full_document' },
          { from: 2, to: 4, scope: 'primary_content' },
        ],
      }),
    ).toEqual(['H1 → H3, full document.', 'H2 → H4, primary content.']);
  });

  it('shows bounded form counts and safe offending-control descriptors', () => {
    expect(
      evidenceStatements({
        control_count: 8,
        missing_accessible_name: 2,
        missing_control_descriptors: [
          { tag: 'input', type: 'text', id: 'search', name: '', ordinal: 3 },
          { tag: 'select', type: '', id: '', name: 'country', ordinal: 7 },
        ],
      }),
    ).toEqual([
      '2 of 8 controls lack accessible names.',
      'input · type=text · id=search · #3',
      'select · name=country · #7',
    ]);
  });

  it('states the exact failed link target and HTTP response', () => {
    expect(
      evidenceStatements({
        failing_targets: [{ url: 'https://example.com/missing', status_code: 404 }],
      }),
    ).toEqual(['Link target https://example.com/missing returned HTTP 404.']);
  });

  it('uses at most six labelled scalar fields for an unknown shape', () => {
    const lines = evidenceStatements({
      a: 1,
      b: true,
      c: 'x'.repeat(200),
      d: 4,
      e: 5,
      f: 6,
      g: 7,
    });
    expect(lines).toHaveLength(6);
    expect(lines[0]).toBe('A: 1.');
    expect(lines[2]).toBe(`C: ${'x'.repeat(160)}.`);
    expect(lines).not.toContain('G: 7.');
  });
});
