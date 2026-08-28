import { describe, expect, it } from 'vitest';

import {
  productUiSourceViolations,
  standalonePlaceholderViolations,
} from './design-system-source-checks.mjs';

describe('standalonePlaceholderViolations', () => {
  it('rejects quoted and JSX em-dash placeholders in product UI', () => {
    expect(
      standalonePlaceholderViolations("const value = '—';", 'lib/value.ts', true),
    ).toHaveLength(1);
    expect(
      standalonePlaceholderViolations('<span>—</span>', 'components/value.tsx', true),
    ).toHaveLength(1);
    expect(
      standalonePlaceholderViolations('const value = `—`;', 'lib/value.ts', true),
    ).toHaveLength(1);
  });

  it('allows semantic labels, prose punctuation, and excluded surfaces', () => {
    expect(
      standalonePlaceholderViolations("const value = 'Not measured';", 'lib/value.ts', true),
    ).toEqual([]);
    expect(
      standalonePlaceholderViolations(
        "const sentence = 'Evidence — with context.';",
        'components/value.tsx',
        true,
      ),
    ).toEqual([]);
    expect(
      standalonePlaceholderViolations(
        "const preview = '—';",
        'components/marketing/demo.tsx',
        false,
      ),
    ).toEqual([]);
  });
});

describe('productUiSourceViolations', () => {
  it('rejects arbitrary product type and raw large spacing', () => {
    const source = '<div className="text-[13px] gap-6 p-5">Example</div>';
    expect(productUiSourceViolations(source, 'components/example.tsx', true)).toHaveLength(2);
  });

  it('allows the even ladder and semantic spacing roles', () => {
    const source =
      '<div className="text-sm gap-[var(--workspace-gap)] p-[var(--card-padding)]">Example</div>';
    expect(productUiSourceViolations(source, 'components/example.tsx', true)).toEqual([]);
  });

  it('rejects website typography inside product UI', () => {
    const source = '<h1 className="website-feature-heading">Example</h1>';
    expect(
      productUiSourceViolations(source, 'components/onboarding/example.tsx', true),
    ).toHaveLength(1);
  });
});
