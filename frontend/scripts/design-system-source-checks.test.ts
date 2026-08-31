import { describe, expect, it } from 'vitest';

import {
  directRadixImportViolations,
  productUiSourceViolations,
  productControlViolations,
  standalonePlaceholderViolations,
  textRoleBackgroundViolations,
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

describe('directRadixImportViolations', () => {
  it('allows Radix only inside shared UI owners', () => {
    const radixModule = ['@radix-ui', 'react-tabs'].join('/');
    const source = `import * as Tabs from '${radixModule}';`;
    expect(directRadixImportViolations(source, 'components/feature/tabs.tsx')).toHaveLength(1);
    expect(directRadixImportViolations(source, 'components/ui/tabs.tsx')).toEqual([]);
  });
});

describe('productControlViolations', () => {
  it('rejects native selects, raw buttons, and cosmetic Button overrides', () => {
    const source = `
      <select><option>One</option></select>
      <button type="button">Open</button>
      <Button className="rounded-full bg-panel text-muted shadow-sm">Save</Button>
    `;
    expect(productControlViolations(source, 'components/example.tsx', true)).toHaveLength(3);
  });

  it('allows shared controls and semantic Button layout classes', () => {
    const source = `
      <Select ariaLabel="Status" options={options} />
      <Pressable className="grid w-full gap-2">Open</Pressable>
      <Button variant="secondary" className="w-full justify-start">Save</Button>
    `;
    expect(productControlViolations(source, 'components/example.tsx', true)).toEqual([]);
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

describe('textRoleBackgroundViolations', () => {
  // Assembled at runtime so this spec -- which the policy walk in
  // check-design-system.mjs also reads -- cannot trip its own rule.
  const banned = (role: string) => ['bg', '-'].join('') + role;

  it('rejects text-ink backgrounds in string, template, and JSX class text', () => {
    expect(
      textRoleBackgroundViolations(`const c = 'rounded ${banned('subtle')} p-2';`, 'lib/x.ts'),
    ).toHaveLength(1);
    expect(
      textRoleBackgroundViolations(`const c = \`flex ${banned('muted')} \${id}\`;`, 'lib/x.ts'),
    ).toHaveLength(1);
    expect(
      textRoleBackgroundViolations(
        `<div className="${banned('secondary')}" />`,
        'components/x.tsx',
      ),
    ).toHaveLength(1);
    expect(
      textRoleBackgroundViolations(`const c = '${banned('subtle')}/70';`, 'lib/x.ts'),
    ).toHaveLength(1);
  });

  it('allows surface tokens, prefixed variants, prose, and non-source files', () => {
    expect(textRoleBackgroundViolations("const c = 'flex bg-panel';", 'lib/x.ts')).toEqual([]);
    // A variant prefix is a different utility; the ESLint selector this
    // replaced anchored on a word boundary too.
    expect(
      textRoleBackgroundViolations(`const c = 'hover:${banned('subtle')}';`, 'lib/x.ts'),
    ).toEqual([]);
    expect(
      textRoleBackgroundViolations(`// never paint with ${banned('subtle')}`, 'lib/x.ts'),
    ).toEqual([]);
    expect(textRoleBackgroundViolations(banned('subtle'), 'app/globals.css')).toEqual([]);
  });
});
