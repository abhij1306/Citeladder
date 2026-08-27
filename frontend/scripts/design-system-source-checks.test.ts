import { describe, expect, it } from 'vitest';

import { standalonePlaceholderViolations } from './design-system-source-checks.mjs';

describe('standalonePlaceholderViolations', () => {
  it('rejects quoted and JSX em-dash placeholders in product UI', () => {
    expect(
      standalonePlaceholderViolations("const value = '—';", 'lib/value.ts', true),
    ).toHaveLength(1);
    expect(
      standalonePlaceholderViolations('<span>—</span>', 'components/value.tsx', true),
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
