import coreWebVitals from 'eslint-config-next/core-web-vitals';
import typescript from 'eslint-config-next/typescript';

// eslint-config-next 16 ships native flat configs, so the old
// `FlatCompat.extends('next/core-web-vitals', 'next/typescript')` bridge is
// replaced by direct imports.
const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      // `_`-prefixed bindings mark intentional omissions (e.g. the
      // destructure-to-omit pattern in tests).
      '@typescript-eslint/no-unused-vars': [
        'warn',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
          ignoreRestSiblings: true,
        },
      ],
      // Require strict equality everywhere except intentional `value == null`
      // null-or-undefined checks (the one allowed loose form).
      eqeqeq: ['error', 'always', { null: 'ignore' }],
      // A Promise executor that returns a value is almost always a bug (the
      // return is ignored) — flag it as an error.
      'no-promise-executor-return': 'error',
      // Constant binary expressions (e.g. always-truthy assertions) are dead
      // logic — flag them as an error.
      'no-constant-binary-expression': 'error',
      // Tailwind v4 generates EVERY utility family from every `@theme` token,
      // so `--color-subtle` / `--color-muted` / `--color-secondary` (the
      // Gray-500/600/700 TEXT inks) silently yield usable `bg-*` utilities.
      // `bg-subtle` painted the page-kind score expansion as a dark slate panel
      // with unreadable controls on it, and neither review nor the type system
      // could catch it. Surfaces are `bg-background`, `bg-background-alt`,
      // `bg-panel`, `bg-well`, `bg-elevated`, `bg-surface-inverse`, or a
      // semantic `bg-*-bg`; neutral fills are the `border-*` scale.
      //
      // NOT listed: `bg-foreground` + `text-background` is the deliberate
      // inverse-chip pattern, and `bg-inverse/70` is a white scrim.
      'no-restricted-syntax': [
        'error',
        {
          selector: 'Literal[value=/(^|\\s)bg-(subtle|secondary|muted)(\\s|\\/|$)/]',
          message:
            'Background utility built from a TEXT-role token. Use a surface token (bg-background-alt, bg-panel, bg-well, bg-elevated, bg-surface-inverse), a border-scale neutral, or a semantic bg-*-bg.',
        },
        {
          selector: 'TemplateElement[value.raw=/(^|\\s)bg-(subtle|secondary|muted)(\\s|\\/|$)/]',
          message:
            'Background utility built from a TEXT-role token. Use a surface token (bg-background-alt, bg-panel, bg-well, bg-elevated, bg-surface-inverse), a border-scale neutral, or a semantic bg-*-bg.',
        },
      ],
    },
  },
  {
    ignores: [
      'node_modules/**',
      '.next/**',
      '.next-stale-codex/**',
      'out/**',
      'coverage/**',
      'playwright-report/**',
      'test-results/**',
      'next-env.d.ts',
    ],
  },
];

export default eslintConfig;
